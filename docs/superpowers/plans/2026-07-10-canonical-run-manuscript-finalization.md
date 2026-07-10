# Canonical Run, Manuscript, and Integrity Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce one clean archive-current study, propagate only its declared evidence into the manuscript, obtain two advisory second-model reviews, complete a fresh ARS integrity pass, and synchronize both Serena memories to verifiable artifacts.

**Architecture:** The source study manifest is the empirical authority, the generated manuscript package is the reporting boundary, and the manuscript is a selective editorial consumer. Preserve the current manuscript worktree and old empirical outputs before mutation. Run the expensive data and study pipeline once from a clean committed source tree; then perform reporting, manuscript, review, and integrity stages in order.

**Tech Stack:** Git, Bash, Python 3.13, uv, just, DuckDB, pytest, MkDocs, LaTeX/latexmk, biber, Poppler, DeepSeek reviewer proxy, Qwen reviewer proxy, Academic Research Suite, Serena.

## Global Constraints

- Complete `2026-07-10-evidence-pipeline-implementation.md` and `2026-07-10-reporting-reproducibility-implementation.md` first.
- Start this plan only from the real integrated source root, never an implementation worktree. At the start of each execution task, resolve `SOURCE_ROOT=$(git rev-parse --show-toplevel)` and `MANUSCRIPT_ROOT=$(cd "$SOURCE_ROOT/../reporting-risk-cascade-manuscript" && pwd)` when either path is needed.
- Use `superpowers:verification-before-completion` before any passing or completion claim.
- Do not clear or reset the manuscript's existing 56 tracked modifications. Anchor them in Git before editing.
- Do not delete historical results. Store them under ignored, dated `artifacts/historical/` storage and retain hashes.
- Perform one full fresh public-lake build and one peer-enabled study after source code is committed and clean.
- Freeze `as_of_date=2026-07-06`, fiscal years 2011-2024, 365-day outcomes, `all + expanding`, and the two approved construct-alignment keys.
- Require `git_dirty=false` for both source study and public lake; the study manifest commit must equal `STUDY_COMMIT`.
- Never bulk-overwrite manuscript table TeX. Preview, then merge accepted changes with `apply_patch`.
- Treat DeepSeek and Qwen as advisory. Verify every proposed correction locally before accepting it.
- Never send raw benchmark data, WRDS rows, crosswalks, secrets, paths, author identities, or the full repository to an external reviewer.
- Do not upload or submit the paper. Stop with locally verified deliverables and author-only blockers.
- Do not add horizons, severity labels, economic outcomes, international samples, causal claims, or estimators.
- Execute every multi-command Bash block as one error-strict transaction with `set -euo pipefail`; wrap expected-no-match `rg` checks in explicit `if ...; then exit 1; fi` guards so an early failure cannot be masked by a later command.

---

### Task 1: Anchor the current manuscript worktree without clearing it

**Repository:** `../reporting-risk-cascade-manuscript`

**Files:**
- Read only: all currently modified manuscript files
- Create through Git object storage: `refs/revision-backups/2026-07-10-pre-canonical-revision`

- [ ] **Step 1: Confirm the exact boundary**

```bash
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
git -C "$MANUSCRIPT" rev-parse --show-toplevel
git -C "$MANUSCRIPT" rev-parse HEAD
git -C "$MANUSCRIPT" status --short
test -z "$(git -C "$MANUSCRIPT" ls-files --others --exclude-standard)"
test -z "$(git -C "$MANUSCRIPT" diff --cached --name-only)"
test "$(git -C "$MANUSCRIPT" status --porcelain=v1 | wc -l | tr -d ' ')" = "56"
```

Expected: the real manuscript root, current base commit, 56 tracked modifications, and no untracked file omitted from the backup contract.

- [ ] **Step 2: Create a stash commit without changing the worktree**

```bash
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
BACKUP_REF="refs/revision-backups/2026-07-10-pre-canonical-revision"
BACKUP_COMMIT="$(git -C "$MANUSCRIPT" stash create "pre-canonical manuscript revision 2026-07-10")"
test -n "$BACKUP_COMMIT"
git -C "$MANUSCRIPT" update-ref "$BACKUP_REF" "$BACKUP_COMMIT"
test "$(git -C "$MANUSCRIPT" rev-parse "$BACKUP_REF")" = "$BACKUP_COMMIT"
git -C "$MANUSCRIPT" diff --quiet "$BACKUP_COMMIT" -- .
git -C "$MANUSCRIPT" status --short
```

Expected: the reference resolves, the diff check succeeds, and all worktree modifications remain. Never use `git stash push`, `git reset`, `git checkout --`, or `git restore`.

- [ ] **Step 3: Put these recovery facts in the execution handoff**

Record the base HEAD, `BACKUP_REF`, and `BACKUP_COMMIT`. The recovery inspection command is:

```bash
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
BACKUP_REF="refs/revision-backups/2026-07-10-pre-canonical-revision"
git -C "$MANUSCRIPT" show "$BACKUP_REF"
```

---

### Task 2: Move pre-revision outputs into history and copy the old issuer panel

**Repository:** source repository

**Files:**
- Read: `artifacts/full_with_peer/**`
- Read: `artifacts/full_full_raw/**`
- Read: `artifacts/public_cascade_smoke/**`
- Read: `artifacts/logs/**`
- Read: `artifacts/manuscript_package/**`
- Read: `${PUBLIC_LAKE_DIR}/gold/issuer_origin_panel.parquet`
- Create: `artifacts/historical/2026-07-06-pre-revision/**`

- [ ] **Step 1: Resolve and validate sources**

```bash
PUBLIC_LAKE_DIR="$(uv run python -c 'from src import PUBLIC_LAKE_DIR; print(PUBLIC_LAKE_DIR)')"
test -f "$PUBLIC_LAKE_DIR/gold/issuer_origin_panel.parquet"
test -d artifacts/full_with_peer
test -d artifacts/full_full_raw
test -d artifacts/public_cascade_smoke
test -d artifacts/logs
test -d artifacts/manuscript_package
```

- [ ] **Step 2: Move active artifact directories into a new ignored history directory**

```bash
PUBLIC_LAKE_DIR="$(uv run python -c 'from src import PUBLIC_LAKE_DIR; print(PUBLIC_LAKE_DIR)')"
HISTORICAL="artifacts/historical/2026-07-06-pre-revision"
test ! -e "$HISTORICAL"
mkdir -p "$HISTORICAL/public_lake_gold"
mv artifacts/full_with_peer "$HISTORICAL/full_with_peer"
mv artifacts/full_full_raw "$HISTORICAL/full_full_raw"
mv artifacts/public_cascade_smoke "$HISTORICAL/public_cascade_smoke"
mv artifacts/logs "$HISTORICAL/logs"
mv artifacts/manuscript_package "$HISTORICAL/manuscript_package"
cp -p "$PUBLIC_LAKE_DIR/gold/issuer_origin_panel.parquet" \
  "$HISTORICAL/public_lake_gold/issuer_origin_panel.parquet"
test ! -e artifacts/full_with_peer
test ! -e artifacts/full_full_raw
test ! -e artifacts/public_cascade_smoke
test ! -e artifacts/logs
test ! -e artifacts/manuscript_package
```

