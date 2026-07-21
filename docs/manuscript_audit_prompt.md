# Manuscript Audit and Polish Brief

Use this editorial brief when reviewing or polishing the
`reporting-risk-cascade paper` in `../reporting-risk-cascade-manuscript` for a
target submission to **The British Accounting Review (BAR)**.

This is an internal quality-control brief for academic review, claim discipline,
and prose polish. It is not manuscript prose. Its purpose is to keep the paper's
accounting contribution, evidence boundary, and terminology stable while making
the argument readable to both accounting/finance and machine-learning readers.

This brief was last reconciled for BAR targeting on 2026-05-28 against the
binding design contract in `reporting-risk-cascade/docs/paper_plan.md` and the
current artifact-backed results in `reporting-risk-cascade/docs/results_snapshot.md`.
The manuscript source lives in `reporting-risk-cascade-manuscript`; live
submission mechanics should be checked against the current official BAR and
Elsevier author instructions before upload.

## Mode Invocation Rule

When executing this brief, run exactly one Review Mode per invocation unless the
user explicitly asks for a combined audit. If the user asks for "full audit",
execute the Full audit mode only; do not also polish sections or rewrite the
Abstract unless separately requested. This keeps outputs deep enough to be
useful and prevents shallow, mixed-mode responses.

This is an author-side internal quality-control brief. It is not a journal
peer-review process and should not be represented as use of AI by a BAR editor
or reviewer. If AI-assisted tools are used in manuscript preparation, the
manuscript must include the required Elsevier-style disclosure and the authors
remain responsible for all citations, claims, tables, and interpretations.

## Editorial Stance

Review the manuscript as a skeptical but fair BAR referee or associate editor.
The strongest version of the paper is an accounting measurement contribution
about label observability in financial reporting, with machine learning used as
measurement infrastructure. The paper is not a generic fraud detection article,
not an algorithm leaderboard, not a network cascade paper, and not a causal
enforcement study.

The likely rejection path is clear: BAR reviewers may decide that the accounting
contribution is obscured by workflow detail, that selected submission-dated
correspondence is oversold as reporting failure or contemporaneously public scrutiny, that sparse Item 4.02
evidence carries too much weight, or that the study is too close to a
comment-letter prediction paper. Every review pass should therefore protect the
construct first, then the evidence, then the style.

Do not invent empirical findings. Empirical claims must be traceable to the
manuscript, the Paper Plan, the Results Snapshot, generated manuscript
tables/figures, or current artifacts.

## Research Object

The central construct is the **filing-origin, submission-dated
review-and-correction outcome state**: whether information verifiably available
when an annual filing becomes public can rank issuers that later enter typed
recorded outcome channels. SEC correspondence is eventually disclosed but is
dated here by the underlying EDGAR submission date, not by an unverified public-
release date.

For continuity with older drafts, the phrase **pre-disclosure reporting-risk state**
may appear in notes, but article prose should prefer
**filing-origin, submission-dated review-and-correction outcome state**. This
reduces terminology drift and ties the construct to the actual predictor and
outcome clocks used in the design.

The paper has three evidence layers:

1. **Benchmark layer.** The detected-misstatement benchmark is at the
   `gvkey x data_year` grain. It is used for timing sensitivity, drift,
   missingness, and peer-compatible model-family checks. It is not the
   definition of the public reporting-risk estimand.
2. **Public cascade layer.** The public-cascade panel is at the
   `issuer_cik x fiscal_year x origin_date` grain. The origin date is the
   selected annual filing date. The headline public tasks are comment_thread,
   amendment, and 8k_402.
3. **Bridge gate.** The gvkey-CIK-year bridge is used only for
   construct-overlap validation. Bridge status must be read from the current
   study manifest, construct-overlap summary, and bridge/overlap artifacts
   before any integrated benchmark-to-public overlap claim is allowed. Current
   artifacts may report `wrds_validated`, but that is a checked artifact state,
   not a permanent prompt fact. If the bridge tier is stale, missing, or
   candidate-only, integrated overlap claims must be downgraded. The standalone
   public-cascade measurement claim does not require bridge validation.

The public-cascade labels are typed recorded outcome states:

| Artifact label | Stable manuscript term | Use when | Claim boundary |
| --- | --- | --- | --- |
| `comment_thread_365` | submission-dated, eventually disclosed SEC correspondence | Describing the correspondence outcome. | Dated by the underlying EDGAR submission, not public release; selected and not the full SEC review universe. |
| `amendment_365` | public amendment/friction/correction channel | Describing the broad amendment or filing-friction outcome. | A heterogeneous filing-friction and correction state, not automatically a material misstatement. |
| `8k_402_365` | Item 4.02 non-reliance event | Describing the underlying 8-K event. | A severe public correction signal, rare but rankable, not fraud occurrence. |
| `8k_402_365` | public Item 4.02 material-correction proxy | Describing the label's construct role. | A proxy for severe public correction, not a complete material-misstatement or fraud label. |

