#!/usr/bin/env bash
set -euo pipefail

MODE="full"
AS_OF_DATE="2026-04-23"
SUBMISSIONS_MAX_CIKS=""
DRY_RUN=0
FORCE=0
MONITOR_INTERVAL=60

usage() {
    cat <<'EOF'
Usage: bash scripts/run_public_lake_full.sh [options]

Options:
  --mode full|smoke              Run against data/public_lake or data/public_lake_smoke.
  --as-of-date YYYY-MM-DD        Censoring date for gold panels. Default: 2026-04-23.
  --submissions-max-ciks N       Optional cap for submissions.zip normalization.
  --dry-run                      Print commands without executing them.
  --force                        Re-download source files even when cached.
  --monitor-interval SECONDS     Background monitor interval. Default: 60.
  -h, --help                     Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --as-of-date)
            AS_OF_DATE="$2"
            shift 2
            ;;
        --submissions-max-ciks)
            SUBMISSIONS_MAX_CIKS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --force)
            FORCE=1
            shift
            ;;
        --monitor-interval)
            MONITOR_INTERVAL="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$MODE" != "full" && "$MODE" != "smoke" ]]; then
    echo "--mode must be full or smoke" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f ".env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source ".env"
    set +a
fi

if [[ -z "${UV_PROJECT_ENVIRONMENT:-}" ]]; then
    echo "UV_PROJECT_ENVIRONMENT is missing in .env" >&2
    exit 1
fi

case "${UV_PROJECT_ENVIRONMENT}" in
    /*)
        ;;
    *)
        echo "UV_PROJECT_ENVIRONMENT must be an absolute path, got: ${UV_PROJECT_ENVIRONMENT}" >&2
        exit 1
        ;;
esac

case "${UV_PROJECT_ENVIRONMENT%/}" in
    "${PWD}"|"${PWD}/"*)
        echo "UV_PROJECT_ENVIRONMENT must point outside this repo, got: ${UV_PROJECT_ENVIRONMENT}" >&2
        exit 1
        ;;
esac
mkdir -p "$(dirname "${UV_PROJECT_ENVIRONMENT}")"

RUN_ID="$(date -u +"%Y%m%dT%H%M%SZ")"
LOG_DIR="artifacts/logs/public_lake_full/${RUN_ID}_${MODE}"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/run.log") 2>&1

if [[ "$MODE" = "smoke" ]]; then
    BRONZE_DIR="data/public_lake_smoke/bronze"
    SILVER_DIR="data/public_lake_smoke/silver"
    GOLD_DIR="data/public_lake_smoke/gold"
    CASCADE_OUT="artifacts/public_cascade_smoke"
    SUBMISSIONS_MAX_CIKS="${SUBMISSIONS_MAX_CIKS:-200}"
    SOURCE_LIMIT_EXTRA="--limit-links 2 --list-only"
else
    BRONZE_DIR="data/public_lake/bronze"
    SILVER_DIR="data/public_lake/silver"
    GOLD_DIR="data/public_lake/gold"
    CASCADE_OUT="artifacts/public_cascade_full"
    SOURCE_LIMIT_EXTRA=""
fi

BASE_DIR_EXTRA="--bronze-dir ${BRONZE_DIR} --silver-dir ${SILVER_DIR} --gold-dir ${GOLD_DIR}"
FORCE_EXTRA=""
if [[ "$FORCE" -eq 1 ]]; then
    FORCE_EXTRA="--force"
fi

run_step() {
    local name="$1"
    shift
    echo
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] START ${name}"
    echo "+ $*"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        "$@"
    fi
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] END ${name}"
}

run_just_fetch() {
    local source="$1"
    local extra="$2"
    run_step "fetch:${source}" just fetch "$source" "${BASE_DIR_EXTRA} ${extra} ${FORCE_EXTRA}"
}

echo "Run ID: ${RUN_ID}"
echo "Mode: ${MODE}"
echo "As-of date: ${AS_OF_DATE}"
echo "Bronze: ${BRONZE_DIR}"
echo "Silver: ${SILVER_DIR}"
echo "Gold: ${GOLD_DIR}"
echo "Dry run: ${DRY_RUN}"
echo "Force: ${FORCE}"

MONITOR_PID=""
if [[ "$DRY_RUN" -eq 0 ]]; then
    uv run python scripts/monitor_public_lake.py \
        --bronze-dir "$BRONZE_DIR" \
        --silver-dir "$SILVER_DIR" \
        --gold-dir "$GOLD_DIR" \
        --log-dir "$LOG_DIR" \
        --interval "$MONITOR_INTERVAL" \
        --pid $$ &
    MONITOR_PID="$!"
    trap 'if [[ -n "${MONITOR_PID}" ]]; then kill "${MONITOR_PID}" 2>/dev/null || true; fi' EXIT
fi

run_step "setup" just setup
run_step "status" just status
run_just_fetch "sec-bulk" ""
run_just_fetch "form-ap" ""
run_just_fetch "aaer" "${SOURCE_LIMIT_EXTRA}"
run_just_fetch "pcaob-inspections" "${SOURCE_LIMIT_EXTRA}"
run_just_fetch "fsds" "--start-year 2011 --end-year 2023 ${SOURCE_LIMIT_EXTRA}"
run_just_fetch "notes" "--start-year 2020 --end-year 2023 ${SOURCE_LIMIT_EXTRA}"

BUILD_EXTRA="${BASE_DIR_EXTRA} --as-of-date ${AS_OF_DATE}"
if [[ -n "$SUBMISSIONS_MAX_CIKS" ]]; then
    BUILD_EXTRA="${BUILD_EXTRA} --submissions-max-ciks ${SUBMISSIONS_MAX_CIKS}"
fi
run_step "build-lake" just fetch build-lake "$BUILD_EXTRA"

run_step "public-cascade" just analysis cascade raw "$CASCADE_OUT" \
    "--issuer-origin-panel ${GOLD_DIR}/issuer_origin_panel.csv.gz"

run_step "final-report" uv run python scripts/monitor_public_lake.py \
    --bronze-dir "$BRONZE_DIR" \
    --silver-dir "$SILVER_DIR" \
    --gold-dir "$GOLD_DIR" \
    --log-dir "$LOG_DIR" \
    --once \
    --report-json "$LOG_DIR/run_report.json"

echo
echo "Public lake run complete. Logs: ${LOG_DIR}"
