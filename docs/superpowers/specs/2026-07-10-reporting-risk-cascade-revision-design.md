# Evidence-Current Reporting-Risk Cascade Revision Design

**Status:** Approved design B, recorded 2026-07-10.

**Repositories:**

- Executable research repository: `reporting-risk-cascade/reporting-risk-cascade`.
- Manuscript repository: `reporting-risk-cascade/reporting-risk-cascade-manuscript`.
- The outer `reporting-risk-cascade` directory is a workspace wrapper, not a Git repository.

## 1. Objective

Produce an evidence-current, internally consistent revision of the reporting-risk-cascade paper in which:

1. the public-lake build consumes the current verified Form AP archive under a strict filing-origin information boundary;
2. headline model results come from one frozen, method-driven primary specification rather than a post-hoc grid average or maximum;
3. a visibility-and-history information-set baseline directly tests the strongest rival explanation for comment-letter prediction;
4. construct-alignment rows are selected by declared keys rather than maximum lift;
5. sample attrition, DML dimensions, input provenance, and empirical uncertainty are auditable;
6. `paper_plan.md`, `results_snapshot.md`, FAQ, Serena memories, generated artifacts, manuscript prose, tables, figures, and submission statements agree with the same clean run; and
7. a real anonymized replication archive and a fresh ARS integrity report support any submission-readiness claim.

The contribution remains a filing-origin public reporting-risk measurement-and-ranking paper. The revision must not turn the project into a fraud detector, causal enforcement model, calibrated operational probability system, or same-estimand model leaderboard.

## 2. Scope and Non-Goals

### In scope

- Form AP archive-extraction freshness and provenance.
- A frozen public primary specification.
- One visibility-and-history feature-family baseline using the existing XGBoost evaluation loop.
- Primary and excluding-2020 performance summaries.
- Declared construct-alignment rows and their bootstrap intervals.
- Auditable sample attrition and DML dimension labels.
- Clean run provenance and reviewer-facing provenance display.
- Artifact-to-docs-to-manuscript synchronization.
- A code-and-metadata replication archive that excludes restricted data.
- Tracked-file mode normalization and removal of transient local build debris created during this revision.
- Manuscript revision, PDF/package rendering, and final academic-integrity verification.

### Out of scope for this revision

- New 180-day, next-filing, or multi-horizon outcome labels.
- Manual amendment-severity annotation or a new amendment taxonomy.
- Economic-consequence outcomes, new international samples, or 2025-2026 test folds.
- A second public-cascade estimator solely for the visibility baseline.
- SHAP or other post-hoc explanation frameworks.
- Deletion of historical empirical runs that cannot be proven regenerable and superseded. Such runs may be labeled non-canonical but are retained unless separately approved.
- Inventing author names, affiliations, funding, acknowledgements, CRediT roles, conflicts, or declaration approvals.

These exclusions are disclosed as limitations or future work rather than implied to have been completed.

## 3. Current Root Causes

### 3.1 Form AP source freshness

`bronze/form-ap/FirmFilings.zip` is newer than the persisted `FirmFilings.csv`. The current normalization path extracts the ZIP member only when the CSV is absent, so a fresh silver/gold build can continue to consume a stale derived CSV.

The newer ZIP contains 675 additional Form AP filing IDs and changes 10 existing IDs. Those differences are dated in 2025-2026 and are not expected to affect the 2011-2024 modeling sample, but the build contract is still wrong and the absence of an expected effect must be verified, not assumed.

### 3.2 No primary public specification

The current public task table averages all feature-set and train-window combinations. The current summary separately reports the ex-post best combination. Neither is a fixed headline estimate.

### 3.3 No visibility/history baseline

The current `metadata` family is a broad catch-all. It does not isolate the filing visibility, filing persistence, and prior public-scrutiny variables that support the strongest rival explanation: the model may predict public SEC visibility rather than an accounting-relevant reporting-risk state.

### 3.4 Post-hoc construct-alignment selection

The manuscript package and results snapshot independently sort 60 public-to-benchmark rows and 720 reciprocal rows by top-decile lift and take the maximum. The bootstrap currently covers only the highest-lift rows. The displayed evidence therefore lacks a declared selection contract.

### 3.5 Hidden provenance and hand-maintained drift