## BAR Positioning

The paper should read as accounting research before it reads as a modeling
exercise.

BAR-facing contribution:

- A measurement redesign for reporting-risk research under partial
  observability.
- A public-data-first, filing-origin outcome system for public
  review-and-correction risk.
- A reproducible SEC/PCAOB public-data architecture with dated sources,
  origin-date discipline, and provenance.
- A bridge-gated comparison to detected-misstatement benchmarks that supports
  related-but-non-identical construct validation.
- Metric-compatible model-family transfer to familiar Dechow, Perols, Bao, and
  Bertomeu-style vocabularies without claiming same-estimand superiority.

Not the contribution:

- Unobserved fraud occurrence detection.
- Causal identification of SEC, issuer, auditor, or enforcement behavior.
- A direct performance ranking over prior fraud-prediction papers.
- A deployment-ready regulatory or audit automation system.
- A claim that public comment letters are the complete SEC review universe.

BAR-specific positioning:

- Route the paper primarily as financial-reporting measurement and disclosure
  review, with audit/regulatory oversight as a secondary fit because PCAOB Form
  AP can supply auditor and engagement-partner features. PCAOB inspection
  archives are Bronze/provenance inputs only, not Gold or model features.
- Let the UK/EU discussion support cautious portability. The paper can say that
  the measurement design is portable to settings with dated filings and public
  review or correction channels; it cannot claim out-of-U.S. validation.
- Policy and practice implications should remain tied to measurement,
  screening, and public-data reproducibility rather than investor-return or
  deployment claims.
- BAR's closed special-issue activity on AI in accounting and finance may be
  used as a contextual scope signal in cover-letter thinking only after source
  verification; do not present a closed call as a live submission target.

## Stable Terminology

Use one term for one concept whenever possible.

Preferred terms:

| Term | Use when | Do not confuse with |
| --- | --- | --- |
| filing-origin, submission-dated review-and-correction outcome state | Naming the paper's central construct. | Detected misstatement, latent fraud occurrence, or a release-time backtest. |
| submission-dated review-and-correction outcomes | Describing the downstream outcome family. | Full SEC review, enforcement, or hidden misconduct. |
| submission-dated, eventually disclosed SEC correspondence | Describing the comment-thread outcome. | Correspondence public availability on the submission date or the complete SEC review universe. |
| public amendment/friction/correction channel | Describing the heterogeneous amendment outcome. | A material-misstatement label. |
| Item 4.02 non-reliance event | Describing the 8-K event itself. | Fraud occurrence. |
| public Item 4.02 material-correction proxy | Describing the label's role as a severe public-correction proxy. | A complete public-material-misstatement universe. |
| detected-misstatement benchmark | Describing the `gvkey x data_year` benchmark layer. | The public-cascade estimand. |
| benchmark layer | Referring to detected-misstatement diagnostics and peer-model checks. | Public-cascade prediction. |
| public cascade layer | Referring to filing-origin public labels and public features. | Benchmark model-family comparison. |
| bridge gate | Referring to the gvkey-CIK-year linkage condition before overlap claims. | A silent join or target merger. |
| WRDS-validated construct-overlap | Referring to integrated overlap only when the current artifacts report a WRDS-validated tier. | Any stale, candidate, or unverifiable crosswalk. |
| bridge-gated construct validation | Referring to the validation design that uses the bridge gate. | Proof of equivalence. |
| related-but-non-identical constructs | Interpreting benchmark/public alignment. | Same-estimand superiority. |
| model-family transfer | Describing Dechow, Perols, Bao, or Bertomeu-style families in this repo. | Original-paper numeric replication. |
| metric-compatible ranking evidence | Describing shared metric language across different targets. | Cross-estimand model superiority. |
| adjusted association | Describing DML or regression-style estimates after controls. | Causal effect. |
| predictive association | Describing score or feature relationships in prediction tasks. | Structural mechanism. |
| annual fold dispersion | Describing variation across annual out-of-time test folds. | Population confidence interval. |
| uncertainty caveat | Flagging interval, sparse-fold, or diagnostic-status limits. | Formal independent-sample inference. |
| limited screening interpretation | Translating ranking evidence into prioritization language. | A calibrated decision rule or deployment protocol. |

Avoid or replace:

| Avoid | Replace with |
| --- | --- |
| fraud detection, true fraud, latent fraud occurrence | detected-misstatement benchmark; unobserved fraud occurrence only when stating a boundary |
| SEC review | selected, eventually disclosed SEC correspondence, unless explicitly discussing the broader institutional process |
| complete enforcement universe | public review-and-correction channels |
| causal effect | adjusted association or predictive association |
| outperforms prior studies | metric-compatible evidence within this estimand |
| state-of-the-art model | implemented model family or peer-compatible model family |
| model-driven insight | measurement-and-ranking evidence |
| cascade as contagion, transmission, diffusion, or spillover | typed recorded outcome states |
| feature importance as mechanism | feature-family or information-set evidence |
| population confidence interval | annual fold dispersion or out-of-time evaluation dispersion |

