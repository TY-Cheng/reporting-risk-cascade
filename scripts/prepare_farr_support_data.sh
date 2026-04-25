#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/prepare_farr_support_data.sh [options]

Export farr AAER and headquarters-state support data, then write diagnostic
artifacts that compare the farr AAER firm-years with the legacy benchmark,
the current bridge, and the public-cascade AAER proxy.

Options:
  --out-dir PATH          External data output directory.
                          Default: data/external
  --artifacts-dir PATH    Diagnostic artifact directory.
                          Default: artifacts/farr_support
  --raw-data PATH         Raw benchmark table.
                          Default: data/raw_dataset_misstatement.parquet
  --crosswalk PATH        GVKEY-CIK-year crosswalk.
                          Default: data/external/gvkey_cik_year.csv
  --issuer-origin PATH    Public issuer-origin panel.
                          Default: data/public_lake/gold/issuer_origin_panel.parquet
  --source-version TEXT   Override farr source version.
  --install-missing       Install the R package farr if missing.
  --repos URL             CRAN repo for --install-missing.
                          Default: https://cloud.r-project.org
  --export-only           Export farr CSV files but skip diagnostics.
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

out_dir="data/external"
artifacts_dir="artifacts/farr_support"
raw_data="data/raw_dataset_misstatement.parquet"
crosswalk="data/external/gvkey_cik_year.csv"
issuer_origin="data/public_lake/gold/issuer_origin_panel.parquet"
source_version=""
install_missing=0
repos="https://cloud.r-project.org"
run_diagnostics=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --out-dir)
      out_dir="$2"
      shift 2
      ;;
    --artifacts-dir)
      artifacts_dir="$2"
      shift 2
      ;;
    --raw-data)
      raw_data="$2"
      shift 2
      ;;
    --crosswalk)
      crosswalk="$2"
      shift 2
      ;;
    --issuer-origin)
      issuer_origin="$2"
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
    --export-only)
      run_diagnostics=0
      shift
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

mkdir -p "$out_dir" "$artifacts_dir"

r_args=("--out-dir" "$out_dir" "--repos" "$repos")
if [ "$install_missing" -eq 1 ]; then
  r_args+=("--install-missing")
fi
if [ -n "$source_version" ]; then
  r_args+=("--source-version" "$source_version")
fi

Rscript scripts/export_farr_support_data.R "${r_args[@]}"

if [ "$run_diagnostics" -eq 1 ]; then
  uv run python scripts/prepare_farr_support_data.py \
    --aaer-dates "$out_dir/farr_aaer_dates.csv" \
    --aaer-firm-year "$out_dir/farr_aaer_firm_year.csv" \
    --state-hq "$out_dir/farr_state_hq.csv" \
    --raw-data "$raw_data" \
    --crosswalk "$crosswalk" \
    --issuer-origin "$issuer_origin" \
    --out-dir "$artifacts_dir"
fi

echo "farr support exports: $out_dir"
echo "farr support diagnostics: $artifacts_dir"
