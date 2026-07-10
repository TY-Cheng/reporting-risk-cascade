# Evidence Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the public data and public-cascade outputs archive-current, revision-frozen, and explicit about visibility, sample attrition, DML dimensions, and study provenance.

**Architecture:** Keep the existing public-lake and XGBoost loops. Add one tested Form AP materialization seam, one exact visibility/history allowlist, one validated primary-spec contract, and small provenance/accounting outputs consumed by later reporting tasks. Do not add an estimator, dependency, or new outcome.

**Tech Stack:** Python 3.13, pandas, DuckDB, scikit-learn, XGBoost, PyYAML, pytest, uv, just, Bash.

## Global Constraints

- Work in an isolated source-repository worktree created with `superpowers:using-git-worktrees` at execution time.
- Preserve the sibling manuscript repository; this plan must not edit it.
- Pin `as_of_date=2026-07-06`; do not advance the public-data vintage.
- Freeze the public primary specification as `feature_set=all`, `train_window=expanding`; describe it as revision-frozen, not preregistered.
- Add `visibility_history` through the existing XGBoost loop; do not add another estimator or dependency.
- Keep notes/disclosure-breadth variables inside `all`; do not add a standalone text-family experiment.
- Keep the sample at fiscal years 2011-2024 and the existing 365-day labels.
- Preserve backward-compatible `n_controls`, but define it as encoded nuisance columns.
- Use red-green-refactor TDD and commit after every independently reviewable task.
- Do not run the expensive public-lake or peer-enabled study in this plan; those runs belong to the canonical-execution plan.

---

### Task 1: Normalize tracked modes and track the dependency lock

**Files:**
- Modify: `.gitignore:88-93`
- Create: `.python-version`
- Track: `uv.lock`
- Modify: `justfile:31-61`
- Create: `tests/test_repo_hygiene.py`

**Interfaces:**
- Consumes: Git index modes and the existing ignored `uv.lock`.
- Produces: a tracked lockfile, a Python 3.13 uv pin, and the invariant that only `scripts/run_public_lake_full.sh` is executable.

- [ ] **Step 1: Write the failing repository-hygiene test**

Create `tests/test_repo_hygiene.py` with this content:

```python
from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def test_uv_lock_is_tracked_and_only_public_lake_shell_is_executable() -> None:
    tracked = set(_git("ls-files").splitlines())
    assert "uv.lock" in tracked
    assert ".python-version" in tracked
    assert (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.13"

    executable = {
        line.split("\t", maxsplit=1)[1]
        for line in _git("ls-files", "-s").splitlines()
        if line.startswith("100755 ")
    }
    assert executable == {"scripts/run_public_lake_full.sh"}
```

Add `tests/test_repo_hygiene.py` to the file list in `justfile::_test-core`.

- [ ] **Step 2: Run the test to verify the current repository fails**

Run:

```bash
uv run pytest -q tests/test_repo_hygiene.py
```

Expected: FAIL because `uv.lock` and `.python-version` are untracked/absent and many tracked files are mode `100755`.

- [ ] **Step 3: Apply the minimal metadata correction**

Remove the active `uv.lock` line from `.gitignore`. Create `.python-version` with
the single line `3.13` using `apply_patch`, then run:

```bash
uv lock
git ls-files -z | xargs -0 chmod -x
chmod +x scripts/run_public_lake_full.sh
git add .gitignore .python-version uv.lock justfile tests/test_repo_hygiene.py
git add -u
```

Do not change file contents while normalizing modes.

- [ ] **Step 4: Verify the lock and mode invariant**

Run:

```bash
uv lock --check
uv run pytest -q tests/test_repo_hygiene.py
git diff --cached --check
git diff --cached --summary
```

Expected: lock check PASS, test PASS, no whitespace errors, and mode changes ending with only `scripts/run_public_lake_full.sh` at `100755`.

- [ ] **Step 5: Commit the metadata-only change**

```bash
git commit -m "chore: normalize tracked modes and track uv lock"
```

---

### Task 2: Prefer the verified Form AP ZIP and pin the public vintage

**Files:**
- Modify: `src/public_lake.py:276-336, 4699-4770`
- Modify: `config/public_data.yaml:1-3`
- Modify: `scripts/run_public_lake_full.sh:15, 42`
- Modify: `justfile:288-425`
- Modify: `tests/test_public_lake.py:925-975, 2217-2274`
- Modify: `tests/test_docs.py`

**Interfaces:**
- Consumes: `bronze/form-ap/FirmFilings.zip`, its `.meta.json` sidecar, and optional standalone `FirmFilings.csv`.
- Produces: `(form_ap_csv, form_ap_source_metadata)` through `_materialize_form_ap_csv(...)`, plus `silver/form_ap_source_metadata.json`.

- [ ] **Step 1: Write failing tests for archive precedence and missing members**

Add these imports and tests to `tests/test_public_lake.py`:

```python
import json
import zipfile


def test_form_ap_materialization_replaces_stale_csv_from_verified_zip(tmp_path: Path) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    silver_dir = tmp_path / "silver"
    form_ap_dir.mkdir(parents=True)
    stale = form_ap_dir / "FirmFilings.csv"
    stale.write_text("Form Filing ID\nold\n", encoding="utf-8")

    archive = form_ap_dir / "FirmFilings.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("FirmFilings.csv", "Form Filing ID\nnew\n")
    public_lake._write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )

    csv_path, metadata_path = public_lake._materialize_form_ap_csv(
        form_ap_dir=form_ap_dir,
        silver_dir=silver_dir,
    )

    assert csv_path == stale
    assert stale.read_text(encoding="utf-8") == "Form Filing ID\nnew\n"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_kind"] == "verified_zip_member"
    assert metadata["member"] == "FirmFilings.csv"
    assert metadata["archive_sha256"] == public_lake._hash_file(archive)
    assert metadata["member_sha256"] == public_lake._hash_file(stale)
    assert public_lake._verify_metadata_hash(stale) is True

    event_path = public_lake.normalize_form_ap_csv(
        form_ap_csv=csv_path,
        silver_dir=silver_dir,
    )
    event = read_table(event_path)
    assert set(event["form_filing_id"].astype(str)) == {"new"}
    assert "old" not in set(event["form_filing_id"].astype(str))


def test_form_ap_materialization_fails_when_verified_zip_lacks_member(tmp_path: Path) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    form_ap_dir.mkdir(parents=True)
    archive = form_ap_dir / "FirmFilings.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("other.csv", "id\n1\n")
    public_lake._write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )

    with pytest.raises(ValueError, match="FirmFilings.csv"):
        public_lake._materialize_form_ap_csv(
            form_ap_dir=form_ap_dir,
            silver_dir=tmp_path / "silver",
        )


def test_form_ap_materialization_rejects_archive_hash_mismatch(tmp_path: Path) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    form_ap_dir.mkdir(parents=True)
    archive = form_ap_dir / "FirmFilings.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("FirmFilings.csv", "filingId\nnew\n")
    public_lake._write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )
    archive.write_bytes(archive.read_bytes() + b"drift")

    with pytest.raises(ValueError, match="Hash mismatch"):
        public_lake._materialize_form_ap_csv(
            form_ap_dir=form_ap_dir,
            silver_dir=tmp_path / "silver",
        )


def test_form_ap_materialization_accepts_standalone_csv_without_sidecar(
    tmp_path: Path,
) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    form_ap_dir.mkdir(parents=True)
    csv_path = form_ap_dir / "FirmFilings.csv"
    csv_path.write_text("filingId\nstandalone\n", encoding="utf-8")

    selected, metadata_path = public_lake._materialize_form_ap_csv(
        form_ap_dir=form_ap_dir,
        silver_dir=tmp_path / "silver",
    )

    assert selected == csv_path
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_kind"] == "standalone_csv_fallback"
    assert metadata["archive_sha256"] is None
    assert metadata["member_sha256"] == public_lake._hash_file(csv_path)
```

Add this docs contract test in `tests/test_docs.py`:

```python
def test_public_data_vintage_is_pinned_across_entry_points_and_docs() -> None:
    paths = [
        "config/public_data.yaml",
        "justfile",
        "scripts/run_public_lake_full.sh",
        "docs/paper_plan.md",
    ]
    for path in paths:
        text = _read(path)
        assert "2026-07-06" in text, path
        assert "2026-05-26" not in text, path
```

- [ ] **Step 2: Run the tests to verify the missing seam and stale dates**

Run:

```bash
uv run pytest -q \
  tests/test_public_lake.py::test_form_ap_materialization_replaces_stale_csv_from_verified_zip \
  tests/test_public_lake.py::test_form_ap_materialization_fails_when_verified_zip_lacks_member \
  tests/test_public_lake.py::test_form_ap_materialization_rejects_archive_hash_mismatch \
  tests/test_public_lake.py::test_form_ap_materialization_accepts_standalone_csv_without_sidecar
uv run pytest -q \
  tests/test_docs.py::test_public_data_vintage_is_pinned_across_entry_points_and_docs
```

Expected: FAIL because `_materialize_form_ap_csv` is absent and the tracked defaults still use 2026-05-26.

- [ ] **Step 3: Implement the archive-first materialization seam**

Add this function near `_verify_metadata_hash` in `src/public_lake.py`:

```python
def _materialize_form_ap_csv(
    *,
    form_ap_dir: Path,
    silver_dir: Path,
) -> tuple[Path | None, Path | None]:
    csv_path = form_ap_dir / "FirmFilings.csv"
    archive_path = form_ap_dir / "FirmFilings.zip"
    metadata_path = silver_dir / "form_ap_source_metadata.json"

    if archive_path.exists():
        if not _verify_metadata_hash(archive_path):
            raise ValueError(f"Missing verified metadata sidecar for {archive_path}")
        form_ap_dir.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        archive_metadata = json.loads(
            _metadata_path(archive_path).read_text(encoding="utf-8")
        )
        member_name = ""
        try:
            with zipfile.ZipFile(archive_path) as zf:
                members = [
                    info
                    for info in zf.infolist()
                    if not info.is_dir() and Path(info.filename).name == "FirmFilings.csv"
                ]
                if len(members) != 1:
                    raise ValueError(
                        f"{archive_path} must contain exactly one FirmFilings.csv member; "
                        f"found {len(members)}"
                    )
                member_name = members[0].filename
                with zf.open(members[0]) as source, tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=form_ap_dir,
                    prefix="FirmFilings.",
                    suffix=".tmp",
                    delete=False,
                ) as target:
                    shutil.copyfileobj(source, target)
                    temp_path = Path(target.name)
            temp_path.replace(csv_path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        source_kind = "verified_zip_member"
        archive_sha256 = _hash_file(archive_path)
        _write_metadata(
            path=csv_path,
            source_url=str(
                archive_metadata.get("source_url") or PCAOB_FORM_AP_ZIP_URL
            ),
            source_name="form-ap-derived",
            extra={
                "derived_from": archive_path.name,
                "derived_from_sha256": archive_sha256,
                "zip_member": member_name,
            },
        )
    elif csv_path.exists():
        if _metadata_path(csv_path).exists() and not _verify_metadata_hash(csv_path):
            raise ValueError(f"Incomplete metadata sidecar for {csv_path}")
        source_kind = "standalone_csv_fallback"
        archive_sha256 = None
        member_name = csv_path.name
    else:
        return None, None

    silver_dir.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(
            {
                "source_kind": source_kind,
                "archive_sha256": archive_sha256,
                "member": member_name,
                "member_sha256": _hash_file(csv_path),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return csv_path, metadata_path
```

Replace the current nested `normalize_form_ap_task()` extraction branch with:

