<!-- --8<-- [start:docs-home] -->
# Reporting Risk Cascade

`reporting-risk-cascade` is the code workspace for a corporate reporting-risk project.
The goal is not to run another model horse race on a static `restatement = 1`
label. The goal is to rebuild the measurement problem around label timing,
concept drift, strategic missingness, and the public review-and-correction
cascade.

**Current main claim:** with public data alone, we can model the publicly observable
review-comment-amendment-correction cascade and estimate a **pre-disclosure reporting-risk state**.
The old restatement CSV remains a benchmark and validation layer, not the sole research object.

## Project Scope

| Path | Purpose | Main files |
| --- | --- | --- |
| Benchmark | Rebuild the old firm-year restatement benchmark with label-observability, drift diagnostics, and legacy missingness checks. | `src/benchmark.py`, `scripts/run_benchmark.py`, `config/benchmark.yaml` |
| Public cascade | Build and model a filing-native SEC/PCAOB public review-and-correction cascade over comment letters, amendments, and 8-K Item 4.02; AAER matches are severity-tail descriptors. | `src/public_lake.py`, `src/public_cascade.py`, `scripts/run_public_cascade.py`, `config/public_cascade.yaml` |
| Study workflow | Run the benchmark and public cascade together, then report what is still needed for overlap validation. | `scripts/run_study.py`, `config/study.yaml` |

The detailed paper design is in `docs/paper_plan.md`. Deferred multimodal, graph,
and market-attention extensions are in `docs/future_work.md`.

## Research Spine

The current paper combines two evidence layers.

**Benchmark layer:** `data/raw_dataset_misstatement.parquet` is a `gvkey x data_year`
panel covering 2001-2019. It is converted from the legacy local
`data/raw_dataset_misstatement.csv` when needed. It is used to show why traditional
pooled restatement prediction is fragile: labels are delayed, positive rates drift,
and missingness is economically meaningful.

**Public cascade layer:** public SEC and PCAOB data are organized around filing-native
keys: `issuer_cik`, `accession/adsh`, `filing_date`, `report_date`,
`fiscal_period_end`, and `origin_date`. The cascade separates comment-letter
scrutiny, amendments, and 8-K Item 4.02 non-reliance events; AAER matches
are retained as sparse severity-tail descriptors.

The bridge still needed for final integration is a provenance-controlled
`gvkey-CIK-year` crosswalk.

## Repository Layout

```text
config/       YAML settings for benchmark, public cascade, public data, and study runs
data/         local raw inputs and ignored public-lake data
docs/         MkDocs source pages
scripts/      thin command-line wrappers and operational scripts
src/          reusable implementation modules
tests/        targeted tests for docs, public lake, and runtime surface
artifacts/    generated outputs, sample panels, logs, and run reports
doc/          local reference PDFs
```

## Local Setup

Use `just` as the front door. It loads `.env` and uses the configured external
`UV_PROJECT_ENVIRONMENT`. The visible command surface is intentionally small:
`setup`, `status`, `check`, `task`, `full`, and `docs`. Use `task` for one-off
prep, analysis, and public-data subtasks.
`just check` is the data-free local quality gate: it runs the pytest coverage
gates, `ruff`, and the strict docs build. Core runtime modules must stay at or
above 95% coverage, and the larger public-lake builder has a separate toy-data
gate at 93% so it is measured with focused public-lake behavior tests without
pretending the full lake is a fast unit-test surface.

```bash
cp .env.example .env
just setup
just status
```

The default local raw input is:

```text
data/raw_dataset_misstatement.parquet
```

If only the legacy CSV exists, convert it once:

```bash
uv run python scripts/convert_raw_dataset.py
```

The `sample` dataset used by local recipes is a deterministic firm-level subset
materialized from the local raw benchmark table. A clean GitHub checkout without
the benchmark data can run `just check` and fixture-based smoke checks, but it
cannot run benchmark, study, or full workflows until the raw benchmark Parquet or
legacy CSV is present.

## Quick Workflow

