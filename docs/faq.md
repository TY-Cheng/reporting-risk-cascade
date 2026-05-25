---
hide:
  - navigation
---

# FAQ

## Core Design

### What is the research question?

Can filing-origin public SEC/PCAOB information predict whether an issuer later
enters observable public review-and-correction channels, and how does that
public reporting-risk construct relate to, but differ from, legacy
detected-misstatement benchmarks?

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
| `aaer_proxy` | Sparse high-severity enforcement support | 730 days |

These are public observability states. They are related to reporting risk, but
they are not interchangeable with fraud, restatement, or enforcement truth.

### What is the bottom line right now?

The current evidence supports a reproducible measurement-and-ranking paper on
public reporting-risk states. It does not support causal claims, unobserved
true-fraud occurrence claims, or same-estimand performance rankings over prior
fraud-prediction papers.

The strongest current sell is:

- A filing-origin public outcome system from SEC/PCAOB data.
- A clean separation between public scrutiny, broad correction/friction, severe
  material correction, and sparse enforcement-tail support.
- Out-of-time ranking evidence showing that public features concentrate later
  review-and-correction events above prevalence.
- A bridge-based construct-overlap check showing that legacy detected
  misstatement and the public cascade are related but not identical.
- A disciplined comparison to legacy detected-misstatement benchmarks without
  treating them as the same estimand.

## Data

### What data are used?

The workflow has four layers.

| Layer | Unit | Role |
| --- | --- | --- |
| Legacy benchmark | `gvkey x data_year` | Detected-misstatement benchmark for timing, drift, missingness, and peer-model diagnostics. |
| Public SEC/PCAOB lake | filings, facts, events | Public-source construction layer for filings, XBRL, Notes summaries, comment letters, amendments, 8-K Item 4.02, Form AP, PCAOB inspections, and AAER support. |
| Public gold panels | `issuer_cik x fiscal_year x origin_date`; filing provenance | Main public issuer-year modeling table and filing-origin provenance table. |
| Linkage bridge | `gvkey-CIK-year` | Crosswalk used only for legacy/public construct-overlap validation. |

Current paper-facing counts:

| Object | Current count |
| --- | ---: |
| Legacy benchmark rows | 82,908 |
| Legacy benchmark firms | 9,156 |
| Legacy years | 2001-2019 |
| Legacy detected-misstatement positives | 2,460 |
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
| SEC AAER pages and farr AAER support | Sparse high-severity support evidence. |

### What is the difference between raw, external, linkage, and public_lake?

`raw/` contains the legacy benchmark material and the new raw CIK-GVKEY link
table. This is treated as primary for the bridge because it is closest to the
benchmark-side source.

`external/` contains support files that are useful but not primary for the
bridge, including farr exports such as `gvkey_ciks`, `aaer_firm_year`,
`aaer_dates`, and `state_hq`.

`linkage/raw_primary_external_supplement/` is the derived bridge folder. It is
not part of `public_lake` because the bridge is a cross-source validation layer,
not a SEC/PCAOB public-source table.

`public_lake/` is the public SEC/PCAOB data lake with bronze, silver, and gold
tables. The linkage builder still writes public-overlap QA summaries for both
`public_lake` and `public_lake_smoke` when those panels exist.

### Why use raw as primary and external as supplement?

The current rule is:

1. Use raw `CIK-GVKEY Link Table.csv` for covered `gvkey x year` rows.
2. Use the external bridge only for `gvkey x year` rows not covered by raw.
3. Keep raw/external conflicts as an audit output instead of silently resolving
   them away.

This rule is conservative. It gives priority to the new raw bridge evidence
while still using external coverage where raw has no candidate CIK.

### Why are there still raw-benchmark conflicts if raw is primary?

The conflict file does not mean the final bridge is using external values over
raw values. It means the QA layer compared raw and external candidate CIK sets
for the same `gvkey x year` and found disjoint CIK assignments.

Current conflict facts:

| Conflict diagnostic | Current count |
| --- | ---: |
| Disjoint raw/external conflict `gvkey x year` cells | 1,198 |
| Raw benchmark rows affected by those conflicts | 372 |
| Positive raw benchmark rows affected | 24 |

Conflicts remain because the sources have different provenance, date ranges,
identifier histories, and coverage rules. Treating raw as primary decides which
CIK wins for covered years; it does not make the disagreement disappear. The
right paper behavior is to report those conflicts and keep the construct-overlap
tier at candidate/mixed-source status until a WRDS-equivalent bridge resolves
the issue.