Moving rather than copying guarantees the canonical study/package start in absent output directories and cannot inherit stale files. The historical copies remain recoverable under the dated directory.

- [ ] **Step 3: Hash and freeze the archive**

```bash
HISTORICAL="artifacts/historical/2026-07-06-pre-revision"
find "$HISTORICAL" -type f ! -name SHA256SUMS -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 > "$HISTORICAL/SHA256SUMS"
shasum -a 256 -c "$HISTORICAL/SHA256SUMS"
chmod -R a-w "$HISTORICAL"
git status --short
```

Expected: hashes pass and Git is unaffected because `artifacts/` is ignored.

---

### Task 3: Establish the clean empirical commit

**Repository:** real integrated source repository root

- [ ] **Step 1: Confirm prerequisite commits and contracts**

```bash
git log --oneline --decorate -20
git status --short
rg -n '2026-07-06|primary_specification|visibility_history|primary_alignment' \
  config src scripts docs tests
```

- [ ] **Step 2: Run the full pre-run gate**

```bash
uv lock --check
just check
uv run --group docs mkdocs build --strict --clean
git diff --check
test -z "$(git status --short)"
```

- [ ] **Step 3: Freeze the code identity**

```bash
STUDY_COMMIT="$(git rev-parse HEAD)"
test -n "$STUDY_COMMIT"
printf '%s\n' "$STUDY_COMMIT"
```

Do not amend, rebase, or create another source commit until the study and manuscript package are generated and verified.

---

### Task 4: Run one full data build and gate model-panel freshness

**Generated files:** `${PUBLIC_LAKE_DIR}/{bronze,silver,gold}/**`

- [ ] **Step 1: Confirm private inputs and disk boundary**

```bash
DATA_DIR="$(uv run python -c 'from src import DATA_DIR; print(DATA_DIR)')"
just paths
test -f "${DATA_DIR}/raw/raw_dataset_misstatement.parquet"
test -f "${DATA_DIR}/linkage/raw_only/gvkey_cik_year.csv"
df -h "${DATA_DIR}"
```

Do not print input contents.

- [ ] **Step 2: Build the public lake once**

```bash
just data full fresh
```

Do not run `just full`, a smoke build, or a second fresh build unless this command fails before publishing gold. Diagnose any failure with `superpowers:systematic-debugging`.

- [ ] **Step 3: Compare old and new schemas and 2011-2024 rows**

```bash
set -euo pipefail
PUBLIC_LAKE_DIR="$(uv run python -c 'from src import PUBLIC_LAKE_DIR; print(PUBLIC_LAKE_DIR)')"
OLD_PANEL="artifacts/historical/2026-07-06-pre-revision/public_lake_gold/issuer_origin_panel.parquet"
NEW_PANEL="$PUBLIC_LAKE_DIR/gold/issuer_origin_panel.parquet"
export OLD_PANEL NEW_PANEL
uv run python - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import duckdb

old_path = Path(os.environ["OLD_PANEL"])
new_path = Path(os.environ["NEW_PANEL"])
con = duckdb.connect()
con.read_parquet(str(old_path)).create_view("old_panel")
con.read_parquet(str(new_path)).create_view("new_panel")
old_columns = {row[0] for row in con.execute("DESCRIBE old_panel").fetchall()}
new_columns = {row[0] for row in con.execute("DESCRIBE new_panel").fetchall()}
if old_columns != new_columns:
    print(
        {
            "added_columns": sorted(new_columns - old_columns),
            "removed_columns": sorted(old_columns - new_columns),
        }
    )
    raise SystemExit("model-panel schema changed; diagnose before fitting models")
columns = sorted(old_columns)
if "fiscal_year" not in columns:
    raise SystemExit("fiscal_year is missing from the model-panel schema")
quoted = ", ".join('"' + name.replace('"', '""') + '"' for name in columns)
diff_query = f"""
WITH
old_sample AS (SELECT {quoted} FROM old_panel WHERE fiscal_year BETWEEN 2011 AND 2024),
new_sample AS (SELECT {quoted} FROM new_panel WHERE fiscal_year BETWEEN 2011 AND 2024),
old_only AS (SELECT * FROM old_sample EXCEPT ALL SELECT * FROM new_sample),
new_only AS (SELECT * FROM new_sample EXCEPT ALL SELECT * FROM old_sample)
SELECT 'old_only' AS difference_side, * FROM old_only
UNION ALL
SELECT 'new_only' AS difference_side, * FROM new_only
"""
difference_rows = con.execute(
    f"SELECT count(*) FROM ({diff_query}) AS differences"
).fetchone()[0]
print({"schema_columns": len(columns), "symmetric_difference_rows": difference_rows})
if difference_rows:
    comparison_path = Path(
        "artifacts/panel_comparison/2011_2024_difference.parquet"
    )
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(diff_query).write_parquet(str(comparison_path))
    def digest(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    facts = {
        "status": "verified_freshness_correction",
        "old_panel_sha256": digest(old_path),
        "new_panel_sha256": digest(new_path),
        "symmetric_difference_rows": int(difference_rows),
    }
    acceptance_path = comparison_path.parent / "acceptance.json"
    print({"difference_artifact": str(comparison_path), **facts})
    if not acceptance_path.is_file():
        raise SystemExit(
            "2011-2024 model panel changed; diagnose and create a matching "
            "acceptance.json only for a verified freshness correction"
        )
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    if any(acceptance.get(key) != value for key, value in facts.items()):
        raise SystemExit("panel-change acceptance does not match current hashes/count")
    if not str(acceptance.get("evidence", "")).strip():
        raise SystemExit("panel-change acceptance lacks evidence")
    print({"panel_change": "accepted_verified_freshness_correction"})
PY
```

Expected: identical schema and either zero symmetric-difference rows or an
explicitly accepted, hash-matched verified freshness correction.

- [ ] **Step 4: Stop and diagnose any mismatch before model fitting**

On a mismatch, use `superpowers:systematic-debugging` and inspect the generated
ignored `artifacts/panel_comparison/2011_2024_difference.parquet`. If it is
transformation drift, fix and commit source, rebuild the lake, and rerun Step 3.
If it is solely the verified archive-first freshness correction, create
`artifacts/panel_comparison/acceptance.json` with `apply_patch`, copying the
exact status/hash/count values printed by Step 3 and adding a nonempty `evidence`
field with the Form AP archive/member hashes and local diagnostic. Rerun Step 3;
it passes only when the acceptance matches the current panels exactly. No peer
study has run yet, preserving the approved one-run strategy.

---

### Task 5: Run the peer-enabled study exactly once and verify it

**Generated files:** `artifacts/full_with_peer/**`

- [ ] **Step 1: Run the complete study once**

```bash
set -euo pipefail
just task study raw artifacts/full_with_peer \
  extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
```

Expected: benchmark, public cascade, bridge, benchmark peer, public peer, construct alignment, DML, and manifests all complete.

- [ ] **Step 2: Verify clean provenance immediately**