```bash
just setup
just status
just check
just task prep sample
just task benchmark raw
just task sec-bulk
just task form-ap
just task build-lake
just task cascade
just task bridge raw
just task study raw
just docs
```

Common variants:

```bash
just task benchmark raw artifacts/benchmark
just task bridge raw artifacts/bridge_probe
just task study raw artifacts/study
just docs
```

## End-to-End Workflow

`just full` is the restartable end-to-end entrypoint. It runs setup, runs the
test and lint gate, builds the public lake, then runs the combined benchmark,
public-cascade, and bridge-probe study workflow. Defaults are Mac-conservative:
two outer model workers, four
threads per model fit, two public-source fetch workers, DuckDB Parquet for the
public-lake build, `10GB` DuckDB memory, `400GB` DuckDB temp spill, FSDS batches
of four archives, and Notes batches of two archives.

For a local smoke run after the raw benchmark Parquet or legacy CSV is present:

```bash
cp .env.example .env
just status
just full smoke sample artifacts/full_smoke_sample
```

For the paper-facing run, first place the local benchmark input at
`data/raw_dataset_misstatement.parquet` or place the legacy CSV at
`data/raw_dataset_misstatement.csv` and let `just full` convert it, then run:

```bash
just full full raw artifacts/full
```

If a full public-lake build stops after Silver normalization but before Gold
panels are written, resume from the DAG markers rather than starting a fresh
build:

```bash
just full mode="full" dataset="raw" out_dir="artifacts/full" resume="1"
```

Prefer named overrides when changing performance settings:

```bash
just full mode="smoke" dataset="sample" out_dir="artifacts/full_smoke_sample" fetch_workers="2" model_jobs="2" model_threads="4" engine="duckdb" storage_format="parquet" notes_mode="summary" fresh_build="1" duckdb_memory_limit="10GB" duckdb_max_temp_size="400GB" fsds_batch_size="4" notes_batch_size="2"
```

The full public run downloads SEC/PCAOB source files and can take a long time.
Use the smoke mode first when validating a new machine or GitHub checkout.

## Public Lake Workflow

For the full public lake, use the operational script so logs and monitoring are
captured.

```bash
bash scripts/run_public_lake_full.sh --dry-run
bash scripts/run_public_lake_full.sh --mode smoke --submissions-max-ciks 200 --fetch-workers 2 --engine duckdb --duckdb-threads 4 --duckdb-memory-limit 10GB --duckdb-max-temp-size 400GB --fsds-batch-size 4 --notes-batch-size 2 --storage-format parquet --notes-mode summary --fresh-build
nohup bash scripts/run_public_lake_full.sh --mode full > artifacts/logs/public_lake_full/nohup.log 2>&1 &
```

The first full lake includes SEC bulk submissions, FSDS, Notes summaries, Form AP,
PCAOB inspections, and AAER severity-tail proxy events. Large Silver and Gold tables use
Parquet by default: `issuer_dim.parquet`, `filing_dim.parquet`,
`form_ap_event.parquet`, `xbrl_fact_summary.parquet`, batch-sharded
`xbrl_core_fact/`, `note_summary.parquet`, `issuer_origin_panel.parquet`, and
year-sharded `filing_origin_panel.parquet`. Parquet is the project default for
tables that can grow past roughly 10MB because it avoids repeated gzip CSV
decompression, keeps types stable, lets DuckDB project only needed columns, and
is much faster to resume/read in the modeling workflow. The default DuckDB build
constructs the annual `issuer_origin_panel.parquet` as the modeling panel with
XBRL core-tag features and label-horizon joins. The full
`filing_origin_panel.parquet` is kept as a lightweight filing-origin base panel
for provenance and audit, not as a 20M-row fully labeled modeling table. Small
diagnostics and human-readable summary/status files remain CSV/JSON/Markdown.
Notes raw text is skipped unless `notes_mode="raw"` is requested.

## Primary Artifacts

Benchmark:

- `artifacts/benchmark/rolling_metrics.csv`
- `artifacts/benchmark/timing_coverage.csv`
- `artifacts/benchmark/feature_family_importance.csv`
- `artifacts/benchmark/missing_profile_clusters.csv`
- `artifacts/benchmark/benchmark_summary.md`