## Cross-Discipline Terminology Bridge

Use short first-use definitions for terms that are familiar in one audience but
not the other. Do not rely on acronyms alone.

| Term | Accounting-reader-friendly definition | ML-reader-friendly accounting bridge |
| --- | --- | --- |
| PR-AUC | Rare-event ranking quality read against the outcome base rate. | Precision-recall area is more informative than ROC-AUC when positives are sparse. |
| ROC-AUC | General ranking separation between positives and negatives. | Useful but can look high when rare-event precision is still weak. |
| ECE | Expected calibration error: whether predicted probabilities match observed rates. | A calibration diagnostic, not a ranking metric. |
| Brier Skill Score | Probability-forecast improvement relative to a baseline. | A calibration and probability-quality check. |
| Bao-style metrics | Top-fraction precision, sensitivity, specificity, BAC, and NDCG used for literature comparability. | A metric-language bridge to Bao-style fraud-prediction evidence, not replication. |
| DML-style high-dimensional adjustment | Flexible adjustment for observed controls before estimating an association. | Double/debiased ML here supports adjusted association, not causal identification. |
| scale_pos_weight | Class-imbalance weight used in tree models. | A modeling device for rare positives, not an economic cost function. |
| annual fold dispersion | Descriptive variation across annual out-of-time folds. | It is not a population confidence interval or superpopulation claim. |
| Item 4.02 non-reliance | A public 8-K signal that prior financial statements should not be relied on. | A severe public-correction proxy, not a direct fraud label. |
| PCAOB Form AP | Public audit-participant disclosure for issuer audits. | A public audit-market feature source, not proof of audit failure. |
| AAER | SEC Accounting and Auditing Enforcement Release. | Enforcement-tail context only; not a headline public-cascade label. |

## Claim Boundaries

These boundaries are non-negotiable:

- Public-cascade labels are not alternative names for fraud.
- The comment-thread label is selected, eventually disclosed SEC correspondence
  dated by its underlying EDGAR submission. It is not a public-release-time
  outcome and not the full SEC review universe.
- Amendment evidence is heterogeneous and must not be collapsed into material
  misstatement evidence.
- Item 4.02 evidence is sparse severe-tail evidence; it cannot alone carry the
  headline construct-validity claim.
- DML-style high-dimensional adjustment estimates are adjusted associations,
  not causal effects.
- Peer-compatible Dechow, Perols, Bao, and Bertomeu-style rows are
  model-family transfer and metric-language alignment, not original-paper
  numeric replication.
- PR-AUC must be interpreted relative to prevalence/base-rate.
- Top-k precision and lift are screening evidence and ranking evidence, not
  calibrated decision rules.
- Point-in-time discipline is mandatory: financial and public predictors must
  be point-in-time, as-first-reported, or explicitly available at or before the
  filing-origin date. Any restated, retroactive, or post-origin predictor
  ambiguity is a look-ahead-bias risk.
- Submission-dated comment-thread history must not enter filing-origin
  predictors unless public-release timing is independently verified. A
  submission before `origin_date` does not establish public availability before
  `origin_date`.
- Public-side folds must use complete origin-calendar-year holdouts. Training
  rows may enter a holdout only when their 365-day outcome windows mature before
  the holdout year begins. This establishes temporal ordering under the stated
  submission-date outcome clock, not a live correspondence-release backtest.
- Uncertainty intervals are annual fold dispersion summaries only when valid
  folds >= 5. Sparse folds with fewer than 10 positives must be excluded from
  formal interval displays and listed in provenance.
- Asymmetric costs and false negatives may motivate limited screening
  interpretation, but the current paper does not estimate a utility model.
- Reciprocal risk-score alignment and event-time concentration are diagnostic
  validation evidence, not equivalence or causality.
- Treat retired enforcement-tail outputs as outside the current paper-facing
  design. This means deprecated AAER or enforcement-tail artifacts, labels, or
  tables are archival/status-only unless the paper plan explicitly reactivates
  them. They cannot enter headline public-task claims, feature-family rankings,
  peer comparisons, robustness claims, or manuscript tables.

Public-data discipline:

- Treat public-data-first as a scientific information-set design, not a budget
  compromise.
- Treat the public-data-only design as reproducible accounting measurement, not
  a weaker substitute for paid data.
- Do not make absence of Audit Analytics or other unprovided commercial datasets
  sound like a fatal manuscript flaw.
- Do not recommend paid data as required for the current v1 paper.
- Do not browse for live pricing, data-budget pages, or commercial-data
  availability unless the user explicitly asks for a separate data-budget task.

## Claim-Strength Ladder

Use this Claim-strength ladder in every audit:

- **reportable finding:** directly supported by current generated artifacts and
  safe for main-text use.
- **candidate evidence:** artifact-backed but limited by sparse labels, coverage,
  bridge tier, or another explicit validation condition.
- **diagnostic only:** useful for motivation, design checks, robustness framing,
  or appendix context, but not a standalone headline claim.
- **not supported:** absent, contradicted, stale, or too speculative for the
  current paper.

## Evidence Order

Read current evidence in this order:

1. `docs/paper_plan.md` for the research-design contract.
2. `docs/results_snapshot.md` for artifact-backed outcomes and current
   evidence boundaries.
3. `reporting-risk-cascade-manuscript/main.tex`, tables, figures, statements,
   submission files, provenance files, and audit notes.
4. Current generated artifacts when a claim depends on them.
5. If `artifacts/full_with_peer` exists, inspect the study manifest, public
   cascade outputs, peer-comparison outputs, bridge probe, and construct-overlap
   ledgers before allowing an integrated claim.

Important artifact families include:

- `study_summary.md`
- `study_run_manifest.json`
- `detected_misstatement_model_family_metrics.csv`
- `public_model_family_metrics.csv`
- `public_model_family_task_status.csv`
- `construct_overlap_summary.md`
- `label_contingency_lift.csv`
- `public_score_benchmark_ranking.csv`
- `reciprocal_alignment.csv`
- `event_time_concentration.csv`

## P0 and P1 Checks

Complete these checks before style polish.

Before stylistic polish, three claim-level checks dominate: the bridge tier must
support any integrated overlap claim; submission-dated, eventually disclosed
SEC correspondence must not be treated as release-time data or the full SEC
review universe; and sparse Item 4.02
evidence must remain rare-tail support rather than the whole validation story.

P0 checks:

- **Bridge freshness check.** Verify the current bridge tier from the study
  manifest and construct-overlap artifacts before allowing integrated
  construct-overlap claims. If the tier is missing, stale, candidate-only, or
  inconsistent across artifacts, downgrade overlap language to candidate
  evidence or diagnostic only. If the current tier is `wrds_validated`,
  WRDS-validated construct-overlap language may be reviewed as reportable
  subject to the stated caveats.
- **Comment-letter date and selection check.** Confirm that the manuscript says
  `comment_thread_365` is dated by the underlying EDGAR correspondence
  submission, not by public release. The outcome is eventually disclosed and
  selected; a model that ranks it may rank both issuer reporting-risk signals
  and the SEC process that selects correspondence for later disclosure.
- **Primary-source citation check.** Require primary-source citations for SEC,
  PCAOB, BAR, and Elsevier policy claims. Public-release timing,
  double-anonymization mechanics, AI disclosure, Form AP, inspection data, Item
  4.02, and AAER coverage claims should be supported by SEC, PCAOB, BAR, or
  Elsevier primary sources; otherwise flag P1.
- **Sparse Item 4.02 check.** Check whether any headline claim relies on sparse
  `8k_402_365` evidence. If so, require rare-but-rankable and severe-tail
  caveats.
- **Retired enforcement-tail check.** Confirm that deprecated AAER or
  enforcement-tail artifacts are absent from the current paper-facing claims
  unless explicitly reactivated by the Paper Plan.
- **Article-prose contamination check.** Check for article prose that still
  sounds like a response memo or design memo, especially phrases where "the
  manuscript" is the subject.

P1 checks:

- **Comment-letter literature differentiation check.** Explain why the paper is
  not merely another comment-letter prediction paper. Predicting comment
  threads is not novel by itself; the novelty is the filing-origin estimand,
  typed public cascade, public-data architecture, and bridge-gated validation.
- Keep the accounting problem before the method in the Abstract, Introduction,
  and Discussion.
- Ensure predictor text and outcome text are separated. Outcome-side amendment,
  Item 4.02, or comment-letter response text filed after `origin_date` must not
  be used as a predictor for the event it defines.
- **Point-in-time predictor check.** Verify point-in-time predictor discipline.
  Financial and public predictors should be as-first-reported or available at or
  before the filing-origin date; retroactively restated or post-origin fields
  require explicit exclusion or a look-ahead-bias caveat.
- **Public-side fold check.** Verify that public-side holdouts use complete
  origin-calendar years, that every training outcome window matures before the
  holdout starts, and that the prose does not misstate this ordering as a
  release-time availability backtest. Submission-dated correspondence histories
  must be excluded from predictors unless release dates are verified.
- **Issuer-dependence check.** Verify that public-opacity nuisance folds keep
  repeated rows for an issuer together and that reported DML-style intervals
  use issuer-clustered covariance. Construct-overlap bootstrap intervals must
  resample issuers rather than rows. If either artifact remains row based,
  downgrade its inferential language and require an explicit dependence caveat.
- Keep feature-family results as feature fusion, not XBRL dominance. The bounded
  phrase is: feature fusion helps, metadata remains strong.