```bash
set -euo pipefail
STUDY_COMMIT="$(git rev-parse HEAD)"
jq -e --arg commit "$STUDY_COMMIT" \
  '.repo_commit == $commit and .git_dirty == false' \
  artifacts/full_with_peer/study_run_manifest.json
jq -e \
  '.public_lake_provenance.as_of_date == "2026-07-06" and
   .public_lake_provenance.fresh_build == true and
   .public_lake_provenance.git_dirty == false and
   .public_lake_provenance.form_ap.source_kind == "verified_zip_member" and
   (.public_lake_provenance.form_ap.archive_sha256 | length) == 64 and
   (.public_lake_provenance.form_ap.member_sha256 | length) == 64' \
  artifacts/full_with_peer/study_run_manifest.json
```

If either check fails, label the run noncanonical and stop before manuscript sync.

- [ ] **Step 3: Reconcile expected sample/model/DML accounting with the clean run**

```bash
set -euo pipefail
jq '{
  sequential_attrition: [.sample_attrition[] | select(.task == "all") | .n_rows],
  primary_metric_rows,
  visibility_history_metric_rows,
  primary_specification,
  primary_specification_status
}' artifacts/full_with_peer/public_cascade/public_cascade_summary.json
uv run python - <<'PY'
import json
from pathlib import Path

import pandas as pd

root = Path("artifacts/full_with_peer/public_cascade")
dml = pd.read_csv(root / "public_opacity_dml.csv")
meta = json.loads((root / "public_opacity_dml_meta.json").read_text(encoding="utf-8"))
print(
    {
        "raw_controls": sorted(dml["n_raw_controls"].dropna().astype(int).unique()),
        "encoded_controls": sorted(
            dml["n_encoded_controls"].dropna().astype(int).unique()
        ),
        "definition": meta["n_controls_definition"],
    }
)
PY
```

Expected comparison values are `205652 -> 97027 -> 96827 -> 96733`, 27 primary task-year rows, 108 visibility/history task-year rows, and 60 raw versus 64 encoded controls. These numbers are not source-code constants: if the clean run differs, diagnose the input/hash or eligibility reason and treat the clean verified output as authoritative before manuscript wording.

---

### Task 6: Build package, snapshot, canonical gate, and report commit

**Files:** `artifacts/manuscript_package/**`, `docs/results_snapshot.md`, generator-produced `docs/assets/**`

- [ ] **Step 1: Build package through the snapshot recipe and verify it**

```bash
set -euo pipefail
just snapshot study_dir=artifacts/full_with_peer
just verify-canonical study_dir=artifacts/full_with_peer package_dir=artifacts/manuscript_package
```

Expected: `CANONICAL RUN VERIFIED`.

- [ ] **Step 2: Inspect the generated snapshot without rebuilding the package**

```bash
set -euo pipefail
git diff -- docs/results_snapshot.md docs/assets
uv run pytest -q tests/test_docs.py
uv run --group docs mkdocs build --strict --clean
```

Require: Table 3/Figure 1 use only `all + expanding`; Tables 4/14 are sensitivities; Table 9/Figure 5 contain the two declared rows; Table 18 shows sequential plus task-branch attrition; excluding-2020 is labeled sensitivity; maxima are exploratory/post-hoc; provenance exposes commits, dirty flags, hashes, date, Form AP hashes, and WRDS source.

- [ ] **Step 3: Commit generated reporting surfaces only**

```bash
set -euo pipefail
STUDY_COMMIT="$(jq -r '.repo_commit' artifacts/full_with_peer/study_run_manifest.json)"
git add docs/results_snapshot.md docs/assets
git diff --cached --check
git diff --cached --stat
git commit -m "docs: publish canonical results snapshot"
REPORT_COMMIT="$(git rev-parse HEAD)"
test "$REPORT_COMMIT" != "$STUDY_COMMIT"
printf 'study_commit=%s\nreport_commit=%s\n' "$STUDY_COMMIT" "$REPORT_COMMIT"
```

If `docs/assets` is unchanged, stage only the snapshot. Never stage ignored empirical payloads.

- [ ] **Step 4: Re-run the source gate**

```bash
set -euo pipefail
just check
uv run --group docs mkdocs build --strict --clean
test -z "$(git status --short)"
```

---

### Task 7: Build and validate the reviewer replication ZIP

**Generated file:** `artifacts/reviewer_package/reporting-risk-cascade-reviewer.zip`

- [ ] **Step 1: Build after `REPORT_COMMIT`**

```bash
just reviewer-package study_dir=artifacts/full_with_peer package_dir=artifacts/manuscript_package
```

- [ ] **Step 2: Verify both identities and exclusions**

```bash
set -euo pipefail
STUDY_COMMIT="$(jq -r '.repo_commit' artifacts/full_with_peer/study_run_manifest.json)"
REPORT_COMMIT="$(git rev-parse HEAD)"
unzip -p artifacts/reviewer_package/reporting-risk-cascade-reviewer.zip \
  provenance/package_manifest.json | jq \
  --arg study "$STUDY_COMMIT" --arg report "$REPORT_COMMIT" \
  -e '.study_commit == $study and .report_commit == $report'
if zipinfo -1 artifacts/reviewer_package/reporting-risk-cascade-reviewer.zip \
  | rg -n '\.(parquet|pkl)$|(^|/)\.env$|(^|/)\.serena/'; then
    echo "forbidden archive entry found" >&2
    exit 1
fi
```

- [ ] **Step 3: Scan extracted text for identity leakage**

```bash
set -euo pipefail
REVIEW_TMP="$(mktemp -d)"
trap 'rm -rf "$REVIEW_TMP"' EXIT
unzip -q artifacts/reviewer_package/reporting-risk-cascade-reviewer.zip -d "$REVIEW_TMP"
if rg -n '/Users/|OneDrive|tycheng|DEEPSEEK_API_KEY|DASHSCOPE_API_KEY|QWEN_API_KEY' \
  "$REVIEW_TMP"; then
    echo "identity or secret marker found" >&2
    exit 1
fi
```

The temporary directory is disposable generated output; never run removal commands against either repository.

---

### Task 8: Selectively synchronize generated evidence into the manuscript

**Repository:** `../reporting-risk-cascade-manuscript`

**Files:**
- Sync mechanically: `figures/figure_01_public_task_pr_auc.pdf` through `figure_05_construct_overlap_lift.pdf`
- Sync mechanically: `provenance/artifact_manifest.json`, `provenance/results_narrative.md`, `provenance/source_tables/**`
- Modify with `apply_patch`: every generated-table counterpart under `tables/` whose preview differs
- Review at minimum: `tables/table_{01,02,03,04,08,09,12,13,14,16,17}_*.tex`
- Review conditionally when the clean run changes them: `tables/table_{05,06,07,15}_*.tex`
- Review manually curated design/literature content: `tables/table_10_prior_literature_map.tex`, `tables/table_11_research_design_summary.tex`
- Create with `apply_patch`: `tables/table_18_public_sample_attrition.tex`

- [ ] **Step 1: Restore the manuscript README worktree mode**

The Git index already records `100644`; only the live filesystem mode is executable. Normalize it without creating a false empty commit:

```bash
test "$(git -C ../reporting-risk-cascade-manuscript ls-files -s README.md | cut -d' ' -f1)" = "100644"
chmod -x ../reporting-risk-cascade-manuscript/README.md
test ! -x ../reporting-risk-cascade-manuscript/README.md
git -C ../reporting-risk-cascade-manuscript diff --summary -- README.md
```

Expected: no mode-change summary; the intended README content remains modified and is committed with the empirical manuscript revision in Task 9.

- [ ] **Step 2: Preview every table change**

```bash
make -C ../reporting-risk-cascade-manuscript sync-table-tex-preview \
  MANUSCRIPT_PACKAGE="$(pwd)/artifacts/manuscript_package"
```

Save the preview in the execution log. Never run `make sync-table-tex CONFIRM=1`.

- [ ] **Step 3: Sync figures and provenance through the provided helper**

```bash
SYNC_NEW_TABLE_TEX=0 make -C ../reporting-risk-cascade-manuscript sync-artifacts \
  MANUSCRIPT_PACKAGE="$(pwd)/artifacts/manuscript_package"
git -C ../reporting-risk-cascade-manuscript diff --stat
git -C ../reporting-risk-cascade-manuscript diff -- \
  provenance/artifact_manifest.json provenance/results_narrative.md
```

- [ ] **Step 4: Merge every changed generated table explicitly**

For every `NEW` or differing table in the preview, compare the generated CSV/Markdown/TeX and use `apply_patch` so numeric cells and notes match while preserving intentional styling. Tables 1/2/4/8/13/14/16/17 are mandatory review surfaces; Tables 5/6/7/15 are conditional on clean-run changes. Tables 10/11 remain curated but must be updated if literature terminology or the research-design contract changed. Enforce these special contracts:

```text
table_03: three tasks, all + expanding, mean PR-AUC, excluding-2020 PR-AUC and delta
table_09: exactly two approved rows, key fields or note, bootstrap interval
table_12: Raw Controls, Encoded Controls, Opacity Components, adjusted-association disclaimer
table_18: source/year/domestic/observable sequence followed by task-specific branches
```

Add `\input{tables/table_18_public_sample_attrition.tex}` near the appendix sample-boundary tables.

- [ ] **Step 5: Reject stale headline language**

```bash
set -euo pipefail
if rg -n 'all \+ rolling_7y|highest[- ]lift|highest reported configuration|pre-registered primary|preregistered primary' \
  ../reporting-risk-cascade-manuscript/main.tex \
  ../reporting-risk-cascade-manuscript/tables \
  ../reporting-risk-cascade-manuscript/provenance; then
    echo "stale primary or post-hoc language found" >&2
    exit 1
fi
```

Expected: no stale primary-spec or post-hoc-primary wording.

---

### Task 9: Revise manuscript claims around the frozen evidence contract

**Repository:** `../reporting-risk-cascade-manuscript`

**Files:**
- Modify with `apply_patch`: `main.tex:58-664`
- Modify with `apply_patch`: `statements/reproducibility.tex`
- Modify with `apply_patch`: `statements/data_availability.tex`
- Modify with `apply_patch`: `statements/ai_declaration.tex`
- Modify with `apply_patch`: `README.md`

- [ ] **Step 1: Align title, abstract, and Introduction**

Use this claim order:

```text
Question: whether ex ante public reporting frictions predict later public review-and-correction events, and how that construct overlaps detected-misstatement risk.
Data: SEC issuer filings; public comment, amendment, and 8-K correction labels; PCAOB Form AP and oversight data; a restricted detected-misstatement benchmark used only through the audited bridge.
Primary model: the existing XGBoost with all public feature families and an expanding training window.
Benchmarks: visibility/history, individual feature families, rolling-window sensitivities, benchmark XGBoost, peer-compatible models, and declared bidirectional alignment rows.
Contribution: a reproducible public measurement system and bounded construct validation, not a causal fraud detector or replacement for restricted benchmark data.
```

Call `all + expanding` revision-frozen. Do not use “preregistered,” “pre-specified before seeing outcomes,” “fraud prediction,” or causal selection language.

- [ ] **Step 2: Align Data and Research Design to code reality**

State exactly:

```text
public vintage 2026-07-06; years 2011-2024; 365-day outcomes
sequential attrition and task exclusions shown in Table 18
metadata, XBRL, auditor, oversight, visibility/history, and all feature sets
notes/disclosure breadth enter all; no standalone text-family ablation
expanding primary; 5-, 7-, and 10-year rolling sensitivities
PR-AUC primary; ROC-AUC, Brier, Brier Skill, ECE, top-decile precision/FDR/lift secondary
construct intervals use seed 42, 1,000 draws, primary plus top five exploratory rows per direction
60 raw and 64 encoded DML controls only if the clean Table 12 reports those exact values
```

Do not translate the Mermaid flow in `docs/paper_plan.md` into a new manuscript figure unless all nodes are verified against the final manifest.

- [ ] **Step 3: Make Results and Discussion consume generated evidence only**

Map every numeric claim to:

```text
primary public results -> Table 3 / Figure 1
feature and window sensitivities -> Tables 4 and 14 / Figure 2
peer-compatible results -> Figures 3 and 4 and generated source tables
construct validation -> Table 9 / Figure 5
DML adjustment -> Table 12
sample construction -> Table 18
```

Treat excluding-2020 as sensitivity and higher-lift alternatives as exploratory/post-hoc. Separate discrimination, calibration, and construct overlap. Keep policy implications conditional and noncausal.

Make these approved corrections explicit:

```text
remove the false sentence that the all-feature specification leads within every public label
report event-time concentration from event_time_concentration.csv with its coverage/balanced-window boundary
report aggregation sensitivity from aggregation_sensitivity.csv rather than lift alone
report timing/drift and shelf-life evidence, including null or unstable results
report benchmark/public peer component fit or skip status from their manifests
state the DML result as a null adjusted-association diagnostic, not main-claim support
collapse the duplicate calibration interpretation around current lines 456 and 460 into one bounded paragraph
replace implementation-facing labels such as feature_set, train_window, label_8k_402_365, and benchmark_naive with reader-facing terms outside code/provenance tables
```

After editing, run:

```bash
set -euo pipefail
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
if rg -n 'all-feature specification leads within each public label|65 post-encoding control|highest reported configuration|\bfeature_set\b|\btrain_window\b|label_8k_402_365|benchmark_naive' \
  "$MANUSCRIPT/main.tex"; then
    echo "stale manuscript claim found" >&2
    exit 1
fi
rg -n 'event-time concentration|aggregation sensitivity|timing|drift|peer-compatible|adjusted associations' \
  "$MANUSCRIPT/main.tex"
```

- [ ] **Step 4: Update reproducibility, availability, and AI statements**

Name the roles of `STUDY_COMMIT`, `REPORT_COMMIT`, the reviewer ZIP, the canonical commands, and excluded restricted inputs. State that AI assisted drafting/review under human verification and was neither empirical evidence nor an author.

- [ ] **Step 5: Preserve author-only blanks**

