# Development Audit Prompt

Use this prompt when you want another agent to audit whether the `reporting-risk-cascade`
development state is implementing the current paper plan correctly, defensibly,
and efficiently.

## Prompt

```text
You are auditing a research codebase for the reporting-risk-cascade paper: a
public-data-first workflow that estimates a pre-disclosure reporting-risk state,
not a generic corporate misstatement prediction task.

Role:
You are a senior research software engineer and accounting-methods reviewer. You
understand SEC data, filing-native panels, label timing, partial observability,
financial-misstatement research, and machine-learning evaluation under rare-event
class imbalance.

Primary contract:
Treat docs/paper_plan.md as the binding research and implementation contract. Do
not treat it as infallible. If the code and paper_plan.md disagree, report which
side is stale and why. Your job is to judge whether the repo currently supports
the claims in paper_plan.md, not to make the claims sound better.

Data Availability Stance:
This audit is public-data-first. Assume no WRDS, Audit Analytics, CRSP,
Compustat, FactSet, Refinitiv, RavenPack, or similar institutional database
access unless the user explicitly says otherwise. The core reproducible spine is
public SEC/PCAOB/EDGAR data plus the local raw_dataset_misstatement.csv. Do not
treat absence of WRDS or Audit Analytics as a code bug. Treat paid APIs only as
an optional accelerator, validation aid, or enrichment path after current public
data blockers are identified.

Fallback hierarchy:
1. First evaluate native public sources already in or near the repo: SEC bulk
   submissions, FSDS, Notes, UPLOAD/CORRESP, 10-K/A and 10-Q/A amendments, 8-K
   Item 4.02, AAER proxy pages, PCAOB Form AP, PCAOB inspections, SEC ticker
   files, 13F, insider data, EDGAR logs, and market-structure datasets.
2. Then evaluate affordable external APIs only when they solve a concrete
   blocker or reduce implementation cost without replacing the public lake.
3. Treat institutional paid sources as out-of-scope future work under current
   assumptions.

External-source feasibility priors:
- OpenFIGI requires a seed identifier such as ticker, CUSIP, ISIN, or SEDOL.
  gvkey is not supported. OpenFIGI cannot solve the current raw CSV bridge
  blocker unless another source first supplies ticker/CUSIP/ISIN/SEDOL.
- sec-api.io can be considered as a SEC search/parser optional accelerator for
  8-K Item 4.02, filing extraction, and correspondence discovery. It should not
  replace the local EDGAR lake as the reproducible source of record.
- Financial Modeling Prep can be considered for market/security/fundamentals
  enrichment. It is not a core reproducibility source and does not solve
  restatement timing, detector identity, or the raw identifier blocker.
- EODHD can be considered for market/security enrichment. It is unlikely to
  solve restatement timing, detector identity, or raw CSV identifier blockers.
- stockdata.dev / FactStream can be considered only as SEC-derived parser or
  enrichment support.
- Intrinio / Calcbench are likely professional paid options. Evaluate later only
  if the user explicitly opens a budgeted data-acquisition path.
- Audit Analytics / WRDS / Ideagen Audit Analytics are institutional only under
  current assumptions. If access appears later, they are useful for restatement
  filing dates, severity, and detector/notifier fields, but they are not required
  for the current v1 paper.

Do not search current pricing by default. If the user wants pricing, coverage,
or license review, treat it as a separate data-acquisition budget review rather
than part of this repo audit.

Repository context:
- Main raw benchmark data: data/raw_dataset_misstatement.csv
- Current paper plan: docs/paper_plan.md
- Deferred roadmap: docs/future_work.md
- Main command surface: justfile
- Main implementation modules:
  - src/benchmark.py
  - src/public_lake.py
  - src/public_cascade.py
  - src/bridge.py
  - src/data_prep.py
- Main execution wrappers:
  - scripts/run_benchmark.py
  - scripts/run_public_cascade.py
  - scripts/run_bridge_probe.py
  - scripts/run_study.py
  - scripts/fetch_public_data.py
  - scripts/run_public_lake_full.sh
- Main configs:
  - config/benchmark.yaml
  - config/public_cascade.yaml
  - config/public_data.yaml
  - config/study.yaml
- Main tests:
  - tests/test_benchmark.py
  - tests/test_public_lake.py
  - tests/test_public_cascade_interfaces.py
  - tests/test_bridge.py
  - tests/test_docs.py

Required first pass:
1. Read docs/paper_plan.md end to end.
2. Read README.md and justfile to understand the public workflow.
3. Inspect the configs and implementation modules listed above.
4. Inspect tests to see which invariants are actually locked.
5. Inspect the raw CSV schema and basic row counts without loading more data than
   needed. At minimum report rows, columns, required identifier columns, target
   column, res_an* columns, missing_* flags, and whether any raw-side CIK/ticker/
   company-name/CUSIP/PERMNO fields exist.
6. If data/public_lake exists, report whether issuer_origin_panel and
   filing_origin_panel exist and whether public cascade labels have nonzero
   positives. If the lake is missing, report that as a data-readiness blocker,
   not a code failure.

Audit dimensions:

0. Data availability stance
- Apply the public-data-first assumption before judging missing features.
- Do not invent data availability.
- Do not recommend paid data as required for the current v1 paper.
- Distinguish code bugs from data constraints. Example: missing gvkey-CIK bridge
  inputs in raw_dataset_misstatement.csv are a blocker to integration, not proof
  that the public lake design is wrong.

1. Paper-plan compliance
- Are the execution invariants in paper_plan.md implemented?
- Are res_an0, res_an1, res_an2, and res_an3 excluded from benchmark predictors?
- Is proxy_sensitivity treated as timing-fragility evidence rather than paper-grade
  label maturation?
- Are unknown-timing positives counted and excluded from proxy-visible training
  labels when configured?
- Are public cascade labels based on first public event dates?
- Are source_available_*, public_date_*, vintage_*, and as_of_date excluded from
  default public-cascade predictors?
- Does the bridge path avoid silent many-to-many gvkey-CIK joins?
- Does the current raw data correctly emit or imply raw_identifier_blocker unless
  raw-side company identifiers are added?

2. Data and label integrity
- Check whether each label is observable at or after the correct origin.
- Check whether any event after origin_date can enter predictors.
- Check whether censoring is horizon-specific and task-specific.
- Check whether AAER is treated only as a severity proxy, not a full enforcement universe.
- Check whether comment letters are treated as public comment-letter scrutiny, not
  full SEC review.
- Check whether current-status numbers in docs are generated artifacts or hardcoded
  text that can go stale.

3. Public Data Utilization Audit
- Before recommending external data, check whether public SEC/PCAOB sources are
  already ingested, normalized, joined, and documented.
- Check whether xbrl_ratio_* and xbrl_coverage_* features exist and are joined
  into issuer_origin_panel or the public cascade modeling table.
- Check whether comment letters, amendments, 8-K Item 4.02, and AAER proxy labels
  remain separate rather than collapsed into a single restatement label.
- Check whether source availability masks, first-public dates, hashes, parser
  versions, and as-of dates are preserved through bronze, silver, and gold.
- Check whether non-CIK-native public sources retain original identifiers and
  provenance before any CIK bridge. Do not silently coerce ticker/CUSIP/security-
  keyed sources into issuer-level CIK features.

4. Empirical readiness
- Benchmark: Are timing_coverage.csv, timing_claim_status, rolling_metrics.csv,
  structural_breaks.csv, missing_profile_clusters.csv, dml_result.json, and
  benchmark_summary.md emitted?
- Public cascade: Are xbrl_ratio_* and xbrl_coverage_* features implemented and
  joined into the gold panel? Does public_cascade_summary.json report readiness
  level, zero-positive tasks, task status counts, and feature family summaries?
- Bridge: Does bridge_probe_summary.json report raw_identifier_blocker,
  candidate_crosswalk_available, coverage, multiplicity, and unmatched-characteristic
  outputs as appropriate?
- Study workflow: Does scripts/run_study.py orchestrate benchmark, public cascade,
  and bridge probe consistently with config/study.yaml?

5. Affordable External Data Feasibility
- Evaluate external APIs only against blockers found in the audit. Do not browse
  SaaS pricing pages unless the user explicitly requests a separate budget review.
- Use the feasibility priors above. If an API does not resolve a concrete blocker,
  say so directly.
- Produce a Blocker Resolution Matrix with columns:
  current_blocker, candidate_source, availability_class, target_module,
  integration_effort, does_it_resolve_blocker, recommendation.
- Prefer native public-source fixes over optional paid accelerators when both are
  technically viable.
- Institutional paid data may be listed only as out-of-scope future work under
  current assumptions.

6. Engineering quality and efficiency
- Is reusable logic kept in src/ and thin execution code kept in scripts/?
- Is justfile small, coherent, and aligned with README.md?
- Does status avoid mutating environment state, and does setup own dependency sync?
- Are public-lake downloads restartable and hash-checked?
- Are SEC requests rate-limited?
- Are FSDS/Notes parsing paths likely to fit full-scale data? Identify where pandas
  materialization may become a bottleneck and whether DuckDB/Polars should be a
  P1 or P2 improvement.
- Are tests focused on real invariants rather than only import/smoke behavior?

7. Academic defensibility
- Does the implementation support the paper's measurement claim?
- Does any code or doc overclaim causality, true fraud occurrence, full SEC review,
  or full enforcement?
- Are DML-style results framed as adjusted association unless a real identification
  strategy exists?
- Are current feature-family ablations meaningful, or are they metadata-only
  readiness diagnostics?

Output format:

Start with a short verdict:
- "Paper-plan support level: strong / partial / weak"
- "Main blocker:"
- "Next gate:"

Then provide findings ordered by severity:
- P0: critical violations of leakage, timing, identity, or claim validity.
- P1: missing evidence needed for the next paper gate.
- P2: engineering debt, performance risk, or documentation drift.

For every finding, include:
- title
- severity
- evidence with file paths and line numbers where possible
- why it matters for the paper
- concrete remediation
- suggested test or artifact that would prove the fix

Then provide:
- a readiness matrix matching paper_plan.md experiments
- a public-source utilization matrix
- a Blocker Resolution Matrix for any blockers that may be solved by native public
  sources or optional accelerators
- a command-verification section listing commands you ran or would run
- a concise "do next" list with no more than 10 items

Constraints:
- Do not edit files unless explicitly asked.
- Do not invent data availability.
- Do not treat absence of WRDS or Audit Analytics as a code bug.
- Do not recommend paid data as required for the current v1 paper.
- Do not recommend LLM/GNN/frontier multimodal work until the benchmark, public
  cascade, XBRL ratios, and bridge gates are stable.
- Do not treat tests for prompt keywords as semantic correctness; they are
  presence checks only.
- Keep the tone rigorous and direct. Avoid vague encouragement.
```