### What bridge coverage do we have?

The raw-primary bridge materially improves coverage over raw alone.

| Bridge diagnostic | Current count |
| --- | ---: |
| Combined bridge rows | 304,726 |
| Combined bridge `gvkey x year` cells | 296,566 |
| Raw-primary matched benchmark rows | 79,273 / 82,908 |
| Raw-primary benchmark coverage | 95.62% |
| Raw-primary matched positives | 2,337 / 2,460 |
| Combined raw + external matched benchmark rows | 82,407 / 82,908 |
| Combined raw + external benchmark coverage | 99.40% |
| Combined matched positives | 2,453 / 2,460 |
| Public-lake overlap benchmark rows | 48,109 |
| Public-lake overlap positives | 1,435 |
| Public-lake-smoke overlap benchmark rows | 246 |
| Public-lake-smoke overlap positives | 5 |

The bridge is usable for candidate overlap validation. It is not yet a
WRDS-validated integrated-claim bridge.

## Data Engineering

### What does the preprocessing pipeline do?

The pipeline has three separate tracks.

| Track | Main action | Main output |
| --- | --- | --- |
| Legacy benchmark | Load `gvkey x data_year` benchmark, define timing-sensitive detected-misstatement labels, exclude leakage columns, run annual out-of-time benchmark models. | Benchmark timing, drift, missingness, and peer-suite artifacts. |
| Public cascade | Build SEC/PCAOB public lake, create annual issuer-origin rows, attach pre-origin features and forward public labels, run annual out-of-time public prediction. | `issuer_origin_panel`, `filing_origin_panel`, public-cascade metrics and predictions. |
| Validation bridge | Build raw-primary + external-supplement `gvkey-CIK-year` crosswalk, join legacy/public only for overlap validation, report coverage/conflicts/multiplicity. | Bridge probe and construct-overlap artifacts. |

The tracks are deliberately separated. The public-cascade model does not need
the legacy bridge. The bridge is needed only when asking how the public cascade
relates to legacy detected-misstatement labels.

### What is the modeling grain?

The legacy benchmark grain is `gvkey x data_year`.

The public cascade grain is `issuer_cik x fiscal_year x origin_date`, where
`origin_date` is the selected annual filing date. Public prediction features
must be visible at or before `origin_date`.

The bridge grain is `gvkey-CIK-year`. It maps the legacy benchmark into the
public panel for overlap validation, not for constructing public labels.

### How is leakage controlled?

The main leakage guards are:

- Public features must be observed at or before `origin_date`.
- Rolling public-history features use only events with `event_date < origin_date`.
- Label, censoring, identifier, source-availability, public-date, vintage, and
  direct event-date fields are excluded from default predictors.
- Legacy `res_an0` to `res_an3` are timing proxies only and never enter
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
| Legacy benchmark core | XGBoost over engineered benchmark predictors | Timing, drift, and missingness diagnostics on detected-misstatement labels. |
| Legacy peer suite | Dechow-style, Perols-style, Bao-inspired, and Bertomeu-style families | Compatibility with accounting ML model-family language. |
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

### Are the legacy and public tasks the same X with different Y?

No. The legacy benchmark uses a `gvkey x data_year` feature table and detected
misstatement labels. The public cascade uses a public SEC/PCAOB
`issuer_cik x fiscal_year x origin_date` panel and later public
review-and-correction labels.

The project holds constant model-family language and metric vocabulary across
tasks. It does not hold constant the exact feature table, information set, or
estimand.

### Why not force the same X onto both Y definitions?

A same-X design is defensible only in the bridge-overlap subset and only as a
construct-validation exercise. The grains, time origins, and information sets
are different. Legacy variables are not always filing-origin public information,
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
review-and-correction events. A legacy PR-AUC asks whether a benchmark feature
table ranks detected-misstatement labels. The bridge and construct-overlap
tables then ask whether those two ranking problems are empirically related.

## Results

### What are the main public-cascade results?

Current public task metrics:

| Task | Positives | Mean prevalence | Mean PR-AUC | Mean ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| `comment_thread` | 24,840 | 0.2615 | 0.3654 | 0.6327 |
| `amendment` | 17,241 | 0.1552 | 0.2530 | 0.6271 |
| `8k_402` | 2,008 | 0.0221 | 0.0506 | 0.6544 |
| `aaer_proxy` | 19 | 0.0012 | 0.0490 | 0.6503 |