The study manifest already records Git, config, input, lock, and WRDS provenance, but the results snapshot does not expose it. The FAQ and manuscript contain hand-maintained numbers that are older than the source package.

### 3.6 Ambiguous DML dimensions

The DML metadata reports 60 raw controls, the result rows report 64 encoded nuisance-model columns, and the manuscript says 65. The three numbers refer to different or erroneous dimensions and must not share one label.

### 3.7 Manuscript synchronization boundary

The manuscript repository has a 56-file working tree containing intentional prose and table-formatting edits. Bulk replacement of curated `tables/*.tex` would destroy manuscript-facing work. Generated source tables and curated manuscript tables require a previewed, selective merge.

## 4. Canonical Evidence Flow

The revision uses one directional truth flow:

```text
verified bronze sources
    -> clean silver/gold public lake
    -> clean full_with_peer study manifest and artifacts
    -> manuscript_package
    -> results_snapshot and stable FAQ links
    -> selective manuscript sync and hand-written interpretation
    -> compiled manuscript and flat submission package
    -> anonymized replication archive and ARS integrity report
```

Downstream files must never overwrite or reinterpret upstream empirical values silently. A prose claim that cannot be traced to the clean manifest, a generated table, or an explicitly labeled descriptive calculation is not reportable.

## 5. Public-Lake Source Contract

### 5.1 Form AP archive precedence

When `FirmFilings.zip` exists:

1. verify its sidecar hash before use;
2. require a `FirmFilings.csv` member;
3. extract the member to a temporary file in the same filesystem;
4. atomically replace the persisted derived CSV; and
5. normalize the newly extracted CSV.

If the ZIP exists but is invalid or lacks the required member, the build fails. It must not fall back to an older CSV. If the ZIP is absent, a standalone CSV remains an explicit compatibility fallback.

The regression test supplies an older CSV and a newer ZIP containing different rows, then proves that normalized output follows the ZIP.

### 5.2 Pinned public-data vintage

The revision pins `as_of_date=2026-07-06`, the date supported by the current cached source snapshot. The value must agree across `config/public_data.yaml`, the full-run shell entry point, the `just` entry point, documentation, and generated run metadata. It must not be advanced to 2026-07-10 without refreshing and validating the corresponding source archives.

### 5.3 Clean rebuild

After source changes are committed, rebuild silver and gold once from cached bronze with `fresh` semantics. Do not force network downloads. Then run the full peer-enabled study once. This avoids the duplicate model execution produced by running both the core `just full` study and a separate peer study.

## 6. Public Prediction Design

### 6.1 Frozen primary specification

The public primary specification is frozen for this revision as:

```yaml
feature_set: all
train_window: expanding
```

This is a method-driven revision freeze, not a claim of historical preregistration. The expanding window uses all prior eligible years, avoids selecting the observed best rolling window, and currently produces an equal-task mean PR-AUC close to the ex-post best rolling-7-year configuration.

The resolved specification is validated against configured feature sets and windows and written into `public_cascade_summary.json` and run-facing provenance.

### 6.2 Headline and sensitivity separation

- Table 3 and Figure 1 report only `all + expanding` annual out-of-time results by task.
- Table 3 reports prevalence, PR-AUC, ROC-AUC, Brier, Brier Skill, ECE, valid-fold dispersion, and an excluding-2020 PR-AUC sensitivity with its delta from the full evaluation period.
- Tables 4 and 14 retain feature-family and train-window grid summaries as sensitivity evidence.
- Best-row diagnostics remain available in raw artifacts but are not headline claims.
- The manuscript describes the freeze timing explicitly and does not use `pre-specified` or `preregistered` for a choice made during revision.

### 6.3 Visibility-and-history baseline

Add one `visibility_history` feature family and evaluate it through the existing XGBoost annual out-of-time loop. No new estimator or dependency is introduced.

The family contains only existing filing-origin variables that represent public visibility, filing persistence, and prior public-event history:

- `size`, `core_type`, `form`, and `entity_type`;
- `isXBRL`, `isInlineXBRL`, and `isXBRLNumeric`;
- `days_since_previous_filing` and `prior_filing_count`;
- `filing_friction_is_nt`, `filing_friction_nt_pre_origin`, and `filing_friction_nt_delay_days`;
- one- and three-year counts for public comment threads and amendments; and
- one- and three-year public-history counts for Item 3.01, 4.01, 4.02, and 5.02 events.

