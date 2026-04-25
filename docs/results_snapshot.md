# Results Snapshot

!!! warning "Static snapshot"
    This page records the current local `artifacts/full` run. It is a docs-facing
    snapshot for inspection and GitHub Pages, not a substitute for rerunning the
    workflow. Regenerate the artifacts with `just full full raw artifacts/full`
    before updating these numbers.

!!! note "Implementation freshness"
    The code now implements the paper-plan timing grid (`proxy_drop_observed` plus
    `proxy_imputed_lag_1y`, `proxy_imputed_lag_2y`, `proxy_imputed_lag_3y`, and
    `proxy_imputed_lag_5y`) and public-label opacity DML
    (`public_opacity_dml.csv`). The `artifacts/full` metrics below predate that
    rerun: they still show the older `proxy_sensitivity` benchmark label and do
    not yet include public opacity DML output. Rerun `just task study raw
    artifacts/full` or `just full full raw artifacts/full` to refresh the snapshot.

## Run Metadata

| Field | Value |
| --- | --- |
| Study manifest timestamp | `2026-04-25T02:12:00+00:00` |
| Runtime | `parallel_jobs=2`, `model_threads=4`, `seed_policy=task-isolated` |
| Benchmark input | `data/raw_dataset_misstatement.parquet` |
| Public issuer panel | `data/public_lake/gold/issuer_origin_panel.parquet` |
| Bridge crosswalk | `data/external/gvkey_cik_year.csv` required; not available in this run |

## Interpretation Summary

The current run supports a conservative result: the empirical workflow is
reproducible, and the public review-and-correction cascade contains measurable
signal for a public reporting-risk state. It does not yet support a claim about
true fraud, causal identification, stable AAER severity-tail modeling, or
completed overlap validation between the old benchmark and the filing-native
public cascade.

| Claim area | Current interpretation |
| --- | --- |
| Public lake scale | Supported now: the local public lake is populated at full-run scale, with 21.7 million filing-origin rows and 205,832 issuer-year rows. |
| Feature readiness | Supported now: XBRL ratio features enter the public cascade, with 11 `xbrl_ratio_*` features and 15 XBRL coverage features in the `all` feature set. |
| Public cascade signal | Supported now: no task is zero-positive, and the repo-generated equal-task ranking selects `all + rolling_10y` with mean PR-AUC `0.2067`. |
| Benchmark role | Diagnostic only: the old restatement benchmark is useful for label-observability checks, not paper-grade label maturation evidence. |
| Opacity role | Implemented in code: public-label DML now uses `label_comment_thread_365`, `label_amendment_365`, and `label_8k_402_365`; the static full snapshot has not yet been rerun with this table. |
| Bridge role | Integrated-paper blocker: `raw_identifier_blocker` means old-vs-public overlap validation has not run because the raw benchmark lacks public issuer identifiers. |
| Overclaim guardrail | Not supported yet: fraud truth, causal claims, stable AAER severity-tail modeling, or integrated benchmark-to-public validation. |

## Public Lake Scale

| Table | Rows |
| --- | ---: |
| `filing_origin_panel.parquet` | 21,741,086 |
| `issuer_origin_panel.parquet` | 205,832 |
| `filing_dim.parquet` | 21,741,086 |
| `issuer_dim.parquet` | 965,861 |
| `xbrl_core_fact/` | 18,010,256 |
| `xbrl_fact_summary.parquet` | 362,013 |
| `note_summary.parquet` | 345,490 |
| `notes_filing_dim.parquet` | 345,492 |
| `comment_thread` | 125,272 |
| `correction_event` | 89,926 |
| `aaer_event` | 100 |

## Public Cascade

| Metric | Value |
| --- | --- |
| Main sample rows | 90,451 |
| Fiscal-year span | 2011-2023 |
| Domestic US GAAP only | `True` |
| Task positives | `comment_thread=24,882`, `amendment=17,256`, `8k_402=2,012`, `aaer_proxy=20` |
| Zero-positive tasks | none |
| Task status counts | `fit=520`, `skipped_one_class_train=120` |
| Readiness level | `xbrl_ratio_baseline` |
| Best feature set | `all` |
| Best train window | `rolling_10y` |
| Best mean PR-AUC | 0.2067 |

Feature availability:

| Feature family | Features | XBRL ratio features | XBRL coverage features |
| --- | ---: | ---: | ---: |
| metadata | 10 | 0 | 0 |
| xbrl | 42 | 11 | 15 |
| text | 2 | 0 | 0 |
| auditor | 3 | 0 | 0 |
| oversight | 1 | 0 | 0 |
| all | 58 | 11 | 15 |

Interpretation: the headline public-cascade result is the repo-generated
equal-task summary, not a row-weighted average over fitted folds. The best
configuration is `all + rolling_10y` with mean PR-AUC `0.2067`. The best
metadata-only configuration is close behind at `0.1981`, so the current result
supports feature fusion as useful but does not support a claim that XBRL ratios
alone dominate the signal.