The strongest current public-cascade specification reported in the snapshot is
`all + rolling_7y`, with mean PR-AUC `0.2430`. The all-feature family is also
the strongest feature-family summary, with mean PR-AUC `0.2730`.

The appropriate reading is feature-fusion gain, not XBRL dominance. Metadata is
already strong, and non-metadata feature families add value most clearly when
combined.

### Which peer models perform best?

In the legacy peer suite, `bertomeu_style_xgb` has the strongest mean PR-AUC
(`0.0427`).

In the public-label peer transfer, `bertomeu_style_xgb` and
`bao_inspired_tree_ensemble` are essentially tied on mean PR-AUC (`0.2247` and
`0.2245`).

These are model-family transfer results. They should not be described as exact
numeric replications of prior papers.

### What does the construct-overlap evidence say?

Legacy detected-misstatement labels and public labels are related but
non-identical.

In the high-confidence bridge tier, legacy positives are most enriched in the
severe public correction channel:

| Public label | Lift public given legacy |
| --- | ---: |
| `label_comment_thread_365` | 1.0184 |
| `label_amendment_365` | 1.9044 |
| `label_8k_402_365` | 8.5776 |

Reciprocal ranking evidence also points to related constructs:

| Direction | Target | PR-AUC | ROC-AUC | Top-decile lift |
| --- | --- | ---: | ---: | ---: |
| Public cascade score -> legacy positives | `8k_402` | 0.0302 | 0.6835 | 2.8981 |
| Legacy/peer score -> public labels | `label_8k_402_365` | 0.0448 | 0.7066 | 3.1174 |

The interpretation is construct overlap, not identity. Comment threads capture
broad scrutiny; amendments capture correction/friction; 8-K Item 4.02 is closer
to severe material correction; AAER is too sparse for headline ranking.

### Are we done, and is it good enough?

For a public-data measurement-and-ranking paper, the current evidence is
coherent enough to write around. The paper has data, experiments, models,
metrics, tables, figures, and a claim boundary.

For a final integrated legacy/public validation claim, the strongest remaining
gate is bridge quality. The raw-primary plus external-supplement bridge is
usable candidate evidence, but the project should keep the current
`candidate_mixed` boundary until WRDS-equivalent validation or an explicit
bridge decision resolves mixed-source provenance and conflicts.

## Paper Framing

### How can this be sold?

The strongest framing is a measurement redesign:

- Prior detected-misstatement benchmarks are useful but combine reporting
  problems with discovery, disclosure delay, and public observability.
- A filing-origin public cascade better matches the information environment
  faced by investors, auditors, researchers, and regulators at filing time.
- The paper shows that public SEC/PCAOB features rank future public
  review-and-correction states.
- The bridge shows the public cascade overlaps with legacy detected
  misstatement most strongly in severe correction outcomes, while remaining a
  distinct construct.

### What should accounting readers take away?

The contribution is not "a better fraud black box." The contribution is a more
explicit construct: public reporting-risk states measured from the filing
origin. The legacy benchmark remains useful, but it is treated as a diagnostic
and validation layer rather than the only empirical truth.

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
- AAER is a complete enforcement universe.
- Public-cascade PR-AUC is directly comparable to prior detected-fraud PR-AUC as
  a same-estimand leaderboard.
- The current raw-primary plus external-supplement bridge is WRDS-validated.

## Reproducibility

### What should be run?

Use `just check` as the data-free quality gate.

Use `just data` or `just data full resume` to rebuild data engineering and the
raw-primary linkage outputs without rerunning all modeling.

Use `just full mode=full dataset=raw` for the paper-facing core run.

Use the peer-enabled study command when the legacy and public peer suites need
to be refreshed:

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
| Bridge coverage and conflicts | `$DATA_DIR/linkage/raw_primary_external_supplement/` |
| Construct overlap | `artifacts/full_with_peer/construct_overlap/` |
| Public-lake scale and gold panels | `$DATA_DIR/public_lake/gold/` |
| Smoke public-lake overlap QA | `$DATA_DIR/linkage/raw_primary_external_supplement/public_lake_smoke/` |

### Does this FAQ replace the paper plan or results snapshot?

No. The paper plan is the design contract. The results snapshot is the
artifact-backed current evidence report. This FAQ is the explanation layer that
keeps accounting and ML readers aligned on what the design means and what the
current results do, and do not, support.