The benchmark metrics include `naive`, `proxy_drop_observed`, and the
`proxy_imputed_lag_*y` timing-assumption grid. The imputed-lag rows are
sensitivity scenarios, not recovered detection truth.

Public cascade:

- `data/public_lake/gold/issuer_origin_panel.parquet`
- `data/public_lake/gold/filing_origin_panel.parquet`
- `artifacts/public_cascade/public_cascade_metrics.csv`
- `artifacts/public_cascade/public_cascade_predictions.parquet`
- `artifacts/public_cascade/public_opacity_dml.csv`
- `artifacts/public_cascade/public_cascade_summary.md`

The public opacity DML table uses public cascade labels as outcomes and reports
high-dimensional adjusted associations for `missingness_density_score`; it is
not a causal estimate.

Bridge probe:

- `artifacts/bridge_probe/bridge_probe_summary.json`
- `artifacts/bridge_probe/coverage_report.csv`
- `artifacts/bridge_probe/multiplicity_report.csv`
- `artifacts/bridge_probe/unmatched_raw_characteristics.csv`

External bridge input:

- `data/external/gvkey_cik_year.csv`

The repo cannot infer this table from the current benchmark panel because the
raw benchmark only has `gvkey` and `data_year`, not CIK, ticker, company name,
CUSIP, or PERMNO. SEC public ticker/CIK files are useful public identifiers, but
they are not a historical GVKEY source. Prefer an authoritative
WRDS/Compustat CIK-GVKEY link export or equivalent institutional crosswalk:

```bash
set -a; source .env; set +a
uv run python scripts/prepare_gvkey_cik_crosswalk.py \
  --input path/to/wrds_cik_gvkey_link.csv \
  --out data/external/gvkey_cik_year.csv \
  --source wrds_compustat_cik_gvkey_link \
  --source-version "YYYY-MM-DD"

just task bridge raw
```

If WRDS is not yet available, the repo can prepare a provenance-tagged bridge
candidate from the public R package `farr::gvkey_ciks`:

```bash
bash scripts/prepare_farr_gvkey_cik_bridge.sh --install-missing
```

This exports `data/external/farr_gvkey_ciks_raw.csv`, normalizes annual links to
`data/external/gvkey_cik_year.csv`, and runs the bridge probe. Treat this as a
candidate bridge whose coverage and multiplicity must be reported, not as a
silent substitute for a WRDS-verified table.

The same public package also provides useful validation and control inputs:

```bash
bash scripts/prepare_farr_support_data.sh --install-missing
```

This exports `farr::aaer_dates`, `farr::aaer_firm_year`, and `farr::state_hq`.
The AAER files are written as overlap diagnostics under
`artifacts/farr_support/`; they do not replace the main public-cascade labels.
`farr::state_hq` is used as a date-bounded, public-origin headquarters-state
metadata feature when `data/external/farr_state_hq.csv` exists.

Accepted source columns are `gvkey`, `issuer_cik` or `cik`, plus either
`data_year`/`fiscal_year`/`fyear` or `start_year` and `end_year`. The prepared
file keeps provenance fields (`source`, `source_version`, `extracted_at`,
`match_method`, `match_score`) so bridge coverage and many-to-many mappings stay
auditable.

Study:

- `artifacts/study/benchmark/`
- `artifacts/study/public_cascade/`
- `artifacts/study/bridge_probe/`
- `artifacts/study/study_run_manifest.json`
- `artifacts/study/study_summary.md`

## Current Gates

1. Treat the full public-cascade run as the current `xbrl_ratio_baseline` snapshot.
2. Use `farr::gvkey_ciks` as the current high-coverage candidate bridge when WRDS
   is unavailable, while still reporting coverage and multiplicity explicitly.
3. Treat the bridge gate as mandatory for an integrated old-benchmark/public-cascade
   paper; without it, the paper should remain a public review-and-correction measurement
   paper rather than a validated fraud/restatement overlap paper.
<!-- --8<-- [end:docs-home] -->
