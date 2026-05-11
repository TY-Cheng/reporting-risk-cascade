#!/usr/bin/env bash
set -euo pipefail

MODE="full"
AS_OF_DATE="2026-04-23"
SUBMISSIONS_MAX_CIKS=""
DRY_RUN=0
FORCE=0
MONITOR_INTERVAL=60
SKIP_PUBLIC_CASCADE=0
FETCH_WORKERS=2
ENGINE="duckdb"
DUCKDB_THREADS=4
DUCKDB_MEMORY_LIMIT="10GB"
DUCKDB_TEMP_DIRECTORY=""
DUCKDB_MAX_TEMP_SIZE="400GB"
SKIP_SETUP=0
STORAGE_FORMAT="parquet"
NOTES_MODE="summary"
FSDS_BATCH_SIZE=4
NOTES_BATCH_SIZE=2
FRESH_BUILD=0
RESUME=0

usage() {
    cat <<'EOF'
Usage: bash scripts/run_public_lake_full.sh [options]

Options:
  --mode full|smoke              Run against DATA_DIR/public_lake or DATA_DIR/public_lake_smoke.
  --as-of-date YYYY-MM-DD        Censoring date for gold panels. Default: 2026-04-23.
  --submissions-max-ciks N       Optional cap for submissions.zip normalization.
  --dry-run                      Print commands without executing them.
  --force                        Re-download source files even when cached.
  --monitor-interval SECONDS     Background monitor interval. Default: 60.
  --skip-public-cascade          Build the public lake only; leave modeling to run_study.py.
  --fetch-workers N              Concurrent source fetch jobs. Default: 2.
  --engine pandas|duckdb         Public-lake build engine. Default: duckdb.
  --duckdb-threads N             DuckDB PRAGMA threads for build-lake. Default: 4.
  --duckdb-memory-limit SIZE     DuckDB memory_limit for build-lake. Default: 10GB.
  --duckdb-temp-directory PATH   DuckDB temp_directory. Default: silver-local temp dir.
  --duckdb-max-temp-size SIZE    DuckDB max_temp_directory_size. Default: 400GB.
  --storage-format parquet|csv-gz Heavy-table storage format. Default: parquet; csv-gz is legacy.
  --notes-mode summary|raw|skip   Notes extraction mode. Default: summary.
  --fsds-batch-size N            FSDS archive batch size for Parquet builds. Default: 4.
  --notes-batch-size N           Notes archive batch size for Parquet builds. Default: 2.
  --fresh-build                  Rebuild silver/gold from bronze without force-fetching bronze.
  --resume                       Reuse build-lake DAG done markers.
  --skip-setup                   Skip just setup; useful when called from just full.
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
        --skip-public-cascade)
            SKIP_PUBLIC_CASCADE=1
            shift
            ;;
        --fetch-workers)
            FETCH_WORKERS="$2"
            shift 2
            ;;
        --engine)
            ENGINE="$2"
            shift 2
            ;;
        --duckdb-threads)
            DUCKDB_THREADS="$2"
            shift 2
            ;;
        --duckdb-memory-limit)
            DUCKDB_MEMORY_LIMIT="$2"
            shift 2
            ;;
        --duckdb-temp-directory)
            DUCKDB_TEMP_DIRECTORY="$2"
            shift 2
            ;;
        --duckdb-max-temp-size)
            DUCKDB_MAX_TEMP_SIZE="$2"
            shift 2
            ;;
        --storage-format)
            STORAGE_FORMAT="$2"
            shift 2
            ;;
        --notes-mode)
            NOTES_MODE="$2"
            shift 2
            ;;
        --fsds-batch-size)
            FSDS_BATCH_SIZE="$2"
            shift 2
            ;;
        --notes-batch-size)
            NOTES_BATCH_SIZE="$2"
            shift 2
            ;;
        --fresh-build)
            FRESH_BUILD=1
            shift
            ;;
        --resume)
            RESUME=1
            shift
            ;;
        --skip-setup)
            SKIP_SETUP=1
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
if [[ "$ENGINE" != "pandas" && "$ENGINE" != "duckdb" ]]; then
    echo "--engine must be pandas or duckdb" >&2
    exit 2
fi
if [[ "$STORAGE_FORMAT" != "parquet" && "$STORAGE_FORMAT" != "csv-gz" ]]; then
    echo "--storage-format must be parquet or csv-gz" >&2
    exit 2
fi
if [[ "$NOTES_MODE" != "summary" && "$NOTES_MODE" != "raw" && "$NOTES_MODE" != "skip" ]]; then
    echo "--notes-mode must be summary, raw, or skip" >&2
    exit 2
fi
if [[ "$STORAGE_FORMAT" = "parquet" && "$ENGINE" != "duckdb" ]]; then
    echo "--storage-format parquet requires --engine duckdb" >&2
    exit 2
fi
if ! [[ "$FETCH_WORKERS" =~ ^[0-9]+$ ]] || [[ "$FETCH_WORKERS" -lt 1 ]]; then
    echo "--fetch-workers must be a positive integer" >&2
    exit 2
