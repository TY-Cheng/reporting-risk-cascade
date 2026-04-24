# Paper Plan

Working title:

**From Restatements to Public Scrutiny: Label Maturation, Strategic Silence, and the Public Reporting-Risk Cascade**

!!! abstract "How to use this page"
    This page is not a brainstorming memo. It is the current paper's execution
    contract: what the paper is claiming, what the code must implement, and which
    gates must be satisfied before the public-cascade result is treated as paper-ready.

[Jump to the readiness matrix](#readiness-matrix){ .md-button .md-button--primary }
[Open deferred future work](future_work.md){ .md-button }

<div class="grid cards" markdown>

-   :material-scale-balance: __Measurement redesign__

    ---

    The contribution is to redesign the outcome and timing problem, not to claim
    that one classifier trivially dominates another.

-   :material-timetable: __Benchmark discipline__

    ---

    The old `gvkey x data_year` panel is kept as a benchmark layer, but it must
    respect label maturation, time ordering, drift, and missingness diagnostics.

-   :material-file-search-outline: __Public cascade__

    ---

    The main paper moves to first-public-date SEC and PCAOB signals: comment
    scrutiny, amendment, 8-K Item 4.02, and AAER severity proxy.

-   :material-bridge: __Overlap validation__

    ---

    The bridge is important, but it is not allowed to silently hold the public
    cascade hostage. It blocks Experiment 6, not the full v1 measurement result.

</div>

=== "This paper is"

    - A timing-aware benchmark paper about why naive restatement prediction can mislead.
    - A public-data measurement paper about the reporting-risk scrutiny-correction cascade.
    - A reproducible workflow paper with explicit readiness gates and blocker states.

=== "This paper is not"

    - Not a generic fraud-detector leaderboard.
    - Not a claim that AAER pages define the full enforcement universe.
    - Not a causal paper about why firms misstate.

## One-Sentence Contribution

The paper shows that corporate misstatement prediction should not be evaluated as a
static `restatement = 1` classifier. Observed restatements are delayed and detected
outcomes, so the defensible public-data estimand is a filing-native, lag-aware
**pre-disclosure reporting-risk state** that predicts the public review-comment-
correction-enforcement cascade.

## Research Positioning

The paper combines two evidence layers:

- **Benchmark layer:** the old `gvkey x data_year` restatement dataset, used to show
  that traditional pooled and naive-label evaluation is unstable.
- **Public cascade layer:** SEC and PCAOB public data, used to construct a filing-native
  public scrutiny and correction process.

The old CSV is not discarded. It is used as a disciplined benchmark and validation layer.
The public lake is the paper's main measurement innovation.

## Evidence State And Decision Gate

The project is deliberately staged into three evidence states.

1. **Benchmark evidence available**

- The raw `gvkey x data_year` CSV supports benchmark prediction, drift diagnostics, and
  missingness analysis.
- Because the raw CSV has no public restatement filing dates and `res_an*` is sparse on
  same-row positives, the benchmark can show timing fragility but cannot claim paper-grade
  label maturation in P0.

2. **Public cascade evidence under construction**

- The public gold panel exists and supports metadata baselines plus public event labels.
- Submission-ready evidence requires non-metadata public features, starting with core XBRL
  ratios built only from facts visible at the filing origin.
- Metadata-only cascade results are readiness diagnostics, not feature-family evidence.

3. **Integration evidence pending gate**

- The old benchmark and public cascade become one integrated paper only if the bridge probe
  yields interpretable overlap coverage and the XBRL cascade produces non-metadata signal.
- This integration gate is the `gvkey-CIK-year` evidence gate.
- If the bridge cannot support credible overlap validation, the project should split into a
  benchmark critique paper and a public cascade measurement paper.

## Prior Literature And Intended Contribution

### Prior literature

This project builds on four adjacent strands rather than starting from a blank slate.

1. Restatement and misstatement prediction benchmarks.

- Dechow, Ge, Larson, and Sloan (2011, *Contemporary Accounting Research*), "Predicting
  Material Accounting Misstatements," is the canonical benchmark that turns detected
  misstatements into a firm-year prediction problem and motivates the F-score style
  screening tradition.
- Perols (2011, *AUDITING: A Journal of Practice & Theory*), "Financial Statement Fraud
  Detection: An Analysis of Statistical and Machine Learning Algorithms," compares
  statistical and machine-learning classifiers in fraud detection and shows that better
  algorithms do not by themselves solve the measurement problem.

2. Machine-learning extensions of accounting fraud or misstatement detection.

- Bao, Ke, Yu, and Zhang (2020, *Journal of Accounting Research*), "Detecting Accounting
  Fraud in Publicly Traded U.S. Firms Using a Machine Learning Approach," shows that
  ensemble learning with theory-motivated raw accounting numbers can materially improve
  fraud prediction relative to older ratio-based benchmarks.
- Bertomeu, Cheynel, Floyd, and Pan, "Using Machine Learning to Detect Misstatements"
  (*Review of Accounting Studies*, forthcoming in the cited SSRN version), shows that
  machine learning can detect interactions across accounting, audit, market, and governance
  variables and can interpret groups at greater risk of misstatements.

3. Partial observability in restatement settings.

- Barton, Burnett, Gunny, and Miller (2024, *Management Science* 70(1): 32-53), "The
  Importance of Separating the Probability of Committing and Detecting Misstatements in the
  Restatement Setting," argues that observed restatements combine occurrence and detection,
  so traditional logistic restatement models are clouded by partial observability.

4. Public disclosure and regulatory-process measurement.

- SEC FSDS, public comment-letter release rules, EDGAR filing histories, PCAOB Form AP, and
  PCAOB inspection data together make it possible to construct a public scrutiny and
  correction process from first public dates rather than from a single ex post restatement
  flag.

### Intended contribution

The intended contribution is not another horse race claiming that one classifier beats
another. The contribution is a measurement redesign.

- We move from a static detected-restatement classifier to a lag-aware benchmark that
  enforces label maturation.
- We move from a single ex post outcome to a filing-native public cascade with distinct
  outcomes for scrutiny, amendment, non-reliance, and enforcement severity proxy.
- We move from pooled prediction to shelf-life analysis through rolling windows, feature
  drift, and regime diagnostics.
- We move from treating missingness as pure nuisance to testing whether opacity regimes are
  economically informative.
- We separate what is publicly observable and reproducible from what remains latent or only
  partially observed.

### Potential findings and selling points

If the empirical results support the design, the paper's main selling points are expected to
be:

- naive restatement prediction likely overstates or distorts performance once label
  maturation is enforced
- public scrutiny and correction events are related to old restatement labels but are not the
  same construct
- shorter rolling windows may outperform expanding windows, implying that reporting-risk
  models have limited shelf-life
- missingness density and missingness regimes may remain associated with risk after
  high-dimensional adjustment
- a public-data-only pipeline can produce a more transparent, reproducible, and regulator-
  facing reporting-risk measure than a static detected-restatement label alone

These are empirical possibilities, not guaranteed outcomes. The implementation and reporting
must remain diagnostic rather than target-seeking.

## Execution Invariants

These rules are binding implementation constraints, not narrative preferences.

- All public cascade labels use the **first public date** observable in EDGAR, PCAOB, or
  the relevant public source.
- In v1, `filing_origin_panel.origin_date = filing_date`; `issuer_origin_panel.origin_date`
  is the selected annual filing date for the issuer-year origin.
- No event released after `origin_date` may enter predictors.
- `source_available_*`, `public_date_*`, `vintage_*`, and `as_of_date` are coverage state
  fields. They are not default predictors.
- `missing_*` and `raw_missing_*` are ordinary missingness signals and may enter
  Experiment 3.
- `res_an0` to `res_an3` are timing proxies only. They never enter benchmark predictors.
- Censoring is horizon-specific: 365-day tasks use `censored_365`; 730-day tasks use
  `censored_730`.
- SEC EDGAR access must respect the current 10 requests/second limit and use retry/backoff
  for network failures.

Official source constraints used by this plan:

- SEC FSDS currently spans January 2009 through March 2026 and notes a December 2024
  reprocessing, so bronze manifests must retain download timestamp, SHA256, parser version,
  schema version, and as-of date:
  <https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets>
- SEC EDGAR fair-access guidance states the 10 requests/second ceiling:
  <https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data>
- SEC AAER pages are severity proxies, not a complete enforcement universe:
  <https://www.sec.gov/enforcement-litigation/accounting-auditing-enforcement-releases>
- PCAOB downloadable inspection datasets begin with annually inspected firms in 2018 and
  triennially inspected firms in 2019, so inspection features are a later-window ablation:
  <https://pcaobus.org/news-events/news-releases/news-release-detail/pcaob-makes-available-new-downloadable-datasets-featuring-pcaob-inspection-findings-from-audit-firm-inspection-reports>
- SEC ticker/CIK files are useful candidate mappings but are not guaranteed for accuracy or
  scope:
  <https://www.sec.gov/about/webmaster-frequently-asked-questions>

## Core Research Questions

1. How much do naive pooled restatement models overstate or distort predictive
   performance once label maturation and time ordering are enforced?
2. Does misstatement-risk prediction decay over regulatory regimes and calendar time?
3. Are missingness regimes economically informative, consistent with strategic silence
   rather than nuisance missing data?
4. Can public SEC/PCAOB data identify a pre-disclosure reporting-risk state before
   comment letters, amendments, 8-K Item 4.02 disclosures, or AAER proxy events?
5. How do old restatement labels align with the public scrutiny-correction-enforcement
   cascade in the overlapping sample?

## Data Architecture

### Existing Benchmark Data

`data/raw_dataset_misstatement.csv`

- Grain: `gvkey x data_year`
- Coverage: 2001-2019
- Role: benchmark layer for traditional restatement prediction
- Known limitation: no `CIK`, `ticker`, `PERMNO`, restatement filing date, detector
  identity, or full public filing history

Required columns:

- identifiers: `gvkey`, `data_year`
- outcome: `misstatement firm-year`
- timing proxies: `res_an0`, `res_an1`, `res_an2`, `res_an3`
- missingness flags: all `missing_*` fields
- feature blocks: accounting, audit, governance, market, and industry variables

### Public Lake Data

`data/public_lake/`

- Bronze: raw downloaded files plus source URL, download timestamp, SHA256 hash, parser
  version, schema version, and as-of date.
- Silver: normalized filing, issuer, XBRL, note, comment-thread, correction-event, Form AP,
  PCAOB inspection, and AAER proxy tables.
- Gold: model-ready `issuer_origin_panel` and `filing_origin_panel`.

Required public sources for v1:

- SEC `submissions.zip` for issuer and filing history.
- SEC FSDS 2011-2023 for compact XBRL numeric features.
- SEC `UPLOAD` and `CORRESP` filings for public comment-letter scrutiny.
- SEC `10-K/A` and `10-Q/A` for amendment labels.
- SEC 8-K Item 4.02 for non-reliance correction labels.
- PCAOB Form AP for auditor, firm, and partner monitoring features.
- SEC AAER pages for severity proxy events only.

Public sample:

- Main years: 2011-2023
- Issuers: domestic U.S. GAAP issuers
- Exclusions: FPI/IFRS main sample excluded in v1
- As-of date for current reproducibility: 2026-04-23
- Current full-gold state: `issuer_origin_rows = 205,833`; 2011-2023 domestic main sample
  has about 90,454 issuer-year rows.
- Current warning: `label_aaer_proxy_730 = 0` in the domestic 2011-2023 main sample, so AAER
  is a readiness/robustness item until a nonzero proxy table is available.

### Bridge Plan

`data/external/gvkey_cik_year.csv`

Required fields:

- `gvkey`
- `issuer_cik`
- `start_year` and `end_year`, or a single `data_year`/`fiscal_year`
- provenance fields such as source, version, extraction date, match method, and match score

Default v1 bridge route:

- Run a public-only bridge probe first; it is a coverage feasibility audit, not an
  authoritative historical crosswalk.
- With the current raw CSV, the expected first output is `raw_identifier_blocker` because
  the raw benchmark has no CIK, ticker, company name, CUSIP, or PERMNO columns.
- If raw-side company identifiers are added later, use public SEC ticker/CIK/company-name
  data to construct a provenance-tagged candidate bridge.
- Do not treat public ticker/CIK files as authoritative; SEC states they are not guaranteed
  for accuracy or scope.
- Emit `bridge_probe_summary.json`, `coverage_report.csv`, `multiplicity_report.csv`, and
  `unmatched_raw_characteristics.csv` before any overlap validation.
- Fail loudly on silent many-to-many joins. Ambiguous mappings remain reported blockers or
  multiplicity rows, not guessed links.
- No overlap model is allowed unless a non-empty, provenance-tagged candidate or external
  crosswalk exists.
- The bridge does not block the public cascade main result; it blocks only Experiment 6.

## Label Ontology

### Old Benchmark Labels

- `naive`: observed `misstatement firm-year` without correcting for detection timing.
- `proxy_sensitivity`: a timing-fragility diagnostic using only observable `res_an*` proxy
  flags and excluding positive rows without any usable timing proxy.
- `external_timing`: paper-grade maturation only if external restatement filing or public
  detection dates are supplied and validated.

### Benchmark Timing-Sensitivity Algorithm

`res_an0` to `res_an3` are not treated as a verified label-maturation system in P0. The raw
CSV shape shows that most positive firm-years do not have same-row `res_an*` timing flags,
so this path is a codebook-dependent sensitivity proxy.

```text
For each benchmark row:
  label_naive = misstatement firm-year

  if misstatement firm-year == 1 and an external public detection year is available:
    timing_claim_status = external_timing
    detection_year = external_detection_year

  else if misstatement firm-year == 1 and a usable res_an* proxy is present:
    timing_claim_status = proxy_sensitivity
    detection_year_proxy = data_year + proxy_lag

  else if misstatement firm-year == 1 and no timing evidence is available:
    timing_claim_status remains proxy_sensitivity or blocked
    exclude the positive row from proxy-visible training labels
    count it in timing_coverage.csv

  proxy-visible training positive:
    1 only when detection_year_proxy <= train_origin_year
    where train_origin_year = test_year - 1
```

Benchmark outputs must include `timing_coverage.csv` and a summary field
`timing_claim_status` with allowed values `external_timing`, `proxy_sensitivity`, or
`blocked`. The main benchmark claim is therefore: traditional restatement benchmarks are
timing-fragile under observable timing proxies. It is not that label maturation has been
fully solved in the raw CSV.

### Public Cascade Labels

Stage 0: source availability state.

- `source_available_*`
- `public_date_*`
- `vintage_*`
- `as_of_date`

These fields document what could have been known; they are coverage metadata, not default
predictive features.

Stage 1: pre-disclosure reporting-risk state.

- This is the latent risk score estimated from pre-origin public features.
- It is not claimed to be true latent fraud occurrence.

Stage 2: public comment-letter scrutiny.

- label: `label_comment_thread_365`
- timing: first public EDGAR date of the comment-letter thread
- caveat: public comment letters are not the full SEC review universe

Stage 3: public correction ladder.

- label: `label_amendment_365`
- label: `label_8k_402_365`
- amendment and non-reliance are separate outcomes
- revision-only restatements are not forced into 8-K Item 4.02

Stage 4: accounting-enforcement severity proxy.

- label: `label_aaer_proxy_730`
- caveat: AAER pages are severity proxies, not a complete enforcement universe
- if 730-day positives are zero, skip AAER model fitting and report the blocker; consider
  1095-day robustness only after a nonzero public proxy table is available

### Outcome Semantics

The public cascade is a multi-label setting:

- Comment thread, amendment, 8-K Item 4.02, and AAER proxy are independent binary tasks.
- A single issuer-year may be positive in multiple tasks.
- A Stage 3 positive does not force `label_comment_thread_365 = 1`; no artificial label
  completion is allowed.
- Co-occurrence, conditional event rates, and calibration by task are reported separately.

## Public Cascade Feature Contract

Feature families must use the same filtered issuer-year sample for fair ablations. Missing
feature values are imputed inside each training fold; rows are not dropped family-by-family
unless the task horizon is censored.

Metadata family:

- `sic`, `form`, `entity_type`
- filing size and XBRL flags available at the origin filing
- prior filing count and days since previous filing
- fiscal-year and issuer-history descriptors that are observable at `origin_date`

XBRL family:

- v1 must include core ratio features prefixed `xbrl_ratio_` and coverage fields prefixed
  `xbrl_coverage_`.
- Minimum ratio families: size, leverage, profitability, working-capital intensity,
  receivables intensity, inventory intensity, cash intensity, debt intensity,
  operating-cash-flow intensity, and year-over-year revenue/assets change when lagged facts
  are available.
- Supporting aggregates such as `xbrl_fact_count`, `xbrl_unique_tags`, and
  `xbrl_unique_units` remain useful but are not enough for a submission-ready feature-family
  ablation.
- Standard tags must come from a controlled list in code or config; ad hoc tag mining is not
  allowed in model code.
- Do not use financial-statement facts filed after `origin_date`.

Public cascade readiness levels:

- `metadata_baseline`: only metadata and issuer-history features are non-empty; this is a
  smoke/readiness result, not feature-family evidence.
- `xbrl_ratio_baseline` or XBRL ratio baseline: at least one `xbrl_ratio_*` feature is
  present and visible at origin; this is the first non-metadata empirical unlock.
- `auditor_form_ap_ablation`: Form AP fields are non-empty in the applicable post-2017
  source window.
- `oversight_pcaob_later_window_ablation`: PCAOB inspection fields are non-empty in the
  2018/2019+ later window.

Auditor family:

- Form AP fields available by source vintage: form filing count, unique partners, average
  participant count, and partner/firm identifiers only when public by `origin_date`.
- 2011-2016 auditor-family ablations must explicitly report Form AP unavailability rather
  than treating unavailable source state as ordinary missingness.

Oversight family:

- PCAOB inspection features are a later-window ablation because downloadable inspection
  datasets begin in 2018/2019.
- Prior filing-count style variables may remain in oversight only if they describe
  pre-origin monitoring exposure rather than source availability.

Excluded by default:

- `source_available_*`, `public_date_*`, `vintage_*`, `items`, raw descriptions, identifiers,
  and all label/censor columns.

## Experiments

### Experiment 1: Naive Versus Timing-Sensitivity Restatement Evaluation

Goal:

- quantify how fragile traditional evaluation is when observable timing proxies are enforced.

Design:

- dataset: old CSV
- models: XGBoost classifier with controlled hyperparameters
- train windows: expanding, rolling 5-year, rolling 7-year, rolling 10-year
- test slices: annual out-of-time slices
- labels: naive versus proxy-visible sensitivity labels
- required timing coverage report: positive total, same-row `res_an*` coverage, unknown-timing
  positives, `res_an0` to `res_an3` cross-tab, and `timing_claim_status`

Metrics:

- PR-AUC
- ROC-AUC
- Brier score
- expected calibration error
- Top-50, Top-100, Top-200, and Top-500 precision
- count of positives dropped for unknown timing in each training split

Diagnostic interpretation:

- compare naive and proxy-visible metrics to quantify label-timing sensitivity; do not frame
  this as a solved label-maturation design unless external timing data are added.

### Experiment 2: Concept Drift And Model Shelf-Life

Goal:

- estimate whether a model trained in one regime remains useful in later regimes.

Design:

- compare expanding and rolling-window performance over test years
- track feature-family importance over time
- run pre/post breakpoint diagnostics around 2005, 2010, and 2017

Structural-break specification:

- primary objects: annual PR-AUC, Brier score, and feature-family importance shares
- v1 statistic: pre/post mean shift and trend-interaction diagnostics by breakpoint
- no Andrews sup-Wald or formal coefficient-stability claim unless implemented and tested

Outputs:

- rolling metrics by test year
- window-summary table
- structural-break diagnostics table
- feature-family importance table

Diagnostic interpretation:

- use the diagnostics to identify model shelf-life and retraining-window sensitivity; do not
  infer structural causality from predictive drift alone.

### Experiment 3: Strategic Silence And MNAR Missingness

Goal:

- test whether missingness profiles are economically informative.

Design:

- build Missing Profile Vectors from `missing_*` flags and high-missing raw variables
- fit candidate cluster counts
- compare opacity regimes by misstatement rate and missingness intensity
- estimate DML-style high-dimensional adjustment

DML PLR specification:

```text
D = missingness_density_score
  = mean(missing_AF, missing_Rating, missing_DD, missing_auopic, ... available missing flags)

Y = misstatement firm-year

X = all non-missing accounting, audit, governance, market, and industry controls
    excluding D, missing_* flags, raw_missing_* flags, res_an*, gvkey, and data_year

Partially linear regression:
  Y = theta * D + g(X) + epsilon
  D = m(X) + nu

Nuisance functions:
  tree-based learners with cross-fitting; LightGBM is preferred when available,
  HistGradientBoosting is the CPU-safe fallback.
```

Interpretation rule:

- describe `theta` as adjusted association or high-dimensional adjustment evidence, not a
  causal effect, unless a stronger disclosure shock is added later.

### Experiment 4: Public Cascade Construction

Goal:

- demonstrate that public data can support a defensible scrutiny-correction-enforcement
  cascade.

Design:

- build the public lake from SEC/PCAOB sources
- construct event labels using first public dates only
- report coverage by fiscal year and source family
- keep comment letters, amendments, 8-K Item 4.02, and AAER proxy events separate

Outputs:

- source coverage table
- public cascade event-rate table
- censoring table
- event timing summaries
- task readiness table, including zero-positive blockers

### Experiment 5: Public Cascade Prediction

Goal:

- estimate the pre-disclosure reporting-risk state from public data.

Design:

- dataset: `issuer_origin_panel`
- tasks: comment thread, amendment, 8-K 4.02, AAER proxy
- feature families: metadata, XBRL, auditor, oversight, all
- train windows: expanding, rolling 5-year, rolling 7-year, rolling 10-year
- skip task-family-window fits when training or test labels have fewer than two classes
- current metadata-only outputs must report `metadata_baseline` readiness and cannot be cited
  as XBRL/auditor/oversight feature-family evidence
- XBRL feature-family evidence begins only when `public_cascade_summary.json` reports
  nonzero `xbrl_ratio_*` feature counts

Metrics:

- PR-AUC
- ROC-AUC
- Brier score
- task-level positive rates
- feature-family ablations
- co-occurrence and calibration summaries across task labels

Diagnostic interpretation:

- compare feature families across tasks only for non-degenerate task folds; if AAER proxy has
  zero positives, report it as a blocker rather than a failed model.

### Experiment 6: Old Benchmark And Public Cascade Overlap

Goal:

- show whether the old restatement benchmark and the public cascade measure related but
  non-identical constructs.

Design:

- first run the public-only bridge probe
- if the raw CSV lacks CIK/ticker/name/CUSIP, emit `raw_identifier_blocker` and stop
- if candidate identifiers exist, build a provenance-tagged candidate bridge and report
  coverage and join multiplicity before modeling
- test whether old positives are followed by public cascade events
- test whether benchmark risk scores predict public cascade labels
- test whether public cascade risk scores predict old restatement labels
- build event-time plots around old restatement firm-years

Outputs:

- crosswalk coverage table
- multiplicity and ambiguous-match blocker reports
- `bridge_probe_summary.json`
- `coverage_report.csv`
- `multiplicity_report.csv`
- `unmatched_raw_characteristics.csv`
- overlap panel
- risk-score alignment table
- event-time distribution figure

## Tables And Figures

Main tables:

- Table 1: sample construction, source coverage, and public-lake availability.
- Table 2: naive versus timing-sensitivity restatement evaluation.
- Table 3: concept-drift and retraining-window comparison.
- Table 4: missingness regimes and strategic-silence evidence.
- Table 5: public cascade event rates, censoring, and task readiness.
- Table 6: public-cascade prediction by task and feature family.
- Table 7: old-label/public-cascade overlap validation.

Main figures:

- Figure 1: old misstatement positive-rate collapse and public cascade event rates.
- Figure 2: model shelf-life and rolling PR-AUC decay.
- Figure 3: public review-comment-correction-enforcement cascade.
- Figure 4: feature-family importance drift.
- Figure 5: missingness-regime risk profile.
- Figure 6: event-time distribution around old restatement firm-years.

## Code Architecture

Production modules:

- `src/benchmark.py`: old benchmark model, timing-sensitivity diagnostics, drift,
  missingness, and DML-style adjustment.
- `src/public_lake.py`: public bronze/silver/gold data lake and cascade labels.
- `src/public_cascade.py`: public cascade prediction and feature-family ablations.
- `src/bridge.py`: public-only bridge feasibility probe, coverage reports, and multiplicity
  diagnostics.

Production scripts:

- `scripts/run_benchmark.py`: run only the old benchmark component.
- `scripts/run_public_cascade.py`: run only the public cascade component.
- `scripts/run_bridge_probe.py`: run only the public bridge coverage probe.
- `scripts/run_study.py`: run the combined paper workflow.
- `scripts/run_public_lake_full.sh`: staged full public-lake download/build job.
- `scripts/monitor_public_lake.py`: disk, manifest, row-count, and memory monitoring.

Current combined workflow:

```bash
just status
just analysis benchmark raw artifacts/benchmark
bash scripts/run_public_lake_full.sh --mode full
just analysis bridge raw artifacts/bridge_probe
just analysis study raw artifacts/study
```

Planned modules:

- `src/study.py`: final table and figure input assembly.
- `src/features.py`: optional future home for expanded XBRL tag and ratio definitions.

Workflow follow-up:

- `just status` is read-only and must not run `uv sync`.
- `just setup` is the environment-sync entrypoint.
- Public-lake v1.1 should retain bronze manifests, support resume/idempotent rebuilds, and
  use DuckDB or Polars for large FSDS/Notes parsing to avoid full pandas materialization.

## Readiness Matrix

| Component | Current status | Gate before paper claim |
| --- | --- | --- |
| Experiment 1 benchmark | benchmark evidence available; timing claim is proxy sensitivity | `timing_coverage.csv` emitted and external timing required for paper-grade maturation |
| Experiment 2 drift | scaffold-only diagnostics | validated breakpoint diagnostics over annual PR-AUC/Brier and feature-family shares |
| Experiment 3 MNAR | implemented as DML-style adjustment, needs PLR alignment | `missingness_density_score` PLR spec and toy checks |
| Experiment 4 public lake | gold-built, needs manifest/readiness audit | source coverage, task positives, censoring, and reproducibility manifest |
| Experiment 5 public cascade | public cascade evidence under construction; metadata baseline only until ratios land | `xbrl_ratio_*` and `xbrl_coverage_*` columns present with tag coverage and non-degenerate metrics |
| Experiment 6 bridge overlap | integration evidence pending gate | public bridge probe emits coverage, multiplicity, unmatched-characteristic reports, and no silent joins |

## Acceptance Criteria

Data integrity:

- no `res_an*` field enters benchmark predictors
- proxy-visible timing labels never use detection information after `train_origin_year`
- unknown-timing positives are counted in `timing_coverage.csv` and excluded from the
  proxy-visible training label
- no event released after `origin_date` enters public cascade predictors
- censoring masks are applied per horizon
- source availability is recorded as state, not treated as ordinary missingness
- crosswalk coverage is reported before overlap validation
- current raw CSV bridge probe reports `raw_identifier_blocker` until raw-side company
  identifiers are supplied

Empirical sufficiency:

- benchmark produces non-empty rolling metrics and missingness-regime outputs
- benchmark summary reports `timing_claim_status`
- public cascade full panel covers fiscal years 2011-2023
- comment-thread, amendment, and 8-K Item 4.02 labels have nonzero positives
- zero-positive task labels, including current AAER proxy if applicable, are skipped and
  reported as blockers
- feature-family ablations are not metadata-only in the full public run; `xbrl_ratio_*`
  features unlock the first non-metadata baseline
- overlap validation reports both alignment and non-equivalence between old labels and public
  cascade labels

Paper-readiness:

- claims are framed as measurement and decision-useful prediction, not causal proof of fraud
  occurrence
- AAER is described as a severity proxy only
- public comment letters are described as public scrutiny only, not full SEC review
- Future-work extensions are kept out of the main contribution unless the base paper is stable