- Apply a common-sample / coverage caveat to XBRL, auditor,
  prior-filing history, and other narrower
  feature-family comparisons. If the comparison is not on a
  common evaluation sample, the text must state that differences may reflect
  both source coverage and signal content.
- **Missingness and opacity check.** Distinguish missingness cases before
  interpreting opacity: economically informative missingness, public-source
  coverage limits, parser/source unavailability, and model imputation are not
  the same. Do not interpret a missingness pattern as strategic silence unless
  the artifact supports that claim. If public-opacity DML p-values are null,
  weaken strategic-silence language.
- **Table/figure interpretation check.** Require table and figure captions for
  performance evidence to state the evaluation unit, task, base-rate context,
  and bounded measurement interpretation. Captions should translate the number
  into a measurement claim, not a model-performance slogan.
- **Model-selection optimism check.** If the manuscript highlights the best
  model, best window, best feature family, or max PR-AUC, require descriptive
  language unless there is a pre-specified selection rule or validation
  correction. A single best configuration should not become the headline claim.
- **Table-unit clarity check.** Audit every column named "Rows". If it counts
  metric rows, fold-task rows, task-window-feature rows, or model-family rows
  rather than issuer-years or firm-years, rename it or require a table note
  explaining the evaluation unit.
- Avoid claims about unpriced market risk unless market variables and current
  artifacts directly support the claim.
- Do not let any single-year `8k_402_365` extreme dominate the evidence narrative.
- Ensure uncertainty intervals are only reported when valid folds >= 5, and
  sparse folds with fewer than 10 positives are properly excluded from formal
  interval displays.
- Scan for AI-flavored prose patterns: triple-hedge sentences, over-compressed
  abstract sentences, formulaic "this paper contributes by" claims without
  accounting motivation, and balanced-but-empty transitions.

## Elegance and Readability

Use structure to lower cognitive burden. Results paragraphs should usually
follow the same four-step rhythm:

1. What was tested, in accounting language.
2. What was found, with numbers and prevalence context.
3. What it means for the accounting construct.
4. What boundary or caveat prevents overclaiming.

When explaining machine-learning concepts to accounting readers, move from
intuition to name to role: explain the practical idea first, name the method
second, and state why it is needed in this paper third. For international
relevance, embed UK/EU examples as portability conditions: the U.S. setting is
the first test, while settings such as the UK FRC Corporate Reporting Review
require jurisdiction-specific label mapping and validation.

Voice and style examples:

| Weak or formulaic | Better academic version |
| --- | --- |
| This paper contributes to the literature in three ways. | The contribution is to make the observability system part of the reporting-risk construct. |
| The model robustly outperforms alternatives. | The specification has the highest reported mean PR-AUC in this table, subject to fold-dispersion and coverage caveats. |
| The results show that AI can detect fraud. | The evidence shows that filing-origin information ranks later submission-dated correspondence and public correction outcomes above their base rates. |
| The table reports 180 rows. | The table reports 180 metric rows across task-window evaluations, not 180 issuer-years. |

## Audit Workflow

| Drafting stage | Primary mode |
| --- | --- |
| Empty or placeholder manuscript only | Skeleton Mode |
| Writing or revising one section | Section-Level Polish |
| After a section is drafted | Triage audit |
| After substantive body completion | Claim-To-Evidence Audit |
| When the full paper reads coherently | BAR Readiness Audit |
| Before submission | Full audit plus Referee Report |
| After revisions or reviewer comments | Delta audit |

## Review Mode: BAR Readiness Audit

Purpose: whole-manuscript review for BAR fit, construct integrity, and likely
referee objections.

Referee robustness check:

- What is the accounting insight beyond another classifier?
- Is the estimand clearly distinct from ex post detected misstatement?
- Why is submission-dated, eventually disclosed SEC correspondence a defensible selected outcome?
- Does the paper separate reporting-risk prediction from predicting which
  filings enter an eventually disclosed correspondence record?
- Why is public-data-first a scientific information-set design?
- Does the benchmark layer remain diagnostic rather than a same-target contest?
- Does the paper remain credible for a BAR reader who is not interested in
  model implementation details?

Review dimensions:

1. Core contribution and "so what".
2. Construct and label integrity.
3. Comment-letter selection and endogenous scrutiny.
4. Timing, censoring, and leakage.
5. Rare-event evaluation and Item 4.02 discipline.
6. Bridge-gated construct validation.
7. Literature positioning, especially the comment-letter prediction literature.
8. Economic mechanism and information-set interpretation.
9. Formulaic prose, response-memo residue, and terminology drift.
10. BAR fit, international relevance, and submission mechanics.

Deliverable:

- Manuscript readiness: not started, outline only, partial draft, submission
  draft, or not assessable.
- BAR fit judgment: one sentence.
- Main paper risk and likely rejection path: one sentence each.
- Best current positioning: one sentence.
- Findings ordered by P0, P1, and P2.
- For each finding: title, severity, location, evidence, why it matters, and
  concrete revision instruction.