fi
if ! [[ "$DUCKDB_THREADS" =~ ^[0-9]+$ ]] || [[ "$DUCKDB_THREADS" -lt 1 ]]; then
    echo "--duckdb-threads must be a positive integer" >&2
    exit 2
fi
if ! [[ "$FSDS_BATCH_SIZE" =~ ^[0-9]+$ ]] || [[ "$FSDS_BATCH_SIZE" -lt 1 ]]; then
    echo "--fsds-batch-size must be a positive integer" >&2
    exit 2
fi
if ! [[ "$NOTES_BATCH_SIZE" =~ ^[0-9]+$ ]] || [[ "$NOTES_BATCH_SIZE" -lt 1 ]]; then
    echo "--notes-batch-size must be a positive integer" >&2
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
if [[ -z "${DATA_DIR:-}" ]]; then
    echo "DATA_DIR is missing in .env; public-lake data must be written to the external data root." >&2
    exit 1
fi
ARTIFACTS_DIR="${ARTIFACTS_DIR:-${REPO_ROOT}/artifacts}"
PUBLIC_LAKE_DIR="${PUBLIC_LAKE_DIR:-${DATA_DIR}/public_lake}"
LAKE_BRONZE_DIR="${LAKE_BRONZE_DIR:-${PUBLIC_LAKE_DIR}/bronze}"
LAKE_SILVER_DIR="${LAKE_SILVER_DIR:-${PUBLIC_LAKE_DIR}/silver}"
LAKE_GOLD_DIR="${LAKE_GOLD_DIR:-${PUBLIC_LAKE_DIR}/gold}"
PUBLIC_LAKE_SMOKE_DIR="${PUBLIC_LAKE_SMOKE_DIR:-${DATA_DIR}/public_lake_smoke}"

