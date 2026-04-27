<!-- --8<-- [start:docs-home] -->
# Reporting Risk Cascade

`reporting-risk-cascade` is a reproducible research workspace for measuring
corporate reporting risk at the filing origin. The project studies whether a
publicly observable review-and-correction process can be predicted from
information available when an issuer files, rather than treating an ex post
detected misstatement label as the only empirical target.

The current paper has two linked evidence layers. The legacy benchmark layer
uses a `gvkey x data_year` detected-misstatement panel to diagnose timing,
observability, drift, and missingness. The public cascade layer builds an
issuer-year panel from SEC and PCAOB sources and predicts subsequent public
scrutiny, amendment or filing friction, Item 4.02 non-reliance, and rare
AAER severity-tail events.

## Research Object

| Layer | Unit | Role |
| --- | --- | --- |
| Legacy benchmark | `gvkey x data_year` | Diagnostic benchmark for detected-misstatement labels, timing assumptions, concept drift, and missingness. |
| Public lake | SEC/PCAOB filings and events | Public-data construction layer for filings, XBRL, Notes summaries, Form AP, PCAOB inspections, comment letters, amendments, 8-K Item 4.02, and AAER support data. |
| Public cascade | `issuer_cik x fiscal_year` | Main filing-origin prediction target for public review-and-correction risk. |
| Bridge validation | `gvkey-CIK-year` | Construct-overlap layer linking legacy detected-misstatement labels to public cascade labels and scores. |

The detailed research design is in [Paper Plan](paper_plan.md).
The static run interpretation is in [Results Snapshot](results_snapshot.md).
Deferred extensions are in [Future Work](future_work.md).

## Public Review-And-Correction Labels

The public cascade is a multi-label outcome design. These labels are public observability states, not alternative names for fraud.

