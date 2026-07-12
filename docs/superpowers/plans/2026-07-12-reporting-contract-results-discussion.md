# Reporting Contract and Results/Discussion Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the public-study artifacts, generated Results and Discussion, paper plan, manuscript package, verifier, and manuscript state the same bounded empirical claims, then regenerate one canonical study and PDF.

**Architecture:** Empirical facts remain owned by the public-cascade and DML artifacts. The manuscript package copies and validates those facts and declares one display owner for each of its 16 tables and 5 figures. The generated snapshot renders those owners once inside six experiment sections; prose and the manuscript consume the same contract without re-deriving headline results.

**Tech Stack:** Python 3.13, pandas, XGBoost, pytest, JSON manifests, Markdown/MkDocs, LaTeX, DuckDB-backed public lake.

## Global Constraints

- Preserve the frozen public primary specification: `feature_set=all`, `train_window=expanding`.
- Preserve legacy artifact keys and model behavior; paper-facing labels may change, artifact keys may not.
- Add no dependency and no speculative abstraction. Reuse current summaries, manifests, table writers, and validators.
- `oversight` displays as `Prior-filing history (legacy artifact key: oversight)` and currently means `prior_filing_count`, not PCAOB inspection.
- The sample field `is_domestic_us_gaap_proxy` validates neither FPI status, domicile, nor US GAAP.
- PCAOB inspection archives are provenance inputs, not current Gold/model predictors.
- Opacity DML is an adjusted-association diagnostic only when at least one required outcome is actually fit; all-skipped evidence is deferred.
- The partner nonadministrative-amendment statistic must declare the post-year-proxy, uncensored public-model-panel scope and must be computed, never hard-coded.
- `docs/results_snapshot.md` remains generated. Edit `scripts/refresh_results_snapshot.py`, not the generated page, before the canonical study.
- Each package table/figure appears exactly once in Results and Discussion. Tables 10/11 remain manuscript-only methods/literature tables.
- Do not overwrite curated manuscript `tables/*.tex`; use `SYNC_NEW_TABLE_TEX=0` and merge table changes selectively.
- The final lake, study, package, verifier attestation, and current source HEAD must share one clean commit. The report child commit may change only the snapshot plus five PNG files.
- External reviewers generate hypotheses only. Verify every Spark, DeepSeek, and Qwen finding locally before revising.

---

### Task 1: Add the public reporting-boundary contract

**Files:**
- Modify: `src/public_cascade.py`
- Test: `tests/test_public_cascade_interfaces.py`

**Interfaces:**
- Consumes: `_infer_feature_families(panel)` and the filtered, uncensored model panel.
- Produces: `feature_family_summary[*].display_name`, `.model_eligible_features`, `.reported_as_standalone`, and `summary.reporting_boundaries` with schema `public-reporting-boundaries-v1`.

- [x] **Step 1: Write failing tests for family display metadata and reporting boundaries**

Assert the existing end-to-end fixture produces:

```python
oversight = summary["feature_family_summary"]["oversight"]
assert oversight["display_name"] == "Prior-filing history (legacy artifact key: oversight)"
assert oversight["model_eligible_features"] == ["prior_filing_count"]
assert oversight["reported_as_standalone"] is True

proxy = summary["reporting_boundaries"]["sample_proxy"]
assert proxy["artifact_field"] == "is_domestic_us_gaap_proxy"
assert proxy["validates_fpi_status"] is False
assert proxy["validates_domicile"] is False
assert proxy["validates_us_gaap"] is False

inspection = summary["reporting_boundaries"]["pcaob_inspection_predictors"]
assert inspection["inspection_event_joined_to_gold"] is False
assert inspection["model_eligible_features"] == []
```

Add zero and varied partner fixtures and assert computed `rows_evaluated`, `nonmissing_rows`, `nonzero_rows`, `n_distinct_nonmissing`, `minimum`, `maximum`, `is_constant_zero`, `total_equals_item_402_rows`, and `total_equals_item_402_for_all_rows`.

- [x] **Step 2: Run the focused tests on parent `8a613a0` and record RED**

Run:

```bash
PATH=/Users/tycheng/.venvs/reporting-risk-cascade/bin:$PATH \
pytest -q tests/test_public_cascade_interfaces.py -k 'reporting_boundar or feature_family'
```

Expected: failure because the new keys are absent while existing summary/model tests remain green.

- [x] **Step 3: Add the minimal computed contract**

Reuse `families` and the filtered `panel`. Extend each existing family summary rather than creating another family map. Add only this new top-level object:

```python
summary["reporting_boundaries"] = {
    "schema_version": "public-reporting-boundaries-v1",
    "sample_proxy": {
        "artifact_field": "is_domestic_us_gaap_proxy",
        "display_name": "10-K/10-K/A with no observed same-year FPI-form proxy",
        "definition": (
            "selected 10-K or 10-K/A with no observed 20-F, 40-F, or 6-K "
            "mapped to the same issuer fiscal year"
        ),
        "validates_fpi_status": False,
        "validates_domicile": False,
        "validates_us_gaap": False,
    },
    "pcaob_inspection_predictors": {
        "inspection_event_joined_to_gold": False,
        "model_eligible_features": [],
        "excluded_availability_markers": ["source_available_pcaob_inspections"],
    },
    "partner_nonadministrative_amendment": partner_boundary,
}
```

The partner scope string is `post-year-proxy uncensored public-model panel`. Do not add Bronze provenance or inspection row counts here.

- [x] **Step 4: Run focused and full interface tests, Ruff, format, and diff checks**

Run the test file, `ruff check` on the changed files, `ruff format --check` on the changed files, and `git diff --check`.

- [x] **Step 5: Commit**

Commit message: `feat(reporting): expose public claim boundaries`.

---

### Task 2: Make DML maturity artifact-derived

**Files:**
- Modify: `src/public_cascade.py`
- Modify: `scripts/run_study.py`
- Test: `tests/test_public_cascade_interfaces.py`
- Test: `tests/test_provenance.py`

**Interfaces:**
- Consumes: `public_opacity_dml.csv`, its metadata, and the required outcome order `comment_thread`, `amendment`, `8k_402`.
- Produces: public summary/component `opacity_dml_evidence` and study-manifest `claim_maturity.opacity_dml`.

- [x] **Step 1: Write RED tests for all-fit, partly fit, and all-skipped evidence**

Require exact ordered outcome coverage, raw `status_by_outcome`, `fit_outcomes`, and:

```python
assert maturity == ("diagnostic" if fit_outcomes else "deferred")
```

Each non-fit outcome remains `deferred`; a complete public component alone is insufficient.
For disabled DML, represent all three required outcomes as raw status `disabled` so the
contract remains complete and `fit_outcomes` is empty. Missing/legacy evidence fails closed.

- [x] **Step 2: Run focused tests on the Task 1 commit and record RED**

Expected: current `_claim_maturity` marks every complete public component diagnostic.

- [x] **Step 3: Implement one authority chain**

Write evidence once from the in-memory DML rows/meta into the public summary, copy it into
`components.public_cascade.opacity_dml_evidence`, and make `_claim_maturity(components)`
consume that copy. Validate the non-disabled outcome sequence exactly as
`["comment_thread", "amendment", "8k_402"]`; preserve raw skip statuses and define
`fit_outcomes` only where status is exactly `fit`. Do not add package-layer maturity
derivation in Task 2. Task 3 will copy and attest upstream evidence and maturity; existing
raw-CSV reconstruction of Table 12 remains a display-integrity path.

- [x] **Step 4: Run focused tests, full related suites, Ruff/format/diff, and commit**

Commit message: `fix(reporting): derive DML maturity from fitted outcomes`.

---

### Task 3: Version and verify the manuscript reporting contract

**Files:**
- Modify: `scripts/build_manuscript_package.py`
- Modify: `scripts/verify_canonical_run.py`
- Modify: `tests/canonical_fixture.py`
- Test: `tests/test_manuscript_package.py`
- Test: `tests/test_canonical_run.py`
- Test: `tests/test_reviewer_package.py`

**Interfaces:**
- Consumes: exact public boundaries, extended family summary, DML evidence/maturity, and the existing 16 table/5 figure package.
- Produces: `manuscript-package-v2`, canonical verifier version 5, and one `reporting_contract` object.

- [x] **Step 1: Write RED validation/mutation tests**

Require exact-copy public boundaries and family metadata, artifact-derived DML evidence, and this ownership map:

```python
ARTIFACT_OWNERSHIP = {
    "reproducibility": {"tables": ["table_01"], "figures": []},
    "experiment_1": {"tables": ["table_05", "table_06"], "figures": ["figure_03"]},
    "experiment_2": {"tables": [], "figures": []},
    "experiment_3": {"tables": ["table_12"], "figures": []},
    "experiment_4": {"tables": ["table_02", "table_18"], "figures": []},
    "experiment_5": {
        "tables": ["table_03", "table_04", "table_07", "table_13", "table_14", "table_17"],
        "figures": ["figure_01", "figure_02", "figure_04"],
    },
    "experiment_6": {
        "tables": ["table_08", "table_09", "table_15", "table_16"],
        "figures": ["figure_05"],
    },
}
```

Flattened keys must equal the package artifact keys exactly with no duplicate. The exact
contract shape is:

```python
reporting_contract = {
    "reporting_boundaries": public_summary["reporting_boundaries"],
    "feature_family_summary": public_summary["feature_family_summary"],
    "opacity_dml_evidence": public_component["opacity_dml_evidence"],
    "claim_maturity": study_manifest["claim_maturity"],
    "artifact_ownership": ARTIFACT_OWNERSHIP,
}
```

