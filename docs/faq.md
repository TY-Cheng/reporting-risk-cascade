---
hide:
  - navigation
---

# FAQ

## Core Design

### What is the research question?

Can filing-origin public SEC/PCAOB information predict whether an issuer later
enters observable public review-and-correction channels, and how does that
public reporting-risk construct relate to, but differ from, the
detected-misstatement benchmark?

The key phrase is **filing-origin**. The model is scored when the filing is
made, using information available at or before that date. The target is not
unobserved fraud truth. The target is whether the issuer later enters a public
review or correction channel.

### What is the main empirical object?

The main empirical object is a public review-and-correction cascade:

| Label | Meaning | Horizon |
| --- | --- | ---: |
| `comment_thread` | Public SEC comment-letter scrutiny | 365 days |
| `amendment` | Amended filing, correction, or filing friction | 365 days |
| `8k_402` | Item 4.02 non-reliance or material-correction signal | 365 days |

These are public observability states. They are related to reporting risk, but
they are not interchangeable with fraud, restatement, or enforcement truth.

### What is the bottom line right now?

The current evidence supports a reproducible measurement-and-ranking paper on
public reporting-risk states. It does not support causal claims, unobserved
true-fraud occurrence claims, or same-estimand performance rankings over prior
fraud-prediction papers.

The strongest current sell is:

- A filing-origin public outcome system from SEC/PCAOB data.
- A clean separation between public scrutiny, broad correction/friction, and
  severe material correction.
- Out-of-time ranking evidence showing that public features concentrate later
  review-and-correction events above prevalence.
- A bridge-based construct-overlap check showing that detected-misstatement
  benchmark labels and the public cascade are related but not identical.
- A disciplined comparison to the detected-misstatement benchmark without
  treating them as the same estimand.

## Data

### What data are used?

The workflow has four layers.

| Layer | Unit | Role |
| --- | --- | --- |
| Detected-misstatement benchmark | `gvkey x data_year` | Timing, drift, missingness, and peer-model diagnostics. |
| Public SEC/PCAOB lake | filings, facts, events | Public-source construction layer for filings, XBRL, Notes summaries, comment letters, amendments, 8-K Item 4.02, Form AP, and PCAOB inspections. |
| Public gold panels | `issuer_cik x fiscal_year x origin_date`; filing provenance | Main public issuer-year modeling table and filing-origin provenance table. |
| Linkage bridge | `gvkey-CIK-year` | Crosswalk used only for benchmark-to-public construct-overlap validation. |

Current paper-facing counts:

| Object | Current count |
| --- | ---: |
| Detected-misstatement benchmark rows | 82,908 |
| Detected-misstatement benchmark firms | 9,156 |
| Benchmark years | 2001-2019 |
| Detected-misstatement positives | 2,460 |
| Public filing provenance rows | 21,786,118 |
| Public issuer-year gold rows | 205,719 |
| Main domestic public-cascade sample rows | 90,342 |
| Main public fiscal-year span | 2011-2023 |

### What public sources are in the lake?

The public lake uses public SEC/PCAOB sources rather than private WRDS/Audit
Analytics files for the main public-cascade task.

| Source family | Output role |
| --- | --- |
| SEC submissions and filing index data | Issuer dimension, filing dimension, annual origin rows, filing provenance. |
| SEC Financial Statement Data Sets / XBRL | XBRL coverage and controlled ratio features. |
| SEC Notes summaries | Disclosure breadth and note-opacity features. |
| SEC `UPLOAD` and `CORRESP` | Public comment-thread signal. |
| 10-K/A and 10-Q/A filings | Amendment and filing-friction signal. |
| 8-K Item 4.02 parsing | Severe material-correction proxy. |
| PCAOB Form AP | Audit-participant and engagement features. |
| PCAOB inspection data | Oversight exposure features. |

### What is the difference between raw, external, linkage, and public_lake?

`raw/` contains the detected-misstatement benchmark material and the new raw CIK-GVKEY link
table. This is treated as primary for the bridge because it is closest to the
benchmark-side source.

`external/` is now historical support only. The previous farr bridge and support
exports no longer feed the default bridge, public-cascade labels, or paper-facing
feature set.

`linkage/raw_only/` is the derived bridge folder. It is not part of
`public_lake` because the bridge is a cross-source validation layer, not a
SEC/PCAOB public-source table.

`public_lake/` is the public SEC/PCAOB data lake with bronze, silver, and gold
tables. The linkage builder still writes public-overlap QA summaries for both
`public_lake` and `public_lake_smoke` when those panels exist.