Do not fabricate author order, affiliations, correspondence, CRediT roles, funding, conflicts, journal choice, access permissions, approval of the exact AI declaration, or the self-citation anonymization decision. Carry these to the submission checklist.

- [ ] **Step 6: Commit empirical manuscript revisions separately**

```bash
set -euo pipefail
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
git -C "$MANUSCRIPT" diff --check
git -C "$MANUSCRIPT" diff --stat
git -C "$MANUSCRIPT" add -- \
  main.tex README.md \
  figures \
  tables \
  provenance/artifact_manifest.json \
  provenance/results_narrative.md \
  provenance/source_tables \
  statements/reproducibility.tex \
  statements/data_availability.tex \
  statements/ai_declaration.tex
git -C "$MANUSCRIPT" diff --cached --check
git -C "$MANUSCRIPT" diff --cached --stat
git -C "$MANUSCRIPT" diff --cached
```

The scoped `tables`, `figures`, and `provenance/source_tables` directories were each reviewed in Task 8; do not add submission files, bibliography, title-page metadata, or competing-interest text here. Then commit:

```bash
set -euo pipefail
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
git -C "$MANUSCRIPT" commit -m "revise manuscript around canonical evidence"
```

Never use `git add -A` in the manuscript repository.

---

### Task 10: Compile and visually inspect the root PDF

**Skills:** `latex:latex-compile`, `pdf:pdf`; use `superpowers:systematic-debugging` on failures.

- [ ] **Step 1: Validate bibliography data and build cleanly**

```bash
set -euo pipefail
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
BIBTMP="$(mktemp -d)"
trap 'rm -rf "$BIBTMP"' EXIT
cp "$MANUSCRIPT/references.bib" "$BIBTMP/references.bib"
(
  cd "$BIBTMP"
  biber --tool --validate-datamodel references.bib
)
(
  cd "$MANUSCRIPT"
  latexmk -C main.tex
  latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
)
```

- [ ] **Step 2: Reject unresolved references and fatal diagnostics**

```bash
set -euo pipefail
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
if rg -n 'LaTeX Warning: (Reference|Citation).*undefined|There were undefined references|Please \(re\)run Biber|Emergency stop|Fatal error' \
  "$MANUSCRIPT/main.log" "$MANUSCRIPT/main.blg"; then
    echo "blocking LaTeX diagnostic found" >&2
    exit 1
fi
```

Expected: no matches. Review each overfull box visually and record any harmless exception in the integrity report.

- [ ] **Step 3: Render and inspect every page**

Use the PDF skill's Poppler workflow. Inspect the title/abstract, Tables 3/4/9/12/14/18, Figures 1/5, all section breaks, references, and statements. Patch, rebuild, and re-render until there are no clipped tables, unreadable figures, orphan headings, accidental blank pages, overlapping floats, stale values, or missing glyphs.

---

### Task 11: Finalize submission-support files locally

**Files:**
- Modify with `apply_patch`: `submission/cover_letter.md`
- Modify with `apply_patch`: `submission/highlights.tex`
- Modify with `apply_patch`: `submission/submission_checklist.md`
- Modify with `apply_patch`: `submission/credit_statement.tex`
- Modify only with supplied author data: `submission/title_page.tex`
- Modify with `apply_patch` only if required: `scripts/package_submission.sh`

- [ ] **Step 1: Bound highlights and cover-letter claims**

Make every claim agree with the abstract, Table 3, Table 9, and limitations. Run:

```bash
set -euo pipefail
make -C ../reporting-risk-cascade-manuscript highlights-check
```

- [ ] **Step 2: Centralize author-only blockers**

Keep one checklist block covering target journal/article type, author order/affiliations, corresponding author, CRediT roles, funding, conflicts, restricted-data wording/permissions, explicit approval of the AI declaration, and the self-citation anonymization decision.

- [ ] **Step 3: Build the title page and flat package**

Build the title page for technical QA using only supplied values or existing explicit placeholders:

```bash
set -euo pipefail
make -C ../reporting-risk-cascade-manuscript title-page
```

Then build the flat package for technical QA:

```bash
set -euo pipefail
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
make -C "$MANUSCRIPT" submission-package
(
  cd "$MANUSCRIPT/submission/package_flat"
  latexmk -C main.tex
  latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
)
```

If author fields are incomplete, keep placeholders explicit and record the title-page blocker; this draft PDF is not upload-ready and must never be described as final.

- [ ] **Step 4: Inspect the flat package**

From the manuscript root:

```bash
set -euo pipefail
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
find "$MANUSCRIPT/submission/package_flat" -maxdepth 1 -type f -print | sort
if rg -n '/Users/|OneDrive|\.\./|input\{tables/|includegraphics\{figures/' \
  "$MANUSCRIPT/submission/package_flat"; then
    echo "flat package contains a local or unresolved nested path" >&2
    exit 1
fi
```

Expected: no local paths or unresolved nested includes. Render all pages of `submission/package_flat/main.pdf` and compare them with root `main.pdf`.

- [ ] **Step 5: Commit support changes separately**

Stage only intended support files, inspect, then:

```bash
set -euo pipefail
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
git -C "$MANUSCRIPT" add -- \
  submission/cover_letter.md \
  submission/highlights.tex \
  submission/submission_checklist.md \
  submission/credit_statement.tex \
  submission/title_page.tex \
  submission/title_page.pdf \
  scripts/package_submission.sh
git -C "$MANUSCRIPT" diff --cached --check
git -C "$MANUSCRIPT" diff --cached --stat
git -C "$MANUSCRIPT" diff --cached
git -C "$MANUSCRIPT" commit -m "align submission materials with revised manuscript"
```

---

### Task 12: Obtain DeepSeek and Qwen reviews and adjudicate them

**Skills:** `deepseek-text-reviewer`, `qwen-text-reviewer`, `superpowers:receiving-code-review`.

**Generated outside tracked source:** `artifacts/reviewer_feedback/{review_context,deepseek_review,qwen_review,adjudication}.md`

All four paths are under the source repository's ignored `artifacts/` directory, never under the manuscript repository.

- [ ] **Step 1: Build a compact anonymized context**

Confirm the only deliberately uncommitted manuscript path is the pre-existing
bibliography revision reserved for the authoritative integrity gate:

```bash
set -euo pipefail
MANUSCRIPT_ROOT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
test "$(git -C "$MANUSCRIPT_ROOT" diff --name-only)" = "references.bib"
test -z "$(git -C "$MANUSCRIPT_ROOT" diff --cached --name-only)"
```

Include only anonymized title/abstract, question/contribution, data summary without paths or rows, models/metrics, rendered Tables 3/9/12/18, key Results/Discussion paragraphs, canonical verifier result, and questions about consistency, overclaiming, caveats, interpretation, and prose.

Create the ignored parent directory first, then create the packet with
`apply_patch`; do not concatenate repository files with shell redirection.

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
mkdir -p "$SOURCE_ROOT/artifacts/reviewer_feedback"
```

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
CONTEXT="$SOURCE_ROOT/artifacts/reviewer_feedback/review_context.md"
test -s "$CONTEXT"
if rg -n '/Users/|OneDrive|tycheng|@|DEEPSEEK_API_KEY|DASHSCOPE_API_KEY|QWEN_API_KEY' \
  "$CONTEXT"; then
    echo "review context contains identity or secret markers" >&2
    exit 1
fi
```