```python
    def normalize_form_ap_task() -> Dict[str, Path]:
        form_ap_csv, source_metadata = _materialize_form_ap_csv(
            form_ap_dir=bronze_dir / "form-ap",
            silver_dir=silver_dir,
        )
        if form_ap_csv is None or source_metadata is None:
            return {}
        return {
            "form_ap_event": normalize_form_ap_csv(
                form_ap_csv=form_ap_csv,
                silver_dir=silver_dir,
            ),
            "form_ap_source_metadata": source_metadata,
        }
```

- [ ] **Step 4: Update the four pinned-vintage surfaces**

Set these exact values:

```yaml
# config/public_data.yaml
lake:
  as_of_date: "2026-07-06"
```

```bash
# scripts/run_public_lake_full.sh
AS_OF_DATE="${AS_OF_DATE:-2026-07-06}"
```

Update the shell help text, `justfile`'s `full` default, and every methods-level as-of statement in `docs/paper_plan.md` to `2026-07-06`.

- [ ] **Step 5: Run focused and public-lake tests**

Run:

```bash
uv run pytest -q \
  tests/test_public_lake.py::test_form_ap_materialization_replaces_stale_csv_from_verified_zip \
  tests/test_public_lake.py::test_form_ap_materialization_fails_when_verified_zip_lacks_member \
  tests/test_public_lake.py::test_form_ap_materialization_rejects_archive_hash_mismatch \
  tests/test_public_lake.py::test_form_ap_materialization_accepts_standalone_csv_without_sidecar \
  tests/test_public_lake.py::test_build_public_lake_csv_gz_path_extracts_form_ap_and_inspection_sources
uv run pytest -q tests/test_docs.py \
  -k 'public_data_vintage_is_pinned or public_lake_full_sources'
```

Expected: PASS.

- [ ] **Step 6: Commit the data-contract fix**

```bash
git add src/public_lake.py config/public_data.yaml scripts/run_public_lake_full.sh justfile docs/paper_plan.md tests/test_public_lake.py tests/test_docs.py
git commit -m "fix(data): prefer verified Form AP archive"
```

---

### Task 3: Add the exact visibility/history family and frozen primary specification

**Files:**
- Modify: `config/public_cascade.yaml:5-17`
- Modify: `src/public_cascade.py:18-170, 704-980`
- Modify: `tests/test_public_cascade_interfaces.py:1-70, 206-535`

**Interfaces:**
- Consumes: `analysis.primary_specification`, `analysis.feature_sets`, and candidate windows.
- Produces: `_resolve_primary_specification(...) -> dict[str, str]`, fail-closed `_validate_primary_metric_rows(...)`, `families["visibility_history"]`, and `summary["primary_specification"]`.

- [ ] **Step 1: Write failing allowlist and primary-validation tests**

Add imports for `VISIBILITY_HISTORY_FEATURES`, `_resolve_primary_specification`,
and `_validate_primary_metric_rows`, then add these tests to
`tests/test_public_cascade_interfaces.py`:

```python
def test_visibility_history_is_exact_and_reports_unavailable_fields() -> None:
    panel = pd.DataFrame(
        {
            "size": [100],
            "form": ["10-K"],
            "entity_type": ["operating"],
            "isXBRL": [1],
            "days_since_previous_filing": [365],
            "prior_filing_count": [8],
            "filing_friction_is_nt": [0],
            "public_history_comment_thread_1y_count": [1],
            "public_history_8k_402_3y_count": [0],
            "label_comment_thread_365": [0],
            "source_available_notes": [1],
            "xbrl_ratio_leverage": [0.2],
        }
    )

    families = _infer_feature_families(panel)

    assert families["visibility_history"] == [
        "size",
        "form",
        "entity_type",
        "isXBRL",
        "days_since_previous_filing",
        "prior_filing_count",
        "filing_friction_is_nt",
        "public_history_comment_thread_1y_count",
        "public_history_8k_402_3y_count",
    ]
    assert "xbrl_ratio_leverage" not in families["visibility_history"]
    assert "source_available_notes" not in families["visibility_history"]


def test_primary_specification_requires_configured_family_and_window() -> None:
    resolved = _resolve_primary_specification(
        {"primary_specification": {"feature_set": "all", "train_window": "expanding"}},
        requested_families=["metadata", "all"],
        train_windows=[None, 5, 7, 10],
    )
    assert resolved == {"feature_set": "all", "train_window": "expanding"}

    with pytest.raises(ValueError, match="primary feature_set"):
        _resolve_primary_specification(
            {"primary_specification": {"feature_set": "missing", "train_window": "expanding"}},
            requested_families=["all"],
            train_windows=[None],
        )


def test_primary_metric_rows_fail_closed_but_allow_all_empty_diagnostics() -> None:
    primary = {"feature_set": "all", "train_window": "expanding"}
    missing = pd.DataFrame(
        {
            "feature_set": ["metadata"],
            "train_window": ["expanding"],
            "task": ["comment_thread"],
            "test_year": [2021],
        }
    )
    with pytest.raises(ValueError, match="produced no metric rows"):
        _validate_primary_metric_rows(missing, primary)

    duplicated = pd.DataFrame(
        {
            "feature_set": ["all", "all"],
            "train_window": ["expanding", "expanding"],
            "task": ["comment_thread", "comment_thread"],
            "test_year": [2021, 2021],
        }
    )
    with pytest.raises(ValueError, match="duplicated task-year"):
        _validate_primary_metric_rows(duplicated, primary)

    empty = pd.DataFrame(
        columns=["feature_set", "train_window", "task", "test_year"]
    )
    assert _validate_primary_metric_rows(empty, primary).empty
```

- [ ] **Step 2: Run the tests to verify the contracts are absent**

Run:

```bash
uv run pytest -q tests/test_public_cascade_interfaces.py \
  -k 'visibility_history or primary_specification or primary_metric_rows'
```

Expected: FAIL because the family and resolver do not exist.

- [ ] **Step 3: Add the exact 24-field allowlist**