### Why use raw-only for the bridge?

The current rule is:

1. Use raw `CIK-GVKEY Link Table.csv` for bridge rows.
2. Do not supplement missing raw `gvkey x year` rows with farr/external
   gvkey-CIK rows.
3. Report raw coverage, multiplicity, and public-lake overlap directly.

This rule is now cleaner than the earlier raw-primary plus external-supplement
design. The raw table has institutional source labels such as CRSP/Compustat
Merged, Compustat Company, Compustat Security, and Capital IQ; farr/external
rows no longer alter the default bridge. The only unique external field was
date-bounded headquarters/business-address state from `farr::state_hq`, and the
current pipeline drops it as nonessential metadata.

### What happened to the raw/external conflict file?

The old conflict file was a QA artifact from comparing raw and external
candidate CIK sets for the same `gvkey x year`. It is no longer part of the
default bridge logic because external gvkey-CIK rows are no longer used.

Historical conflict facts from the earlier raw-primary plus external-supplement
build were:

| Conflict diagnostic | Current count |
| --- | ---: |
| Disjoint raw/external conflict `gvkey x year` cells | 1,198 |
| Raw benchmark rows affected by those conflicts | 372 |
| Positive raw benchmark rows affected | 24 |

Those counts explain why the default bridge was simplified to raw-only.
Disagreements can still be discussed as historical sensitivity evidence, but
they no longer affect the main crosswalk.

### What bridge coverage do we have?

The raw-only bridge has high coverage without external supplementation.

| Bridge diagnostic | Current count |
| --- | ---: |
| Combined bridge rows | 274,979 |
| Combined bridge `gvkey x year` cells | 266,982 |
| Raw-only matched benchmark rows | 79,273 / 82,908 |
| Raw-only benchmark coverage | 95.62% |
| Raw-only matched positives | 2,337 / 2,460 |
| Raw-only public-lake overlap benchmark rows | 46,440 |
| Raw-only public-lake overlap positives | 1,371 |
| Public-lake-smoke overlap benchmark rows | 242 |
| Public-lake-smoke overlap positives | 5 |

The bridge is WRDS-validated using the collaborator-provided WRDS SEC Analytics
Suite CIK-GVKEY export. It supports related-but-non-identical construct-overlap
claims, not causal fraud-occurrence claims or same-estimand performance
rankings.

## Data Engineering

### What does the preprocessing pipeline do?

The pipeline has three separate tracks.

| Track | Main action | Main output |
| --- | --- | --- |
| Detected-misstatement benchmark | Load `gvkey x data_year` benchmark, define timing-sensitive detected-misstatement labels, exclude leakage columns, run annual out-of-time benchmark models. | Benchmark timing, drift, missingness, and peer-suite artifacts. |
| Public cascade | Build SEC/PCAOB public lake, create annual issuer-origin rows, attach pre-origin features and forward public labels, run annual out-of-time public prediction. | `issuer_origin_panel`, `filing_origin_panel`, public-cascade metrics and predictions. |
| Validation bridge | Build raw-only `gvkey-CIK-year` crosswalk, join benchmark/public rows only for overlap validation, report coverage and multiplicity. | Bridge probe and construct-overlap artifacts. |

The tracks are deliberately separated. The public-cascade model does not need
the benchmark-to-public bridge. The bridge is needed only when asking how the
public cascade relates to detected-misstatement benchmark labels.

### What is the modeling grain?

The detected-misstatement benchmark grain is `gvkey x data_year`.

The public cascade grain is `issuer_cik x fiscal_year x origin_date`, where
`origin_date` is the selected annual filing date. Public prediction features
must be visible at or before `origin_date`.

The bridge grain is `gvkey-CIK-year`. It maps the detected-misstatement benchmark into the
public panel for overlap validation, not for constructing public labels.

### How is leakage controlled?

The main leakage guards are:

- Public features must be observed at or before `origin_date`.
- Rolling public-history features use only events with `event_date < origin_date`.
- Label, censoring, identifier, source-availability, public-date, vintage, and
  direct event-date fields are excluded from default predictors.
- Benchmark `res_an0` to `res_an3` are timing proxies only and never enter
  benchmark predictors.
- Imputation and model-specific transformations are fit inside each training
  fold and then applied to the held-out fiscal year.

### Why Parquet?

The large public lake tables use Parquet because the workflow needs typed
columns, faster repeated reads, and projection pushdown at SEC/PCAOB scale.
Small diagnostic files remain CSV, JSON, or Markdown so they can be inspected
directly.

## Models