case "${DATA_DIR}" in
    /*)
        ;;
    *)
        echo "DATA_DIR must be an absolute path, got: ${DATA_DIR}" >&2
        exit 1
        ;;
esac
case "${DATA_DIR%/}" in
    "${PWD}"|"${PWD}/"*)
        echo "DATA_DIR must point outside this repo, got: ${DATA_DIR}" >&2
        exit 1
        ;;
esac
case "${ARTIFACTS_DIR}" in
    /*)
        ;;
    *)
        echo "ARTIFACTS_DIR must be an absolute path, got: ${ARTIFACTS_DIR}" >&2
        exit 1
        ;;
esac

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
LOG_DIR="${ARTIFACTS_DIR}/logs/public_lake_full/${RUN_ID}_${MODE}"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/run.log") 2>&1

if [[ "$MODE" = "smoke" ]]; then
    BRONZE_DIR="${PUBLIC_LAKE_SMOKE_DIR}/bronze"
    SILVER_DIR="${PUBLIC_LAKE_SMOKE_DIR}/silver"
    GOLD_DIR="${PUBLIC_LAKE_SMOKE_DIR}/gold"
    CASCADE_OUT="${ARTIFACTS_DIR}/public_cascade_smoke"
    SUBMISSIONS_MAX_CIKS="${SUBMISSIONS_MAX_CIKS:-200}"
    SOURCE_LIMIT_EXTRA="--limit-links 2 --list-only"
else
    BRONZE_DIR="${LAKE_BRONZE_DIR}"
    SILVER_DIR="${LAKE_SILVER_DIR}"
    GOLD_DIR="${LAKE_GOLD_DIR}"
    CASCADE_OUT="${ARTIFACTS_DIR}/public_cascade_full"
    SOURCE_LIMIT_EXTRA=""
fi
if [[ "$ENGINE" = "duckdb" && -z "$DUCKDB_TEMP_DIRECTORY" ]]; then
    DUCKDB_TEMP_DIRECTORY="${SILVER_DIR}/._duckdb_tmp"
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

fetch_command() {
    local source="$1"
    local extra="$2"
    # extra is controlled by this script and intentionally split into CLI tokens.
    # shellcheck disable=SC2086
    uv run python scripts/fetch_public_data.py \
        --mode "$source" \
        --bronze-dir "$BRONZE_DIR" \
        --silver-dir "$SILVER_DIR" \
        --gold-dir "$GOLD_DIR" \
        ${extra} ${FORCE_EXTRA}
}

active_pids=()
active_names=()
active_logs=()
fetch_failures=0

wait_for_fetch_slot() {
    if [[ "${#active_pids[@]}" -ge "$FETCH_WORKERS" ]]; then
        wait_for_all_fetches
    fi
}

start_fetch() {
    local source="$1"
    local extra="$2"
    local log="$LOG_DIR/fetch_${source}.log"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        wait_for_fetch_slot
    fi
    echo
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] START fetch:${source}"
    echo "+ uv run python scripts/fetch_public_data.py --mode ${source} ${BASE_DIR_EXTRA} ${extra} ${FORCE_EXTRA}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] END fetch:${source}"
        return
    fi
    (
        set -euo pipefail
        fetch_command "$source" "$extra"
    ) >"$log" 2>&1 &
    active_pids+=("$!")
    active_names+=("$source")
    active_logs+=("$log")
}

wait_for_all_fetches() {
    local idx pid name log status
    for idx in "${!active_pids[@]}"; do
        pid="${active_pids[$idx]}"
        name="${active_names[$idx]}"
        log="${active_logs[$idx]}"
        set +e
        wait "$pid"
        status="$?"
        set -e
        if [[ "$status" -eq 0 ]]; then
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] END fetch:${name}"
        else
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] FAIL fetch:${name} status=${status}"
            echo "--- ${log} ---"
            tail -n 80 "$log" || true
            fetch_failures=$((fetch_failures + 1))
        fi
    done
    active_pids=()
    active_names=()
    active_logs=()
    if [[ "$fetch_failures" -gt 0 ]]; then
        echo "${fetch_failures} fetch source(s) failed; build-lake will not start." >&2
        exit 1
    fi
}

echo "Run ID: ${RUN_ID}"
echo "Mode: ${MODE}"
echo "As-of date: ${AS_OF_DATE}"
echo "Bronze: ${BRONZE_DIR}"
echo "Silver: ${SILVER_DIR}"
echo "Gold: ${GOLD_DIR}"
echo "Dry run: ${DRY_RUN}"
echo "Force: ${FORCE}"
echo "Skip public cascade: ${SKIP_PUBLIC_CASCADE}"
echo "Fetch workers: ${FETCH_WORKERS}"
echo "Engine: ${ENGINE}"
echo "DuckDB threads: ${DUCKDB_THREADS}"
echo "DuckDB memory limit: ${DUCKDB_MEMORY_LIMIT}"
echo "DuckDB temp directory: ${DUCKDB_TEMP_DIRECTORY:-<not set>}"
echo "DuckDB max temp size: ${DUCKDB_MAX_TEMP_SIZE}"
echo "Storage format: ${STORAGE_FORMAT}"
echo "Notes mode: ${NOTES_MODE}"
echo "FSDS batch size: ${FSDS_BATCH_SIZE}"
echo "Notes batch size: ${NOTES_BATCH_SIZE}"
echo "Fresh build: ${FRESH_BUILD}"
echo "Resume: ${RESUME}"
echo "Skip setup: ${SKIP_SETUP}"

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

if [[ "$SKIP_SETUP" -eq 0 ]]; then
    run_step "setup" just setup
fi
run_step "status" just status
start_fetch "sec-bulk" ""
start_fetch "form-ap" ""
start_fetch "aaer" "${SOURCE_LIMIT_EXTRA}"
start_fetch "pcaob-inspections" "${SOURCE_LIMIT_EXTRA}"
start_fetch "fsds" "--start-year 2011 --end-year 2023 ${SOURCE_LIMIT_EXTRA}"
start_fetch "notes" "--start-year 2020 --end-year 2023 ${SOURCE_LIMIT_EXTRA}"
wait_for_all_fetches

BUILD_ARGS=(
    uv run python scripts/fetch_public_data.py
    --mode build-lake
    --bronze-dir "$BRONZE_DIR"
    --silver-dir "$SILVER_DIR"
    --gold-dir "$GOLD_DIR"
    --as-of-date "$AS_OF_DATE"
    --engine "$ENGINE"
    --duckdb-threads "$DUCKDB_THREADS"
    --duckdb-memory-limit "$DUCKDB_MEMORY_LIMIT"
    --duckdb-max-temp-size "$DUCKDB_MAX_TEMP_SIZE"
    --storage-format "$STORAGE_FORMAT"
    --notes-mode "$NOTES_MODE"
    --fsds-batch-size "$FSDS_BATCH_SIZE"
    --notes-batch-size "$NOTES_BATCH_SIZE"
)
if [[ "$ENGINE" = "duckdb" && -n "$DUCKDB_TEMP_DIRECTORY" ]]; then
    BUILD_ARGS+=(--duckdb-temp-directory "$DUCKDB_TEMP_DIRECTORY")
fi
if [[ "$FRESH_BUILD" -eq 1 ]]; then
    BUILD_ARGS+=(--fresh-build)
fi
if [[ "$RESUME" -eq 1 ]]; then
    BUILD_ARGS+=(--resume)
fi
if [[ -n "$SUBMISSIONS_MAX_CIKS" ]]; then
    BUILD_ARGS+=(--submissions-max-ciks "$SUBMISSIONS_MAX_CIKS")
fi
run_step "build-lake" "${BUILD_ARGS[@]}"

if [[ "$SKIP_PUBLIC_CASCADE" -eq 0 ]]; then
    run_step "public-cascade" uv run python scripts/run_public_cascade.py \
        --out-dir "$CASCADE_OUT" \
        --issuer-origin-panel "${GOLD_DIR}/issuer_origin_panel.parquet"
fi

run_step "final-report" uv run python scripts/monitor_public_lake.py \
    --bronze-dir "$BRONZE_DIR" \
    --silver-dir "$SILVER_DIR" \
    --gold-dir "$GOLD_DIR" \
    --log-dir "$LOG_DIR" \
    --once \
    --report-json "$LOG_DIR/run_report.json"

echo
echo "Public lake run complete. Logs: ${LOG_DIR}"