| Label | Horizon | Interpretation | Primary public source |
| --- | ---: | --- | --- |
| `label_comment_thread_365` | 365 days | SEC comment-letter scrutiny after the filing origin. | [SEC filing review process](https://www.sec.gov/about/divisions-offices/division-corporation-finance/filing-review-process-corp-fin) and public EDGAR correspondence. |
| `label_amendment_365` | 365 days | Amended filing, correction, or filing-friction signal. | [SEC EDGAR filing access](https://www.sec.gov/edgar/search-and-access) and amended filing form metadata. |
| `label_8k_402_365` | 365 days | Item 4.02 non-reliance or material-correction signal. | [SEC Form 8-K](https://www.sec.gov/files/form8-k.pdf), Item 4.02. |
| `label_aaer_proxy_730` | 730 days | Rare enforcement severity-tail descriptor. | [SEC Accounting and Auditing Enforcement Releases](https://www.sec.gov/enforcement-litigation/accounting-auditing-enforcement-releases) and `farr::aaer_*` support data. |

AAER is retained as severity-tail evidence because it is sparse and selective;
it is not the headline prediction target.

## Repository Layout

```text
config/       YAML settings for benchmark, public cascade, public data, and study runs
data/         local raw inputs and ignored public-lake data
docs/         MkDocs source pages
scripts/      thin command-line wrappers and operational scripts
src/          reusable implementation modules
tests/        tests for runtime behavior, docs, public lake, and model contracts
artifacts/    generated outputs, sample panels, logs, and run reports
doc/          local reference PDFs
```

## Setup

Use `just` as the stable command surface. It loads `.env` and uses the external
`UV_PROJECT_ENVIRONMENT` configured for this machine.

```bash
cp .env.example .env
just setup
just status
```

The default local benchmark input is:

```text
data/raw_dataset_misstatement.parquet
```

If only the legacy CSV exists, convert it once:

```bash
uv run python scripts/convert_raw_dataset.py
```

A clean GitHub checkout without the benchmark data can run `just check` and
fixture-based smoke checks. Benchmark, study, and full workflows require the
raw benchmark Parquet or the legacy CSV.

## Execution Contract

Quality gate:

```bash
just check
```

`just check` is data-free. It runs the core pytest coverage gate, the focused
public-lake coverage gate, `ruff`, and the strict MkDocs build. Core runtime
modules must remain at or above 95% coverage; the larger public-lake builder has
a separate 93% toy-data gate.

Paper-facing core run:

```bash
just full full raw artifacts/full
```

This runs setup, tests, lint, public-lake build or resume, and the core study
components: benchmark, public cascade, bridge probe, and construct-overlap
validation when inputs exist. If a full build has already completed earlier
stages, resume from DAG markers:

```bash
just full mode=full dataset=raw out_dir=artifacts/full resume=1
```

Peer-compatible model-family transfer:

```bash
just task study raw artifacts/full_with_peer \
  extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
```

This reruns the study layer against the completed public lake and adds the
legacy benchmark peer suite plus the public-label peer transfer suite on
`issuer_origin_panel.parquet`. The public peer suite covers `comment_thread`,
`amendment`, and `8k_402`; `aaer_proxy` remains a sparse severity-tail status.
Use `--peer-target public` to refresh public-label peer outputs without rerunning
the legacy benchmark peer suite.

Component reruns:

```bash
just task benchmark raw artifacts/benchmark
just task cascade raw artifacts/public_cascade
just task bridge raw artifacts/bridge_probe
just task study raw artifacts/study
uv run python scripts/run_construct_overlap.py --study-dir artifacts/full_with_peer
just docs
```

`just docs` first runs a strict clean MkDocs build, then serves the site on the
first free local port in `8001-8010`.

## Public Lake

For the full public lake, use the operational script so logs and monitoring are
captured:

```bash
bash scripts/run_public_lake_full.sh --dry-run
bash scripts/run_public_lake_full.sh --mode smoke --submissions-max-ciks 200 --fetch-workers 2 --engine duckdb --duckdb-threads 4 --duckdb-memory-limit 10GB --duckdb-max-temp-size 400GB --fsds-batch-size 4 --notes-batch-size 2 --storage-format parquet --notes-mode summary --fresh-build
nohup bash scripts/run_public_lake_full.sh --mode full > artifacts/logs/public_lake_full/nohup.log 2>&1 &
```

Large Silver and Gold tables use Parquet by default:
`issuer_dim.parquet`, `filing_dim.parquet`, `form_ap_event.parquet`,
`xbrl_fact_summary.parquet`, batch-sharded `xbrl_core_fact/`,
`note_summary.parquet`, `issuer_origin_panel.parquet`, and year-sharded
`filing_origin_panel.parquet`. Parquet is the default for tables that can grow
past roughly 10MB because it avoids repeated gzip CSV decompression, preserves
types, and lets DuckDB project only needed columns.

Small diagnostics and human-readable status files remain CSV, JSON, or
Markdown. Notes raw text is skipped unless `notes_mode="raw"` is requested.

## Primary Artifacts

Benchmark:

- `artifacts/benchmark/rolling_metrics.csv`
- `artifacts/benchmark/timing_coverage.csv`
- `artifacts/benchmark/feature_family_importance.csv`
- `artifacts/benchmark/missing_profile_clusters.csv`
- `artifacts/benchmark/benchmark_summary.md`

Public cascade:

- `data/public_lake/gold/issuer_origin_panel.parquet`
- `data/public_lake/gold/filing_origin_panel.parquet`
- `artifacts/public_cascade/public_cascade_metrics.csv`
- `artifacts/public_cascade/public_cascade_predictions.parquet`
- `artifacts/public_cascade/public_opacity_dml.csv`
- `artifacts/public_cascade/public_cascade_summary.md`

Bridge and construct overlap:

- `artifacts/bridge_probe/bridge_probe_summary.json`
- `artifacts/bridge_probe/coverage_report.csv`
- `artifacts/bridge_probe/multiplicity_report.csv`
- `artifacts/full_with_peer/construct_overlap/construct_overlap_summary.md`
- `artifacts/full_with_peer/construct_overlap/public_score_legacy_ranking.csv`
- `artifacts/full_with_peer/construct_overlap/reciprocal_alignment.csv`

Peer-compatible model-family suites:

- `artifacts/full_with_peer/peer_comparison/`
- `artifacts/full_with_peer/public_peer_comparison/`

## Bridge Inputs

The integration bridge is:

```text
data/external/gvkey_cik_year.csv
```

The repo cannot infer this table from the legacy benchmark alone because the
benchmark has `gvkey` and `data_year`, but not CIK, ticker, company name, CUSIP,
or PERMNO. Prefer a WRDS/Compustat CIK-GVKEY link export or equivalent
institutional crosswalk:

```bash
set -a; source .env; set +a
uv run python scripts/prepare_gvkey_cik_crosswalk.py \
  --input path/to/wrds_cik_gvkey_link.csv \
  --out data/external/gvkey_cik_year.csv \
  --source wrds_compustat_cik_gvkey_link \
  --source-version "YYYY-MM-DD"

just task bridge raw
```

When WRDS is unavailable, prepare a provenance-tagged candidate bridge from
`farr::gvkey_ciks`:

```bash
bash scripts/prepare_farr_gvkey_cik_bridge.sh --install-missing
```

This exports `data/external/farr_gvkey_ciks_raw.csv`, normalizes annual links to
`data/external/gvkey_cik_year.csv`, and runs the bridge probe. Treat this as a
candidate bridge whose coverage and multiplicity must be reported, not as a
silent substitute for a WRDS-verified table.

The same package provides support inputs:

```bash
bash scripts/prepare_farr_support_data.sh --install-missing
```

This exports `farr::aaer_dates`, `farr::aaer_firm_year`, and `farr::state_hq`.
The AAER files support severity-tail overlap diagnostics; they do not replace
the main public-cascade labels. `farr::state_hq` is used as a date-bounded,
public-origin headquarters-state metadata feature when
`data/external/farr_state_hq.csv` exists.

Accepted crosswalk columns are `gvkey`, `issuer_cik` or `cik`, plus either
`data_year`/`fiscal_year`/`fyear` or `start_year` and `end_year`. Prepared files
retain provenance fields: `source`, `source_version`, `extracted_at`,
`match_method`, and `match_score`.

## Current Gates

1. The public-cascade run is the current non-metadata `xbrl_ratio_baseline`
   snapshot.
2. `farr::gvkey_ciks` is the current high-coverage candidate bridge when WRDS is
   unavailable; coverage and multiplicity must be reported.
3. Candidate bridge overlap can support a related-but-non-identical construct
   argument. WRDS or equivalent validation remains preferred for final
   manuscript-grade integrated claims.
4. AAER is a severity-tail descriptor and robustness anchor, not the headline
   prediction target.
<!-- --8<-- [end:docs-home] -->