### What are the main models?

| Component | Models | Purpose |
| --- | --- | --- |
| Detected-misstatement benchmark core | XGBoost over engineered benchmark predictors | Timing, drift, and missingness diagnostics on detected-misstatement labels. |
| Detected-misstatement peer benchmark | Dechow-style, Perols-style, Bao-inspired, and Bertomeu-style families | Compatibility with accounting ML model-family language. |
| Public cascade core | XGBoost over feature-family ablations | Main filing-origin public review-and-correction prediction. |
| Public-label peer suite | Same peer-family vocabulary transferred to public labels where mapping gates permit | Tests whether familiar model families rank public outcomes. |
| Public-label opacity DML | Cross-fitted partially linear DML | Adjusted association between opacity/missingness and public labels, not causal identification. |
| Construct-overlap layer | Contingency, lift, reciprocal ranking, event-time concentration | Tests related-but-non-identical construct evidence. |

### What are "ours" and what are benchmarks?

The public-cascade measurement design is the project's main contribution. The
core public XGBoost model is the main ranking implementation used to compare
feature families and training windows.

The Dechow, Perols, Bao, and Bertomeu-style models are benchmarks in the sense
of model-family and metric-language alignment. They are not exact replications
of those papers' original samples, labels, or private data settings.

### Are the benchmark and public tasks the same X with different Y?

No. The detected-misstatement benchmark uses a `gvkey x data_year` feature
table and detected-misstatement labels. The public cascade uses a public SEC/PCAOB
`issuer_cik x fiscal_year x origin_date` panel and later public
review-and-correction labels.

The project holds constant model-family language and metric vocabulary across
tasks. It does not hold constant the exact feature table, information set, or
estimand.

### Why not force the same X onto both Y definitions?

A same-X design is defensible only in the bridge-overlap subset and only as a
construct-validation exercise. The grains, time origins, and information sets
are different. Benchmark variables are not always filing-origin public information,
while public features are designed around `origin_date` leakage guards.

## Metrics

### What metrics are reported?

The common metric vocabulary is:

- PR-AUC relative to prevalence.
- ROC-AUC.
- Brier score and Brier Skill Score.
- Expected calibration error.
- Top-50, top-100, and top-200 precision.
- Top-decile lift.
- Bao-style top-fraction precision, sensitivity, specificity, balanced
  accuracy, and NDCG.

### Which metric is the headline?

PR-AUC is the primary headline ranking metric because the tasks are imbalanced
and prevalence differs sharply by label. A random ranking has expected PR-AUC
near the positive-class prevalence, so PR-AUC can be read against the base rate.

Top-decile lift and Bao-style top-fraction metrics translate the same ranking
problem into screening language. ROC-AUC is useful for comparability but can be
less informative than PR-AUC in rare-event settings. Brier and ECE are
calibration diagnostics.

### How should metric comparisons be read?

Comparisons are valid within the same task, split, feature family, and label
definition. They are not direct cross-estimand performance comparisons.

A public-cascade PR-AUC asks whether public SEC/PCAOB features rank later public
review-and-correction events. A detected-misstatement benchmark PR-AUC asks
whether a benchmark feature table ranks detected-misstatement labels. The bridge
and construct-overlap tables then ask whether those two ranking problems are
empirically related.

## Results

### What are the main public-cascade results?

Current public task metrics:

| Task | Positives | Mean prevalence | Mean PR-AUC | Mean ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| `comment_thread` | 24,840 | 0.2615 | 0.3654 | 0.6327 |
| `amendment` | 17,241 | 0.1552 | 0.2530 | 0.6271 |
| `8k_402` | 2,008 | 0.0221 | 0.0506 | 0.6544 |

The strongest current public-cascade specification reported in the snapshot is
`all + expanding`, with mean PR-AUC `0.2887`. The all-feature family is also
the strongest feature-family summary, with mean PR-AUC `0.2875`.

The appropriate reading is feature-fusion gain, not XBRL dominance. Metadata is
already strong, and non-metadata feature families add value most clearly when
combined.

### Which peer models perform best?

In the detected-misstatement peer benchmark, `bertomeu_style_xgb` has the strongest mean PR-AUC
(`0.0427`).

In the public-label peer transfer, `bertomeu_style_xgb` and
`bao_inspired_tree_ensemble` are essentially tied on mean PR-AUC (`0.2247` and
`0.2245`).

These are model-family transfer results. They should not be described as exact
numeric replications of prior papers.

### What does the construct-overlap evidence say?

Detected-misstatement benchmark labels and public labels are related but
non-identical.