- Required ledgers: terminology ledger, claim-to-evidence + claim-strength
  table, bridge-gate assessment, economic-mechanism assessment, citation audit,
  public-data support ledger, and no more than 10 revision priorities.

## Review Mode: Claim-To-Evidence Audit

Purpose: claim extraction and evidence classification before substantive prose
polish.

Audit every empirical claim and classify it with the Claim-strength ladder.

Benchmark layer checks:

- Are timing diagnostics described as label-observability sensitivity?
- Are financial predictors explicitly point-in-time, as-first-reported, or
  available at or before the filing-origin date?
- Are `res_an*` outputs kept out of predictors and outside paper-grade label
  maturation unless externally validated dates exist?
- Are `naive`, `proxy_drop_observed`, and `proxy_imputed_lag` modes
  distinguished?
- Are drift and missingness results diagnostic unless stronger evidence exists?

Public cascade layer checks:

- Are `comment_thread_365`, `amendment_365`, and `8k_402_365` reported
  separately?
- Are headline public tasks are comment_thread, amendment, and 8k_402?
- Are public-cascade labels described as typed recorded outcomes, not fraud or
  real-time public-release states?
- Are PR-AUC, ROC-AUC, Brier, Brier Skill Score, ECE, top-k precision,
  top-decile lift, and Bao-style metrics interpreted under rare-event
  prevalence/base-rate?
- Are top-k and lift framed as screening evidence, not calibrated decision
  rules?

Bridge and overlap checks:

- Is bridge status read from the current manifest and construct-overlap
  artifacts, rather than assumed from stale prompt text?
- If the current artifacts state `wrds_validated`, is WRDS-validated
  construct-overlap language used only for the integrated overlap layer?
- Are high-confidence, ambiguous, and dropped bridge cases distinguished when
  overlap claims depend on them?
- Is construct overlap described as related-but-non-identical?
- Is reciprocal risk-score alignment presented as diagnostic validation rather
  than equivalence?
- Is event-time concentration used as validation context rather than causal
  proof?

Sparse Item 4.02 checks:

- Does any headline claim rely too heavily on sparse `8k_402_365` evidence?
- Does the text describe Item 4.02 as rare but rankable?
- Does it avoid promoting a single-year `8k_402_365` extreme over averages or
  validation ledgers?
- If top-decile lift is strong but PR-AUC is close to a low base rate, require a
  sparse severe-label caveat.

Peer-compatible model-family checks:

- Are Dechow, Perols, Bao, and Bertomeu-style models described as model-family
  transfer and metric-language alignment?
- Does the manuscript avoid original-paper replication claims unless mapping
  and sample gates support that claim?
- Does it avoid outperformance or superiority language across estimands?

DML and opacity checks:

- Are DML estimates described as DML-style high-dimensional adjustment or
  adjusted association?
- Are machine-learning scores described as predictive association rather than
  structural mechanism?
- If p-values are null, does the manuscript avoid a strong strategic-silence claim?
- Does the manuscript distinguish disclosure breadth and tag entropy from
  mechanical opacity?
- Does it distinguish economically informative missingness, public-source
  coverage limitations, parser/source unavailability, and model imputation?
- Does the manuscript avoid claims about unpriced market risk unless market
  variables and artifact support are present?

Deliverable:

- A table with: claim, manuscript location, supporting artifact, classification,
  problem if any, and required revision.
- The three most dangerous unsupported claims.
- The three claims strong enough to lead the paper.
- The three claims that should move to limitations, robustness, or future work.

## Review Mode: Section-Level Polish

Purpose: one-section revision after the claim audit has cleared the section's
empirical statements.

Section objectives:

1. State the accounting problem before the method.
2. Define the estimand before discussing models.
3. Keep the benchmark layer, public cascade layer, and bridge gate distinct.
4. Use mechanism-aware accounting prose without converting prediction evidence
   into causal mechanism.
5. Remove response-memo and formulaic prose.
6. Remove promotional model language.
7. Convert overclaiming into disciplined contribution language.
8. Explain why each table or figure matters immediately after the callout.
9. Ensure performance captions state evaluation unit, task, base-rate context,
   and bounded measurement interpretation.

Style constraints:

- Prefer short, high-information sentences.
- Avoid "the manuscript should", "this draft", and similar internal-process
  residue in article prose.
- Avoid repetitive contribution lists without economic logic.
- Do not call the cascade contagion, transmission, network diffusion, or
  spillover.
- Do not call the task fraud detection.
- Do not use feature importance as mechanism.
- Do not use "outperforms", "superior", "state-of-the-art", "model-driven",
  "robust insights", "comprehensive framework", or "to the best of our
  knowledge" to inflate claims.

Results and Discussion polish:

- Translate precision or lift into practical screening economics only when the
  table values directly support the translation. If prevalence is 0.0208, the
  baseline screen implies roughly one positive per 48 issuer-years; do not
  invent utility or cost savings.
- Treat best-model, best-window, and max-PR-AUC language as descriptive ranking
  evidence unless selection was pre-specified or separately validated.
- Keep feature-family results as feature fusion, not XBRL dominance.
- Use common-sample / coverage caveat language for XBRL, auditor, and
  prior-filing history feature-family comparisons.
- Treat public-data reproducibility as open-science and accounting-measurement
  value. Do not oversell deployment-ready RegTech.

Subsection template:

1. What was tested, in one accounting-framed sentence.
2. What was found, with numbers and prevalence/base-rate context.
3. What the result means for the accounting construct.
4. Boundary, caveat, or diagnostic status.

Deliverable:

- Section diagnosis.
- Structural revision plan.
- Five sentence-level revisions: original, problem, revised.
- Polished section text.
- Residual caveats needing artifact verification or citation support.

## Review Mode: Abstract And Introduction

Purpose: storyline revision before submission or after a major audit.

The Abstract and Introduction should answer the BAR referee's "so what" question
without overstating the evidence. The sequence should be:

1. Measurement problem: observed restatement, correction, comment-letter, and
   enforcement labels mix occurrence, detection, timing, institutional
   selection, and public observability.
2. Estimand: filing-origin, submission-dated review-and-correction outcome state.
3. Public-data design: dated filing-origin predictors, correspondence submission
   dates, and public correction dates give a sharper event clock than many
   year-level detected-misstatement labels without implying correspondence was
   public on submission.
4. Public cascade: submission-dated eventually disclosed correspondence,
   amendment/friction/correction, and Item 4.02 non-reliance as typed recorded
   outcomes.
5. Evidence architecture: benchmark layer, public cascade layer, bridge gate.
6. Contribution: measurement redesign under partial observability,
   reproducible public-data architecture, typed cascade ontology, and
   bridge-gated validation.
7. Main evidence: filing-origin information ranks future submission-dated
   correspondence and public correction events; correspondence is broad and ranked
   above base rate across folds; amendments are intermediate; Item 4.02 is rare
   but rankable; feature fusion helps, metadata remains strong; bridge-gated
   overlap supports related-but-non-identical constructs.
8. Claim boundary: not unobserved fraud occurrence, not causal enforcement
   effects, not full SEC review universe, not full enforcement universe, and
   not same-estimand superiority over prior fraud-prediction papers.

Deliverable:

- Revised Abstract, normally 150-250 words unless live BAR guidance states
  otherwise.
- Revised Introduction opening, 5-7 paragraphs.
- Contribution paragraph.
- Claim-boundary paragraph.
- Sentences to delete because they sound like a design memo or response memo.

## Review Mode: Referee Report

Purpose: skeptical but fair referee simulation after the polished draft
compiles.

Write a skeptical but fair referee report. Do not rewrite the paper. Identify
the main reasons the paper would receive a major revision.

Focus on:

- whether the estimand is distinct from prior detected-misstatement prediction;
- whether submission-dated correspondence is a defensible selected outcome;
- whether the paper is too close to the comment-letter prediction literature;
- whether the amendment label is too heterogeneous;
- whether Item 4.02 is too sparse for headline inference;
- whether WRDS-validated bridge evidence is sufficient for overlap claims;
- whether public-data-first is positioned as scientific design rather than
  constraint;
- whether model evaluation is appropriate for rare events;
- whether peer-compatible model-family results are overinterpreted;
- whether feature-family evidence has economic content;
- whether the paper honestly handles partial observability, endogenous
  scrutiny, detection delay, right censoring, and public-source incompleteness.

Deliverable:

- Summary assessment, one paragraph.
- Major concerns, 5-8 items.
- Minor concerns, 5-10 items.
- Required revisions for credible resubmission.
- Best possible contribution if revised correctly.
- What the paper must not claim.

## Audit Output Types

Use a **triage audit** for fast P0/P1 prevention while drafting.

Triage audit deliverable:

1. Audit date, repo SHA if available, manuscript readiness, audit mode, BAR fit
   judgment, main paper risk, and likely rejection path.
2. P0/P1 findings only.
3. Claim-to-evidence + claim-strength table for at most five main claims.
4. Bridge-gate assessment.
5. No more than five revision actions.

Use a **full audit** when the paper is close to submission.

Full audit deliverable:

1. All P0/P1/P2 findings.
2. Claim-to-evidence + claim-strength table.
3. Terminology ledger.
4. Bridge-gate assessment.
5. Economic-mechanism assessment.
6. Literature and citation audit.
7. Public-data support ledger.
8. Table/figure architecture review.
9. Abstract audit.
10. Conclusion audit.
11. Revision priorities.

Use a **delta audit** after revisions.

Delta audit deliverable:

1. Changed sections or files reviewed.
2. Earlier P0/P1 issues marked resolved, partially resolved, or open.
3. New or changed claims only, unless they affect the global story.

## Skeleton Mode

Fallback only. The current manuscript is drafted; use skeleton mode only if the
manuscript folder is empty or has no real body. Do not simulate a review of
nonexistent text.

Skeleton deliverable:

- Working title and thesis.
- Abstract target of 150-250 words unless live BAR guidance states otherwise.
- Introduction: measurement problem, contribution, main evidence, boundaries.
- Literature and construct development: detected-misstatement labels, partial
  observability, public disclosure review, audit/oversight signals, and machine
  learning as measurement infrastructure.
- Data and label construction: public SEC/PCAOB/EDGAR sources, origin date,
  public labels, censoring, public/private status, and bridge gate.
- Research design: filing-origin information set, model families, metrics,
  benchmark layer, public cascade layer, and construct-overlap design.
- Results: public cascade performance, feature-family evidence, peer
  model-family alignment, and construct-overlap evidence.
- Additional analyses and robustness: common-sample checks, sparse Item 4.02
  interpretation, DML-style high-dimensional adjustment, and sensitivity checks.
- Discussion: limited screening interpretation, asymmetric costs, false
  negatives, public-data reproducibility, and international relevance.
- Conclusion: accounting insight, strongest evidence, limitations, and honest
  generalizability.

## BAR Mechanics and Citation Discipline

- Use the official BAR Guide for Authors and Elsevier instructions as the live
  source for submission mechanics. Verify mechanics against primary sources
  before upload.
- Keep manuscript files double-anonymized when current BAR/Elsevier instructions
  require it, with title page and anonymized manuscript separated as instructed.
- Keep the abstract concise and factual.
- Provide no more than 6 keywords unless live instructions say otherwise.
- If highlights are required or submitted, keep them short, specific, factual,
  and within the current Elsevier length rule.
- Tables should be editable text with concise titles and self-contained notes.
- Include data availability, competing interest, CRediT, and tool-use
  disclosures as required by Elsevier and coauthor policy.
- Use primary sources for SEC/PCAOB/BAR/Elsevier rules.
- If live web verification is needed, use primary sources only and state exactly
  which claims were verified.
- Elsevier-style AI policy should be kept separate by role. Author-side AI tools
  may be used only with human oversight, disclosure, and author responsibility
  under current instructions. Reviewers and editors should not upload submitted
  manuscripts or confidential peer-review material to generative-AI tools. This
  brief is author-side QC, not journal peer review.
- A closed BAR special issue or article collection on AI in accounting and
  finance can support scope alignment only as verified editorial context; it is
  not a live special-issue target and should not make the cover letter sound
  AI-led. Verify through primary sources such as the
  [BAR special issues page](https://www.sciencedirect.com/journal/the-british-accounting-review/special-issues)
  or the
  [AI in Accounting and Finance Research and Practice collection](https://www.sciencedirect.com/special-issue/10NTKFHG83V).

Core literature coverage should include:

- Dechow, Ge, Larson, and Sloan on the F-score / misstatement-prediction
  tradition.
- Perols on classifier comparison.
- Bao, Ke, Li, Yu, and Zhang on machine-learning fraud detection.
- Bertomeu, Cheynel, Floyd, and Pan on machine-learning misstatement detection.
- Barton, Burnett, Gunny, and Miller on occurrence versus detection.
- Comment-letter and disclosure-review studies, including the comment-letter
  prediction literature.
- Restatement, amendment, and correction studies.
- Auditing and PCAOB/Form AP/inspection oversight work.
- Disclosure opacity, XBRL, structured reporting, and public-data processing.
- Partial observability, selection, drift, rare-event ranking, and
  cost-sensitive evaluation.
- International accounting and enforcement portability when discussing UK/EU
  relevance.

## Table And Figure Architecture

Keep numbering generic in audit language. Refer to functions, not fixed numbers,
because numbering can change during revision.

- The conceptual figure should show the reporting-risk cascade as typed recorded
  outcomes, not contagion or a release-time sequence.
- The label ontology table should define construct, horizon, source, and caveat.
- Public-lake scale tables should separate public-source construction from
  benchmark compatibility.
- Performance tables should report PR-AUC with prevalence/base-rate and an
  uncertainty caveat or fold dispersion where available.
- Performance tables and figures should state evaluation unit, task, base-rate
  context, and bounded measurement interpretation in the caption or note.
- Feature-family tables should be information-set evidence with a common-sample
  / coverage caveat.
- Feature-family tables should not let model-selection optimism or max metrics
  become the headline claim.
- Peer-model tables should state model-family transfer, not original-study
  replication.
- Construct-overlap tables should show related-but-non-identical evidence, not
  equivalence.
- Opacity/DML tables should state adjusted association and avoid causal
  language.
- Captions must tell the bounded economic or measurement interpretation without
  requiring repository knowledge.