Add this tuple near the existing feature constants:

```python
VISIBILITY_HISTORY_FEATURES = (
    "size",
    "core_type",
    "form",
    "entity_type",
    "isXBRL",
    "isInlineXBRL",
    "isXBRLNumeric",
    "days_since_previous_filing",
    "prior_filing_count",
    "filing_friction_is_nt",
    "filing_friction_nt_pre_origin",
    "filing_friction_nt_delay_days",
    "public_history_comment_thread_1y_count",
    "public_history_comment_thread_3y_count",
    "public_history_amendment_1y_count",
    "public_history_amendment_3y_count",
    "public_history_8k_301_1y_count",
    "public_history_8k_301_3y_count",
    "public_history_8k_401_1y_count",
    "public_history_8k_401_3y_count",
    "public_history_8k_402_1y_count",
    "public_history_8k_402_3y_count",
    "public_history_8k_502_1y_count",
    "public_history_8k_502_3y_count",
)
```

Initialize `visibility_history` in `_infer_feature_families`, then set it after the existing classification loop:

```python
    families["visibility_history"] = [
        col for col in VISIBILITY_HISTORY_FEATURES if col in candidate_cols
    ]
```

Keep `families["all"]` as the union of metadata, XBRL, text, auditor, and oversight only; the visibility family is a comparison view over already-eligible columns.

- [ ] **Step 4: Implement primary-spec validation and summary provenance**

Add:

```python
def _resolve_primary_specification(
    analysis_cfg: Dict[str, object],
    *,
    requested_families: Sequence[str],
    train_windows: Sequence[Optional[int]],
) -> Dict[str, str]:
    primary = dict(analysis_cfg.get("primary_specification", {}))
    feature_set = str(primary.get("feature_set", ""))
    train_window = str(primary.get("train_window", ""))
    available_windows = {
        "expanding" if window is None else f"rolling_{int(window)}y"
        for window in train_windows
    }
    if feature_set not in requested_families:
        raise ValueError(f"primary feature_set is not configured: {feature_set}")
    if train_window not in available_windows:
        raise ValueError(f"primary train_window is not configured: {train_window}")
    return {"feature_set": feature_set, "train_window": train_window}


def _validate_primary_metric_rows(
    metrics: pd.DataFrame,
    primary_specification: Dict[str, str],
) -> pd.DataFrame:
    if metrics.empty:
        return metrics.copy()
    required = {"feature_set", "train_window", "task", "test_year"}
    if not required <= set(metrics):
        raise ValueError("metric artifact lacks primary identity columns")
    selected = metrics.loc[
        metrics["feature_set"].eq(primary_specification["feature_set"])
        & metrics["train_window"].eq(primary_specification["train_window"])
    ].copy()
    if selected.empty:
        raise ValueError("primary specification produced no metric rows")
    if selected.duplicated(["task", "test_year"]).any():
        raise ValueError("primary specification duplicated task-year metric rows")
    return selected
```

In `run_public_cascade`, resolve the specification after requested families and
windows are known. After `metrics_df` is complete, call
`primary_metrics = _validate_primary_metric_rows(metrics_df, primary_specification)`.
Add to the summary:

```python
        "primary_specification_status": "revision_frozen",
        "primary_specification": primary_specification,
        "primary_metric_rows": int(len(primary_metrics)),
        "visibility_history_metric_rows": int(
            metrics_df["feature_set"].eq("visibility_history").sum()
        ),
        "visibility_history_requested_features": list(VISIBILITY_HISTORY_FEATURES),
        "visibility_history_missing_features": [
            col for col in VISIBILITY_HISTORY_FEATURES
            if col not in families["visibility_history"]
        ],
```

Immediately after the existing `feature_family_summary` is built, make its visibility entry self-describing:

```python
    feature_family_summary["visibility_history"].update(
        {
            "configured_features": list(VISIBILITY_HISTORY_FEATURES),
            "available_features": list(families["visibility_history"]),
            "unavailable_features": [
                column
                for column in VISIBILITY_HISTORY_FEATURES
                if column not in families["visibility_history"]
            ],
        }
    )
```

Extend the existing XBRL-readiness integration fixture so its panel rows also
contain `"size": 100`, its `analysis.feature_sets` is
`["xbrl", "visibility_history"]`, and its inline analysis config includes:

```yaml
  primary_specification:
    feature_set: xbrl
    train_window: expanding
```

Then add these exact assertions after loading that run's summary:

```python
    visibility = summary["feature_family_summary"]["visibility_history"]
    assert visibility["configured_features"] == list(VISIBILITY_HISTORY_FEATURES)
    assert visibility["available_features"] == ["size", "form"]
    assert visibility["unavailable_features"] == [
        field for field in VISIBILITY_HISTORY_FEATURES if field not in {"size", "form"}
    ]
```

Add a matching `analysis.primary_specification` to every other inline public-cascade
YAML fixture: use one of that fixture's requested feature sets and use `expanding`
when its candidate window is `null`. This keeps existing interface tests meaningful
under the newly required contract instead of weakening the resolver for tests.

In every toy integration fixture, read the generated metric CSV and use these exact assertions:

```python
    metrics = pd.read_csv(result["metrics_csv"])
    assert summary["visibility_history_metric_rows"] == int(
        metrics["feature_set"].eq("visibility_history").sum()
    )
    assert summary["primary_metric_rows"] == int(
        (
            metrics["feature_set"].eq(summary["primary_specification"]["feature_set"])
            & metrics["train_window"].eq(
                summary["primary_specification"]["train_window"]
            )
        ).sum()
    )
```

The canonical clean-run audit, not a source-code constant, must then confirm 108 `visibility_history` task-year rows and 27 `all + expanding` primary task-year rows.

Update `config/public_cascade.yaml`:

```yaml
analysis:
  candidate_train_windows: [null, 5, 7, 10]
  min_train_years: 5
  feature_sets: ["metadata", "xbrl", "auditor", "oversight", "visibility_history", "all"]
  primary_specification:
    feature_set: "all"
    train_window: "expanding"
```

