<!-- --8<-- [start:docs-home] -->
# cls_miss

Code workspace for firm-year accounting misstatement classification experiments.
The sibling directory `../cls_miss_manuscript/` is reserved for paper writing.

## Local inputs

- `data/raw_dataset_misstatement.csv`: full firm-year panel with 82,908 rows, 9,156
  firms, 2001-2019 coverage, and 86 columns including the binary target
  `misstatement firm-year`.
- `doc/s11142-020-09563-8.pdf`: source paper describing the prediction problem,
  feature families, and benchmark framing.
- There is no checked-in sample CSV. `just smoke-sample` materializes a deterministic
  500-firm sample under `artifacts/sample_dataset_misstatement.csv` at runtime.

## Layout

- `src/`: reusable project code.
- `scripts/`: thin wrappers for repeatable local runs.
- `config/`: YAML configuration for data prep and evaluation settings.
- `artifacts/`: generated sample datasets and run outputs.
- `data/public/`: fetched SEC and PCAOB public inputs (ignored by git).
- `docs/`: reserved for future MkDocs source pages; intentionally light for now.
- `doc/`: local reference material such as the source paper PDF.

## Current runtime state

- `src/data_prep.py` loads the CSV, infers schema, performs an out-of-time test
  split, builds CV folds, and writes baseline artifacts.
- `src/paper1.py` now implements the first paper spine:
  matured-label fallback timing, rolling backtests, drift diagnostics, missing-profile
  clustering, DML-style adjustment, and retraining recommendations.
- `src/public_data.py` and `src/paper2.py` now implement the public-data and
  lightweight multimodal spine for the second paper:
  SEC reference fetches, filing indexes, filing downloads, section parsing,
  cheap text features, compact CPU-friendly embeddings, and PCAOB Form AP
  monitoring aggregates.
- `scripts/generate_sample_dataset.py` creates a deterministic firm-level sample
  panel for quick smoke runs.

## Setup

1. Copy `.env.example` to `.env` and fill in repo-local absolute paths.
2. Set `DIR_MANUSCRIPT` to the sibling manuscript workspace.
3. Run `just setup` to lock and sync the external uv environment declared in
   `.env`.

## Main workflow

```bash
just setup
just status
just run dataset=sample
just analysis stage=paper1 dataset=raw
just fetch source=references
just check
just docs build
```

The canonical local workflow is `just` rather than ad hoc `uv` calls, because
`justfile` loads `.env` and therefore uses the intended `UV_PROJECT_ENVIRONMENT`.

## Just entrypoints

```bash
just setup
just status
just run dataset=sample
just run dataset=raw
just analysis stage=paper1 dataset=raw
just fetch source=references
just check dataset=raw
just format
just docs build
just docs serve
```

## Paper 1 workflow

```bash
just analysis stage=paper1 dataset=raw
just analysis stage=paper1 dataset=raw out_dir=artifacts/paper1_with_timing extra="--timing-csv path/to/restatement_timing.csv"
```

Outputs include:

- `artifacts/paper1/master_panel.csv.gz`
- `artifacts/paper1/rolling_metrics.csv`
- `artifacts/paper1/feature_family_importance.csv`
- `artifacts/paper1/missing_profile_clusters.csv`
- `artifacts/paper1/dml_result.json`
- `artifacts/paper1/recommendation.json`
- `artifacts/paper1/paper1_summary.md`

## Paper 2 public-data workflow

```bash
just fetch source=references
just fetch source=sec-index extra="--master-panel artifacts/paper1/master_panel.csv.gz --gvkey-cik-csv path/to/gvkey_cik.csv"
just fetch source=sec-download extra="--out-csv data/public/sec/sec_filing_index.csv --limit 100"
just analysis stage=paper2 dataset=raw extra="--master-panel artifacts/paper1/master_panel.csv.gz"
```

Notes:

- `gvkey -> cik` is still the main external link dependency for SEC filing joins.
- The public SEC spine is exact on `reportDate` when available and falls back to
  filing-year heuristics only when the submissions JSON omits the report date.
- Paper 2 currently stops at data/feature readiness and lightweight CPU embeddings;
  detector-specific labels and long-context GPU embeddings remain follow-on work.

## Near-term next steps still pending

- Merge Audit Analytics / WRDS timing data to replace the fallback `res_an*`
  maturation proxy in the Paper 1 production run.
- Add detector and severity labels once notifier/comment-letter/enforcement data are available.
- Upgrade text features from TF-IDF + SVD to finance-specific long-context embeddings
  after GPU access is in place.
<!-- --8<-- [end:docs-home] -->