Require summary evidence to equal the component copy before packaging. Mutation of proxy
flags, oversight features, inspection predictor status, partner variation, ownership, DML
evidence, or DML maturity must fail verification. Include valid diagnostic and valid
all-skipped/deferred fixtures.

- [x] **Step 2: Implement the smallest versioned package contract**

Set `MANUSCRIPT_PACKAGE_SCHEMA = "manuscript-package-v2"`; keep
`ATTESTATION_SCHEMA = "canonical-attestation-v1"` and set only
`VERIFIER_VERSION = "5"`. Copy upstream facts without recomputation. Add
`public_cascade_task_status.csv`, `public_opacity_dml.csv`, and
`public_opacity_dml_meta.json` to the package's early required-artifact list. Update the
shared canonical fixture and the independent package-manifest fixture.

- [x] **Step 3: Make verifier v5 reconstruct and compare the same contract**

Keep all existing canonical gates. Add only exact contract reconstruction/comparison and ownership completeness checks.
The package-manifest hash already attests the contract, so do not duplicate it into the
attestation. Replace the hard-coded diagnostic DML gate with consistency against the
artifact-derived study maturity. Reviewer production code remains unchanged; add ZIP
readback assertions for package v2/contract and verifier version 5.

- [x] **Step 4: Run package/canonical/reviewer tests, full suite, Ruff/format/diff, and commit**

Commit message: `feat(reporting): attest package claim contract`.

---

### Task 4: Align package labels and evidence caveats

**Files:**
- Modify: `scripts/build_manuscript_package.py`
- Test: `tests/test_manuscript_package.py`

**Interfaces:**
- Consumes: the Task 3 reporting contract and existing package tables/figures/narrative.
- Produces: safe paper-facing display labels and artifact-derived DML/partner caveats while preserving raw CSV keys.

- [x] **Step 1: Write RED display and narrative tests**

Require Tables 4/14 to display family names while their CSV `Feature_Set` keys remain raw.
Require Figure 2 fold dots to remain after tick-label substitution. Require Table 17 to
describe the observed same-year FPI-form indicator and Table 18 to display the exact sample
proxy label. Require diagnostic/deferred DML and constant/varied partner narrative cases;
forbid `highest mean PR-AUC`, `leads on mean PR-AUC`, `winner`, and `leader` prose.

- [x] **Step 2: Add one scalar display-name helper**

Use the upstream `feature_family_summary` display name in Markdown/LaTeX and plot ticks only.
Preserve raw keys for CSVs and Figure 2 fold-row matching. Table 17 owns the observed
`issuer_has_fpi_form_year` indicator and must not reuse the sample-proxy label. Table 18 maps
its raw stage `domestic_us_gaap_proxy` to the contract display name only in Markdown/LaTeX;
the contract artifact field is `is_domestic_us_gaap_proxy` and is not the raw stage key.

- [x] **Step 3: Generate caveats from the contract**

Build DML prose from all four evidence fields plus aggregate maturity. Build the partner
caveat from scope/count/range/constant/equality fields. Remove ranking language while
retaining the peer transfer/estimand boundary.

- [x] **Step 4: Run package tests, full related suites, Ruff/format/diff, and commit**

Commit message: `fix(reporting): align package labels and caveats`.

---

### Task 5: Restructure the plan and generated Results and Discussion

**Files:**
- Modify: `docs/paper_plan.md`
- Modify: `scripts/refresh_results_snapshot.py`
- Modify: `tests/test_docs.py`

`docs/faq.md` requires no change: its links target the page rather than removed gallery
fragments. Do not add a legacy package-v1 compatibility branch.

**Interfaces:**
- Consumes: package `reporting_contract`, its 16 Markdown tables and 5 PNG figures, and dynamic experiment-only artifacts.
- Produces: a generated `# Results and Discussion` page aligned with `paper_plan.md`.

- [x] **Step 1: Write RED structure/ownership/wording tests**

Assert six ordered experiment sections, an interpretation subsection for each, a conventional
Discussion spine, provenance last, and every package artifact exactly once in its declared
owner section. Use a package-v2 fixture with the reporting contract; the checked-in historical
study/package is v1 and cannot prove this structure. Assert absence of gallery headings,
`Highest equal-task`, `Sellable claim`, paper-facing `Max config PR-AUC`, `Domestic US GAAP
only`, and inspection-as-predictor prose. Static tests must not require the checked-in generated
snapshot to change before Task 6.

- [x] **Step 2: Tighten `paper_plan.md` without rewriting its valid spine**