Update every test fixture YAML that calls `run_public_cascade` by adding this mapping under its existing `analysis` block, substituting only the fixture's already-declared family when it intentionally omits `all`:

```yaml
  primary_specification:
    feature_set: "all"
    train_window: "expanding"
```

For the existing XBRL-only fixture, use `feature_set: "xbrl"`; for metadata-only fixtures, use `feature_set: "metadata"`. All use `train_window: "expanding"` because their candidate list contains `null`.

- [ ] **Step 5: Run the public-cascade interface suite**

Run:

```bash
uv run pytest -q tests/test_public_cascade_interfaces.py
```

Expected: PASS, including serial/parallel determinism and all fixture runs.

- [ ] **Step 6: Commit the public-model contract**

```bash
git add config/public_cascade.yaml src/public_cascade.py tests/test_public_cascade_interfaces.py
git commit -m "feat(research): freeze public reporting specification"
```

---

### Task 4: Emit sequential attrition and distinguish raw versus encoded DML controls

**Files:**
- Modify: `src/public_cascade.py:103-117, 313-518, 704-1078`
- Modify: `tests/test_public_cascade_interfaces.py`
- Modify: `src/construct_overlap.py:1043-1075`
- Modify: `tests/test_construct_overlap.py`

**Interfaces:**
- Produces: `_sample_attrition(...) -> pd.DataFrame`, `public_sample_attrition.csv`, DML columns `n_raw_controls`, `n_encoded_controls`, and compatibility `n_controls`.
- Later consumers: manuscript-package Table 18, DML table notes, canonical-run verifier.

- [ ] **Step 1: Write failing attrition and DML-dimension tests**

Add:

```python
def test_sample_attrition_is_sequential_and_task_specific() -> None:
    panel = pd.DataFrame(
        {
            "fiscal_year": [2010, 2011, 2011, 2011, 2011],
            "is_domestic_us_gaap_proxy": [1, 0, 1, 1, 1],
            "censored_365": [0, 0, 1, 0, 0],
            "label_comment_thread_365": [0, 0, 0, 1, 0],
            "label_amendment_365": [0, 0, 0, 0, 1],
            "label_8k_402_365": [0, 0, 0, 1, 0],
            "k402_item_metadata_unknown_365": [0, 0, 0, 1, 0],
        }
    )

    attrition = _sample_attrition(
        panel,
        start_year=2011,
        end_year=2024,
        domestic_only=True,
    ).set_index("stage")

    assert attrition.loc["source_issuer_origin", "n_rows"] == 5
    assert attrition.loc["fiscal_year_2011_2024", "n_rows"] == 4
    assert attrition.loc["domestic_us_gaap_proxy", "n_rows"] == 3
    assert attrition.loc["observable_365_day_horizon", "n_rows"] == 2
    assert attrition.loc["eligible_comment_thread", "n_rows"] == 2
    assert attrition.loc["eligible_8k_402", "n_rows"] == 1


def test_public_opacity_dml_uses_public_labels_not_benchmark_misstatement() -> None:
    rows = []
    for year in range(2011, 2017):
        for issuer_id in range(12):
            opaque = int(issuer_id % 3 == 0)
            rows.append(
                {
                    "issuer_cik": f"{issuer_id:010d}",
                    "accession": f"{issuer_id:010d}-{year}-000001",
                    "origin_date": f"{year + 1}-03-01",
                    "fiscal_year": year,
                    "form": "10-K",
                    "sic": 1200 + issuer_id,
                    "is_domestic_us_gaap_proxy": 1,
                    "xbrl_coverage_assets": 1 - opaque,
                    "note_text_count": 0 if opaque else 3,
                    "xbrl_ratio_leverage": 0.1 + issuer_id / 100,
                    "prior_filing_count": year - 2010,
                    "label_comment_thread_365": int(
                        opaque or (year + issuer_id) % 7 == 0
                    ),
                    "label_amendment_365": int(opaque and year % 2 == 0),
                    "label_8k_402_365": int(opaque and issuer_id % 2 == 0),
                    "censored_365": 0,
                }
            )
    rows.append(
        {
            **rows[0],
            "issuer_cik": "9999999999",
            "accession": "9999999999-2011-000001",
            "censored_365": pd.NA,
        }
    )
    panel = pd.DataFrame(rows)
    scored, components = build_public_missingness_density_score(panel)
    dml, meta = fit_public_opacity_dml(
        scored,
        outcomes=["comment_thread", "amendment", "8k_402"],
        seed=42,
        n_splits=3,
        max_iter=5,
    )

    assert components
    assert set(dml["status"]) == {"fit"}
    assert (dml["n_obs"] == len(rows) - 1).all()
    assert (dml["n_raw_controls"] == len(meta["control_columns"])).all()
    assert (dml["n_encoded_controls"] == dml["n_controls"]).all()
    assert set(dml["n_controls_definition"]) == {"encoded_nuisance_columns"}
    assert meta["n_raw_controls"] == len(meta["control_columns"])
    assert meta["n_controls_definition"] == "encoded_nuisance_columns"
    for row in dml.itertuples(index=False):
        assert meta["n_encoded_controls_by_outcome"][row.outcome] == row.n_encoded_controls
```

Import `_sample_attrition` in the test module. Replace the existing DML test with the complete version above so no hidden fixture supplies model columns.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
uv run pytest -q tests/test_public_cascade_interfaces.py \
  -k 'sample_attrition or uses_public_labels_not_benchmark_misstatement'