- [ ] **Step 2: Identify providers and content class before calls**

Tell the user in commentary that DeepSeek uses the configured reviewer model via `api.deepseek.com`, Qwen uses the configured DashScope/Qwen reviewer model, and the content is anonymized manuscript text plus aggregate public results. Run each skill's credential-presence check without printing values.

```bash
set -euo pipefail
grep -q '^DEEPSEEK_API_KEY=.' "$HOME/.codex/.env"
grep -q '^QWEN_API_KEY=.' "$HOME/.codex/.env"
grep -q '^QWEN_MODEL=.' "$HOME/.codex/.env"
```

- [ ] **Step 3: Run both proxies independently**

Run the skill-provided text-only proxies in separate tool calls and capture each
complete stdout response; do not redirect shell output into repository files:

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
CONTEXT="$SOURCE_ROOT/artifacts/reviewer_feedback/review_context.md"
python3 "$HOME/.codex/proxies/deepseek-text-review.py" \
  "$CONTEXT"
```

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
CONTEXT="$SOURCE_ROOT/artifacts/reviewer_feedback/review_context.md"
python3 "$HOME/.codex/proxies/qwen-text-review.py" \
  "$CONTEXT"
```

Use `apply_patch` to write the captured responses verbatim to
`artifacts/reviewer_feedback/deepseek_review.md` and
`artifacts/reviewer_feedback/qwen_review.md`, then require both files to be
nonempty. Each call may wait up to the skill-authorized 666 seconds. Do not run
setup smoke tests unless a credential/API/configuration failure occurs. Neither
reviewer may modify files or run code.

- [ ] **Step 4: Adjudicate every substantive finding**

Use one row per finding:

```text
Reviewer | Finding | Local evidence checked | Decision | Manuscript action
```

Allowed decisions: `accept`, `accept with narrower wording`, `reject as contradicted`, `defer to author input`. Reviewer output alone is never evidence.

Create `artifacts/reviewer_feedback/adjudication.md` with `apply_patch`. Include
the SHA-256 of both reviewer reports, the table above, and a local file/table/
manifest locator for every evidence check. If neither reviewer raises a
substantive finding, record that outcome explicitly rather than omitting the
file. Then verify it exists:

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
test -s "$SOURCE_ROOT/artifacts/reviewer_feedback/adjudication.md"
rg -n 'DeepSeek|Qwen|Local evidence checked|Decision' \
  "$SOURCE_ROOT/artifacts/reviewer_feedback/adjudication.md"