Unavailable listed fields are omitted deterministically and reported in the feature-family summary. The family may not include labels, censoring flags, direct identifiers, source-availability flags, public dates, vintage fields, financial-statement values/ratios, note breadth, Form AP variables, or PCAOB inspection variables.

The comparison asks whether the all-feature model adds ranking information beyond a compact visibility/history information set. It is an information-set comparison, not a causal selection correction.

## 7. Sample and DML Accounting

### 7.1 Sample attrition

The public-cascade summary records the sequential sample flow from the unfiltered issuer-origin panel:

1. source issuer-origin rows;
2. rows within fiscal years 2011-2024;
3. domestic US-GAAP proxy rows;
4. rows with an observable 365-day horizon; and
5. task-specific exclusions, including unknown Item 4.02 item metadata.

The current expected sequence is 205,652 -> 97,027 -> 96,827 -> 96,733 before task-specific exclusions. The clean rerun is authoritative; the generator must not freeze these values in source code or `paper_plan.md`.

A generated attrition table is added to the manuscript package and results snapshot. Manuscript prose cites the generated table instead of manually maintaining the sequence.

### 7.2 DML dimensions

The DML output distinguishes:

- `n_raw_controls`: source control variables before encoding;
- `n_encoded_controls`: columns supplied to the nuisance learners after categorical expansion and imputation; and
- `n_opacity_components`: components used to form the missingness-density treatment.

Backward-compatible `n_controls` may remain temporarily only if it is explicitly defined as encoded controls in the artifact schema. Generated table notes and manuscript prose report 60 raw controls and 64 encoded columns only when confirmed by the clean run.

The DML interpretation remains a null adjusted-association diagnostic. It is neither causal evidence nor a required support for the main ranking claim.

## 8. Construct-Alignment Design

### 8.1 Frozen primary rows

The alignment specification is frozen for this revision as follows.

Public score to benchmark positives:

```yaml
model_id: public_cascade
task: 8k_402
feature_set: all
train_window: expanding
label_mode: benchmark_naive
score_aggregation: mean
bridge_tier: high_confidence
```

Benchmark score to public labels:

```yaml
model_id: benchmark_xgb
target_public_label: label_8k_402_365
feature_set: benchmark_all
train_window: expanding
label_mode: naive
score_aggregation: benchmark_score
bridge_tier: high_confidence
```

The exact keys live in tracked configuration, are copied into construct-overlap provenance, and are used by both the manuscript package and results snapshot. A missing or duplicated primary row fails package generation rather than silently selecting another row.

### 8.2 Bootstrap and exploratory rows

The row-level percentile bootstrap remains at seed 42 and 1,000 replicates. Bootstrap scope includes:

- both frozen primary rows; and
- the five highest-lift rows in each direction retained for exploratory sensitivity.

Table 9 and Figure 5 report the frozen primary rows. The results snapshot separately identifies the exploratory maximum rows, their search-universe sizes, and the difference from the primary rows. Maximum rows are labeled exploratory and never called primary, confirmatory, or pre-specified.

The broader three-label contingency matrix, event-time concentration, aggregation sensitivity, bridge sample boundaries, precision, FDR, and base-rate context remain part of construct validation. Lift alone is not sufficient evidence.

## 9. Generated Reporting and Documentation

### 9.1 Manuscript package before snapshot

The snapshot must not render a stale manuscript package. The canonical command sequence builds `artifacts/manuscript_package` from the selected study directory before refreshing `docs/results_snapshot.md`.

The snapshot reads the generated Table 9 rather than independently reimplementing row selection. Selection logic has one owner.

### 9.2 Provenance display

The snapshot reproducibility section reports, from the study manifest:

- artifact generation time;
- Git commit and dirty state;
- config hash and input hash;
- `uv.lock` hash;
- pinned public-data as-of date;
- WRDS bridge source/version/extraction/hash fields when present; and
- component and claim-maturity status.

If `git_dirty=true`, the page says the run is non-canonical. It never hides or rewrites the flag.

### 9.3 Results and Discussion structure