```

Expected: FAIL because the helper and fields are absent.

- [ ] **Step 3: Implement the sequential attrition helper**

Add after `_filter_main_sample`:

```python
def _sample_attrition(
    panel: pd.DataFrame,
    *,
    start_year: int,
    end_year: int,
    domestic_only: bool,
) -> pd.DataFrame:
    work = panel.copy()
    rows = [{"stage": "source_issuer_origin", "n_rows": int(len(work)), "task": "all"}]
    fiscal_year = pd.to_numeric(work["fiscal_year"], errors="coerce")
    work = work.loc[fiscal_year.between(start_year, end_year)].copy()
    rows.append(
        {"stage": f"fiscal_year_{start_year}_{end_year}", "n_rows": int(len(work)), "task": "all"}
    )
    if domestic_only and "is_domestic_us_gaap_proxy" in work:
        work = work.loc[
            pd.to_numeric(work["is_domestic_us_gaap_proxy"], errors="coerce").eq(1)
        ].copy()
    rows.append({"stage": "domestic_us_gaap_proxy", "n_rows": int(len(work)), "task": "all"})
    observable = work.loc[
        pd.to_numeric(work["censored_365"], errors="coerce").fillna(1).eq(0)
    ].copy()
    rows.append(
        {"stage": "observable_365_day_horizon", "n_rows": int(len(observable)), "task": "all"}
    )
    for task_name, meta in TASKS.items():
        excluded = _task_exclusion_mask(
            observable,
            task_name=task_name,
            label_col=str(meta["label"]),
        )
        rows.append(
            {
                "stage": f"eligible_{task_name}",
                "n_rows": int((~excluded).sum()),
                "task": task_name,
            }
        )
    return pd.DataFrame(rows)
```

Call it on the unfiltered panel in `run_public_cascade`, write it to `out_dir / "public_sample_attrition.csv"`, include the rows in `summary["sample_attrition"]`, and return the path as `sample_attrition_csv`.

After calculating attrition and applying the existing year/domestic filter, set
the analysis panel to rows with an explicitly observed horizon only:

```python
    panel = panel.loc[
        pd.to_numeric(panel["censored_365"], errors="coerce").eq(0)
    ].copy()
```

Do this before feature-family inference, task folds, and DML so the reported
observable-horizon parent is also the shared analysis parent. In
`fit_public_opacity_dml`, independently remove the current missing-as-observed
fallback as a defensive invariant:

```python
        uncensored = pd.to_numeric(
            panel_with_score[censor_col], errors="coerce"
        ).eq(0)
```

- [ ] **Step 4: Separate DML dimensions without changing the estimator**

Change the DML base row and fitted row to use:

```python
        base_row = {
            # existing fields remain unchanged
            "n_raw_controls": int(len(controls)),
            "n_encoded_controls": np.nan,
            "n_controls": np.nan,
            "n_controls_definition": "encoded_nuisance_columns",
            "n_opacity_components": int(len(opacity_components)),
        }
```

After `_public_dml_matrix(...)`:

```python
        n_encoded_controls = int(len(used_controls))
        encoded_counts[outcome] = n_encoded_controls
```

For fitted and post-matrix skipped rows, set:

```python
                "n_raw_controls": int(len(controls)),
                "n_encoded_controls": n_encoded_controls,
                "n_controls": n_encoded_controls,
                "n_controls_definition": "encoded_nuisance_columns",
```

Every pre-matrix skipped row must retain the base-row values `n_raw_controls=len(controls)`, `n_encoded_controls=NaN`, `n_controls=NaN`, and the explicit definition. Every post-matrix skipped row must report the actual encoded count. Add this pre-matrix branch test after the complete panel construction from Step 1:

```python
    degenerate = scored.assign(label_amendment_365=0)
    skipped, skipped_meta = fit_public_opacity_dml(
        degenerate,
        outcomes=["amendment"],
        seed=42,
        n_splits=3,
        max_iter=5,
    )
    skipped_row = skipped.iloc[0]
    assert skipped_row["status"] == "skipped_one_class_or_too_small"
    assert skipped_row["n_raw_controls"] == len(skipped_meta["control_columns"])
    assert pd.isna(skipped_row["n_encoded_controls"])
    assert pd.isna(skipped_row["n_controls"])
    assert skipped_row["n_controls_definition"] == "encoded_nuisance_columns"
```

Initialize `encoded_counts: Dict[str, int] = {}` before the outcome loop and emit:

```python
    meta = {
        "treatment": "missingness_density_score",
        "opacity_components": opacity_components,
        "control_columns": controls,
        "n_opacity_components": int(len(opacity_components)),
        "n_raw_controls": int(len(controls)),
        "n_encoded_controls_by_outcome": encoded_counts,
        "n_controls": max(encoded_counts.values(), default=0),
        "n_controls_definition": "encoded_nuisance_columns",
        "control_columns_definition": "raw_controls_before_encoding",
    }
```

For the disabled DML branch, emit the same schema with empty control/component lists, `n_raw_controls=0`, `n_encoded_controls_by_outcome={}`, `n_controls=0`, `n_controls_definition="encoded_nuisance_columns"`, and `control_columns_definition="raw_controls_before_encoding"`; do not return the old ambiguous metadata shape.

Update `_opacity_refresh` in `src/construct_overlap.py` to replace ambiguous `n_controls_meta` with:

```python
    encoded_by_outcome = dict(meta.get("n_encoded_controls_by_outcome", {}))
    dml["n_raw_controls_meta"] = int(meta.get("n_raw_controls", 0))
    dml["n_encoded_controls_meta"] = dml["outcome"].map(encoded_by_outcome)
    dml["n_opacity_components_meta"] = int(meta.get("n_opacity_components", 0))
    dml["n_controls_definition_meta"] = meta.get("n_controls_definition")