In the high-confidence bridge tier, benchmark positives are most enriched in the
severe public correction channel:

| Public label | Lift public given benchmark |
| --- | ---: |
| `label_comment_thread_365` | 1.0279 |
| `label_amendment_365` | 1.9229 |
| `label_8k_402_365` | 8.5832 |

Reciprocal ranking evidence also points to related constructs:

| Direction | Target | PR-AUC | ROC-AUC | Top-decile lift |
| --- | --- | ---: | ---: | ---: |
| Public cascade score -> benchmark positives | `8k_402` | 0.0310 | 0.6836 | 2.9627 |
| Detected-misstatement score -> public labels | `label_8k_402_365` | 0.0463 | 0.7101 | 3.1495 |

The interpretation is construct overlap, not identity. Comment threads capture
broad scrutiny; amendments capture correction/friction; 8-K Item 4.02 is closer
to severe material correction.

### Are we done, and is it good enough?

For a public-data measurement-and-ranking paper, the current evidence is
coherent enough to write around. The paper has data, experiments, models,
metrics, tables, figures, and a claim boundary.

For a final integrated detected-misstatement/public validation claim, the bridge
provenance gate is now satisfied: the raw-only bridge is a collaborator-provided
WRDS SEC Analytics Suite CIK-GVKEY export. The current boundary is therefore not
bridge provenance; its validation tier is `wrds_validated`. The WRDS bridge supports
related-but-non-identical construct-overlap claims, not causal fraud-occurrence
claims or same-estimand performance rankings.

## Paper Framing

### How can this be sold?

The strongest framing is a measurement redesign:

- Prior detected-misstatement benchmarks are useful but combine reporting
  problems with discovery, disclosure delay, and public observability.
- A filing-origin public cascade better matches the information environment
  faced by investors, auditors, researchers, and regulators at filing time.
- The paper shows that public SEC/PCAOB features rank future public
  review-and-correction states.
- The bridge shows the public cascade overlaps with detected-misstatement
  benchmark labels most strongly in severe correction outcomes, while remaining
  a distinct construct.

### What should accounting readers take away?

The contribution is not "a better fraud black box." The contribution is a more
explicit construct: public reporting-risk states measured from the filing
origin. The detected-misstatement benchmark remains useful, but it is treated as
a diagnostic and validation layer rather than the only empirical truth.

### What should ML readers take away?

The important ML design choices are the estimand, time origin, leakage guards,
out-of-time splits, rare-event metrics, calibration diagnostics, and construct
boundary. Model families are intentionally familiar so the empirical question
does not depend on algorithm novelty.

### What should not be claimed?

Do not claim:

- The public labels are true fraud labels.
- The model causally identifies fraud, scrutiny, correction, or enforcement.
- Comment letters are the full SEC review universe.
- Public-cascade PR-AUC is directly comparable to prior detected-fraud PR-AUC as
  a same-estimand leaderboard.

## Reproducibility

### What should be run?

Use `just check` as the data-free quality gate.

Use `just data` or `just data full resume` to rebuild data engineering and the
raw-only linkage outputs without rerunning all modeling.

Use `just full mode=full dataset=raw` for the paper-facing core run.

Use the peer-enabled study command when the detected-misstatement and public
peer suites need to be refreshed:

```bash
just task study raw artifacts/full_with_peer \
  extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
```

Then run:

```bash
just snapshot
just manuscript
```

### Which artifacts answer the core questions?

| Question | Artifacts |
| --- | --- |
| Current paper structure | `docs/paper_plan.md` |
| Current results and tables/figures | `docs/results_snapshot.md`, `artifacts/manuscript_package` |
| Public-cascade metrics | `artifacts/full_with_peer/public_cascade/public_cascade_metrics.csv` |
| Peer model-family transfer | `artifacts/full_with_peer/peer_comparison/`, `artifacts/full_with_peer/public_peer_comparison/` |
| Bridge coverage and multiplicity | `$DATA_DIR/linkage/raw_only/` |
| Construct overlap | `artifacts/full_with_peer/construct_overlap/` |
| Public-lake scale and gold panels | `$DATA_DIR/public_lake/gold/` |
| Smoke public-lake overlap QA | `$DATA_DIR/linkage/raw_only/public_lake_smoke/` |

### Does this FAQ replace the paper plan or results snapshot?

No. The paper plan is the design contract. The results snapshot is the
artifact-backed current evidence report. This FAQ is the explanation layer that
keeps accounting and ML readers aligned on what the design means and what the
current results do, and do not, support.
