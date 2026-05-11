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
AAER high-severity enforcement indicators.

## Research Object

| Layer | Unit | Role |
| --- | --- | --- |
| Legacy benchmark | `gvkey x data_year` | Diagnostic benchmark for detected-misstatement labels, timing assumptions, concept drift, and missingness. |
| Public lake | SEC/PCAOB filings and events | Public-data construction layer for filings, XBRL, Notes summaries, Form AP, PCAOB inspections, comment letters, amendments, 8-K Item 4.02, and AAER support data. |
| Public cascade | `issuer_cik x fiscal_year` | Main filing-origin prediction target for public review-and-correction risk. |
| Bridge validation | `gvkey-CIK-year` | Construct-overlap layer linking legacy detected-misstatement labels to public cascade labels and scores. |

Documentation site: [Reporting Risk Cascade](https://ty-cheng.github.io/reporting-risk-cascade/).
The detailed research design is in [Paper Plan](https://ty-cheng.github.io/reporting-risk-cascade/paper_plan/).
The static run interpretation is in [Results Snapshot](https://ty-cheng.github.io/reporting-risk-cascade/results_snapshot/).
Deferred extensions are in [Future Work](https://ty-cheng.github.io/reporting-risk-cascade/future_work/).

## Public Review-and-Correction Labels

The public cascade is a multi-label outcome design. These labels are public observability states, not alternative names for fraud.

| Label | Horizon | Interpretation | Primary public source |
| --- | ---: | --- | --- |
| `label_comment_thread_365` | 365 days | SEC comment-letter scrutiny after the filing origin. | [SEC filing review process](https://www.sec.gov/about/divisions-offices/division-corporation-finance/filing-review-process-corp-fin) and public EDGAR correspondence. |
| `label_amendment_365` | 365 days | Amended filing, correction, or filing-friction signal. | [SEC EDGAR filing access](https://www.sec.gov/edgar/search-and-access) and amended filing form metadata. |
| `label_8k_402_365` | 365 days | Item 4.02 non-reliance or material-correction signal. | [SEC Form 8-K](https://www.sec.gov/files/form8-k.pdf), Item 4.02. |
| `label_aaer_proxy_730` | 730 days | Rare high-severity enforcement indicator. | [SEC Accounting and Auditing Enforcement Releases](https://www.sec.gov/enforcement-litigation/accounting-auditing-enforcement-releases) and `farr::aaer_*` support data. |

AAER is retained as high-severity enforcement evidence because it is sparse and selective;
it is not the headline prediction target.

## Repository Layout

```text
config/       YAML settings for benchmark, public cascade, public data, and study runs
docs/         MkDocs source pages
scripts/      thin command-line wrappers and operational scripts
src/          reusable implementation modules
tests/        tests for runtime behavior, docs, public lake, and model contracts
doc/          local reference PDFs
```

## Setup

Use `just` as the stable command surface. It loads `.env` and uses the external
`UV_PROJECT_ENVIRONMENT` configured for this machine.

```bash
cp .env.example .env
# Fill PROJECT_ROOT/DOCS_DIR/PAPER_DIR/ARTIFACTS_DIR for this checkout,
# and keep DATA_DIR on the external drive.
just setup
just status
```

This checkout should not contain a repo-local `data/` directory or symlink.
Data engineering paths come from `.env`: `DATA_DIR` holds raw/public-lake data,
and `ARTIFACTS_DIR` holds generated outputs, sample panels, logs, and run
reports. `ARTIFACTS_DIR` can be repo-local `artifacts/` because it is small and
gitignored; `DATA_DIR` should stay external.
For direct shell commands that use `$DATA_DIR` or `$ARTIFACTS_DIR`, source the
local environment first with `set -a; source .env; set +a`.

The default benchmark input is:

```text
$DATA_DIR/raw_dataset_misstatement.parquet
```

If only the legacy CSV or ZIP exists, keep it at one of these paths and
materialize the Parquet once:

```text
$DATA_DIR/raw_dataset_misstatement.csv
$DATA_DIR/raw_dataset_misstatement.zip
$DATA_DIR/external/raw_dataset_misstatement.zip
```

```bash
uv run python scripts/convert_raw_dataset.py
```

A clean GitHub checkout without the benchmark data can run `just check` and
fixture-based smoke checks. Benchmark, study, and full workflows require the
raw benchmark Parquet or a materializable legacy CSV/ZIP.

## Execution Contract

Quality gate:

```bash
just check
```

`just check` is data-free. It runs the core pytest coverage gate, the focused
public-lake coverage gate, `ruff`, and the strict MkDocs build. Core runtime
modules must remain at or above 95% coverage; the larger public-lake builder has
a separate 93% toy-data gate.

Data-engineering only:

```bash
just data
just data smoke
just data full force
```

`just data` materializes the raw benchmark Parquet from CSV/ZIP when needed and
builds the public lake without running the model study. The optional second
argument controls refresh behavior: `fresh` rebuilds silver/gold from cached
bronze, `resume` reuses DAG markers, and `force` re-downloads public source
payloads before rebuilding.

Paper-facing core run:

```bash
just full mode=full dataset=raw
```

This runs setup, tests, lint, public-lake build or resume, and the core study
components: benchmark, public cascade, bridge probe, and construct-overlap
validation when inputs exist. If a full build has already completed earlier
stages, resume from DAG markers:

```bash
just full mode=full dataset=raw resume=1
```

Peer-compatible model-family transfer:

```bash
just task study raw artifacts/full_with_peer \
  extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
```

This reruns the study layer against the completed public lake and adds the
legacy benchmark peer suite plus the public-label peer transfer suite on
`issuer_origin_panel.parquet`. The public peer suite covers `comment_thread`,
`amendment`, and `8k_402`; `aaer_proxy` remains a sparse high-severity status.
Use `--peer-target public` to refresh public-label peer outputs without rerunning
the legacy benchmark peer suite.

Refresh the docs snapshot and run the full quality gate after the peer run:

```bash
just snapshot
```

`just snapshot` regenerates `docs/results_snapshot.md` from
`artifacts/full_with_peer` and then runs `just check`. For a non-peer current
study snapshot, use `just snapshot artifacts/study allow_partial=1`.

Build paper-facing tables, figures, and result prose:

```bash
just manuscript
```

This reads `artifacts/full_with_peer` and writes
`artifacts/manuscript_package` with CSV/Markdown/LaTeX tables, PNG/PDF figures,
and a manuscript-results narrative.

Component reruns:

```bash
just task benchmark raw
just task cascade raw
just task bridge raw
just task study raw
just snapshot
```

`just docs` first runs a strict clean MkDocs build, then serves the site on the
first free local port in `8001-8010`.

## Public Lake

For the full public lake, use the operational script so logs and monitoring are
captured:

```bash
bash scripts/run_public_lake_full.sh --dry-run
bash scripts/run_public_lake_full.sh --mode smoke --submissions-max-ciks 200 --fetch-workers 2 --engine duckdb --duckdb-threads 4 --duckdb-memory-limit 10GB --duckdb-max-temp-size 400GB --fsds-batch-size 4 --notes-batch-size 2 --storage-format parquet --notes-mode summary --fresh-build
set -a; source .env; set +a
nohup bash scripts/run_public_lake_full.sh --mode full > "$ARTIFACTS_DIR/logs/public_lake_full/nohup.log" 2>&1 &
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

- `artifacts/full_with_peer/benchmark/rolling_metrics.csv`
- `artifacts/full_with_peer/benchmark/timing_coverage.csv`
- `artifacts/full_with_peer/benchmark/feature_family_importance.csv`
- `artifacts/full_with_peer/benchmark/missing_profile_clusters.csv`
- `artifacts/full_with_peer/benchmark/benchmark_summary.md`

Public cascade:

- `$DATA_DIR/public_lake/gold/issuer_origin_panel.parquet`
- `$DATA_DIR/public_lake/gold/filing_origin_panel.parquet`
- `artifacts/full_with_peer/public_cascade/public_cascade_metrics.csv`
- `artifacts/full_with_peer/public_cascade/public_cascade_predictions.parquet`
- `artifacts/full_with_peer/public_cascade/public_opacity_dml.csv`
- `artifacts/full_with_peer/public_cascade/public_cascade_summary.md`

Bridge and construct overlap:

- `artifacts/full_with_peer/bridge_probe/bridge_probe_summary.json`
- `artifacts/full_with_peer/bridge_probe/coverage_report.csv`
- `artifacts/full_with_peer/bridge_probe/multiplicity_report.csv`
- `artifacts/full_with_peer/construct_overlap/construct_overlap_summary.md`
- `artifacts/full_with_peer/construct_overlap/public_score_legacy_ranking.csv`
- `artifacts/full_with_peer/construct_overlap/reciprocal_alignment.csv`

Peer-compatible model-family suites:

- `artifacts/full_with_peer/peer_comparison/`
- `artifacts/full_with_peer/public_peer_comparison/`

Manuscript package:

- `artifacts/manuscript_package/results_narrative.md`
- `artifacts/manuscript_package/tables/`
- `artifacts/manuscript_package/figures/`

## Bridge Inputs

The integration bridge is:

```text
$DATA_DIR/external/gvkey_cik_year.csv
```

The repo cannot infer this table from the legacy benchmark alone because the
benchmark has `gvkey` and `data_year`, but not CIK, ticker, company name, CUSIP,
or PERMNO. Prefer a WRDS/Compustat CIK-GVKEY link export or equivalent
institutional crosswalk:

```bash
set -a; source .env; set +a
uv run python scripts/prepare_gvkey_cik_crosswalk.py \
  --input path/to/wrds_cik_gvkey_link.csv \
  --out "$DATA_DIR/external/gvkey_cik_year.csv" \
  --source wrds_compustat_cik_gvkey_link \
  --source-version "YYYY-MM-DD"

just task bridge raw
```

After replacing the bridge file in a peer-enabled study directory, refresh the
bridge probe and construct-overlap layer without refitting models:

```bash
just task bridge raw artifacts/full_with_peer/bridge_probe
uv run python scripts/run_construct_overlap.py --study-dir artifacts/full_with_peer
```

When WRDS is unavailable, prepare a provenance-tagged candidate bridge from
`farr::gvkey_ciks`:

```bash
bash scripts/prepare_farr_gvkey_cik_bridge.sh --install-missing
```

This exports `$DATA_DIR/external/farr_gvkey_ciks_raw.csv`, normalizes annual links to
`$DATA_DIR/external/gvkey_cik_year.csv`, and runs the bridge probe. Treat this as a
candidate bridge whose coverage and multiplicity must be reported, not as a
silent substitute for a WRDS-verified table.

The same package provides support inputs:

```bash
bash scripts/prepare_farr_support_data.sh --install-missing
```

This exports `farr::aaer_dates`, `farr::aaer_firm_year`, and `farr::state_hq`.
The AAER files support high-severity overlap diagnostics; they do not replace
the main public-cascade labels. `farr::state_hq` is used as a date-bounded,
public-origin headquarters-state metadata feature when
`$DATA_DIR/external/farr_state_hq.csv` exists.

Accepted crosswalk columns are `gvkey`, `issuer_cik` or `cik`, plus either
`data_year`/`fiscal_year`/`fyear` or `start_year` and `end_year`. Prepared files
retain provenance fields: `source`, `source_version`, `extracted_at`,
`match_method`, and `match_score`.

Construct-overlap validation reads those provenance fields to infer
`validation_tier`: farr exports remain `candidate_farr`, while WRDS/Compustat
source or match-method provenance is reported as `wrds_validated`. Mixed
WRDS/farr crosswalks remain candidate evidence until the mixed-source rows are
resolved.

## Current Gates

1. The public-cascade run is the current non-metadata `xbrl_ratio_baseline`
   snapshot.
2. `farr::gvkey_ciks` is the current high-coverage candidate bridge when WRDS is
   unavailable; coverage, multiplicity, and inferred validation tier must be
   reported.
3. Candidate bridge overlap can support a related-but-non-identical construct
   argument. The construct-overlap manifest should move from `candidate_farr` to
   `wrds_validated` only after a provenance-tagged WRDS or equivalent crosswalk
   is supplied and the overlap layer is rerun.
4. AAER is a high-severity enforcement descriptor and robustness anchor, not the headline
   prediction target.
<!-- --8<-- [end:docs-home] -->