```

Replace the toy opacity fixture with two rows whose `outcome` values are `comment_thread` and `amendment`, `n_raw_controls=[60, 60]`, `n_encoded_controls=[64, 63]`, `n_controls=[64, 63]`, `n_controls_definition="encoded_nuisance_columns"`, and `n_opacity_components=[17, 17]`. Write this exact metadata:

```python
{
    "n_raw_controls": 60,
    "n_encoded_controls_by_outcome": {
        "comment_thread": 64,
        "amendment": 63,
    },
    "n_opacity_components": 17,
    "n_controls_definition": "encoded_nuisance_columns",
}
```

Then extend `test_construct_overlap_end_to_end_writes_validation_artifacts` with:

```python
    refreshed = pd.read_csv(
        study / "opacity_validation_refresh" / "opacity_diagnostics_summary.csv"
    ).set_index("outcome")
    assert set(refreshed["n_raw_controls_meta"]) == {60}
    assert refreshed["n_encoded_controls_meta"].to_dict() == {
        "comment_thread": 64,
        "amendment": 63,
    }
    assert set(refreshed["n_opacity_components_meta"]) == {17}
    assert set(refreshed["n_controls_definition_meta"]) == {
        "encoded_nuisance_columns"
    }
```

- [ ] **Step 5: Run the focused and full public-cascade tests**

Run:

```bash
uv run pytest -q tests/test_public_cascade_interfaces.py
uv run pytest -q tests/test_construct_overlap.py -k opacity
```

Expected: PASS and the existing DML behavior remains unchanged apart from explicit dimension names.

- [ ] **Step 6: Commit the accounting outputs**

```bash
git add src/public_cascade.py src/construct_overlap.py tests/test_public_cascade_interfaces.py tests/test_construct_overlap.py
git commit -m "feat(research): report sample attrition and dml dimensions"
```

---

### Task 5: Carry public-lake and Form AP provenance into the study manifest

**Files:**
- Modify: `config/study.yaml:8-17`
- Modify: `src/provenance.py`
- Modify: `scripts/run_study.py:78-191, 259-390`
- Modify: `tests/test_provenance.py`

**Interfaces:**
- Consumes: `silver/public_lake_run_metadata.json` and `silver/form_ap_source_metadata.json`.
- Produces: pathless `manifest["public_lake_provenance"]`, a URL/hash-only `source_metadata_inventory`, plus hashes for both metadata files under general input provenance.

- [ ] **Step 1: Write the failing provenance-reduction test**

Add `import json`, extend the `src.provenance` import with
`public_lake_provenance`, and import `_claim_maturity` from `scripts.run_study`.
Then add to `tests/test_provenance.py`:

```python
def test_public_lake_provenance_is_pathless_and_keeps_form_ap_hashes(tmp_path: Path) -> None:
    run_metadata = tmp_path / "public_lake_run_metadata.json"
    form_ap_metadata = tmp_path / "form_ap_source_metadata.json"
    source_sidecar = tmp_path / "bronze" / "form-ap" / "FirmFilings.zip.meta.json"
    source_sidecar.parent.mkdir(parents=True)
    source_sidecar.write_text(
        json.dumps(
            {
                "source_name": "form-ap",
                "source_url": "https://example.invalid/FirmFilings.zip",
                "downloaded_at_utc": "2026-07-06T00:00:00+00:00",
                "sha256": "payload-hash",
                "size_bytes": 123,
                "parser_version": "public-lake-v1",
                "schema_version": "public-lake-v1",
            }
        ),
        encoding="utf-8",
    )
    run_metadata.write_text(
        json.dumps(
            {
                "as_of_date": "2026-07-06",
                "fresh_build": True,
                "provenance": {
                    "commit_sha": "abc123",
                    "dirty": False,
                    "config_hash": "config-hash",
                    "input_hash": "input-hash",
                    "uv_lock_hash": "lock-hash",
                    "input_files": [
                        {
                            "path": str(source_sidecar),
                            "sha256": "sidecar-hash",
                            "size_bytes": source_sidecar.stat().st_size,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    form_ap_metadata.write_text(
        json.dumps(
            {
                "source_kind": "verified_zip_member",
                "archive_sha256": "archive-hash",
                "member": "FirmFilings.csv",
                "member_sha256": "member-hash",
            }
        ),
        encoding="utf-8",
    )

    reduced = public_lake_provenance(run_metadata, form_ap_metadata)

    assert reduced["as_of_date"] == "2026-07-06"
    assert reduced["git_dirty"] is False
    assert reduced["form_ap"]["archive_sha256"] == "archive-hash"
    assert reduced["source_metadata_inventory"] == [
        {
            "metadata_file": "form-ap/FirmFilings.zip.meta.json",
            "metadata_sha256": "sidecar-hash",
            "source_name": "form-ap",
            "source_url": "https://example.invalid/FirmFilings.zip",
            "downloaded_at_utc": "2026-07-06T00:00:00+00:00",
            "payload_sha256": "payload-hash",
            "payload_size_bytes": 123,
            "parser_version": "public-lake-v1",
            "schema_version": "public-lake-v1",
        }
    ]
    assert str(tmp_path) not in json.dumps(reduced)


def test_claim_maturity_is_controlled_by_component_status() -> None:
    maturity = _claim_maturity(
        {
            "public_cascade": {"status": "complete"},
            "construct_overlap": {"run_status": "complete"},
        }
    )

    assert maturity == {
        "public_prediction": "reportable",
        "feature_and_window_sensitivity": "supporting",
        "construct_alignment": "supporting",
        "opacity_dml": "diagnostic",
    }
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
uv run pytest -q tests/test_provenance.py -k public_lake_provenance
```

Expected: FAIL because `public_lake_provenance` does not exist.

- [ ] **Step 3: Implement the pathless reducer**

Add to `src/provenance.py`:

```python
def _source_metadata_inventory(input_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for record in input_files:
        path = Path(str(record.get("path", "")))
        parts = path.parts
        relative_name = path.name
        if "bronze" in parts:
            relative_name = "/".join(parts[parts.index("bronze") + 1 :])
        item: dict[str, Any] = {
            "metadata_file": relative_name,
            "metadata_sha256": record.get("sha256"),
        }
        if path.name.endswith(".meta.json") and path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            item.update(
                {
                    "source_name": payload.get("source_name"),
                    "source_url": payload.get("source_url"),
                    "downloaded_at_utc": payload.get("downloaded_at_utc"),
                    "payload_sha256": payload.get("sha256"),
                    "payload_size_bytes": payload.get("size_bytes"),
                    "parser_version": payload.get("parser_version"),
                    "schema_version": payload.get("schema_version"),
                }
            )
        inventory.append(item)
    return sorted(inventory, key=lambda item: str(item["metadata_file"]))


def public_lake_provenance(
    run_metadata_path: Path,
    form_ap_metadata_path: Path,
) -> dict[str, Any]:
    run_metadata = json.loads(Path(run_metadata_path).read_text(encoding="utf-8"))
    form_ap = json.loads(Path(form_ap_metadata_path).read_text(encoding="utf-8"))
    provenance = dict(run_metadata.get("provenance", {}))
    return {
        "as_of_date": run_metadata.get("as_of_date"),
        "fresh_build": bool(run_metadata.get("fresh_build")),
        "commit_sha": provenance.get("commit_sha"),
        "git_dirty": provenance.get("dirty"),
        "config_hash": provenance.get("config_hash"),
        "input_hash": provenance.get("input_hash"),
        "uv_lock_hash": provenance.get("uv_lock_hash"),
        "source_metadata_inventory": _source_metadata_inventory(
            list(provenance.get("input_files", []))
        ),
        "form_ap": {
            "source_kind": form_ap.get("source_kind"),
            "archive_sha256": form_ap.get("archive_sha256"),
            "member": form_ap.get("member"),
            "member_sha256": form_ap.get("member_sha256"),
        },
    }
```

- [ ] **Step 4: Wire the stable metadata inputs into `run_study.py`**

Add to `config/study.yaml`:

```yaml
inputs:
  public_lake_run_metadata: "${LAKE_SILVER_DIR}/public_lake_run_metadata.json"
  form_ap_source_metadata: "${LAKE_SILVER_DIR}/form_ap_source_metadata.json"
```

Resolve both paths beside the existing issuer panel and include them in `input_provenance(...)`. Capture the public-cascade return value, read its summary JSON, and add both the reduced lake provenance and the public-cascade evidence identity:

```python
def _claim_maturity(components: dict[str, Any]) -> dict[str, str]:
    public_complete = components.get("public_cascade", {}).get("status") == "complete"
    construct_complete = (
        components.get("construct_overlap", {}).get("run_status") == "complete"
    )
    return {
        "public_prediction": "reportable" if public_complete else "deferred",
        "feature_and_window_sensitivity": "supporting" if public_complete else "deferred",
        "construct_alignment": "supporting" if construct_complete else "deferred",
        "opacity_dml": "diagnostic" if public_complete else "deferred",
    }
```

Inside `main()`, in the existing non-skipped public-cascade branch, replace the
unassigned `run_public_cascade(...)` call with this result capture and component
assignment:

```python
    public_cascade_result = run_public_cascade(
        config_path=args.public_cascade_config,
        issuer_origin_panel_path=issuer_origin_panel,
        out_dir=public_cascade_out,
        parallel_jobs=args.parallel_jobs,
        model_threads=args.model_threads,
        seed_policy=args.seed_policy.replace("-", "_") if args.seed_policy else None,
    )
    public_cascade_summary = json.loads(
        Path(public_cascade_result["summary_json"]).read_text(encoding="utf-8")
    )
    manifest["components"]["public_cascade"] = {
        "status": "complete",
        "out_dir": str(public_cascade_out),
        "summary_json": str(public_cascade_result["summary_json"]),
        "sample_attrition_csv": str(public_cascade_result["sample_attrition_csv"]),
        "primary_specification": public_cascade_summary["primary_specification"],
    }
```

After every component, including construct overlap, has written its final status
but immediately before the existing final manifest write, add:

```python
    manifest["public_lake_provenance"] = public_lake_provenance(
        public_lake_run_metadata,
        form_ap_source_metadata,
    )
    manifest["claim_maturity"] = _claim_maturity(manifest["components"])
```

Do not run the component twice. Import the reducer from `src.provenance`. Fail
with `FileNotFoundError` if either metadata file is missing for a non-skipped
public-cascade run.

- [ ] **Step 5: Run provenance tests and the source quality gate**

Run:

```bash
uv run pytest -q tests/test_provenance.py
just check
```

Expected: both PASS.

- [ ] **Step 6: Commit the study-provenance contract**

```bash
git add config/study.yaml src/provenance.py scripts/run_study.py tests/test_provenance.py
git commit -m "feat(provenance): carry public lake evidence into study runs"
```

---

### Task 6: Verify this sub-project against the approved design

**Files:**
- Review only: all files changed in Tasks 1-5
- Review against: `docs/superpowers/specs/2026-07-10-reporting-risk-cascade-revision-design.md`

**Interfaces:**
- Produces: a clean, fully tested source branch ready for the reporting/reproducibility plan.

- [ ] **Step 1: Run all source checks from a clean index**

Run:

```bash
just check
git diff --check HEAD~5..HEAD
git status --short
```

Expected: `just check` PASS, no whitespace errors, and no uncommitted files.

- [ ] **Step 2: Audit the frozen values and forbidden expansion**

Run:

```bash
! rg -n '2026-05-26|preregistered primary|pre-registered primary|historically pre-specified|pre-specified before (seeing|observing)' \
  config src scripts justfile docs/paper_plan.md tests
rg -n 'primary_specification|visibility_history|n_raw_controls|n_encoded_controls|sample_attrition|form_ap_source_metadata' \
  config src scripts tests
```

Expected: the first command returns no stale date or historical-registration language; the second finds each new contract in implementation and tests.

- [ ] **Step 3: Record the handoff facts**

Record in the execution log:

```text
source_checks=pass
public_vintage=2026-07-06
primary_specification=all+expanding
visibility_estimator=existing_xgboost
new_outcomes=none
new_dependencies=none
```

Do not write empirical counts yet; the clean run is authoritative.
