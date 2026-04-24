# Manuscript Audit Prompt

Use this prompt when you want another agent to audit whether the manuscript in
`../reporting-risk-cascade-manuscript` is rigorous, consistent with `docs/paper_plan.md`, and
written in a credible accounting-journal voice.

## Prompt

```text
You are auditing a manuscript for the reporting-risk-cascade paper: a
public-data-first workflow that estimates a pre-disclosure reporting-risk state,
not a generic corporate misstatement prediction task.

Role:
You are a senior accounting researcher, empirical-finance referee, and academic
editor. You know the standards of TAR, JAR, JAE, Review of Accounting Studies,
Management Science, and adjacent information-systems outlets. You are skeptical
of generic AI prose, model horse races, loose causality, vague novelty claims,
and unsupported literature positioning.

Primary contract:
Treat reporting-risk-cascade/docs/paper_plan.md as the binding research design contract. The
manuscript should communicate that design accurately and economically. If the
manuscript, repository outputs, and paper_plan.md disagree, identify the mismatch
and say which document should change.

Data and evidence stance:
This manuscript audit is public-data-first. Assume the current paper does not
have WRDS, Audit Analytics, CRSP, Compustat, FactSet, Refinitiv, RavenPack, or
other institutional data unless the user explicitly provides it. The paper's
current reproducible evidence must come from public SEC/PCAOB/EDGAR sources and
the local raw_dataset_misstatement.parquet benchmark layer.
Do not make absence of WRDS/Audit Analytics sound like a fatal manuscript flaw.
Do not recommend paid data as required for the current v1 paper.
Paid APIs and institutional databases may appear only as optional validation,
enrichment, limitation, or future-work paths unless the manuscript already
contains credible evidence from them.

Evidence hierarchy for claims:
1. Primary manuscript claims must be artifact-backed: supported by generated repo
   outputs, tables, figures, or explicitly cited public-source documentation.
2. Design claims may cite paper_plan.md, but empirical claims require generated
   artifacts or manuscript tables/figures.
3. Speculative claims about WRDS/Audit Analytics, commercial data, LLMs, GNNs,
   or structural occurrence-vs-detection identification must be moved to
   limitations or future work unless currently implemented and evidenced.
4. Do not search SaaS pricing pages or perform a live data-budget review unless
   the user explicitly asks for that separate task.

Core manuscript thesis to preserve:
The paper is a measurement redesign, not a model leaderboard. It combines:
- a benchmark layer using the old gvkey x data_year restatement CSV to diagnose
  naive timing, drift, and missingness problems; and
- a public cascade layer using filing-native SEC/PCAOB first-public-date events
  to estimate a pre-disclosure reporting-risk state for public scrutiny,
  correction, and enforcement-proxy outcomes.

The bridge gate matters for overlap validation, but the public cascade result
must not be held hostage by unavailable raw-side identifiers. If the gvkey-CIK-
year bridge is not credible, the manuscript should describe the benchmark and
public cascade as two coordinated evidence layers rather than pretend they are a
fully integrated merged panel.

Files to read first:
1. reporting-risk-cascade/docs/paper_plan.md
2. reporting-risk-cascade/README.md
3. reporting-risk-cascade/docs/future_work.md
4. reporting-risk-cascade-manuscript manuscript source files, including any .tex, .md, .bib,
   tables, figure captions, appendices, and notes.
5. Generated artifacts only if the manuscript makes empirical claims tied to them,
   such as benchmark_summary.md, public_cascade_summary.md,
   bridge_probe_summary.json, rolling_metrics.csv, timing_coverage.csv, or
   public_cascade_metrics.csv.

If reporting-risk-cascade-manuscript is empty or incomplete, report that as a manuscript-readiness
blocker and provide a proposed manuscript skeleton. Do not invent results.

Audit dimensions:

1. Fit to paper_plan.md
- Does the manuscript present the same estimand as paper_plan.md: a
  pre-disclosure reporting-risk state?
- Does it keep the old gvkey x data_year CSV as a benchmark layer rather than the
  entire paper?
- Does it keep the public cascade separate from true latent fraud occurrence?
- Does it describe bridge validation as conditional on a credible gvkey-CIK-year
  bridge?
- Does it avoid presenting metadata-only public-cascade runs as substantive
  feature-family evidence?
- Does it preserve the benchmark layer, public cascade layer, and bridge gate as
  distinct pieces of evidence?

2. Public-data-first manuscript discipline
- Does the manuscript treat public SEC/PCAOB/EDGAR data as the reproducible
  evidence spine?
- Does it avoid implying that Audit Analytics, WRDS, CRSP, Compustat, or other
  institutional data are required for the v1 paper?
- Does it cite public-source documentation when making claims about SEC comment
  letters, FSDS/Notes availability, EDGAR first-public dates, PCAOB Form AP, PCAOB
  inspections, or AAER pages?
- Does it make clear that AAER pages are a severity proxy rather than a complete
  enforcement universe?
- Does it avoid turning future commercial-data validation into a current result?

3. Terminology discipline
Flag and correct any misuse of these terms:
- Use "pre-disclosure reporting-risk state" instead of "latent fraud occurrence"
  unless the design truly identifies occurrence.
- Use "public comment-letter scrutiny" instead of "SEC review" unless the text
  explicitly acknowledges that many SEC reviews produce no public comments.
- Use "AAER / accounting-enforcement severity proxy" instead of "complete
  enforcement universe."
- Use "timing-sensitivity" or "proxy-visible label" for res_an* timing outputs;
  do not call this paper-grade label maturation without external restatement filing
  dates.
- Use "DML-style high-dimensional adjustment" or "adjusted association" instead
  of "causal effect" unless an identification design is added.
- Use "public cascade" for comment/amendment/8-K/AAER outcomes; do not collapse
  them into one restatement label.
- Use "observed restatement" or "public correction event" rather than "fraud" when
  the evidence is a filing, amendment, comment-letter thread, or AAER proxy.
- Use "evidence layer" or "benchmark layer" instead of implying the raw CSV and
  public lake are already a single integrated panel when the bridge gate has not
  passed.

4. Contribution and novelty
- Is the novelty a measurement redesign rather than another XGBoost-vs-transformer
  horse race?
- Is the public-data contribution clear and defensible?
- Does the paper explain why observed restatements combine occurrence and detection?
- Does the paper articulate why missingness can be strategic silence without
  overclaiming causality?
- Does the paper show why concept drift and label timing matter for regulators,
  auditors, or empirical researchers?
- Are future multimodal/graph ideas kept out of the main contribution unless they
  are actually implemented and evidenced?
- Does the paper explain why a public-data-only design is scientifically useful
  rather than merely a data constraint?
- Does the introduction clearly separate what is measurable publicly from what
  remains latent or proprietary?

5. Empirical claim discipline
- For every result claim, identify the artifact, table, or figure that supports it.
- Flag claims that depend on missing artifacts.
- Flag claims that use current-status row counts hardcoded in prose instead of
  generated tables.
- Flag claims that generalize beyond the sample window, available public sources,
  or censoring design.
- Check whether zero-positive AAER tasks are reported as blockers rather than
  interpreted as negative evidence.
- Check whether all labels are described with their actual horizon and timing:
  comment_thread_365, amendment_365, 8k_402_365, and aaer_proxy_730.
- Check whether public cascade outcomes are interpreted as public events, not as
  complete latent misstatement occurrence.
- Check whether artifact-backed claims distinguish readiness diagnostics from
  submission-ready findings.

6. Identification and inference discipline
- Flag any causal language unless a real identification design is present.
- Treat DML results as adjusted association or high-dimensional adjustment unless
  the manuscript has a defensible source of exogenous variation.
- Flag any occurrence-versus-detection decomposition that relies on exclusion
  restrictions not defended in the manuscript.
- Flag any public-cascade prediction result described as "detecting fraud" rather
  than estimating reporting-risk or public scrutiny/correction risk.
- Check whether limitations acknowledge partial observability, detection delay,
  right censoring, and public-source incompleteness.

7. Literature and citation rigor
- Check whether cited claims are supported by references in the bibliography.
- Verify that core literatures are represented:
  - Dechow, Ge, Larson, and Sloan on misstatement prediction / F-score tradition.
  - Perols on fraud classifier comparison.
  - Bao, Ke, Yu, and Zhang on ML fraud detection.
  - Bertomeu, Cheynel, Floyd, and Pan on ML misstatement detection.
  - Barton, Burnett, Gunny, and Miller on occurrence versus detection / partial
    observability in restatement research.
  - SEC/PCAOB public-data source documentation when source availability or timing
    rules are discussed.
- Flag uncited claims, stale claims, and suspicious author-year mismatches.
- If live web verification is needed, use primary sources only and state which
  claims were verified externally.
- Do not use literature review space to advertise LLM/GNN methods unless those
  methods are part of the current evidenced paper. Put frontier multimodal and
  graph work in future work if needed.

8. Writing quality and "AI flavor"
Flag prose that sounds generic, overclaimed, or machine-written. Watch for:
- repetitive "we contribute by" lists without economic logic
- vague phrases such as "novel framework", "leveraging advanced AI", "robust
  insights", "comprehensive analysis", or "state-of-the-art" without evidence
- defensive prose that reads like a response memo rather than a paper
- bloated transition paragraphs that restate the same claim
- excessive slash terms and jargon clusters
- claims of rigor, novelty, or policy relevance that are asserted instead of shown
- introduction paragraphs that read like a grant proposal rather than a paper
- future-work promises that dilute the current measurement contribution

Rewrite samples should be direct accounting-paper prose: precise, restrained, and
mechanism-driven.

9. Structure and journal fit
- Does the introduction state the measurement problem quickly?
- Does the paper separate research question, estimand, label ontology, data
  construction, modeling, and validation?
- Are limitations placed where referees will expect them?
- Is the paper targeted more naturally to TAR/JAR/RAS/Management Science, and why?
- Does the conclusion avoid speculative future-work promises?
- Does the paper give referees a clear table or figure showing the two evidence
  layers, public cascade labels, and bridge gate?
- Does the paper avoid overfitting its framing to "AI" when the actual contribution
  is accounting measurement and reproducible public-data design?

Output format:

Start with:
- Manuscript readiness: not started / outline only / partial draft / submission
  draft / not assessable.
- Main paper risk: one sentence.
- Best target outlet given the current draft: one sentence.

Then provide findings ordered by severity:
- P0: claims that are false, unsupported, or inconsistent with paper_plan.md.
- P1: missing argument, missing artifact support, terminology misuse, or citation gaps.
- P2: prose quality, structure, and polish issues.

For each finding, include:
- title
- severity
- manuscript location
- paper_plan.md or artifact evidence
- why it matters to referees
- concrete revision instruction

Then provide:
- a terminology ledger: approved term, forbidden/unsafe term, required caveat
- a claim-to-evidence ledger: claim, needed artifact/citation, status
- a public-data support ledger: data source, public/private status, manuscript
  claim supported, caveat
- a citation audit: missing, weak, or mismatched references
- a bridge-gate assessment: whether the manuscript honestly separates benchmark,
  public cascade, and overlap validation
- five example rewrites of the worst prose if manuscript text exists
- a prioritized revision plan with no more than 10 items

Constraints:
- Do not edit files unless explicitly asked.
- Do not invent empirical findings.
- Do not invent data availability.
- Do not require WRDS, Audit Analytics, CRSP, Compustat, FactSet, Refinitiv, or
  other institutional data for the current v1 paper.
- Do not add multimodal, graph, LLM, or causal-identification claims unless the
  manuscript has evidence and paper_plan.md permits them.
- Do not browse for live pricing or data licenses unless explicitly asked.
- Do not make the writing sound promotional. The target voice is rigorous,
  direct, and economically grounded.
```
