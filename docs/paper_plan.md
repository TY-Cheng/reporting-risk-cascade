---
hide:
  - navigation
---

# Manuscript Skeleton

Working title:

**From Restatements to Public Review and Correction: Label Observability and the Public Reporting-Risk Cascade**

## Introduction

### Overview and Why This Work

- **Research setting.** Traditional misstatement and restatement benchmarks label firm-years after misconduct is detected, disclosed, or made publicly visible.
- **Measurement problem.** These labels are useful, but they mix the underlying reporting problem with discovery probability, disclosure delay, and selective public observability.
- **Empirical object.** The paper studies a filing-native public reporting-risk cascade built from SEC and PCAOB data.
- **Primary target.** The cascade measures public review-and-correction outcomes from the filing origin, not unobserved fraud occurrence.
- **Why this work.** Users of reporting-risk models need signals that are aligned with the public information set available when a filing is made. A filing-origin design is closer to the decision problem than an ex post detected-misstatement label alone.

### Research Question and Contribution

- **Core question.** Can reporting-risk prediction be reframed from ex post detected misconduct to filing-origin public review-and-correction risk?
- **Timing contamination.** Static detected-misstatement labels mix occurrence, discovery, disclosure lag, and public visibility.
- **Main contribution.** The intended contribution is a measurement redesign, not a claim that a new classifier performs better than prior fraud-prediction models.
- **Filing-origin estimand.** The repo defines a filing-origin public reporting-risk estimand based only on information visible at or before `origin_date`.
- **Construct claim.** The public cascade is expected to be related to, but not identical with, detected-misstatement benchmark labels.
- **Peer comparison boundary.** Peer models and metrics are used for compatibility checks; comparisons provide metric-compatible ranking evidence, not same-estimand performance rankings.
- **Model-family boundary.** The detected-misstatement peer benchmark and the public-label transfer suite use the same Dechow, Perols, Bao, and Bertomeu model-family vocabulary. Mapping quality determines whether Dechow/Bao adapters can use stronger names or must be reported as mapped or inspired variants. Public peer transfer runs only in `full` mode so the default workflow stays bounded.
- **Evidence requirement.** Credible bridge-based overlap validation is required before any integrated benchmark-to-public claim.

### Research Gap

- **Gap 1: outcome observability.** Existing detected-misstatement and fraud-prediction studies typically evaluate labels observed after detection and disclosure. They do not isolate whether a filing-year model is predicting underlying misconduct, later discovery, public disclosure, or enforcement visibility.
- **Gap 2: public review process.** SEC comment-letter and disclosure-review studies establish that public scrutiny is economically meaningful, but they usually do not build a multi-outcome, filing-origin prediction cascade from public SEC/PCAOB data.
- **Gap 3: comparable but different targets.** Hidden-misconduct and partial-observability papers motivate separating occurrence and detection. They are construct anchors, not PR-AUC comparators for the public filing-origin target.
- **Gap 4: reproducible bridge evidence.** The detected-misstatement benchmark uses `gvkey x data_year`; the public cascade uses `issuer_cik x fiscal_year x origin_date`. An integrated claim requires a documented gvkey-CIK-year bridge with coverage, multiplicity, conflict, and overlap diagnostics.

### Sellable Thesis

- **Sell.** The paper sells a measurement-and-ranking framework for public reporting-risk states. The contribution is a public, filing-origin outcome system and a transparent comparison to the detected-misstatement benchmark.
- **Not the sell.** The paper does not sell an unobserved-fraud detector, a causal enforcement model, or a same-estimand performance ranking against prior fraud-prediction papers.

## Literature and Research Gap

### Literature Streams and Existing Results

- **Literature role.** Prior work supplies model families, performance metrics, and construct anchors.
- **Estimand shift.** Prior fraud and restatement studies often predict detected ex post misconduct labels; this paper predicts subsequent public review-and-correction events from a filing-origin information set.
- **Metric-compatible comparison.** Metric-compatible comparison is evidence about ranking behavior under a shared scoring language, not evidence that the tasks share the same estimand.