Task-level signal under the `all + rolling_10y` configuration:

| Task | Positives | Approx. fitted test prevalence | PR-AUC | Interpretation |
| --- | ---: | ---: | ---: | --- |
| `comment_thread` | 24,882 | 0.2615 | 0.4305 | Strongest and best-supported public scrutiny signal. |
| `amendment` | 17,256 | 0.1552 | 0.2794 | Solid amended-filing signal. |
| `8k_402` | 2,012 | 0.0221 | 0.0771 | Rarer event with meaningful ranking signal. |
| `aaer_proxy` | 20 | 0.0013 | 0.0397 | Feasibility signal only; fitted only in late years and not a stable performance claim. |

## Benchmark Layer

| Metric | Value |
| --- | --- |
| Rows | 82,908 |
| Firms | 9,156 |
| Years | 2001-2019 |
| Positive rate | 0.0297 |
| Positive rows without timing proxy | 2,309 |
| Timing claim status | `proxy_sensitivity` |

Best rolling backtest rows from the current summary:

| Label mode | Train window | PR-AUC | Brier | Top-100 precision |
| --- | --- | ---: | ---: | ---: |
| naive | rolling_5y | 0.0729 | 0.0823 | 0.0879 |
| naive | rolling_7y | 0.0704 | 0.0965 | 0.0836 |
| naive | rolling_10y | 0.0593 | 0.1067 | 0.0793 |
| naive | expanding | 0.0545 | 0.1008 | 0.0786 |
| proxy_sensitivity | expanding | 0.0237 | 0.0196 | 0.0279 |
| proxy_sensitivity | rolling_10y | 0.0227 | 0.0180 | 0.0243 |

Interpretation: the benchmark layer is useful as a label-observability and
timing-sensitivity diagnostic. The naive rows look stronger, with best PR-AUC
`0.0729`, but the current `proxy_sensitivity` rows are a legacy drop-observed
stress test and fall to best PR-AUC `0.0237`. Only `151` of about `2,460`
positive rows have a same-row `res_an*` timing proxy, so the benchmark supports
the label-observability motivation rather than paper-grade label maturation
evidence. The metric drop should not be described as proof of look-ahead bias by
itself because deleting most positives changes the estimand and class balance.
The missingness clusters are descriptive: higher missingness groups have higher
raw positive rates, but the old-benchmark DML-style adjustment is not significant
(`p=0.5925`) and should be treated as legacy diagnostic evidence until the
full study is refreshed with the implemented public review/correction opacity
DML output.

Implementation update: the benchmark code now separates this legacy
drop-observed path into the explicit `proxy_drop_observed` label mode and expands
`proxy_imputed_lag` into fixed 1-, 2-, 3-, and 5-year assumptions. New
`rolling_metrics.csv` files include `timing_assumption`, `imputed_lag_years`,
and `retained_positive_train_share`, so the class-balance cost of each timing
assumption is visible in the artifact.

## Public Opacity DML

The public-cascade code now writes `public_opacity_dml.csv` and
`public_opacity_dml_meta.json` beside the public-cascade metrics. The treatment is
`missingness_density_score`, built from pre-origin opacity and coverage
components such as `xbrl_coverage_*` and notes-summary availability. The primary
outcomes are public labels:

- `label_comment_thread_365`
- `label_amendment_365`
- `label_8k_402_365`

Interpretation remains conservative: these are DML-style high-dimensional
adjusted associations, not causal effects. The current full snapshot predates
this output, so the table should be refreshed before citing numeric DML results.

## Bridge Gate

| Field | Value |
| --- | --- |
| Bridge probe status | `raw_identifier_blocker` |
| Crosswalk available | `False` |
| Raw rows checked | 82,908 |
| Candidate crosswalk rows | 0 |
| Blocker | Raw benchmark table has no CIK, ticker, company-name, or CUSIP columns |

The next required integration input is an authoritative `gvkey-CIK-year`
crosswalk. This is mandatory for an integrated old-benchmark/public-cascade
paper claim. The file path `data/external/gvkey_cik_year.csv` is a required
input, not evidence that the crosswalk was available in this snapshot. Once it
is prepared, rerun:

```bash
just task bridge raw artifacts/bridge_probe
just task study raw artifacts/study
```

## Artifact Index

- `artifacts/full/study_summary.md`
- `artifacts/full/study_run_manifest.json`
- `artifacts/full/benchmark/benchmark_summary.md`
- `artifacts/full/public_cascade/public_cascade_summary.md`
- `artifacts/full/public_cascade/public_opacity_dml.csv` after the next study rerun
- `artifacts/full/bridge_probe/bridge_probe_summary.json`