`paper_plan.md` remains the design and claim contract. It contains Introduction, literature and gap, contributions, Materials and Methods, data construction and Mermaid flow, preprocessing/features, models, metric rationale, expected experiments, and evidence gates without freezing empirical numbers.

`results_snapshot.md` remains generated and follows the six planned experiments. It adds a conventional Discussion spine:

- answer to each research question;
- comparison with prior literature at the level supported by verified citations;
- accounting and institutional interpretation;
- selection/visibility interpretation;
- generalizability;
- limitations and future work; and
- a claim ledger distinguishing reportable, supporting, diagnostic, and deferred evidence.

Every current generated figure and table remains rendered inline with claim, evidence, and boundary notes.

### 9.4 FAQ and stable prose

Remove volatile empirical result tables from `docs/faq.md`. The FAQ explains the design and links to the generated results snapshot for current values. Historical conflict counts are labeled historical rather than current.

Across the plan, snapshot, FAQ, and manuscript, note/disclosure-breadth variables are described as entering the `all` feature set; there is no reported standalone text-family ablation.

### 9.5 Serena memories

Keep separate source and manuscript memories. Update them only after the clean run and manuscript build:

- source memory records the clean commit, manifest, primary specification, baseline, artifact inventory, and canonical commands;
- manuscript memory records the synchronized provenance date, PDF/package state, remaining author-input blockers, and truth hierarchy; and
- neither memory is allowed to claim current dirty paths or submission readiness from an older snapshot.

## 10. Reproducibility and Repository Hygiene

### 10.1 Dependency lock and file modes

Track `uv.lock` because the project is an executable research application and already hashes the lock in provenance.

Normalize tracked file modes to `100644` except files that are directly executable by design, notably `scripts/run_public_lake_full.sh`. Python scripts without shebangs remain non-executable and are invoked through Python.

Restore the manuscript README mode to `100644`. Mode cleanup is kept separate from empirical logic in Git history.

### 10.2 Replication archive

Add a standard-library-based packaging command that builds an ignored ZIP under `artifacts/reviewer_package/` from the exact clean study commit recorded in the manifest.

The archive includes:

- tracked source, configuration, tests, docs, and `uv.lock` from the study commit;
- a replication README with exact smoke, test, data-build, study, snapshot, and manuscript-package commands;
- sanitized study/public-lake provenance without user-specific absolute paths;
- generated manuscript-package tables, figures, narrative, and manifest; and
- source manifest metadata and hashes required to reacquire public inputs.

The archive excludes:

- `.env`, `.serena`, local virtual environments, caches, and build directories;
- the local detected-misstatement benchmark file;
- raw or normalized WRDS crosswalk data;
- full bronze, silver, gold, prediction, or proprietary data; and
- user names or local absolute paths.

An automated archive-content test asserts required and forbidden paths. Submission statements use present-tense `included` or `uploaded` language only after the archive exists and passes inspection.

### 10.3 Legacy/generated outputs

After verification, remove only transient outputs created by the revision, such as `.coverage`, `site/`, `__pycache__`, and temporary rendering directories. Existing historical empirical runs are labeled non-canonical in documentation but retained unless a separate deletion decision is approved.

## 11. Manuscript Revision and Sync Safety

Before touching the manuscript repository, create a recoverable Git object for the current 56-file working tree without clearing or overwriting it. Do not bulk-checkout, reset, or stash-pop user changes.

Synchronization rules:

1. preview generated table differences;
2. sync figures and provenance with the existing safe sync command;
3. do not run wholesale `sync-table-tex CONFIRM=1` against curated manuscript tables;
4. hand-merge empirical cells and notes from generated source tables into curated `tables/*.tex`;
5. revise `main.tex` after the generated artifacts are final; and
6. regenerate the flat submission package only after root manuscript verification.

The revision updates:

- all stale empirical values and the false claim that `all` leads within every label;
- exact sample vintage, windows, model parameters, weighting, seeds, preprocessing, and bootstrap scope;
- primary-versus-sensitivity language;
- visibility/history baseline results;
- sample attrition;
- event-time concentration, aggregation sensitivity, timing/drift, peer fit/skip status, and DML null interpretation;
- the duplicate calibration sentence and implementation-facing labels;
- data availability, reproducibility, cover-letter, highlights, README, and checklist wording; and
- table/figure legibility where the current 47-page PDF is too dense.