| Stream | Canonical anchors | Typical models and metrics | Role in this paper |
| --- | --- | --- | --- |
| Detected misstatement and fraud prediction | [Dechow, Ge, Larson, and Sloan (2011)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=997483); [Perols (2011)](https://doi.org/10.2308/ajpt-50009); [Bao, Ke, Li, Yu, and Zhang (2020)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2670703); [Bertomeu, Cheynel, Floyd, and Pan (2021)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3496297), "Using Machine Learning to Detect Misstatements" | Logistic/F-score models, SVM, decision trees, bagging, stacking, neural nets, and tree ensembles; AUC, classification rates, lift, variable importance, and top-fraction ranking metrics | Supplies the benchmark peer suite: Dechow-style scores, a Perols-style benchmark model zoo, Bao-style top-fraction balanced accuracy and NDCG, and Bertomeu-style XGBoost feature importance. |
| Partial observability and hidden misconduct | [Barton, Burnett, Gunny, and Miller (2024)](https://pubsonline.informs.org/doi/10.1287/mnsc.2022.4627); [Dyck, Morse, and Zingales (2024)](https://link.springer.com/article/10.1007/s11142-022-09738-5) | Occurrence/detection separation, hidden misconduct estimation, likelihood and coefficient evidence | Motivates the estimand shift; these models are not PR-AUC comparators for the current design. |
| SEC comment-letter and disclosure-review research | [Cassell, Cunningham, and Myers (2013)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1951445); [Bozanic, Dietrich, and Johnson (2018)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2989164); [Brown, Tian, and Tucker (2018)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2551451); the [SEC filing review process](https://www.sec.gov/about/divisions-offices/division-corporation-finance/filing-review-process-corp-fin) | Regression-style evidence on comment receipt, remediation, and disclosure response | Establishes public comment-letter scrutiny as economically meaningful; this paper embeds it as one public-cascade outcome rather than the sole endpoint. This stream supplies regression-style evidence rather than direct ranking-score comparators. |
| Public regulatory and structured-data sources | [SEC Item 4.02 guidance](https://www.sec.gov/about/divisions-offices/division-corporation-finance/financial-reporting-manual/frm-topic-4); [PCAOB Form AP](https://pcaobus.org/oversight/standards/implementation-resources-PCAOB-standards-rules/form-ap-auditor-reporting-certain-audit-participants); [SEC Inline eXtensible Business Reporting Language (XBRL)](https://www.sec.gov/data-research/structured-data/inline-xbrl) | Public filing events, audit-participant data, oversight data, and standardized financial facts | Supplies the filing-native public lake and reproducible feature construction. |

### Positioning Against Existing Results

- **Positioning.** The paper aligns the prediction target to the observable public process.
- **Benchmark role.** The detected-misstatement benchmark remains a disciplined diagnostic for timing sensitivity, label observability, concept drift, and missingness.
- **Overlap role.** The bridge tests where the public cascade agrees or disagrees with detected-misstatement labels.
- **What prior results can support.** The prior literature supports the model-family vocabulary, the importance of hidden detection, the economic relevance of SEC review, and the use of ranking/calibration metrics.
- **What prior results cannot support.** Prior results do not make public review-and-correction labels equivalent to fraud, and they do not make the public cascade a same-estimand benchmark against detected-misstatement classifiers.

## Data and Sample Construction

### Reproduction Inputs

- **Operational inputs.** A reproducible run needs the detected-misstatement benchmark file, the public SEC/PCAOB lake configuration, and the WRDS bridge export:
    - `$DATA_DIR/raw/raw_dataset_misstatement.parquet` for the `gvkey x data_year` detected-misstatement benchmark.
    - `config/public_data.yaml` and `config/study.yaml` for public-source and study defaults.
    - `$DATA_DIR/linkage/raw_only/gvkey_cik_year.csv` for bridge validation, generated only from the raw CIK-GVKEY link table.
- **Public-data run.** The current paper-facing public lake is built with `storage_format=parquet`, `notes_mode=summary`, DuckDB, and as-of date `2026-04-23`.
- **Peer and overlap run.** The peer-enabled study is a separate run so the default workflow stays bounded.

### Data Engineering and Preprocessing Overview

```mermaid
flowchart LR
    subgraph BENCHMARK["Detected-misstatement benchmark diagnostic: external benchmark, not SEC/PCAOB public lake"]
        L0["Input panel<br/>gvkey x data_year<br/>2001-2019<br/>accounting, audit, governance,<br/>market, and industry predictors"]
        L1["Benchmark X<br/>engineered benchmark predictors<br/>exclude ids, labels, res_an* timing proxies,<br/>and post-outcome fields"]
        L2["Benchmark Y<br/>detected misstatement firm-year<br/>naive, proxy_drop_observed,<br/>proxy_imputed_lag 1/2/3/5y<br/>external_timing only if validated dates exist"]
        L3["Benchmark prediction loops<br/>annual out-of-time test years<br/>rolling_5y, rolling_7y, rolling_10y, expanding<br/>core benchmark plus detected-misstatement peer suite<br/>Dechow / Perols / Bao / Bertomeu families"]
        L4["Benchmark metrics<br/>PR-AUC relative to prevalence, ROC-AUC,<br/>Brier/BSS, ECE, top-50/100/200 precision,<br/>Bao top-fraction precision, sensitivity, BAC, NDCG"]
        L5["Benchmark interpretation<br/>label observability, timing fragility,<br/>concept drift, missingness diagnostics<br/>not unobserved fraud occurrence"]
        L0 --> L1
        L0 --> L2
        L1 --> L3
        L2 --> L3
        L3 --> L4
        L4 --> L5
    end

    subgraph PUBLIC["Public filing-origin cascade: SEC/PCAOB public information set"]
        P0["Public inputs<br/>EDGAR filings, FSDS/XBRL, Notes summaries,<br/>comment letters, amendments, 8-K Item 4.02,<br/>PCAOB Form AP, PCAOB inspections<br/>public sample 2011-2023, as-of 2026-04-23"]
        P1["Parquet public lake<br/>Bronze source cache<br/>Silver normalized event and fact tables<br/>Gold filing_origin_panel and issuer_origin_panel"]
        P2["Public modeling grain<br/>issuer_cik x fiscal_year<br/>origin_date is selected annual filing date<br/>features visible at or before origin_date"]
        P3["Public X<br/>metadata, XBRL ratios, auditor, oversight, all<br/>rolling public history requires event_date < origin_date<br/>exclude source_available_*, public_date_*, vintage_* fields"]
        P4["Public Y<br/>label_comment_thread_365: SEC comment-thread scrutiny<br/>label_amendment_365: amended filing or filing friction<br/>label_8k_402_365: Item 4.02 non-reliance"]
        P5["Public prediction loops<br/>annual out-of-time fiscal-year tests<br/>rolling/expanding windows from earlier years only<br/>core cascade model plus public-label peer suite<br/>same Dechow / Perols / Bao / Bertomeu families"]
        P6["Public metrics<br/>same metric vocabulary as benchmark where defined<br/>PR-AUC vs prevalence, ROC-AUC, Brier/BSS, ECE,<br/>top-50/100/200 precision, top-decile lift,<br/>Bao-style top-fraction metrics"]
        P7["Public interpretation<br/>filing-origin review-and-correction risk signal<br/>feature-family value and model-family transfer evidence<br/>not a performance ranking on the detected-misstatement benchmark estimand"]
        P8["Public-label opacity DML<br/>missingness_density_score to public labels<br/>cross-fitted nuisance models<br/>adjusted association, not causal effect"]
        P0 --> P1
        P1 --> P2
        P2 --> P3
        P2 --> P4
        P3 --> P5
        P4 --> P5
        P5 --> P6
        P6 --> P7
        P3 --> P8
    end

    subgraph VALIDATION["Bridge and interpretation layer"]
        V0["Bridge gate<br/>raw-only gvkey-CIK-year crosswalk<br/>confirmed WRDS SEC Analytics Suite CIK-GVKEY link table<br/>no farr/external CIK supplement in the default bridge"]
        V1["Linkage QA<br/>coverage, multiplicity, unmatched rows,<br/>raw source composition,<br/>public_lake and public_lake_smoke overlap summaries<br/>before any construct-overlap claim"]
        V2["Construct-overlap checks<br/>matched 2011-2019 benchmark/public sample<br/>benchmark labels vs public labels<br/>public scores rank benchmark positives<br/>benchmark scores rank public labels<br/>event-time concentration"]
        V3["Final claim boundary<br/>public cascade is related to,<br/>but not identical with,<br/>detected-misstatement benchmark labels<br/>current bridge tier: wrds_validated"]
        V4["If bridge validation is incomplete<br/>report public-cascade measurement result<br/>without unobserved-fraud or same-estimand performance claim"]
        V0 --> V1
        V1 --> V2
        V2 --> V3
        V0 -.-> V4
    end

    L5 --> V0
    P7 --> V0
    P8 --> V0
```

### Detected-Misstatement Benchmark Panel

- **File.** `$DATA_DIR/raw/raw_dataset_misstatement.parquet`.
- **Grain.** `gvkey x data_year`.
- **Coverage.** 2001-2019.
- **Required fields.** `gvkey`, `data_year`, `misstatement firm-year`, `res_an0` to `res_an3`, `missing_*` flags, and accounting/audit/governance/market/industry predictors.
- **Predictor surface.** Benchmark predictors are the engineered columns already present in the raw benchmark panel. `gvkey`, `data_year`, target columns, timing proxy columns, missingness labels, and post-outcome fields are not treated as ordinary predictors.
- **Evaluation grain.** All benchmark prediction rows remain annual firm-year rows evaluated by out-of-time test year.
- **Limitation.** No CIK, ticker, PERMNO, restatement filing date, detector identity, or complete public filing history.

### Public SEC/PCAOB Lake

- **Storage design.** `$DATA_DIR/public_lake/` is organized as bronze, silver, and gold.
- **Bronze.** Downloaded public files with source URL, timestamp, SHA256 hash, parser version, schema version, and as-of date.
- **Silver.** Normalized issuer, filing, XBRL, Notes, comment-thread, correction, Form AP, and PCAOB inspection tables; large Silver tables are Parquet-first.
- **Gold.** `issuer_origin_panel.parquet` and `filing_origin_panel.parquet`.
- **DuckDB path.** The default DuckDB path uses SQL for XBRL core-tag pivoting, label-horizon joins, and Parquet output on the annual issuer-year modeling panel.
- **Filing-origin provenance.** The full filing-origin panel is retained as a lightweight, year-sharded provenance panel rather than a fully labeled 20M-row modeling table.
- **Required v1 sources.** SEC submissions, SEC Financial Statement Data Sets (FSDS), SEC `UPLOAD` and `CORRESP`, 10-K/A and 10-Q/A amendments, 8-K Item 4.02, PCAOB Form AP, and PCAOB inspection datasets.
- **Main public sample.** Domestic U.S. GAAP issuer-years from 2011-2023, with `2026-04-23` as the current reproducibility as-of date.
- **Source-to-table mapping.**
    - SEC submissions and filing index data form `filing_dim.parquet`, `issuer_dim.parquet`, `filing_origin_panel.parquet`, and the annual `issuer_origin_panel.parquet`.
    - FSDS/XBRL `sub` and `num` files form `filing_xbrl_dim.parquet`, `xbrl_fact_summary.parquet`, and `xbrl_core_fact/`.
    - SEC Notes are normalized in summary mode into `notes_filing_dim.parquet` and `note_summary.parquet`; raw text blobs are not part of the default paper-facing run.
    - SEC `UPLOAD` and `CORRESP` produce `comment_thread.csv.gz` with first public correspondence dates.
    - 10-K/A and 10-Q/A filings, explanatory notes, and form-level filters produce `correction_event.csv.gz` and `amendment_annotation.csv.gz`.
    - 8-K Item 4.02 parsing produces `issuer_8k_item_event.csv.gz`.
    - PCAOB Form AP and inspection sources produce auditor and oversight features in the Silver/Gold panels.

### Public Review-and-Correction Labels

- **Public-label grain.** Public labels are attached to the annual `issuer_cik x fiscal_year x origin_date` issuer-year row.
- **Outcome design.** The public cascade is a multi-label outcome system, not a deterministic hierarchy.
- **Public labels.**
    - `label_comment_thread_365`: public comment-letter scrutiny, measured from the first public EDGAR date of the comment-thread sequence; source: [SEC filing review process](https://www.sec.gov/about/divisions-offices/division-corporation-finance/filing-review-process-corp-fin) and public EDGAR correspondence.
    - `label_amendment_365`: broad amendment/friction signal, including administrative amendments, filing friction, and potentially material corrections; source: [SEC EDGAR filing access](https://www.sec.gov/edgar/search-and-access) and amended filing form metadata.
    - `label_8k_402_365`: Item 4.02 non-reliance and material-correction proxy; source: [SEC Form 8-K](https://www.sec.gov/files/form8-k.pdf), Item 4.02.
- **Forward horizons.**
    - `label_comment_thread_365 = 1` if a public SEC comment-letter thread is first observed after `origin_date` and within 365 days.
    - `label_amendment_365 = 1` if a qualifying amended-filing or correction/friction event appears after `origin_date` and within 365 days.
    - `label_8k_402_365 = 1` if an 8-K Item 4.02 non-reliance event appears after `origin_date` and within 365 days.
- **Co-occurrence rule.** A later-stage positive does not mechanically force an earlier-stage label.
- **Construct meaning.** These labels are not alternative names for fraud. They are public observability states: regulatory scrutiny (`comment_thread`), filing correction or friction (`amendment`), and material non-reliance (`8k_402`).
- **Target distinction.** The target is public review-and-correction risk rather than unobserved fraud occurrence.

### Bridge Validation Inputs

- **Bridge file.** `$DATA_DIR/linkage/raw_only/gvkey_cik_year.csv`.
- **Required fields.** `gvkey`, `issuer_cik`, a single year or start/end years, and provenance fields such as source, version, extraction date, match method, and match score.
- **Bridge grain.** Bridge validation maps detected-misstatement benchmark `gvkey x data_year` rows to public `issuer_cik x fiscal_year` rows. It must report coverage, multiplicity, high-confidence and ambiguous matches, and unmatched diagnostics before overlap evidence is interpreted.
- **Raw-only rule.** `raw/CIK-GVKEY Link Table.csv` is the default bridge source. The previous farr/external gvkey-CIK bridge is no longer used as a supplement for missing raw gvkey-years.
- **Current raw-only WRDS route.**

```bash
uv run python scripts/build_linkage_bridge.py
```

- **Alternative WRDS route for a new export.**

```bash
set -a; source .env; set +a
uv run python scripts/prepare_gvkey_cik_crosswalk.py \
  --input path/to/wrds_cik_gvkey_link.csv \
  --out "$DATA_DIR/linkage/wrds_candidate/gvkey_cik_year.csv" \
  --source wrds_compustat_cik_gvkey_link \
  --source-version "YYYY-MM-DD"

just task bridge raw artifacts/wrds_candidate_bridge_probe \
  extra="--crosswalk $DATA_DIR/linkage/wrds_candidate/gvkey_cik_year.csv"
uv run python scripts/run_construct_overlap.py \
  --study-dir artifacts/full_with_peer \
  --crosswalk "$DATA_DIR/linkage/wrds_candidate/gvkey_cik_year.csv"
```

- **Current WRDS bridge.** The raw-only bridge is the working WRDS bridge. The confirmed source is WRDS SEC Analytics Suite `CIK-GVKEY Link Table.csv`, received from the collaborator via Outlook. Its source field includes CRSP/Compustat Merged, Compustat Company, Compustat Security, and Capital IQ rows.
- **Validation tier.** Construct-overlap outputs infer `validation_tier` from normalized crosswalk provenance: the current raw-only WRDS bridge is `wrds_validated`.
- **External support policy.** The default pipeline no longer uses farr/external support files. The only unique external support field was date-bounded headquarters/business-address state from `farr::state_hq`; it is dropped as a nonessential metadata feature.
- **Missing bridge behavior.** If no usable crosswalk exists, the bridge probe must report `raw_identifier_blocker` rather than infer links from benchmark identifiers alone.

### Preprocessing and Feature Construction

- **Common sample rule.** Feature families use the same filtered issuer-year sample for fair ablations.
- **Missing-value rule.** Tree models with native missing-value handling retain numeric `np.nan`; non-tree adapters use fold-internal imputation only when required.
- **Excluded columns.** Label, censoring, identifier, source-availability, public-date, and vintage columns are excluded by default.
- **Metadata.** SIC, form, SEC submissions `entityType`, filing size, XBRL flags, prior filing count, days since prior filing, and headquarters-state controls when available.
- **Filing friction and public history.** Current-cycle NT status and amendment friction, plus strictly pre-origin rolling counts and recency for prior NT filings, comment threads, amendments, and 8-K instability items. Rolling public-history features must use only events with `event_date < origin_date`.
- **XBRL.** `xbrl_ratio_*` and `xbrl_coverage_*` features from controlled core tags, including size, leverage, profitability, working capital, receivables, inventory, cash, debt, operating cash flow, and year-over-year revenue/assets changes.
- **Auditor and oversight.** PCAOB Form AP fields, engagement-partner exposure, and PCAOB inspection features in their public source windows.
- **Note opacity.** Note count, note character count, note-tag coverage, and tag entropy as a disclosure breadth measure.
- **Leakage exclusions.** `source_available_*`, `public_date_*`, `vintage_*`, `as_of_date`, accession identifiers, CIK/GVKEY identifiers, labels, censoring flags, and direct event-date fields document provenance and timing but are not default predictors.
- **Fold-local transformations.** Imputation, scaling, and any model-specific preprocessing are fit inside the training fold and then applied to the held-out fiscal year.
- **Deferred extensions.** Proxy-governance content, SEC insider-pressure features, macro-vintage controls, auditor-firm public-status fields, and broader security/attention layers are useful extensions, not required for the current v1 paper claim.

### Timing, Censoring, and Sample Rules

- **Origin date.** In the current v1 panel, `filing_origin_panel.origin_date = filing_date`, and `issuer_origin_panel.origin_date` is the selected annual filing date for the issuer-year.
- **No post-origin leakage.** No event released after `origin_date` may enter predictors.
- **Excluded coverage fields.** `source_available_*`, `public_date_*`, `vintage_*`, and `as_of_date` document source availability and public vintages but are excluded from default predictors.
- **Censoring.** Horizon-specific censoring flags remove issuer-years whose outcome window extends beyond the as-of date. Current public labels use 365-day censoring.
- **Split design.** Prediction experiments use annual out-of-time evaluation, not random cross-validation.
- **Training windows.** For a given test year, training uses earlier years only, with expanding or rolling 5-, 7-, and 10-year windows.

## Methods and Models

### Measurement Design

- **Detected-Misstatement Benchmark Labels.** The benchmark panel uses `gvkey`, `data_year`, and `misstatement firm-year`. It tests whether traditional restatement prediction is sensitive to timing, drift, and missingness.
- **Label modes.**
    - `naive`: the observed `misstatement firm-year` label without detection-timing adjustment.
    - `proxy_drop_observed`: a coverage stress test using sparse same-row `res_an*` timing proxies, excluding positives without usable timing evidence.
    - `proxy_imputed_lag`: a timing-assumption grid assigning unknown positives one-, two-, three-, or five-year detection lags.
    - `external_timing`: the paper-grade benchmark maturation target, available only if validated public restatement or detection dates are supplied.
- **Leakage rule.** `res_an0`, `res_an1`, `res_an2`, and `res_an3` are timing proxies only and never enter predictors.
- **Required reporting.** `timing_coverage.csv` must report same-row timing coverage, unknown positives, retained-positive share, and class-balance changes.

### Model Families

| Component | Models | Inputs | Role |
| --- | --- | --- | --- |
| Detected-misstatement benchmark core | XGBoost classifier over engineered benchmark predictors | `raw_dataset_misstatement.parquet`, excluding ids, labels, `res_an*`, missingness labels, and post-outcome fields | Timing, drift, and missingness diagnostics on the detected-misstatement label. |
| Detected-misstatement peer benchmark | Dechow fixed and variable logit, Perols logit/tree/bagging/SVM/stacking/MLP, Bao-style or Bao-inspired ensemble, Bertomeu-style XGBoost | Same benchmark folds and repo-native variable mappings | Model-family transfer and metric-language compatibility, not original-paper numeric replication. |
| Public cascade core | XGBoost classifier over metadata, XBRL, text/notes, auditor, oversight, and all-feature sets | `issuer_origin_panel` rows with pre-origin public features | Main filing-origin public review-and-correction prediction task. |
| Public-label peer suite | Dechow variable/fixed mapped variants and Bao-inspired tree ensemble when mapping gates permit | Public issuer-origin feature families | Checks whether familiar model-family vocabularies transfer to the public-label task. |
| Public-label opacity DML | Double / Debiased Machine Learning (DML) partially linear regressions with cross-fitted nuisance models | `missingness_density_score` and pre-origin controls | Adjusted association between opacity/missingness and public labels, not a causal effect. |
| Construct-overlap layer | Contingency, top-decile lift, reciprocal ranking, and event-time concentration checks | Raw-only WRDS gvkey-CIK-year bridge, benchmark predictions, public predictions | Tests related but non-identical construct evidence. |

### Model Selection and Skip Rules

- **Primary public model.** The public cascade reports XGBoost by feature family and training window because tree models handle nonlinear interactions and native missingness while keeping feature-family ablations interpretable.
- **Peer models.** Peer suites are included to place results in Dechow, Perols, Bao, and Bertomeu-style model-family language. They are not treated as exact replications unless the variable mapping and sample gates support that claim.
- **Public peer mapping.** Public peer transfer reuses Dechow/Perols/Bao/Bertomeu model-family language. Dechow and Bao labels are reported as fixed, mapped, or inspired variants according to mapping quality; public Bao transfer uses `public_issuer_origin` input and is therefore `bao_inspired_tree_ensemble`, not a Bao raw-accounting-number replication.
- **Skip rule.** Skip task/family/window fits with one-class train or test labels.

## Evaluation Metrics

### Metric Selection Criteria

- **Primary criterion.** PR-AUC relative to prevalence is the first-read metric because the labels are rare and ranking useful public review-and-correction cases is the main empirical task.
- **Discrimination criterion.** ROC-AUC is reported for compatibility with prior fraud-prediction studies, but it is not sufficient on its own in rare-event settings.
- **Calibration criterion.** Brier score, Brier Skill Score, and expected calibration error are reported because risk scores should be interpretable as probabilities, not only rankings.
- **Operational ranking criterion.** Top-50/100/200 precision and top-decile lift describe what a reviewer sees when inspecting the highest-risk issuer-years.
- **Literature-comparability criterion.** Bao-style top-fraction precision, sensitivity, specificity, balanced accuracy, and binary-relevance NDCG@k are retained for model-family comparability.

### Metric Definitions and Interpretation

- **Predictive metrics.** PR-AUC, ROC-AUC, Brier score, Brier Skill Score, expected calibration error, top-50/100/200 precision, and Bao-style top-fraction metrics.
- **Bao-style metrics.** Top-fraction precision, sensitivity, specificity, balanced accuracy, and binary-relevance NDCG@k.
- **Calibration.** Calibration metrics are diagnostic under class imbalance and resampling.
- **Prevalence.** `Prevalence` is the positive-class rate in the evaluated sample and the natural random-ranking baseline for PR-AUC.
- **PR-AUC interpretation.** When positives are rare, a numerically small PR-AUC can still represent meaningful lift over the base rate.
- **ROC-AUC contrast.** ROC-AUC has a fixed random baseline near 0.5 and can look much larger than PR-AUC in rare-event settings.
- **DML separation.** Cross-fitting appears separately in Double / Debiased Machine Learning (DML) opacity diagnostics; it is not the train/test split used for headline prediction tables.
- **No absolute sufficiency threshold.** Prediction metrics are read relative to each task's prevalence; there is no absolute PR-AUC sufficiency threshold.

## Experiments

### Experiment 1: Label Observability and Detection Timing

- **Purpose.** Quantify how sensitive traditional restatement evaluation is to timing coverage and unknown-positive assumptions.
- **Design.** Run annual out-of-time benchmark backtests across expanding, rolling 5-year, rolling 7-year, and rolling 10-year windows; compare `naive`, `proxy_drop_observed`, and `proxy_imputed_lag` labels.
- **Outputs.** `rolling_metrics.csv`, `rolling_predictions.parquet`, `timing_coverage.csv`, `timing_summary.json`, `timing_claim_status`, and window summaries.
- **Interpretation.** This is a benchmark-validity diagnostic; a decline under `proxy_drop_observed` is timing-observability sensitivity, not proof of look-ahead bias by itself.

### Experiment 2: Concept Drift and Model Shelf-Life

- **Purpose.** Estimate whether reporting-risk models trained in one regime remain useful in later regimes.
- **Design.** Compare rolling and expanding windows over test years; track feature-family importance; report pre/post diagnostics around major regulatory and data-regime breakpoints.
- **Outputs.** Annual metrics, window summaries, structural-break diagnostics, and feature-family importance.
- **Interpretation.** The experiment supports model shelf-life and retraining-window evidence; it does not establish structural causality from predictive drift alone.

### Experiment 3: Opacity and Public Review/Correction Risk

- **Purpose.** Test whether pre-origin opacity and missingness profiles predict later public scrutiny or correction.
- **Design.** Construct missingness-density and missing-profile indicators; estimate Double / Debiased Machine Learning (DML) partially linear regressions on public labels.
- **Primary outcomes.** `label_comment_thread_365`, `label_amendment_365`, and `label_8k_402_365`.
- **Treatment-like variable.** `D = missingness_density_score`.
- **Controls.** `X = pre-origin metadata, XBRL, filing-friction, public-history, auditor, oversight, note-opacity, and calendar controls`.
- **Outputs.** Missing-profile clusters, public-label PLR spec results, nuisance-model metadata, and diagnostic benchmark-side DML outputs.
- **Interpretation.** Coefficients are adjusted associations, not causal effects; the `misstatement firm-year` outcome remains a detected-misstatement benchmark diagnostic only.

### Experiment 4: Public Cascade Construction

- **Purpose.** Demonstrate that public data can support a defensible review-and-correction cascade.
- **Design.** Build the public lake from SEC/PCAOB sources; construct labels from first public dates; report source coverage, event rates, censoring, and task readiness.
- **Outputs.** Source coverage tables, event-rate tables, censoring summaries, public-lake metadata, and task-positive counts.
- **Interpretation.** This experiment validates the measurement surface for observable public review and correction states.

### Experiment 5: Public Cascade Prediction

- **Purpose.** Estimate the pre-disclosure public reporting-risk state from public features.
- **Design.** Use `issuer_origin_panel` to predict comment-thread scrutiny, broad amendment/friction, and 8-K Item 4.02 outcomes; run feature-family ablations over metadata, XBRL, auditor, oversight, and all-feature sets.
- **Skip rule.** Skip task/family/window fits with one-class train or test labels.
- **Outputs.** `public_cascade_metrics.csv`, `public_cascade_predictions.parquet`, `public_cascade_task_status.csv`, `public_cascade_summary.md`, and `public_opacity_dml.csv`.
- **Interpretation.** Full public-cascade claims require non-metadata features; `metadata_baseline` is a readiness state, and `xbrl_ratio_baseline` is the first non-metadata empirical baseline.

### Experiment 6: Detected-Misstatement Benchmark and Public Cascade Overlap

- **Purpose.** Test whether detected-misstatement benchmark labels and public review-and-correction labels measure related but non-identical constructs.
- **Design.** Run the bridge probe, report coverage and multiplicity, then test event-time concentration and reciprocal risk-score alignment in the mapped sample.
- **Current bridge.** The current implementation uses the raw-only bridge at `$DATA_DIR/linkage/raw_only/gvkey_cik_year.csv`: raw `CIK-GVKEY Link Table.csv` links define the mapped `gvkey x data_year` rows. Farr `gvkey_ciks` no longer supplements missing raw years in the default workflow.
- **Outputs.** `bridge_probe_summary.json`, `coverage_report.csv`, `multiplicity_report.csv`, `unmatched_raw_characteristics.csv`, `construct_overlap/label_contingency_lift.csv`, `construct_overlap/public_score_legacy_ranking.csv`, `construct_overlap/reciprocal_alignment.csv`, and `construct_overlap/event_time_concentration.csv`.
- **Interpretation.** This is the integrated-paper gate; the raw-only bridge now supports WRDS-validated overlap evidence while preserving the related-but-non-identical construct boundary.

## Expected and Current Results

### Expected Evidence Pattern

- **Benchmark expectation.** Detected-misstatement benchmark performance should be sensitive to timing assumptions, label observability, class balance, and retraining window.
- **Public-cascade expectation.** Public features should predict later public review-and-correction outcomes above each task's prevalence baseline, especially for comment-thread and amendment/friction labels.
- **Feature-family expectation.** Metadata is a readiness baseline; XBRL, auditor, oversight, note-opacity, and all-feature models test whether non-metadata public information adds empirical value.
- **Overlap expectation.** Detected-misstatement benchmark labels and public labels should show enrichment and reciprocal ranking alignment, but not one-to-one equivalence.

### Current Result Snapshot

- **Public cascade.** Current full-run public-cascade state is complete; the best specification in the current snapshot is `all + expanding` with reported mean PR-AUC `0.2887`. The all-feature family is also the strongest feature-family summary, with mean PR-AUC `0.2875`.
- **Public sample.** The public cascade covers fiscal years 2011-2023 in the full panel, with nonzero positives for comment-thread, amendment, and 8-K Item 4.02 tasks.
- **Detected-misstatement benchmark.** Benchmark outputs include non-empty rolling metrics, timing coverage, and missingness diagnostics.
- **Bridge overlap.** Raw-only WRDS overlap is implemented. Construct-overlap outputs carry `validation_tier = wrds_validated` for the current raw-only bridge.

### Artifact Map

| Evidence | Primary artifacts |
| --- | --- |
| Benchmark timing and drift | `artifacts/full_with_peer/benchmark/rolling_metrics.csv`, `timing_coverage.csv`, `timing_summary.json` |
| Public cascade prediction | `artifacts/full_with_peer/public_cascade/public_cascade_metrics.csv`, `public_cascade_predictions.parquet`, `public_cascade_task_status.csv` |
| Public opacity DML | `artifacts/full_with_peer/public_cascade/public_opacity_dml.csv`, `public_opacity_dml_meta.json` |
| Bridge probe | `artifacts/full_with_peer/bridge_probe/bridge_probe_summary.json`, `coverage_report.csv`, `multiplicity_report.csv` |
| Construct overlap | `artifacts/full_with_peer/construct_overlap/public_score_legacy_ranking.csv`, `construct_overlap/reciprocal_alignment.csv`, `event_time_concentration.csv` |
| Paper-facing summary | `docs/results_snapshot.md`, `artifacts/manuscript_package` |

## Claim Boundaries

### Claim Boundaries

> The public-cascade design supports evidence about a public reporting-risk state. It does not by itself identify unobserved fraud occurrence, causal effects, or a stable enforcement-prediction result.

> Comment letters are public scrutiny signals, not the full SEC review universe.

> Bridge validation is mandatory for an integrated claim that the public cascade and the detected-misstatement benchmark measure related but non-identical constructs. Without that validation, the public-cascade result remains a public-data measurement result rather than a validated fraud/restatement overlap paper.

### Evidence Gates

| Component | Current status | Gate before paper claim |
| --- | --- | --- |
| Benchmark timing | implemented as observability sensitivity | report `timing_coverage.csv`, retained positives, and imputed-lag scenarios; external timing required for paper-grade maturation |
| Concept drift | implemented as rolling-window diagnostics | validate annual PR-AUC, Brier Skill Score, feature-importance drift, and breakpoint summaries |
| Opacity | public-label DML implemented; refresh summary is separate from construct overlap | public-label PLR results must use `label_comment_thread_365`, `label_amendment_365`, and `label_8k_402_365` as primary outcomes |
| Public lake | full public lake path implemented | refreshed source coverage, row counts, censoring, and reproducibility metadata |
| Public cascade | current full-run state is `xbrl_ratio_baseline` | non-degenerate comment-thread, amendment, and 8-K Item 4.02 tasks |
| Bridge overlap | raw-only WRDS overlap implemented | coverage, multiplicity, reciprocal alignment, and no silent many-to-many joins before final integrated claims |

- **Data integrity gates.**
    - No post-`origin_date` event enters predictors.
    - No `res_an*` column enters benchmark predictors.
    - `source_available_*`, `public_date_*`, `vintage_*`, and `as_of_date` stay outside default predictors.
    - Censoring masks are horizon-specific.
    - Crosswalk coverage and multiplicity are reported before overlap validation.
- **Empirical sufficiency gates.**
    - Benchmark outputs non-empty rolling metrics, timing coverage, and missingness diagnostics.
    - Public cascade covers fiscal years 2011-2023 in the full panel.
    - Comment-thread, amendment, and 8-K Item 4.02 tasks have nonzero positives.
    - `xbrl_ratio_*` and `xbrl_coverage_*` features are present for non-metadata public-cascade evidence.
    - Prediction metrics are read relative to each task's prevalence; there is no absolute PR-AUC sufficiency threshold.
    - Overlap evidence reports top-decile lift, reciprocal alignment, bridge tiers, and bridge coverage before integrated claims are made.
- **Paper-readiness gates.**
    - Claims remain measurement and decision-useful prediction claims, not causal proof of fraud occurrence.
    - Comment letters are described as public scrutiny, not complete SEC review.
    - Bridge validation is mandatory for the integrated old-benchmark/public-cascade paper claim.
    - WRDS-validated raw-only overlap can support a related-but-non-identical construct argument, but not causal fraud-occurrence claims.

## Reproducibility and Execution Contract

### Core Commands

- **Operational reference.** The operational command surface lives in the repository home page and README so there is a single maintained entrypoint for users and coauthors.
- **Quality gate.**

```bash
just check
```

- **Paper-facing core run.**

```bash
just full mode=full dataset=raw
```

- **Peer-compatible model-family transfer.**

```bash
just task study raw artifacts/full_with_peer \
  extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
just snapshot
just manuscript
```

### Command Boundary

- **Command boundary.** `just check` is the local quality gate; `just full mode=full dataset=raw` is the paper-facing core run for data engineering and core experiments; `full_with_peer` adds the detected-misstatement and public-label peer model-family transfer suites; `just snapshot` refreshes the results snapshot from `artifacts/full_with_peer` and then runs `just check`; `just manuscript` builds paper-facing tables, figures, and result prose in `artifacts/manuscript_package`. Use `--peer-target public` when only the public-label peer transfer needs to be refreshed.
- **Detailed operations.** Component-level reruns and public-lake operational details are documented in [the repository home page](index.md), which includes the root `README.md`.
