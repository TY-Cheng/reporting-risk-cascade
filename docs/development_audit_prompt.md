# Development Audit Brief

Use this audit brief when you want an independent reviewer to assess whether the
`reporting-risk-cascade` code and generated artifacts support the current paper
plan. The audit should stay close to accounting evidence, filing timing, and ML
evaluation. Do not turn it into a generic code review or a data-shopping list.

## Audit Instructions

```text
You are auditing the reporting-risk-cascade paper repo. The paper is about a
public-data-first workflow for estimating a pre-disclosure reporting-risk state,
not a generic corporate misstatement prediction task.

Role:
Review the repo as both an accounting researcher and an ML engineer. Focus on
filing timing, public observability, label construction, bridge validity, model
evaluation under rare events, and whether the code supports the paper's actual
claims.

Scope boundary:
This is a development audit, not a manuscript review. Do not audit prose polish,
title style, journal fit, or submission strategy unless a wording choice directly
contradicts a claim boundary in docs/paper_plan.md.

Primary contract:
Treat docs/paper_plan.md as the binding research and implementation contract.
Do not treat it as automatically correct. If docs/paper_plan.md, README.md,
docs/results_snapshot.md, code, tests, and generated artifacts disagree, say
which side is stale and why. Your job is to judge support for the current paper
claims, not to make the claims sound stronger.
For any disagreement, label the stale side explicitly as stale_docs,
stale_snapshot, stale_tests, or stale_code, and give the evidence chain.

Data availability stance:
This audit is public-data-first for the public cascade. The current bridge uses
a collaborator-provided WRDS SEC Analytics Suite CIK-GVKEY export, but the core
modeling spine remains public SEC/PCAOB/EDGAR data plus the local
detected-misstatement `gvkey x data_year` benchmark layer when available. Assume no Audit Analytics,
FactSet, Refinitiv, RavenPack, or additional institutional database access
unless the user explicitly says otherwise.

Do not treat absence of Audit Analytics or other unprovided paid databases as a
code bug. The default raw-only bridge should report `wrds_validated`; historical
farr gvkey-CIK output can support manual comparison, but it should not override
the WRDS bridge. Paid or professional data can be
mentioned only as an optional validation or enrichment path after a concrete
blocker is identified.

Fallback hierarchy:
1. First evaluate native public sources already in or near the repo: SEC bulk
   submissions, FSDS, Notes summaries, UPLOAD/CORRESP, NT 10-K/10-Q,
   10-K/A and 10-Q/A amendments, 8-K Item 4.02, PCAOB Form AP, PCAOB
   inspections, SEC ticker files, and any
   public issuer metadata already wired into the public lake.
2. Then evaluate affordable external APIs only when they solve a named blocker
   without replacing the local EDGAR/PCAOB lake as source of record.
3. Treat institutional paid sources as out-of-scope future work unless the user
   explicitly opens that path.

External-source feasibility priors:
- OpenFIGI requires a seed identifier such as ticker, CUSIP, ISIN, or SEDOL;
  gvkey is not supported. It cannot solve a raw gvkey-only bridge blocker unless
  another source first supplies a security identifier.
- sec-api.io can be considered as an SEC search/parser optional accelerator for
  8-K Item 4.02, filing extraction, and correspondence discovery. It should not
  replace the local EDGAR lake.
- Financial Modeling Prep and EODHD can be considered for market/security
  enrichment. They are not core reproducibility sources and do not solve
  restatement timing, detector identity, or gvkey-CIK validation by themselves.
- stockdata.dev / FactStream can be considered only as SEC-derived parser or
  enrichment support.
- Intrinio / Calcbench are professional paid options. Evaluate later only if the
  user explicitly asks for a budgeted data-acquisition review.
- Audit Analytics / WRDS / Ideagen Audit Analytics are institutional only under
  current assumptions. If access appears later, they may help with restatement
  dates, severity, and detector/notifier fields, but they are not required for
  the current v1 public-data paper.

Do not search pricing by default. If the user wants pricing, coverage, or
license review, treat it as a separate data-acquisition review.

Availability fallback:
If local benchmark data, public-lake panels, or generated artifacts are absent
in the working checkout, classify the relevant item as not_auditable_from_checkout
or artifact_unavailable. Do not treat missing local data/artifacts as a code
bug. Distinguish code-path support, documented contract, and live local evidence.

Repository context:
- Authoritative reference files are README.md, docs/paper_plan.md,
  docs/results_snapshot.md, docs/future_work.md, justfile, .env,
  pyproject.toml, uv.lock, and the YAML files under config/.
- Source code, wrappers, and tests live under src/, scripts/, and tests/.
  Discover the current file inventory from the checkout instead of relying on a
  hand-maintained list in this prompt.
- Generated evidence lives under artifacts/. Discover study outputs from
  manifests, summaries, component subdirectories, and artifact indexes. Do not
  assume that a directory name is a just recipe.
- When docs/results_snapshot.md is generated from artifacts/full_with_peer and
  its manifest timestamp is not older than the relevant data/model artifacts,
  treat it as the current artifact-backed result surface rather than as a
  placeholder.
- The raw benchmark source is the local gvkey x data_year misstatement panel
  when available. Public evidence comes from the public SEC/PCAOB lake and its
  derived gold panels when available.
- UV_PROJECT_ENVIRONMENT must be an absolute path outside the repository;
  repo-local .venv creation is workflow drift.

Required first pass:
1. Read docs/paper_plan.md end to end.
2. Read README.md, docs/results_snapshot.md, and justfile to understand the
   current workflow and artifact claims.
3. Inspect config/*.yaml and confirm the command defaults against justfile.
4. Inspect the relevant src/ modules and scripts/ wrappers. Do not skip
   construct-overlap or public-peer code paths if they exist in the checkout.
5. Inspect tests to see which invariants are actually locked. Do not treat
   tests for prompt keywords as semantic correctness; they are presence checks.
6. Inspect the raw benchmark schema and basic row counts without loading more
   data than needed. Report rows, columns, identifier columns, target column,
   res_an* columns, missing_* flags, and whether raw-side CIK/ticker/company
   name/CUSIP/PERMNO fields exist.
7. If the public lake exists, report whether the gold issuer-year and
   filing-origin panels exist, their row counts, fiscal-year span, and whether
   comment_thread, amendment, and 8-K Item 4.02 labels have nonzero positives.
8. If artifacts exist, inspect the study manifest, component summaries, and
   selected artifact indexes. Say when a docs number is a static snapshot rather
   than a live result.

Audit dimensions:

0. Data availability stance
- Apply the public-data-first assumption before judging missing features.
- Do not invent data availability.
- Do not recommend paid data as required for the current v1 paper.
- Separate code bugs from data constraints.
- Treat raw_identifier_blocker as a bridge/input condition, not as proof that
  the public lake design is wrong.
- Treat the raw-only WRDS SEC Analytics Suite bridge as `wrds_validated`.
- Treat farr gvkey-CIK output as historical/manual comparison, not as a
  replacement for the WRDS bridge.

1. Workflow and command contract
- Discover the active command surface from justfile rather than assuming recipe
  names from this prompt.
- Does just check remain the data-free quality gate?
- Does the paper-facing full command still run setup/tests/lint, public-lake
  build or resume, benchmark, public cascade, bridge probe, and construct
  overlap when required inputs exist?
- Does just full intentionally leave peer comparison at its default none mode,
  with peer evidence requiring an explicit study rerun that passes
  --peer-comparison-mode and, when needed, --peer-target? Treat full_with_peer as
  a conventional output directory name if present, not as a recipe unless
  justfile defines it.
- Does the task dispatcher, if present, route prep, component analyses, study
  runs, and public-data fetch/build tasks consistently with README and justfile?
- Does the study runner orchestrate benchmark, public cascade, bridge probe,
  detected-misstatement peer comparison, public peer comparison, and construct overlap
  consistently with config defaults and CLI overrides?
- If skip flags or target flags exist, verify that they skip only their intended
  component and leave unrelated components unchanged.
- Does CI use bounded smoke targets rather than accidentally triggering full
  public-lake or full peer suites?
- Does status avoid mutating environment state, and does setup own dependency
  sync through UV_PROJECT_ENVIRONMENT?
- Does the justfile keep UV_PROJECT_ENVIRONMENT outside the repo and avoid
  silently creating a repo-local .venv?

2. Paper-plan compliance
- Are the execution gates in docs/paper_plan.md implemented or honestly marked
  as pending?
- Are res_an0, res_an1, res_an2, and res_an3 excluded from benchmark predictors?
- Are res_an* outputs treated as label-observability sensitivity rather than
  paper-grade label maturation?
- Are unknown-timing positives counted, and are drop-observed versus imputed-lag
  sensitivity scenarios clearly separated?
- Are public cascade labels based on first public event dates?
- Are source_available_*, public_date_*, vintage_*, and as_of_date excluded from
  default public-cascade predictors?
- Does the bridge path avoid silent many-to-many gvkey-CIK joins?
- Do construct-overlap outputs carry validation_tier = wrds_validated for the
  raw-only WRDS bridge?

3. Data and label integrity
- Check whether each public label is observable only after the correct filing
  origin.
- Check whether any event after origin_date can enter predictors.
- Check whether origin_date is the focal public filing date, not
  fiscal_period_end. If a panel uses fiscal_period_end as the prediction anchor,
  treat that as a timing-risk finding unless the code proves otherwise.
- Check whether acceptance_datetime or an equivalent filing acceptance timestamp
  is retained when same-day ordering matters. If the modeling panel uses
  date-only fields, record same-day predictor/label ambiguity as a
  timing-resolution limitation unless the code proves acceptance-time-safe
  ordering.
- Check whether all rolling history features use event_date < origin_date,
  including prior comment threads, prior NT filings, prior amendments, prior
  8-K instability items, and prior auditor/oversight events.
- Require code or artifact evidence for temporal ordering. Do not accept a
  narrative statement that there is no post-origin leakage without checking the
  joins or generated feature dates.
- Check whether label_8k_402_365 is derived from SEC submissions items metadata.
  If items are missing for a filing, verify that item_metadata_missing is
  recorded rather than silently falling back to HTML/TXT parsing or
  primary_doc_description as a label source.
- Check whether XBRL features are as-first-reported for the origin-time panel:
  facts must be tied to filings available before or at the origin, and later
  amendments or restated values must not overwrite what was known at origin_date.
- Check whether censoring is horizon-specific and task-specific.
- Check whether comment letters are described as public comment-letter scrutiny,
  not full SEC review.
- Check whether label_comment_thread_365, label_amendment_365,
  and label_8k_402_365 remain separate rather than being collapsed into a single
  fraud or restatement label.

4. Benchmark layer
- Does the benchmark run emit a complete, inspectable set of panel, timing,
  rolling-prediction, rolling-metric, drift, missingness, DML-style, and summary
  artifacts? Discover the exact filenames from the output directory and code
  rather than relying on this prompt as an exhaustive list.
- Does timing_claim_status distinguish sensitivity evidence from paper-grade
  maturation evidence?
- Do benchmark models use annual out-of-time windows rather than random
  cross-validation for headline prediction tables?
- Are DML-style benchmark rows framed as adjusted associations, not causal
  effects?
- Do reported metrics include prevalence, PR-AUC, ROC-AUC, Brier, Brier Skill
  Score, ECE where applicable, top-k precision, and Bao-style top-fraction
  metrics where expected?

5. Public cascade and public-label DML
- Are xbrl_ratio_* and xbrl_coverage_* features present in the issuer-year panel
  and joined into public-cascade modeling?
- Check whether xbrl_coverage_* by fiscal year or origin year is reported or can
  be computed from the artifacts. Pay special attention to 2011-2013 because
  phased XBRL adoption can create sample-composition differences.
- If early years have materially lower XBRL feature density than later years,
  require the audit to report this as a sample-composition limitation rather
  than a model failure.
- Check whether source_available_form_ap or auditor/oversight feature density is
  reported by fiscal year or origin year. Form AP is available from 2017-01-31,
  so 2011-2016 auditor partner features should be treated as structurally
  coverage-limited unless another public source is documented.
- Do the public-cascade summaries report readiness level, zero-positive tasks,
  task status counts, feature-family summaries, and public-opacity DML status?
- Are one-class train/test task fits skipped and reported rather than forced into
  metrics?
- Are public-opacity DML artifacts based on label_comment_thread_365,
  label_amendment_365, and label_8k_402_365 as primary outcomes?
- Are public-label DML results described as adjusted associations, not causal
  evidence of strategic silence?
- Is AAER absent from the paper-facing labels, metrics, feature-family rankings,
  and manuscript claims?

6. Benchmark and public peer model-family transfer
- Discover detected-misstatement peer and public-peer artifacts from their component
  directories, manifests, summaries, and schema tests. Do not treat this prompt
  as an exhaustive artifact list.
- For each peer suite, check metrics, predictions, task status, mapping
  attrition, imbalance strategy, feature importance where applicable, manifests,
  and blockers when those artifact classes are implemented.
- Check whether task-status tables carry imbalance_strategy and reason_code
  fields, not just an uninformative status flag.
- Check whether the peer suites are described as model-family transfer and
  metric-compatible ranking evidence, not same-estimand replication of prior
  fraud-prediction papers.
- Check whether skipped rows include specific reason_code values that a
  developer can act on. Do not accept a generic "skipped" status without a
  reason.
- Check whether mapping-attrition outputs record missing, exact, and proxy
  mappings for public Dechow/Bao-style variables.
- Check whether Bao/Dechow public transfer states plainly when raw
  accounting-number model replication is not supported by public issuer-origin
  inputs.
- Check whether mapping_attrition_rate is interpreted as variable-mapping
  attrition, not sample attrition.
- Check whether weak proxy mappings for Dechow/Bao-style variables are reported
  plainly.
- Check whether undersampling, class weights, calibration warnings, and Brier/ECE
  interpretation are documented under rare-event imbalance.
- Check whether public peer transfer covers comment_thread, amendment, and
  8k_402 only.

7. Bridge and construct-overlap validation
- Discover bridge-probe and construct-overlap artifacts from manifests,
  summaries, blocker files, component directories, and docs artifact indexes.
- Check bridge coverage, multiplicity, unmatched diagnostics, validation tier,
  overlap sample flow, overlap panel grain, bridge confidence tiers, aggregation
  sensitivity, label contingency/lift, public-score-to-benchmark ranking,
  benchmark-score-to-public ranking, top-decile lift, label co-occurrence,
  event-time concentration, event-time coverage, and res_an proxy
  coverage when those outputs are implemented.
- Check opacity-refresh outputs separately from construct-overlap outputs.
  Missing opacity artifacts should be reported as a refresh blocker rather than
  as a failure of construct-overlap validation.
- Check whether high-confidence, ambiguous, and dropped bridge tiers are reported
  separately.
- Audit the grain explicitly: raw panel grain, prediction grain, and overlap
  aggregation grain. State whether the primary overlap result is annual-primary,
  origin-level, or max-score/max-label aggregated, and require an aggregation
  sensitivity output when multiple public-origin rows can map to one annual
  benchmark row.
- Check whether overlap claims are limited to related-but-non-identical
  constructs.
- Check whether amendment and 8-K Item 4.02 evidence are separated from the
  broader comment-letter signal.
- Check whether stale AAER outputs are excluded from current results and
  manuscript claims.

8. Public Data Utilization Audit
- Before recommending external data, check whether public SEC/PCAOB sources are
  already ingested, normalized, joined, and documented.
- Check whether amendment annotations use the conservative mixed-content
  priority: financial/non-admin triggers override Part III/proxy admin triggers,
  with an explicit annotation note.
- Check whether amendment_annotation uses a bounded explanatory-note scan, not only
  filing timing or form type. Confirm that
  tests or artifacts expose admin_part_iii/proxy handling, financial_override,
  and mixed-content priority.
- Do not let Part III/proxy administrative amendments and financial corrections
  collapse into the same reporting-risk label without an explicit annotation.
- Check whether rolling public-history features are anchored on origin_date, not
  fiscal-year end.
- Check whether filing-friction level features are kept separate from
  public-history rolling counts.
- Check whether note tag entropy has a formal definition and is interpreted as
  disclosure dispersion/breadth rather than mechanically as opacity.
- Check whether source availability masks, first-public dates, hashes, parser
  versions, and as-of dates are preserved through bronze, silver, and gold.
- Check whether non-CIK-native public sources retain original identifiers and
  provenance before any CIK bridge.

9. ML evaluation and reporting
- For every headline prediction claim, report the evaluation unit, label, test
  years, train window, feature set, prevalence, PR-AUC, ROC-AUC, Brier/BSS, ECE
  when available, and top-k or top-fraction metrics.
- Read PR-AUC against prevalence. Do not call a low PR-AUC bad without checking
  the base rate.
- Do not treat ROC-AUC alone as enough for rare-event reporting-risk tasks.
- For models trained with undersample_equal or other artificial balancing, treat
  PR-AUC, top-k precision, and Bao-style top-fraction metrics as the ranking
  evidence. Treat Brier and ECE as calibration diagnostics that can be distorted
  by train-test prevalence mismatch.
- Do not use default 0.5-threshold F1, recall, or accuracy as headline evidence
  for rare-event reporting-risk tasks unless the threshold policy is explicitly
  justified.
- Check whether summaries that highlight the best feature set, train window, or
  model family acknowledge model-selection optimism. If no correction is applied,
  claims should stay at model-family or diagnostic ranking level, not
  configuration-level superiority.
- Check whether predictions are annual out-of-time. If any random CV is used,
  identify whether it is only for DML nuisance fitting or another secondary use.
- Inspect the actual feature-selection code path or emitted feature schema to
  confirm that availability masks, public dates, vintage fields, labels, censor
  columns, and provenance identifiers are excluded from default predictor
  matrices.
- Check for distribution leakage in feature engineering. Imputation, scaling,
  and binning parameters must be fit within the training fold or a trailing
  window, not with global panel statistics.
- Check whether duplicate issuer-year or gvkey-year prediction rows are blocked.
- Check whether model seeds, task seeds, parallel jobs, and model threads are
  recorded in manifests.

10. Documentation and results snapshot
- Does README.md describe the current command surface without duplicating stale
  paper-plan text?
- Does docs/paper_plan.md Design Overview match the implemented computation
  flow, including benchmark/public X/Y, time spans, out-of-time splits, peer
  suites, metrics, DML, and bridge validation?
- Does docs/results_snapshot.md Evidence Map describe the current artifact state
  rather than only the intended design?
- Are the Paper Plan Design Overview and Results Snapshot Evidence Map
  logically consistent while preserving their different roles: design contract
  versus current evidence state?
- Does docs/results_snapshot.md clearly say it is a static snapshot?
- Do results-snapshot tables match the actual artifacts in the active study
  directory or directories?
- If docs/results_snapshot.md uses a Selected Artifact Index, does it clearly
  say the list is selected rather than exhaustive, and do all listed artifacts
  exist locally?
- Are wide-table pages configured for readable docs output where needed?
- Do docs avoid claiming true fraud, causal identification, full SEC review, or
  full enforcement coverage?
- Do docs keep future work separate from current v1 evidence?

11. Engineering quality and efficiency
- Is reusable logic kept in src/ and thin execution code kept in scripts/?
- Are tests checking behavior and artifact contracts rather than only imports?
- Do the core quality gates include data-prep and table-I/O tests alongside the
  benchmark, bridge, public-cascade, peer, and docs tests?
- Are public-lake downloads restartable and hash-checked?
- Are SEC requests rate-limited?
- Are full-scale FSDS/Notes paths using Parquet/DuckDB where pandas-only
  materialization would be risky?
- Does DuckDB memory configuration, a temp/spill directory, or an equivalent
  out-of-core strategy protect large FSDS/Notes/public-lake aggregations from
  avoidable OOM failures?
- Does the public-lake workflow preserve the conservative defaults unless
  explicitly overridden: DuckDB memory limit 10GB, max temp size 400GB, and
  temp/spill directory under the active Silver lake directory?
- Do imputation, feature selection, and prediction schemas avoid fold-dependent
  shape drift, especially with all-missing features?
- Does the peer runtime fail fast when parallel_jobs * model_threads exceeds the
  available worker budget?
- Does the full peer run loop over tasks, model families, feature sets, and
  windows without materializing every fitted model at once?
- Are prediction artifacts written with compact dtypes where practical, such as
  predicted probabilities as float32 and observed labels as int8?
- Does uv.lock provide exact resolved versions for core ML/data dependencies,
  while pyproject.toml can keep reasonable range constraints?
- Do manifests record seeds, task seeds or seed policy, parallel jobs, model
  threads, and enough package/runtime context to interpret results?
- If interruption could leave a corrupt JSON/CSV artifact, suggest atomic writes
  as remediation. Do not require atomic writes as a blanket rule for every
  output.
- Are generated artifacts ignored appropriately while source docs and tests are
  tracked?

Output format:

Start with a short verdict:
- "Paper-plan support level: strong / partial / weak"
- "Main blocker:"
- "Next gate:"

Then provide findings ordered by severity:
- P0: critical violations of leakage, timing, identity, or claim validity.
- P1: missing evidence needed for the next paper gate.
- P2: implementation debt, performance risk, or documentation drift.

For every finding, include:
- title
- severity
- evidence with file paths and line numbers where possible
- why it matters for the paper
- concrete remediation
- suggested test or artifact that would prove the fix

Then provide:
- a claim-support matrix keyed to docs/paper_plan.md gates: data integrity,
  empirical sufficiency, and paper-readiness; mark each as supported, partial,
  unsupported, or not_auditable_locally, and cite the exact artifact, test,
  config, or code path
- one component status table covering benchmark, public cascade, detected-misstatement peer,
  public peer, bridge probe, construct overlap, opacity refresh, docs, and tests
- a short public-source utilization note, focused only on sources that affect the
  findings
- a Blocker Resolution Matrix only if there is a P0/P1 blocker or a native
  public source/optional accelerator would directly resolve a blocker
- a command-verification section listing commands you ran or would run
- a concise "do next" list with no more than 10 items

Constraints:
- Do not edit files unless explicitly asked.
- Do not invent data availability.
- Do not treat absence of Audit Analytics or other unprovided paid databases as
  a code bug.
- Do not recommend paid data as required for the current v1 paper.
- Do not recommend LLM/GNN or multimodal extensions until the benchmark, public
  cascade, XBRL ratios, peer-transfer evidence, and bridge/construct-overlap
  gates are stable.
- Do not present historical farr bridge diagnostics as WRDS-quality validation.
- Do not use vague phrases such as "robust evidence" unless you say which
  artifact supports it.
- Keep the tone direct and technical. Avoid sales language and generic praise.
```
