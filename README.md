<!-- --8<-- [start:docs-home] -->
# Reporting Risk Cascade

`reporting-risk-cascade` is the code workspace for a corporate reporting-risk project.
The goal is not to run another model horse race on a static `restatement = 1`
label. The goal is to rebuild the measurement problem around label timing,
concept drift, strategic missingness, and the public scrutiny-correction-
enforcement cascade.

**Current main claim:** with public data alone, we can model the publicly observable
review-comment-amendment-enforcement cascade and estimate a **pre-disclosure reporting-risk state**.
The old restatement CSV remains a benchmark and validation layer, not the sole research object.

## What This Repo Does

| Path | Purpose | Main files |
| --- | --- | --- |
| Benchmark | Rebuild the old firm-year restatement benchmark with label maturation, drift diagnostics, missingness regimes, and DML-style adjustment. | `src/benchmark.py`, `scripts/run_benchmark.py`, `config/benchmark.yaml` |
| Public cascade | Build and model a filing-native SEC/PCAOB public cascade over comment letters, amendments, 8-K Item 4.02, and AAER proxy events. | `src/public_lake.py`, `src/public_cascade.py`, `scripts/run_public_cascade.py`, `config/public_cascade.yaml` |
| Study workflow | Run the benchmark and public cascade together, then report what is still needed for overlap validation. | `scripts/run_study.py`, `config/study.yaml` |

The detailed paper design is in `docs/paper_plan.md`. Deferred multimodal, graph,
and market-attention extensions are in `docs/future_work.md`.

## Research Spine

The current paper combines two evidence layers.

**Benchmark layer:** `data/raw_dataset_misstatement.csv` is a `gvkey x data_year`
panel covering 2001-2019. It is used to show why traditional pooled restatement
prediction is fragile: labels are delayed, positive rates drift, and missingness is
economically meaningful.

**Public cascade layer:** public SEC and PCAOB data are organized around filing-native
keys: `issuer_cik`, `accession/adsh`, `filing_date`, `report_date`,
`fiscal_period_end`, and `origin_date`. The cascade separates comment-letter
scrutiny, amendments, 8-K Item 4.02 non-reliance events, and AAER proxy events.

The bridge still needed for final integration is a provenance-controlled
`gvkey-CIK-year` crosswalk.

## Layout

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

## Setup

Use `just` as the front door. It loads `.env`, uses the configured external
`UV_PROJECT_ENVIRONMENT`, and runs `ruff` after mutating or analysis recipes.

```bash
cp .env.example .env
just setup
just status
```

The required local raw input is:

```text
data/raw_dataset_misstatement.csv
```

## 5-Minute Workflow

```bash
just setup
just status
just run sample
just analysis benchmark raw
just fetch sec-bulk
just fetch form-ap
just fetch build-lake
just analysis cascade
just analysis bridge raw
just analysis study raw
just docs
```

Common variants:

```bash
just analysis benchmark raw artifacts/benchmark
just analysis bridge raw artifacts/bridge_probe
just analysis study raw artifacts/study
just docs
```

## Public Lake Run

For the full public lake, use the operational script so logs and monitoring are
captured.

```bash
bash scripts/run_public_lake_full.sh --dry-run
bash scripts/run_public_lake_full.sh --mode smoke --submissions-max-ciks 200
nohup bash scripts/run_public_lake_full.sh --mode full > artifacts/logs/public_lake_full/nohup.log 2>&1 &
```

The first full lake includes SEC bulk submissions, FSDS, Notes, Form AP, PCAOB
inspections, and AAER proxy events. It intentionally excludes raw filing HTML, 13F,
insider transactions, EDGAR logs, and market-structure data until the gold panel
coverage is validated.

## Main Outputs

Benchmark:

- `artifacts/benchmark/rolling_metrics.csv`
- `artifacts/benchmark/feature_family_importance.csv`
- `artifacts/benchmark/missing_profile_clusters.csv`
- `artifacts/benchmark/benchmark_summary.md`

Public cascade:

- `data/public_lake/gold/issuer_origin_panel.csv.gz`
- `data/public_lake/gold/filing_origin_panel.csv.gz`
- `artifacts/public_cascade/public_cascade_metrics.csv`
- `artifacts/public_cascade/public_cascade_summary.md`

Bridge probe:

- `artifacts/bridge_probe/bridge_probe_summary.json`
- `artifacts/bridge_probe/coverage_report.csv`
- `artifacts/bridge_probe/multiplicity_report.csv`
- `artifacts/bridge_probe/unmatched_raw_characteristics.csv`

Study:

- `artifacts/study/benchmark/`
- `artifacts/study/public_cascade/`
- `artifacts/study/bridge_probe/`
- `artifacts/study/study_run_manifest.json`
- `artifacts/study/study_summary.md`

## Current Priorities

1. Audit and enrich the existing public lake with core `xbrl_ratio_*` features.
2. Run benchmark timing-coverage outputs and public cascade readiness summaries.
3. Run the public-only bridge probe and report `raw_identifier_blocker`, coverage, and
   multiplicity instead of guessing crosswalks.
4. Use XBRL baseline plus bridge-probe evidence to decide whether the project remains one
   integrated paper or splits into benchmark critique and public cascade papers.
<!-- --8<-- [end:docs-home] -->