```

- [ ] **Step 5: Apply only confirmed corrections**

Patch confirmed issues with `apply_patch`. The manuscript was clean before this
step, so every new unstaged tracked path must correspond to an accepted
adjudication row. Stage each such path individually, reject unexpected paths,
inspect the staged diff, and commit only when nonempty:

```bash
set -euo pipefail
MANUSCRIPT="$(cd ../reporting-risk-cascade-manuscript && pwd)"
git -C "$MANUSCRIPT" diff --name-only
while IFS= read -r path; do
  test -n "$path" || continue
  case "$path" in
    references.bib)
      continue
      ;;
    main.tex|README.md|figures/*|tables/*|provenance/*|statements/*|submission/*)
      git -C "$MANUSCRIPT" add -- "$path"
      ;;
    *)
      echo "unexpected external-review path: $path" >&2
      exit 1
      ;;
  esac
done < <(git -C "$MANUSCRIPT" diff --name-only)
git -C "$MANUSCRIPT" diff --cached --check
if git -C "$MANUSCRIPT" diff --cached --quiet; then
  echo "No tracked correction accepted from external review."
else
  git -C "$MANUSCRIPT" diff --cached
  git -C "$MANUSCRIPT" commit -m "address verified external review findings"
  make -C "$MANUSCRIPT" submission-package
  (
    cd "$MANUSCRIPT"
    latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
  )
  (
    cd "$MANUSCRIPT/submission/package_flat"
    latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
  )
fi
test "$(git -C "$MANUSCRIPT" diff --name-only)" = "references.bib"
```

Update `adjudication.md` with each action's final commit or no-change disposition.
The block rebuilds both PDFs only when a tracked correction exists; rerun the
canonical verifier if an evidence reference changes. The latest verified PDFs
become the inputs to the applicable Stage 3/3-prime review and Stage 4.5.

---

### Task 13: Run the applicable ARS reviewer stage and Stage 4.5

**Skill:** `academic-research-suite`, using its research-to-paper reviewer and integrity agents.

**Files:**
- Create: `provenance/integrity/stage_3_review.md`
- Create: `provenance/integrity/stage_4_5_integrity.md`
- Create: `provenance/integrity/material_passport.yaml`
- Create: `provenance/integrity/claim_intent_manifest.yaml`
- Create: `provenance/integrity/claim_registry.csv`
- Create: `provenance/integrity/figure_table_trace.yaml`
- Create: `provenance/integrity/experiment_provenance.yaml`

- [ ] **Step 1: Create the ARS intake boundary and obtain the scholar declaration**

Create the tracked audit directory before writing ARS outputs:

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
MANUSCRIPT_ROOT="$(cd "$SOURCE_ROOT/../reporting-risk-cascade-manuscript" && pwd)"
mkdir -p "$MANUSCRIPT_ROOT/provenance/integrity"
```

Prepare six frozen experiment IDs matching the realized Results headings:

```text
exp-label-observability-timing
exp-drift-shelf-life
exp-opacity-public-risk
exp-public-cascade-construction
exp-public-cascade-prediction
exp-construct-overlap
```

For each ID, show the user the planned units, executed artifacts, skipped units
and reasons, negative/null findings, and known limitations from the canonical
manifests. This is the ARS Stage-1 intake decision: stop and obtain explicit user
confirmation before recording
`experiment_intake_declaration.status: experiments_declared`; set
`declared_by: scholar` and an actual UTC `declared_at`. Do not infer the scholar
declaration merely from file existence.

- [ ] **Step 2: Write and validate experiment provenance and claim intent**

Create the four YAML/CSV contracts with `apply_patch`, using actual values only:

- `material_passport.yaml` must include every required Schema 9 identity field,
  `repro_lock: null` as the explicit honest passport-level opt-out,
  `experiment_intake_declaration`, `experiment_provenance[]`, and
  `claim_intent_manifests[]`.
- `experiment_provenance.yaml` must contain the same six-entry
  `experiment_provenance[]` ledger embedded in the passport. Every entry has
  `experiment_id`, `title`, a fully populated nested `repro_lock`, at least one
  `planned_vs_executed` unit, and present `negative_results` and
  `known_limitations` arrays. Record `executed: false` with `skip_reason` for any
  approved unit not produced; never omit it.
- Each nested experiment `repro_lock` uses schema `1.0`, the required verbatim
  stochasticity declaration, the installed ARS adapter version and upstream
  commit from `academic-research-suite/manifest.json`, model/config identity from
  the canonical study manifest and `uv.lock`, SHA-256 hashes of the approved
  design and relevant source/config bundle, a sorted material-list hash/count,
  `s2_api_protocol_version: not_used_in_empirical_run`,
  `s2_snapshot_available: false`, and cross-model `false`/`null`. These locks
  document configuration; they do not claim deterministic replay.
- `claim_intent_manifest.yaml` must conform to version `1.0`, use a valid
  `M-<UTC>-<4hex>` ID and `emitted_by: draft_writer_agent`, and list every
  abstract, contribution, empirical headline, policy, and limitation claim.
  Every empirical claim carries one or more `planned_experiment_ids` resolving
  to the six-entry ledger. Add manifest-level negative constraints against
  causal, hidden-misconduct, preregistration, severity, economic-outcome, and
  international-generalization claims.
- `claim_registry.csv` is the human-readable projection of the same manifest,
  with columns `manifest_id,claim_id,claim_text,intended_evidence_kind,planned_experiment_ids,evidence_locator,boundary`;
  it must not introduce claims or experiment IDs absent from the YAML.

Run the ARS shape checks and an exact embedding comparison:

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
MANUSCRIPT_ROOT="$(cd "$SOURCE_ROOT/../reporting-risk-cascade-manuscript" && pwd)"
ARS_ROOT="$HOME/.codex/skills/academic-research-suite/ars"
uv run python "$ARS_ROOT/scripts/check_repro_lock.py" \
  "$MANUSCRIPT_ROOT/provenance/integrity/material_passport.yaml"
uv run --with jsonschema python "$ARS_ROOT/scripts/check_experiment_provenance.py" \
  "$MANUSCRIPT_ROOT/provenance/integrity/material_passport.yaml"
export MANUSCRIPT_ROOT
uv run python - <<'PY'
import csv
import os
from pathlib import Path

import yaml

root = Path(os.environ["MANUSCRIPT_ROOT"]) / "provenance" / "integrity"
passport = yaml.safe_load((root / "material_passport.yaml").read_text(encoding="utf-8"))
ledger = yaml.safe_load((root / "experiment_provenance.yaml").read_text(encoding="utf-8"))
claim_manifest = yaml.safe_load(
    (root / "claim_intent_manifest.yaml").read_text(encoding="utf-8")
)
assert passport["repro_lock"] is None
assert passport["experiment_intake_declaration"]["status"] == "experiments_declared"
assert passport["experiment_provenance"] == ledger["experiment_provenance"]
assert passport["claim_intent_manifests"] == [claim_manifest]
declared = {row["experiment_id"] for row in passport["experiment_provenance"]}
assert len(declared) == len(passport["experiment_provenance"]) == 6
linked = {
    experiment_id
    for claim in claim_manifest["claims"]
    for experiment_id in claim.get("planned_experiment_ids", [])
}
assert linked == declared
with (root / "claim_registry.csv").open(encoding="utf-8", newline="") as handle:
    registry = list(csv.DictReader(handle))
assert {(row["manifest_id"], row["claim_id"]) for row in registry} == {
    (claim_manifest["manifest_id"], claim["claim_id"])
    for claim in claim_manifest["claims"]
}
PY
PASSPORT_YAML="$MANUSCRIPT_ROOT/provenance/integrity/material_passport.yaml"
PASSPORT_JSON="$(mktemp)"
export PASSPORT_YAML PASSPORT_JSON
trap 'rm -f "$PASSPORT_JSON"' EXIT
uv run python - <<'PY'
import json
import os
from pathlib import Path

import yaml

source = Path(os.environ["PASSPORT_YAML"])
target = Path(os.environ["PASSPORT_JSON"])
target.write_text(
    json.dumps(yaml.safe_load(source.read_text(encoding="utf-8"))),
    encoding="utf-8",
)
PY
uv run --with jsonschema python \
  "$ARS_ROOT/scripts/check_claim_audit_consistency.py" \
  --passport "$PASSPORT_JSON"
rm -f "$PASSPORT_JSON"
trap - EXIT
```

The `check_repro_lock.py` warning for an explicit passport-level null is expected;
the nested experiment locks must still be fully populated and pass their schema.
The authoritative consistency lint must also pass; the custom equality check is
only a readable preflight, not a substitute for EP/EA invariant validation.

- [ ] **Step 3: Run the truthful reviewer branch and stop at its mandatory checkpoint**

Score research question, literature/gap, data/preprocessing, models/benchmarks,
metrics, results consistency, claim calibration, limitations, and submission
readiness. Every issue needs severity, section, evidence, and disposition.

If original journal reports, an editorial decision, and an earlier revision
roadmap are actually supplied, run formal Stage 3-prime re-review and verify each
commitment. Otherwise record `not supplied` and run a fresh full Stage 3 reviewer
simulation against the approved design, DeepSeek/Qwen adjudication, and canonical
evidence. Record `review_mode: re_review_stage_3_prime` or
`review_mode: fresh_full_stage_3` in `stage_3_review.md`; never label the latter
as Stage 3-prime or fabricate response-to-reviewers history.

The ARS review decision is a MANDATORY checkpoint. Present the report, decision,
item counts, and options, then stop for explicit user confirmation. `continue`
after Accept/Minor permits Stage 4.5; Major routes to a revision round and then a
formal re-review; Reject/abort stops. Do not advance from review to integrity in
the same unattended turn.

- [ ] **Step 4: Refresh the material passport and trace every claim/table/figure**

Hash and identify `STUDY_COMMIT`, `REPORT_COMMIT`, study/public/construct/package manifests, Tables 3/9/12/18 source CSVs, `main.tex`, `main.pdf`, `references.bib`, flat `main.tex`/`main.pdf`, and reviewer ZIP. Map every abstract, contribution, headline, policy, and limitation claim to a source/table/figure or an interpretation label.

Record generated source, generator, study component/input, manuscript destination, note/caption check, and numeric spot check. Require 100% coverage; Table 9 must trace to `is_primary` rows.

- [ ] **Step 5: Run fresh Stage 4.5 integrity checks**

Require 100% bibliography metadata validation, citation reconciliation, citation-context support, empirical headline reconciliation, figure/table tracing, and experiment provenance; at least 50% originality sampling of unchanged prose; and 100% review of substantively revised paragraphs. Check all seven ARS failure modes explicitly.

The integrity agent must write `experiment_alignment_results[]` back into the
Material Passport for every experiment-backed claim, using only `ALIGNED`,
`OVERSTATED`, `NOT_SUPPORTED_BY_PROVENANCE`, or
`PROVENANCE_INSUFFICIENT`. Re-run the YAML-to-temporary-JSON conversion and
`check_claim_audit_consistency.py --passport ...` command from Step 2 after
those rows are present. A PASS requires every headline empirical claim to be
`ALIGNED`; do not discard the aggregate after the gate.

If `references.bib` contains verified corrections, stage it alone, inspect, and commit `fix: verify manuscript bibliography`; then rebuild root PDF, regenerate/rebuild the flat package, and rerun affected citation/claim checks before final hashes are recorded. If a reference cannot be authoritatively verified, do not commit a guessed repair; mark the integrity gate failed.

- [ ] **Step 6: Enforce zero unresolved factual issues and stop at the integrity checkpoint**

Stage 4.5 may say PASS only when critical, major, and unresolved factual issues
are zero. Otherwise use `apply_patch`, stage only confirmed manuscript
corrections, inspect, and commit `address integrity review findings`; regenerate
the flat package; rebuild and render root/flat PDFs; then rerun reviewer items
affected by the correction and Stage 4.5 from scratch. Repeat until PASS or the
three-round ARS limit is reached. Only the final post-correction PDFs and
manifests may enter the material passport.

Stage 4.5 is a MANDATORY checkpoint even on PASS. Present the complete integrity
metrics and final hashes, stop, and require explicit user confirmation before
Serena synchronization/final handoff. Record that acknowledgement and timestamp
in the integrity audit trail; it does not waive any failed finding.

- [ ] **Step 7: Commit the integrity packet after acknowledgement**

```bash
git -C ../reporting-risk-cascade-manuscript add provenance/integrity
git -C ../reporting-risk-cascade-manuscript diff --cached --check
git -C ../reporting-risk-cascade-manuscript commit -m "document manuscript integrity verification"
```

---

### Task 14: Synchronize both Serena memories last

**Files:** `.serena/memories/current_status.md`, `../reporting-risk-cascade-manuscript/.serena/memories/current_status.md`

- [ ] **Step 1: Initialize Serena and activate the source project**

Use Serena itself, not only direct filesystem edits:

1. Call Serena `initial_instructions` once and follow the returned project rules.
2. Call Serena `activate_project` with the absolute real source root.
3. Confirm the activated project name matches `.serena/project.yml`.
4. Call Serena `list_memories`, then `read_memory` for `current_status` before editing.

- [ ] **Step 2: Update and read back the source memory through Serena**

Record question/boundary, sources/vintage/years/horizon, ours/benchmarks, metrics/rationale, frozen primary, alignment keys, canonical commands, actual commits/hashes/status, artifact inventory, historical archive, author blockers, and truth hierarchy `manifests/source tables -> snapshot -> manuscript -> FAQ/Serena`.

Use Serena `write_memory` (or `edit_memory` when the server exposes it) for
`current_status`, then immediately call `read_memory` and compare the returned
content to the intended text. A successful filesystem write without Serena
readback does not satisfy this step.

- [ ] **Step 3: Activate the manuscript project, update it, and read it back**

Call Serena `activate_project` with the absolute manuscript root, confirm its
distinct project name from that repo's `.serena/project.yml`, list/read
`current_status`, and then update it through Serena.

Add root/flat PDF commands, synchronization boundary, manuscript commits, backup ref, the truthful Stage 3 or 3-prime review mode and Stage 4.5 status, review adjudication path, submission blockers, and no-upload status.

Immediately read the manuscript memory back through Serena and compare it with
the intended text. Reactivate the source project and read its `current_status`
once more to prove that switching projects did not overwrite or conflate the two
memories.

- [ ] **Step 4: Cross-check both against live files**

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
MANUSCRIPT_ROOT="$(cd "$SOURCE_ROOT/../reporting-risk-cascade-manuscript" && pwd)"
rg -n '2026-07-06|all \+ expanding|CANONICAL|author-only' \
  "$SOURCE_ROOT/.serena/memories/current_status.md" \
  "$MANUSCRIPT_ROOT/.serena/memories/current_status.md"
git -C "$SOURCE_ROOT" status --short
git -C "$MANUSCRIPT_ROOT" status --short
```

Write actual hashes; do not leave symbolic commit names in memory. Serena remains local and outside Git.

---

### Task 15: Final verification and readiness verdict

**Skill:** `superpowers:verification-before-completion`.

- [ ] **Step 1: Verify source from its final commit**

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
(
  cd "$SOURCE_ROOT"
  uv lock --check
  just check
  uv run --group docs mkdocs build --strict --clean
  just verify-canonical study_dir=artifacts/full_with_peer package_dir=artifacts/manuscript_package
  test -z "$(git status --short)"
)
```

Expected: all pass, verifier prints `CANONICAL RUN VERIFIED`, tracked status is clean.

- [ ] **Step 2: Verify manuscript and flat package**

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
MANUSCRIPT="$(cd "$SOURCE_ROOT/../reporting-risk-cascade-manuscript" && pwd)"
BIBTMP="$(mktemp -d)"
trap 'rm -rf "$BIBTMP"' EXIT
cp "$MANUSCRIPT/references.bib" "$BIBTMP/references.bib"
(
  cd "$BIBTMP"
  biber --tool --validate-datamodel references.bib
)
(
  cd "$MANUSCRIPT"
  latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
)
make -C "$MANUSCRIPT" highlights-check
(
  cd "$MANUSCRIPT/submission/package_flat"
  latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
)
test -z "$(git -C "$MANUSCRIPT" status --short)"
```

Do not regenerate the flat package at this stage; the latest Task 11, 12, or 13
correction loop created the package that Stage 4.5 hashed. Render both PDFs after
this exact up-to-date check. Confirm Stage 4.5 passport hashes match final files.
If latexmk changes either PDF or any hash differs, route back to Task 13 Steps
4-7: refresh all traces/hashes, rerun Stage 4.5, obtain the mandatory user
acknowledgement, and commit the refreshed integrity packet. Then restart Task 15
from Step 1. Do not leave a stale passport, an uncommitted integrity diff, or a
silently changed PDF.

- [ ] **Step 3: Remove only revision-generated transient outputs**

Guard both roots, then remove only ignored caches/build trees named by the approved design:

```bash
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
MANUSCRIPT_ROOT="$(cd "$SOURCE_ROOT/../reporting-risk-cascade-manuscript" && pwd)"
test "$SOURCE_ROOT" = "$(git -C "$SOURCE_ROOT" rev-parse --show-toplevel)"
test "$MANUSCRIPT_ROOT" = "$(git -C "$MANUSCRIPT_ROOT" rev-parse --show-toplevel)"
rm -f "$SOURCE_ROOT/.coverage"
rm -rf \
  "$SOURCE_ROOT/site" \
  "$SOURCE_ROOT/.pytest_cache" \
  "$SOURCE_ROOT/.ruff_cache" \
  "$SOURCE_ROOT/src/__pycache__" \
  "$SOURCE_ROOT/scripts/__pycache__" \
  "$SOURCE_ROOT/tests/__pycache__"
```

Do not remove `artifacts/historical`, the canonical study/package/ZIP, either PDF, the manuscript backup ref, or any tracked output. Confirm both Git statuses after cleanup.

- [ ] **Step 4: Answer readiness questions with evidence**

Report data availability/redistribution boundaries; approved comparison coverage; model inventory; tables/figures/analyses; Stage 4.5 sufficiency; author/journal submission blockers; historical archive instead of deletion; and Serena synchronization.

- [ ] **Step 5: Hand off without uploading**

Return paths to the canonical manifest, snapshot, root/flat PDFs, reviewer ZIP, integrity report, and both Serena memories. Report actual study/report/manuscript commits, manuscript backup ref, verification outputs, and remaining author-only blockers. Do not claim journal submission or send files externally.