Author names, affiliations, correspondence details, funding, acknowledgements, named CRediT roles, competing-interest confirmation, AI-declaration approval, and self-citation anonymization remain explicit human-input blockers. The paper may be evidence-current while still not upload-ready.

## 12. Execution Sequence

The implementation sequence is:

1. preserve manuscript worktree recoverability;
2. implement source behavior with failing tests first;
3. run targeted and full source quality gates;
4. commit all study-affecting source/config/lock changes so the source tree is clean;
5. rebuild the public lake once from cached bronze at the pinned date;
6. rebuild linkage once;
7. run one full peer-enabled study into `artifacts/full_with_peer`;
8. verify the study manifest is clean and matches the committed code/config/input hashes;
9. build the manuscript package, snapshot, and replication archive;
10. selectively sync and revise the manuscript;
11. compile and visually inspect root and flat-package PDFs;
12. perform reviewer re-review; and
13. run ARS Stage 4.5 integrity verification from scratch.

No final empirical number is written into manuscript prose before step 8 succeeds.

## 13. Error Handling

- Missing or invalid Form AP ZIP member: fail the data build; do not use stale CSV.
- Primary public specification absent from results: fail public summary/package generation.
- Primary alignment key missing or duplicated: fail construct packaging.
- Dirty study manifest: label run non-canonical and block manuscript finalization.
- Missing required manuscript artifact: fail sync/package generation.
- Replication archive contains a forbidden path or lacks a required file: fail archive validation.
- PDF build error, undefined citation/reference, missing figure/table, or visual clipping: block packaging.
- Unverified reference, statistic, or claim: mark unverified and block ARS Stage 4.5.
- Missing author metadata: allow anonymous evidence-current PDF, but block upload-readiness claims.

## 14. Verification Strategy

All behavioral changes follow red-green-refactor TDD.

Required focused tests cover:

- stale CSV versus newer Form AP ZIP precedence;
- primary public-spec validation and summary fields;
- exact `visibility_history` inclusion/exclusion rules;
- primary-only Table 3/Figure 1 aggregation and excluding-2020 sensitivity;
- sequential sample attrition;
- raw versus encoded DML control counts;
- exact primary alignment selection in the presence of higher-lift distractors;
- bootstrap inclusion of primary alignment rows;
- snapshot provenance visibility and single-owner Table 9 routing;
- FAQ absence of volatile values;
- replication archive required/forbidden paths; and
- consistent pinned as-of dates and documentation anchors.

Repository gates:

- targeted pytest commands for each red-green cycle;
- full `just check` with the external project environment;
- clean public-lake manifest inspection;
- full study manifest and component-status inspection;
- generated artifact inventory and source/manuscript cross-check;
- LaTeX compilation, log scan, and page rendering;
- flat-package independent compilation; and
- 100% citation/data/claim verification plus the seven-mode AI research failure checklist at ARS Stage 4.5.

External-model reviewer comments remain advisory. Any DeepSeek or Qwen re-review finding must be verified against the clean code, artifacts, and manuscript before it becomes a revision requirement.

## 15. Completion Criteria

The revision is complete only when all of the following are true:

1. source tests, lint, and strict docs build pass;
2. Form AP normalization is archive-current and regression-tested;
3. the public lake and full study were generated from clean committed code at the pinned vintage;
4. the study manifest reports `git_dirty=false` and the expected commit/config/input/lock hashes;
5. the primary public and construct-alignment specifications are present exactly once and are disclosed as revision-frozen choices;
6. Table 3/Figure 1, visibility baseline, sample attrition, DML dimensions, Table 9, snapshot, and FAQ satisfy this design;
7. every manuscript number and empirical claim traces to the clean artifacts;
8. the manuscript and flat package compile without undefined citations/references or missing assets and pass visual inspection;
9. the anonymized replication archive exists and passes content validation;
10. source and manuscript Serena memories describe the verified current state;
11. ARS Stage 4.5 passes from scratch with zero unresolved integrity issues; and
12. any remaining missing author metadata is explicitly reported as an upload blocker rather than silently treated as complete.
