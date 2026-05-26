#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/prepare_farr_gvkey_cik_bridge.sh [options]

Export farr::gvkey_ciks and normalize it to DATA_DIR/external/gvkey_cik_year.csv.
The default integration bridge remains DATA_DIR/linkage/raw_only and is not
supplemented by this farr export.

Options:
  --raw-out PATH          Raw farr export path.
                          Default: DATA_DIR/external/farr_gvkey_ciks_raw.csv
  --out PATH              Normalized annual crosswalk path.
                          Default: DATA_DIR/external/gvkey_cik_year.csv
  --summary-json PATH     Crosswalk summary JSON.
                          Default: ARTIFACTS_DIR/bridge_crosswalk/farr_crosswalk_summary.json
  --as-of-year YEAR       End year for open-ended links.
                          Default: current calendar year
  --source-version TEXT   Override farr source version.
  --install-missing       Install the R package farr if missing.
  --repos URL             CRAN repo for --install-missing.
                          Default: https://cloud.r-project.org
  --no-raw-filter         Do not restrict link years to raw benchmark years.
  --skip-bridge-probe     Prepare the crosswalk but do not run just task bridge.
  --bridge-out-dir PATH   Bridge probe output directory.
                          Default: ARTIFACTS_DIR/bridge_probe
  --help                  Show this message.
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  . ".env"
  set +a
fi

if [ -z "${UV_PROJECT_ENVIRONMENT:-}" ]; then
  echo "UV_PROJECT_ENVIRONMENT is missing in .env" >&2
  exit 1
fi

physical_path() {
  python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$1"
}

repo_root_real="$(physical_path "${repo_root}")"

require_absolute_path() {
  local name="$1"
  local value="$2"
  case "${value}" in
    /*) ;;
    *)
      echo "${name} must be an absolute path, got: ${value}" >&2
      exit 1
      ;;
  esac
}

require_outside_repo() {
  local name="$1"
  local value="$2"
  local value_real
  require_absolute_path "${name}" "${value}"
  value_real="$(physical_path "${value}")"
  case "${value_real}" in
    "${repo_root_real}"|"${repo_root_real}/"*)
      echo "${name} must point outside this repo, got: ${value}" >&2
      exit 1
      ;;
  esac
}

require_outside_repo "UV_PROJECT_ENVIRONMENT" "${UV_PROJECT_ENVIRONMENT}"
mkdir -p "$(dirname "${UV_PROJECT_ENVIRONMENT}")"

if [ -z "${DATA_DIR:-}" ]; then
  echo "DATA_DIR is missing in .env; farr bridge data must be written to the external data root." >&2
  exit 1
fi
require_outside_repo "DATA_DIR" "${DATA_DIR}"

ARTIFACTS_DIR="${ARTIFACTS_DIR:-${repo_root}/artifacts}"
case "${ARTIFACTS_DIR}" in
  /*) ;;
  *)
    echo "ARTIFACTS_DIR must be an absolute path, got: ${ARTIFACTS_DIR}" >&2
    exit 1
    ;;
esac

raw_out="${DATA_DIR}/external/farr_gvkey_ciks_raw.csv"
out="${DATA_DIR}/external/gvkey_cik_year.csv"
summary_json="${ARTIFACTS_DIR}/bridge_crosswalk/farr_crosswalk_summary.json"
as_of_year="$(date +%Y)"
source_version=""
install_missing=0
repos="https://cloud.r-project.org"
no_raw_filter=0
run_bridge_probe=1
bridge_out_dir="${ARTIFACTS_DIR}/bridge_probe"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --raw-out)
      raw_out="$2"
      shift 2
      ;;
    --out)
      out="$2"
      shift 2
      ;;
    --summary-json)
      summary_json="$2"
      shift 2
      ;;
    --as-of-year)
      as_of_year="$2"
      shift 2
      ;;
    --source-version)
      source_version="$2"
      shift 2
      ;;
    --install-missing)
      install_missing=1
      shift
      ;;
    --repos)
      repos="$2"
      shift 2
      ;;
    --no-raw-filter)
      no_raw_filter=1
      shift
      ;;
    --skip-bridge-probe)
      run_bridge_probe=0
      shift
      ;;
    --bridge-out-dir)
      bridge_out_dir="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$(dirname "$raw_out")" "$(dirname "$out")" "$(dirname "$summary_json")"

r_args=(
  "--out" "$raw_out"
  "--as-of-year" "$as_of_year"
  "--repos" "$repos"
)
if [ "$install_missing" -eq 1 ]; then
  r_args+=("--install-missing")
fi
if [ -n "$source_version" ]; then
  r_args+=("--source-version" "$source_version")
fi

Rscript scripts/export_farr_gvkey_ciks.R "${r_args[@]}"

python_args=(
  "--input" "$raw_out"
  "--out" "$out"
  "--source" "farr_gvkey_ciks"
  "--match-method" "farr_gvkey_ciks_date_range"
  "--summary-json" "$summary_json"
)
if [ -n "$source_version" ]; then
  python_args+=("--source-version" "$source_version")
fi
if [ "$no_raw_filter" -eq 1 ]; then
  python_args+=("--no-raw-filter")
fi

uv run python scripts/prepare_gvkey_cik_crosswalk.py "${python_args[@]}"
uv run python scripts/build_linkage_bridge.py

if [ "$run_bridge_probe" -eq 1 ]; then
  just task bridge raw "$bridge_out_dir"
fi

echo "Raw farr export: $raw_out"
echo "Normalized crosswalk: $out"
echo "Raw-only bridge: ${DATA_DIR}/linkage/raw_only/gvkey_cik_year.csv"
echo "Crosswalk summary: $summary_json"