Keep Introduction, Materials and Methods, Mermaid preprocessing flow, models, metric rationale,
six expected experiments, and reproducibility contract. Make the Introduction explicitly cover
overview and motivation, prior literature and current evidence, the gap, research question, and
bounded contributions. Make Materials and Methods explicitly cover institutional/data context,
preprocessing/pretreatment/features, ours and benchmark models, and metric-selection rationale.
Move Tables 4/14 from Experiment 2 to Experiment 5; make Experiment 2 dynamic-only; mark DML
diagnostic only when at least one required outcome is fit; add source/feature readiness to
Experiment 4; keep only `all + expanding` as headline; state the five claim boundaries verbatim.

- [x] **Step 3: Rewrite only the snapshot assembly layer**

Keep existing data loaders/calculations that do not duplicate package displays. Replace the
gallery assembly with singular owner-directed `render_table(key)` and `render_figure(key)` calls
driven by `manifest.reporting_contract.artifact_ownership`. Keep dynamic benchmark-panel,
window, break, feature-importance, readiness/skip, per-task peer, exploratory-maxima,
aggregation, co-occurrence, and event-time results in their experiments. Remove raw displays
duplicated by package owners. Put provenance last and render Table 1 there.

- [x] **Step 4: Run docs tests against fixture-generated output, build MkDocs strict, full suite, Ruff/format/diff, and commit**

Do not regenerate the tracked `docs/results_snapshot.md` from the historical package v1. Task 6
owns the first real package-v2 snapshot refresh and the constrained report child commit.

Commit message: `docs: align plan and generated results discussion`.

---

### Task 6: Produce the final canonical empirical/report chain

**Files:** generated/ignored artifacts only until the six-path report commit.

**Interfaces:**
- Consumes: clean Task 5 commit, accepted Run G/H inventories, cached Bronze, raw benchmark, and WRDS crosswalk input.
- Produces: Run I, one linkage, full peer study, package v2, generated snapshot, verifier attestation, report child commit, and reviewer ZIP.

- [ ] **Step 1: Run full source gates and commit any review fixes before data execution**
- [ ] **Step 2: Fresh-build Run I at the clean Task 5 commit**
- [ ] **Step 3: Prove Run I scientific files, schemas, counts, and semantic profiles equal accepted G/H; only commit-bound provenance may differ**
- [ ] **Step 4: Archive the old `artifacts/full_with_peer` plus its bound crosswalk/package/attestation without deletion**
- [ ] **Step 5: Run `uv run python scripts/build_linkage_bridge.py` exactly once**
- [ ] **Step 6: Run the canonical study exactly once**

```bash
just task study raw artifacts/full_with_peer \
  extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
```

- [ ] **Step 7: Build package/snapshot and run `just verify-canonical`**
- [ ] **Step 8: Commit only `docs/results_snapshot.md` plus its five PNGs as the direct report child**
- [ ] **Step 9: Build and validate the anonymized reviewer archive**

---

### Task 7: Synchronize, review, and finalize the manuscript

**Files:**
- Modify selectively in sibling repo: `main.tex`, curated `tables/*.tex`, figures/provenance, README/highlights/cover letter/checklists as evidence requires.
- Preserve all pre-existing manuscript worktree changes.

- [ ] **Step 1: Run safe artifact sync**

```bash
SYNC_NEW_TABLE_TEX=0 make sync-artifacts \
  MANUSCRIPT_PACKAGE=../reporting-risk-cascade/artifacts/manuscript_package
```

- [ ] **Step 2: Hand-merge generated table evidence and revise six-experiment prose**
- [ ] **Step 3: Compile root and flat-package PDFs; scan logs and render pages for visual inspection**
- [ ] **Step 4: Run the ARS pre-review integrity/failure-mode gate**
- [ ] **Step 5: Run exactly two Spark read-only reviewers in parallel, then DeepSeek and Qwen on the same sanitized review package**
- [ ] **Step 6: Verify/deduplicate every finding locally, revise once, and perform focused re-review**
- [ ] **Step 7: Run ARS Stage 4.5 from scratch; zero unresolved integrity issues are required**
- [ ] **Step 8: Onboard separate source/manuscript Serena memories in topic subfolders**
- [ ] **Step 9: Remove only proven transient/merged legacy material; preserve non-regenerable historical empirical runs**
- [ ] **Step 10: Run final source/manuscript/package verification and issue a readiness verdict**

## Self-Review

- Spec coverage: all user-requested data/model/result truth checks, docs structure, canonical execution, manuscript review, cross-model review, Serena synchronization, and legacy audit have an owner.
- Placeholder scan: no implementation step is deferred; every later empirical value is intentionally generated by Task 6 rather than frozen in this plan.
- Type/contract consistency: Task 1 owns public facts; Task 2 owns DML maturity; Task 3 copies/attests; Task 4 labels; Task 5 renders; Tasks 6/7 regenerate and review.
