# Reporting and Reproducibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make construct alignment, manuscript-package tables/figures, the results snapshot, stable docs, canonical-run validation, and the anonymized reviewer archive consume one declared evidence contract.

**Architecture:** Put primary alignment keys in `config/study.yaml`, mark primary/exploratory rows in the construct artifacts, and let the manuscript package own Table 3, Table 9, Figure 1, and Figure 5 selection. The snapshot reads those generated tables instead of reselecting rows. Two small standard-library CLIs validate a canonical run and build a restricted-data-safe reviewer ZIP.

**Tech Stack:** Python 3.13, pandas, NumPy, DuckDB, matplotlib, PyYAML, pytest, zipfile, subprocess, pathlib, just, MkDocs.

## Global Constraints

- Complete the evidence-pipeline plan first; consume its new summary, attrition, DML, and provenance fields exactly.
- Execute in the same isolated source worktree as the completed evidence plan, or create a new one with `superpowers:using-git-worktrees` from the integrated evidence commit; never edit the sibling manuscript in this plan.
- Freeze the two approved construct-alignment rows; never select Table 9 by maximum lift.
- Bootstrap primary rows plus the top five exploratory rows in each direction, seed 42, 1,000 replicates.
- Table 3 and Figure 1 use only `all + expanding`; Tables 4 and 14 remain grid sensitivities.
- Table 9 and Figure 5 use only declared primary alignment rows.
- `results_snapshot.md` is generated after the manuscript package and must expose dirty/noncanonical provenance honestly.
- Keep volatile empirical values out of `docs/faq.md` and `docs/paper_plan.md`.
- Use only the Python standard library for the reviewer ZIP builder; add no dependency.
- Exclude benchmark data, WRDS rows, public-lake payloads, secrets, local paths, and user-identifying paths from the reviewer ZIP.
- Preserve historical empirical runs; this plan changes generators and validation, not old artifacts.
- Use red-green-refactor TDD and frequent commits.

---

### Task 1: Freeze construct-alignment keys and bootstrap scope

**Files:**
- Modify: `config/study.yaml`
- Modify: `src/construct_overlap.py:620-710, 750-950, 1184-1310`
- Modify: `scripts/run_study.py:259-490`
- Modify: `scripts/run_construct_overlap.py`
- Modify: `tests/test_construct_overlap.py`

**Interfaces:**
- Consumes: `construct_alignment` config with `public_to_benchmark_primary` and `benchmark_to_public_primary` mappings.
- Produces: alignment CSV flags `is_primary`, `is_exploratory_top5`; a manifest `primary_alignment`; exact primary rows with intervals.

- [ ] **Step 1: Write failing selection and bootstrap-union tests**

Add `import pytest` and `import src.construct_overlap as construct_overlap`.
Extend the existing `from src.construct_overlap import (...)` list with
`_finalize_alignment_rows` and `_select_unique_row`, then add these direct helper
tests in `tests/test_construct_overlap.py`:

```python
TEST_ALIGNMENT_CONFIG = {
    "bootstrap_seed": 42,
    "bootstrap_reps": 1000,
    "exploratory_top_n": 5,
    "public_to_benchmark_primary": {
        "model_id": "public_cascade",
        "task": "8k_402",
        "feature_set": "all",
        "train_window": "expanding",
        "label_mode": "benchmark_naive",
        "score_aggregation": "mean",
        "bridge_tier": "high_confidence",
    },
    "benchmark_to_public_primary": {
        "model_id": "benchmark_xgb",
        "target_public_label": "label_8k_402_365",
        "feature_set": "benchmark_all",
        "train_window": "expanding",
        "label_mode": "naive",
        "score_aggregation": "benchmark_score",
        "bridge_tier": "high_confidence",
    },
}
```

Add `alignment_config=TEST_ALIGNMENT_CONFIG` to all four existing direct
`run_construct_overlap(...)` calls in this test module. The argument remains
required in production; do not add a hidden default that could revive post-hoc
selection.

Make `_write_toy_study` contain a valid declared primary row and enough positives
for the mandatory interval: change its main loop to `range(80)`, benchmark
positives to `idx < 32`, comment-thread positives to `idx < 40`, amendment
positives to `idx < 36`, and Item 4.02 positives to `idx < 30`; change public
prediction `task` to `8k_402`; and change public, benchmark, and peer train-window
values from `rolling_5y` to `expanding`. Do not lower
`BOOTSTRAP_POSITIVE_THRESHOLD` merely to make the fixture pass.

```python
def test_select_unique_row_ignores_higher_lift_distractor() -> None:
    frame = pd.DataFrame(
        [
            {
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "expanding",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "bridge_tier": "high_confidence",
                "top_decile_lift": 2.0,
            },
            {
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "rolling_7y",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "bridge_tier": "high_confidence",
                "top_decile_lift": 9.0,
            },
        ]
    )
    keys = {
        "model_id": "public_cascade",
        "task": "8k_402",
        "feature_set": "all",
        "train_window": "expanding",
        "label_mode": "benchmark_naive",
        "score_aggregation": "mean",
        "bridge_tier": "high_confidence",
    }

    selected = _select_unique_row(frame, keys=keys, direction="public_to_benchmark")

    assert selected["train_window"] == "expanding"
    assert selected["top_decile_lift"] == 2.0


def test_bootstrap_union_includes_primary_outside_top_five(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "model_id": "m",
            "task": f"task_{idx}",
            "metric_status": "fit",
            "top_decile_lift": float(10 - idx),
        }
        for idx in range(7)
    ]
    frame = pd.DataFrame(
        {
            "model_id": ["m"] * 14,
            "task": [f"task_{idx}" for idx in range(7) for _ in range(2)],
            "target": [0, 1] * 7,
            "score": [0.1, 0.9] * 7,
        }
    )
    monkeypatch.setattr(
        construct_overlap,
        "_bootstrap_lift_ci",
        lambda y, score, *, reps, seed: (1.0, 2.0),
    )

    finalized = _finalize_alignment_rows(
        rows,
        frame=frame,
        group_cols=["model_id", "task"],
        target_col="target",
        score_col="score",
        primary_keys={"model_id": "m", "task": "task_6"},
        exploratory_top_n=5,
        direction="public_to_benchmark",
        bootstrap_seed=42,
        bootstrap_reps=1000,
    )

    assert all(
        pd.notna(finalized[idx]["top_decile_lift_ci_low"])
        for idx in [0, 1, 2, 3, 4, 6]
    )
    assert pd.isna(finalized[5].get("top_decile_lift_ci_low", np.nan))
```

Add these missing/duplicate-key tests:

```python
def test_select_unique_row_rejects_missing_primary() -> None:
    frame = pd.DataFrame({"model_id": ["other"], "task": ["8k_402"]})
    with pytest.raises(ValueError, match="matched 0"):
        _select_unique_row(
            frame,
            keys={"model_id": "public_cascade", "task": "8k_402"},
            direction="public_to_benchmark",
        )


def test_select_unique_row_rejects_duplicate_primary() -> None:
    frame = pd.DataFrame(
        {"model_id": ["public_cascade", "public_cascade"], "task": ["8k_402"] * 2}
    )
    with pytest.raises(ValueError, match="matched 2"):
        _select_unique_row(
            frame,
            keys={"model_id": "public_cascade", "task": "8k_402"},
            direction="public_to_benchmark",
        )
```

Extend the existing end-to-end construct test after reading `construct_overlap_manifest.json`:

```python
    primary = construct_manifest["primary_alignment"]
    assert primary["public_to_benchmark_count"] == 1
    assert primary["benchmark_to_public_count"] == 1
    assert primary["public_to_benchmark"]["train_window"] == "expanding"
    assert primary["benchmark_to_public"]["model_id"] == "benchmark_xgb"
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
uv run pytest -q tests/test_construct_overlap.py \
  -k 'select_unique_row or bootstrap_union or primary_alignment'
```

Expected: FAIL because the helpers, flags, and manifest contract are absent.

- [ ] **Step 3: Add the exact configuration**

Add to `config/study.yaml`:

```yaml
construct_alignment:
  bootstrap_seed: 42
  bootstrap_reps: 1000
  exploratory_top_n: 5
  public_to_benchmark_primary:
    model_id: "public_cascade"
    task: "8k_402"
    feature_set: "all"
    train_window: "expanding"
    label_mode: "benchmark_naive"
    score_aggregation: "mean"
    bridge_tier: "high_confidence"
  benchmark_to_public_primary:
    model_id: "benchmark_xgb"
    target_public_label: "label_8k_402_365"
    feature_set: "benchmark_all"
    train_window: "expanding"
    label_mode: "naive"
    score_aggregation: "benchmark_score"
    bridge_tier: "high_confidence"
```

- [ ] **Step 4: Implement unique selection and row flags**

Add to `src/construct_overlap.py`:

```python
def _row_mask(frame: pd.DataFrame, keys: dict[str, object]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for column, value in keys.items():
        if column not in frame.columns:
            raise ValueError(f"alignment key column is missing: {column}")
        mask &= frame[column].isna() if pd.isna(value) else frame[column].eq(value)
    return mask


def _select_unique_row(
    frame: pd.DataFrame,
    *,
    keys: dict[str, object],
    direction: str,
) -> pd.Series:
    selected = frame.loc[_row_mask(frame, keys)]
    if len(selected) != 1:
        raise ValueError(
            f"{direction} primary alignment must match exactly one row; matched {len(selected)}"
        )
    return selected.iloc[0]


def _mark_alignment_rows(
    frame: pd.DataFrame,
    *,
    primary_keys: dict[str, object],
    exploratory_top_n: int,
    direction: str,
) -> pd.DataFrame:
    out = frame.copy()
    primary = _select_unique_row(out, keys=primary_keys, direction=direction)
    out["is_primary"] = False
    out.loc[primary.name, "is_primary"] = True
    fitted = out.loc[
        out["metric_status"].eq("fit")
        & pd.to_numeric(out["top_decile_lift"], errors="coerce").notna()
    ]
    top_index = fitted.nlargest(exploratory_top_n, "top_decile_lift").index
    out["is_exploratory_top5"] = out.index.isin(top_index)
    return out
```

Replace the top-only bootstrap function with a union selector:

```python
def _add_bootstrap_intervals_to_selected_rows(
    rows: list[dict[str, Any]],
    *,
    frame: pd.DataFrame,
    group_cols: Sequence[str],
    target_col: str,
    score_col: str,
    bootstrap_seed: int,
    bootstrap_reps: int,
) -> None:
    for idx, row in enumerate(rows):
        if not (row.get("is_primary") or row.get("is_exploratory_top5")):
            continue
        mask = _row_mask(frame, {column: row.get(column) for column in group_cols})
        sample = frame.loc[mask]
        ci_low, ci_high = _bootstrap_lift_ci(
            sample[target_col].to_numpy(),
            sample[score_col].to_numpy(),
            reps=bootstrap_reps,
            seed=bootstrap_seed,
        )
        rows[idx]["top_decile_lift_ci_low"] = ci_low
        rows[idx]["top_decile_lift_ci_high"] = ci_high


def _finalize_alignment_rows(
    rows: list[dict[str, Any]],
    *,
    frame: pd.DataFrame,
    group_cols: Sequence[str],
    target_col: str,
    score_col: str,
    primary_keys: dict[str, object],
    exploratory_top_n: int,
    direction: str,
    bootstrap_seed: int,
    bootstrap_reps: int,
) -> list[dict[str, Any]]:
    marked = _mark_alignment_rows(
        pd.DataFrame(rows),
        primary_keys=primary_keys,
        exploratory_top_n=exploratory_top_n,
        direction=direction,
    )
    finalized = marked.to_dict("records")
    _add_bootstrap_intervals_to_selected_rows(
        finalized,
        frame=frame,
        group_cols=group_cols,
        target_col=target_col,
        score_col=score_col,
        bootstrap_seed=bootstrap_seed,
        bootstrap_reps=bootstrap_reps,
    )
    return finalized
```

Remove `bootstrap_top_rows` and the `_add_bootstrap_intervals_to_top_rows(...)` call from `_score_metric_rows`; it must compute unbootstrapped metric rows only. Then finalize the two declared search universes explicitly:

```python
    main_rows = _finalize_alignment_rows(
        main_rows,
        frame=main,
        group_cols=public_group_cols,
        target_col="benchmark_label",
        score_col="score",
        primary_keys=alignment_config["public_to_benchmark_primary"],
        exploratory_top_n=int(alignment_config["exploratory_top_n"]),
        direction="public_to_benchmark",
        bootstrap_seed=int(alignment_config["bootstrap_seed"]),
        bootstrap_reps=int(alignment_config["bootstrap_reps"]),
    )

    rows = _finalize_alignment_rows(
        rows,
        frame=base,
        group_cols=reciprocal_group_cols,
        target_col="target_label",
        score_col="score",
        primary_keys=alignment_config["benchmark_to_public_primary"],
        exploratory_top_n=int(alignment_config["exploratory_top_n"]),
        direction="benchmark_to_public",
        bootstrap_seed=int(alignment_config["bootstrap_seed"]),
        bootstrap_reps=int(alignment_config["bootstrap_reps"]),
    )
```

Define `public_group_cols` and `reciprocal_group_cols` once and pass the same lists to `_score_metric_rows` and `_finalize_alignment_rows`. Leave the broader public sensitivity artifact unbootstrapped. This ordering guarantees flags exist before interval selection; deduplication is automatic because each row is visited once.

Add `alignment_config: dict[str, Any]` to both `_public_ranking(...)` and
`_reciprocal_alignment(...)`. In `run_construct_overlap(...)`, pass its required
`alignment_config` argument unchanged into both helpers:

```python
        public_ranking, _ = _public_ranking(
            con,
            required["public_predictions"],
            out_dir,
            bridge_source,
            alignment_config=alignment_config,
        )
        reciprocal = _reciprocal_alignment(
            con,
            benchmark_predictions_path=required["benchmark_predictions"],
            peer_predictions_path=(
                study_dir
                / "peer_comparison"
                / "detected_misstatement_model_family_predictions.parquet"
            ),
            out_dir=out_dir,
            bridge_source=bridge_source,
            alignment_config=alignment_config,
        )
```

- [ ] **Step 5: Wire config through both entry points and manifest provenance**

Change `run_construct_overlap(...)` to accept:

```python
alignment_config: dict[str, Any],
```

Pass `cfg["construct_alignment"]` from `scripts/run_study.py`. Add `--config` to `scripts/run_construct_overlap.py`, load `config/study.yaml`, and pass the same block.

Select the two primary rows again from the finalized frames and validate their
reporting evidence before constructing the manifest:

```python
def _primary_evidence(row: pd.Series, *, direction: str) -> dict[str, object]:
    if row.get("metric_status") != "fit":
        raise ValueError(f"{direction} primary alignment is not fitted")
    values = {
        "top_decile_lift": float(row.get("top_decile_lift", np.nan)),
        "ci_low": float(row.get("top_decile_lift_ci_low", np.nan)),
        "ci_high": float(row.get("top_decile_lift_ci_high", np.nan)),
    }
    if not all(np.isfinite(value) for value in values.values()):
        raise ValueError(f"{direction} primary alignment lacks a finite interval")
    if values["ci_low"] > values["ci_high"]:
        raise ValueError(f"{direction} primary alignment interval is reversed")
    return {"metric_status": "fit", **values}


def _exploratory_maximum(
    frame: pd.DataFrame,
    *,
    primary_row: pd.Series,
    key_columns: Sequence[str],
    direction: str,
) -> dict[str, object]:
    fitted = frame.loc[
        frame["metric_status"].eq("fit")
        & pd.to_numeric(frame["top_decile_lift"], errors="coerce").notna()
    ]
    if fitted.empty:
        raise ValueError(f"{direction} has no fitted exploratory rows")
    maximum = fitted.nlargest(1, "top_decile_lift").iloc[0]
    maximum_lift = float(maximum["top_decile_lift"])
    primary_lift = float(primary_row["top_decile_lift"])
    return {
        "keys": {column: str(maximum[column]) for column in key_columns},
        "top_decile_lift": maximum_lift,
        "primary_lift": primary_lift,
        "lift_minus_primary": maximum_lift - primary_lift,
    }


public_primary_keys = dict(alignment_config["public_to_benchmark_primary"])
reciprocal_primary_keys = dict(alignment_config["benchmark_to_public_primary"])
public_primary_row = _select_unique_row(
    public_ranking,
    keys=public_primary_keys,
    direction="public_to_benchmark",
)
reciprocal_primary_row = _select_unique_row(
    reciprocal,
    keys=reciprocal_primary_keys,
    direction="benchmark_to_public",
)
```

Record this exact manifest shape; the key contract and realized evidence are
separate so downstream verification can compare the former without silently
accepting extra fields:

```python
        "primary_alignment": {
            "public_to_benchmark": public_primary_keys,
            "benchmark_to_public": reciprocal_primary_keys,
            "public_to_benchmark_count": int(public_ranking["is_primary"].sum()),
            "benchmark_to_public_count": int(reciprocal["is_primary"].sum()),
        },
        "primary_alignment_evidence": {
            "public_to_benchmark": _primary_evidence(
                public_primary_row, direction="public_to_benchmark"
            ),
            "benchmark_to_public": _primary_evidence(
                reciprocal_primary_row, direction="benchmark_to_public"
            ),
        },
        "exploratory_maxima": {
            "public_to_benchmark": _exploratory_maximum(
                public_ranking,
                primary_row=public_primary_row,
                key_columns=public_group_cols,
                direction="public_to_benchmark",
            ),
            "benchmark_to_public": _exploratory_maximum(
                reciprocal,
                primary_row=reciprocal_primary_row,
                key_columns=reciprocal_group_cols,
                direction="benchmark_to_public",
            ),
        },
        "search_universe_rows": {
            "public_to_benchmark": int(len(public_ranking)),
            "benchmark_to_public": int(len(reciprocal)),
        },
        "interval_scope": "primary_plus_top_5_per_direction",
        "interval_seed": 42,
        "interval_reps": 1000,
```

Extend the end-to-end manifest test to require fitted primary evidence with
finite ordered intervals and to assert, for each direction,
`lift_minus_primary == top_decile_lift - primary_lift` with `pytest.approx`.

- [ ] **Step 6: Run construct-overlap tests**

Run:

```bash
uv run pytest -q tests/test_construct_overlap.py
```

Expected: PASS.

- [ ] **Step 7: Commit the construct-validation contract**

```bash
git add config/study.yaml src/construct_overlap.py scripts/run_study.py scripts/run_construct_overlap.py tests/test_construct_overlap.py
git commit -m "feat(validation): freeze construct alignment evidence"
```

---

### Task 2: Route package headlines through primary public and alignment rows

**Files:**
- Modify: `scripts/build_manuscript_package.py:1-180, 476-575, 695-760, 967-1015, 1160-1625`
- Modify: `tests/test_manuscript_package.py`

**Interfaces:**
- Consumes: public summary primary spec, full public metric grid, `is_primary` alignment flags, attrition CSV, explicit DML dimensions.
- Produces: primary-only Table 3/Figure 1, primary-only Table 9/Figure 5, Table 18 attrition, explicit Table 12 dimensions.

- [ ] **Step 1: Write failing primary-package tests**

Extend the existing `from scripts.build_manuscript_package import (...)` list
with `_package_primary_identity`, `_public_sample_attrition_table`, and
`_select_primary_public_metrics`.
Then add tests that construct a primary row plus higher-performing distractors:

```python
def test_select_primary_public_metrics_excludes_grid_distractors() -> None:
    metrics = pd.DataFrame(
        {
            "feature_set": ["all", "all", "metadata"],
            "train_window": ["expanding", "rolling_7y", "expanding"],
            "task": ["comment_thread"] * 3,
            "test_year": [2021, 2021, 2021],
            "pr_auc": [0.30, 0.90, 0.80],
        }
    )
    summary = {
        "primary_specification": {"feature_set": "all", "train_window": "expanding"}
    }

    selected = _select_primary_public_metrics(metrics, summary)

    assert selected[["feature_set", "train_window", "pr_auc"]].to_dict("records") == [
        {"feature_set": "all", "train_window": "expanding", "pr_auc": 0.30}
    ]


def test_primary_public_package_identity_records_summary_contract() -> None:
    identity = _package_primary_identity(
        {"primary_specification": {"feature_set": "all", "train_window": "expanding"}}
    )

    assert identity == {
        "primary_public_specification": {
            "feature_set": "all",
            "train_window": "expanding",
        }
    }


def test_construct_alignment_uses_is_primary_not_maximum_lift(tmp_path: Path) -> None:
    overlap_dir = tmp_path / "construct_overlap"
    overlap_dir.mkdir()
    common = {
        "bridge_tier": "high_confidence",
        "metric_status": "fit",
        "bridge_source": "wrds",
        "roc_auc": 0.70,
        "pr_auc": 0.04,
        "top_1pct_precision": 0.10,
        "top_5pct_precision": 0.08,
        "top_10pct_precision": 0.06,
        "top_decile_lift_ci_low": 1.20,
        "top_decile_lift_ci_high": 2.80,
    }
    pd.DataFrame(
        [
            {
                **common,
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "expanding",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "n_benchmark_positives_in_overlap": 10,
                "n_benchmark_negatives_in_overlap": 90,
                "top_decile_lift": 2.0,
                "is_primary": True,
            },
            {
                **common,
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "rolling_7y",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "n_benchmark_positives_in_overlap": 10,
                "n_benchmark_negatives_in_overlap": 90,
                "top_decile_lift": 9.0,
                "is_primary": False,
            },
        ]
    ).to_csv(overlap_dir / "public_score_benchmark_ranking.csv", index=False)
    pd.DataFrame(
        [
            {
                **common,
                "model_id": "benchmark_xgb",
                "target_public_label": "label_8k_402_365",
                "feature_set": "benchmark_all",
                "train_window": "expanding",
                "label_mode": "naive",
                "score_aggregation": "benchmark_score",
                "n_public_positives_in_overlap": 20,
                "n_public_negatives_in_overlap": 180,
                "top_decile_lift": 1.8,
                "is_primary": True,
            },
            {
                **common,
                "model_id": "benchmark_xgb",
                "target_public_label": "label_8k_402_365",
                "feature_set": "benchmark_all",
                "train_window": "rolling_7y",
                "label_mode": "naive",
                "score_aggregation": "benchmark_score",
                "n_public_positives_in_overlap": 20,
                "n_public_negatives_in_overlap": 180,
                "top_decile_lift": 8.0,
                "is_primary": False,
            },
        ]
    ).to_csv(overlap_dir / "reciprocal_alignment.csv", index=False)

    table = _construct_alignment(tmp_path)

    assert set(table["Window"]) == {"expanding"}
    assert set(table["Top_Decile_Lift"]) == {"2.0000", "1.8000"}
```

Update the existing precision/FDR alignment test to mark both fixture rows `is_primary=True`. In `test_public_task_metrics_include_calibration_diagnostics`, use test years `[2020, 2021, 2022, 2023, 2024]` and PR-AUC values `[0.10, 0.30, 0.30, 0.30, 0.30]`, then add:

```python
    assert table.loc[0, "Mean_PR_AUC"] == "0.2600"
    assert table.loc[0, "Excluding_2020_PR_AUC"] == "0.3000"
    assert table.loc[0, "Excluding_2020_Delta"] == "0.0400"
```

Add:

```python
def test_public_sample_attrition_preserves_sequence_and_task_branches() -> None:
    summary = {
        "sample_attrition": [
            {"stage": "source_issuer_origin", "n_rows": 100, "task": "all"},
            {"stage": "fiscal_year_2011_2024", "n_rows": 80, "task": "all"},
            {"stage": "domestic_us_gaap_proxy", "n_rows": 75, "task": "all"},
            {"stage": "observable_365_day_horizon", "n_rows": 70, "task": "all"},
            {"stage": "eligible_comment_thread", "n_rows": 68, "task": "comment_thread"},
            {"stage": "eligible_amendment", "n_rows": 69, "task": "amendment"},
            {"stage": "eligible_8k_402", "n_rows": 65, "task": "8k_402"},
        ]
    }

    table = _public_sample_attrition_table(summary).set_index("Stage")

    assert table.loc["source_issuer_origin", "Dropped_From_Parent"] == 0
    assert table.loc["fiscal_year_2011_2024", "Dropped_From_Parent"] == 20
    assert table.loc["observable_365_day_horizon", "Dropped_From_Parent"] == 5
    assert table.loc["eligible_comment_thread", "Dropped_From_Parent"] == 2
    assert table.loc["eligible_amendment", "Dropped_From_Parent"] == 1
    assert table.loc["eligible_8k_402", "Dropped_From_Parent"] == 5
```

- [ ] **Step 2: Run focused tests and confirm the old aggregations fail**

Run:

```bash
uv run pytest -q tests/test_manuscript_package.py \
  -k 'primary_public or construct_alignment or excluding_2020 or attrition or opacity'
```

Expected: FAIL because Table 3 averages the grid and Table 9 takes maxima.

- [ ] **Step 3: Implement one primary public selector**

Add:

```python
def _package_primary_identity(public_summary: dict[str, Any]) -> dict[str, Any]:
    primary = dict(public_summary.get("primary_specification", {}))
    if set(primary) != {"feature_set", "train_window"}:
        raise ValueError("public primary specification is missing or malformed")
    return {"primary_public_specification": primary}


def _select_primary_public_metrics(
    metrics: pd.DataFrame,
    summary: dict[str, Any],
) -> pd.DataFrame:
    primary = dict(summary.get("primary_specification", {}))
    required = {"feature_set", "train_window"}
    if set(primary) != required:
        raise ValueError("public primary specification is missing or malformed")
    selected = metrics.loc[
        metrics["feature_set"].eq(primary["feature_set"])
        & metrics["train_window"].eq(primary["train_window"])
    ].copy()
    if selected.empty:
        raise ValueError("public primary specification produced no metric rows")
    if selected.duplicated(["task", "test_year"]).any():
        raise ValueError("public primary specification duplicated task-year rows")
    return selected
```

Call it once in `main()` and pass the selected frame to `_public_task_metrics` and `_annual_fold_frame` for Figure 1. Leave `_feature_family_metrics` and `_task_feature_family_metrics` on the full grid.

In the existing `package_manifest = { ... }` literal, insert
`**_package_primary_identity(public_summary),` immediately before
`"generated_at_utc"`; retain every existing key. The resulting `manifest.json`
must expose `primary_public_specification` for the canonical verifier.

- [ ] **Step 4: Add excluding-2020 sensitivity and primary disclosure**

Inside `_public_task_metrics`, calculate the full valid-fold mean and an otherwise identical summary after `test_year != 2020`; emit:

```python
    grouped["Excluding_2020_PR_AUC"] = grouped["task"].map(excluding_2020)
    grouped["Excluding_2020_Delta"] = (
        grouped["Excluding_2020_PR_AUC"] - grouped["Mean_PR_AUC"]
    )
```

Format only after computing the delta. Update `PUBLIC_TASK_NOTE` to name `all + expanding` and the excluding-2020 sensitivity. Replace the narrative's “highest reported configuration” sentence with “revision-frozen primary specification.”

- [ ] **Step 5: Select Table 9 by `is_primary` and make it Figure 5's only input**

Add:

```python
def _primary_alignment_row(frame: pd.DataFrame, *, direction: str) -> pd.Series:
    if "is_primary" not in frame:
        raise ValueError(f"{direction} alignment is missing is_primary")
    selected = frame.loc[frame["is_primary"].astype(bool)]
    if len(selected) != 1:
        raise ValueError(f"{direction} alignment requires exactly one primary row")
    return selected.iloc[0]
```

Use it in both branches of `_construct_alignment`. Remove sorting by lift. Keep `_plot_construct_lift(construct_alignment, ...)` unchanged so Figure 5 receives exactly the two Table 9 rows.

- [ ] **Step 6: Generate attrition and explicit DML dimensions**

Add `_public_sample_attrition_table(summary)` returning:

```text
Scope | Stage | Task | Rows | Dropped_From_Parent
```

Use `summary["sample_attrition"]`; sequential stages compare to the preceding row and task rows compare to `observable_365_day_horizon`. Write it as `table_18_public_sample_attrition` with a note explaining the branch.

Update `_public_opacity_dml_table` to display `Raw_Controls`, `Encoded_Controls`, and `Opacity_Components`. Replace the hard-coded DML note with definitions only:

```python
DML_INTERVAL_NOTE = (
    "Raw controls are source variables before encoding; encoded controls are nuisance-model "
    "columns after categorical expansion and imputation; opacity components form the "
    "missingness-density treatment. Intervals use HC3 residual OLS after cross-fitting. "
    "The estimates are adjusted associations, not identified structural effects."
)
```

- [ ] **Step 7: Run package tests and commit**

Run:

```bash
uv run pytest -q tests/test_manuscript_package.py
```

Expected: PASS.

Commit:

```bash
git add scripts/build_manuscript_package.py tests/test_manuscript_package.py
git commit -m "feat(reporting): route headlines through frozen evidence"
```

---

### Task 3: Build the manuscript package before the snapshot and expose canonical provenance

**Files:**
- Modify: `justfile:447-530`
- Modify: `scripts/refresh_results_snapshot.py:1-180, 986-1050, 1050-1750`
- Modify: `tests/test_docs.py`

**Interfaces:**
- Consumes: generated manuscript-package Table 3/Table 9/Table 18 and study/public-lake provenance.
- Produces: `docs/results_snapshot.md` with primary evidence, exploratory maxima labels, and a visible canonical/noncanonical status.

- [ ] **Step 1: Write failing ordering and single-owner tests**

Add `import pandas as pd` and import `_construct_alignment_rows` from
`scripts.refresh_results_snapshot` in `tests/test_docs.py`.

Update `tests/test_docs.py` so the snapshot recipe must contain `just manuscript` before `scripts/refresh_results_snapshot.py`:

```python
    manuscript_index = snapshot_recipe.index("just manuscript")
    snapshot_index = snapshot_recipe.index("scripts/refresh_results_snapshot.py")
    assert manuscript_index < snapshot_index
```

Add this single-owner test:

```python
def test_snapshot_construct_rows_read_generated_table_only(tmp_path: Path) -> None:
    package_dir = tmp_path / "manuscript_package"
    tables_dir = package_dir / "tables"
    tables_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "Direction": "Public score to benchmark positives",
                "Model": "public_cascade",
                "Target": "8k_402",
                "PR_AUC": "0.0400",
                "ROC_AUC": "0.7000",
                "Top_10pct_Precision": "0.0600",
                "Top_10pct_FDR": "0.9400",
                "Top_Decile_Lift": "2.0000",
                "Lift_Bootstrap_Interval": "[1.2000, 2.8000]",
            },
            {
                "Direction": "Benchmark score to public positives",
                "Model": "benchmark_xgb",
                "Target": "label_8k_402_365",
                "PR_AUC": "0.0300",
                "ROC_AUC": "0.6000",
                "Top_10pct_Precision": "0.0500",
                "Top_10pct_FDR": "0.9500",
                "Top_Decile_Lift": "1.8000",
                "Lift_Bootstrap_Interval": "[1.1000, 2.5000]",
            },
        ]
    ).to_csv(tables_dir / "table_09_construct_alignment.csv", index=False)

    rows = _construct_alignment_rows(package_dir)

    assert len(rows) == 2
    assert {row[1] for row in rows} == {"`public_cascade`", "`benchmark_xgb`"}
    assert {row[7] for row in rows} == {"2.0000", "1.8000"}
```

Add required snapshot phrases: `Artifact generation time`, `Study commit`, `Git dirty`, `Config hash`, `Input hash`, `uv.lock hash`, `Public-data as-of date`, `Form AP archive hash`, `WRDS source`, `WRDS version`, `WRDS extraction time`, `WRDS hash`, `Component status`, `Claim maturity`, `Canonical status`, all six realized experiment headings, every Discussion-spine heading, and all four claim-ledger categories.

Add a negative assertion that generated snapshot text contains none of `"/Users/"`, `"/Volumes/"`, or `"OneDrive"`; source roles and hashes replace local input paths.

- [ ] **Step 2: Run docs tests and verify failure**

Run:

```bash
uv run pytest -q tests/test_docs.py \
  -k 'snapshot or current_main_artifact_results or faq'
```

Expected: FAIL because the current snapshot reselects Table 9 and hides provenance.

- [ ] **Step 3: Make package generation part of the snapshot recipe**

In `justfile::snapshot`, run:

```bash
just manuscript study_dir="$study_dir_arg" out_dir="artifacts/manuscript_package"
uv run python scripts/refresh_results_snapshot.py \
  --study-dir "$study_dir_arg" \
  --manuscript-package "artifacts/manuscript_package" \
  $partial_flag
just check
```

Add `--manuscript-package` to the snapshot CLI and pass the resolved path to `build_snapshot(...)`.

- [ ] **Step 4: Remove independent Table 9 selection**

Replace `_construct_alignment_rows(study_dir)` with:

```python
def _construct_alignment_rows(manuscript_package: Path) -> list[list[str]]:
    frame = _read_csv(
        manuscript_package / "tables" / "table_09_construct_alignment.csv"
    )
    required = {
        "Direction",
        "Model",
        "Target",
        "PR_AUC",
        "ROC_AUC",
        "Top_10pct_Precision",
        "Top_10pct_FDR",
        "Top_Decile_Lift",
        "Lift_Bootstrap_Interval",
    }
    if len(frame) != 2 or not required.issubset(frame.columns):
        raise ValueError("generated Table 9 must contain exactly two primary rows")
    return [
        [
            row["Direction"],
            _code(row["Model"]),
            _code(row["Target"]),
            _fmt(row["PR_AUC"]),
            _fmt(row["ROC_AUC"]),
            _fmt(row["Top_10pct_Precision"]),
            _fmt(row["Top_10pct_FDR"]),
            _fmt(row["Top_Decile_Lift"]),
            str(row["Lift_Bootstrap_Interval"]),
        ]
        for _, row in frame.iterrows()
    ]
```

Add a separately titled “Exploratory maxima” table sourced from raw alignment CSVs and construct-manifest search-universe counts. It must show the max-row keys, max lift, primary lift, and `max_minus_primary`, and use the words `exploratory` and `post-hoc`.

- [ ] **Step 5: Expose provenance and canonical status**

Read:

```python
    provenance = dict(manifest.get("provenance", {}))
    public_lake = dict(manifest.get("public_lake_provenance", {}))
    wrds = dict(provenance.get("wrds_export_metadata", {}))
    canonical = (
        manifest.get("git_dirty") is False
        and public_lake.get("git_dirty") is False
        and public_lake.get("fresh_build") is True
        and public_lake.get("as_of_date") == "2026-07-06"
        and bool(manifest.get("repo_commit"))
        and manifest.get("repo_commit") == provenance.get("commit_sha")
        and manifest.get("repo_commit") == public_lake.get("commit_sha")
    )
```

Add the requested fields to the reproducibility table, including `generated_at_utc`, all four WRDS descriptors (`source_values`, `source_version_values`, `extracted_at_values`, `sha256`), every component status, and claim-maturity status. Render canonical status as `CANONICAL` only when the complete predicate above passes; otherwise render `NON-CANONICAL` and list the failed freshness, date, identity, or dirty-state conditions.

Remove the current `Raw benchmark input`, `Public issuer panel`, and `Bridge crosswalk` path rows. Replace them with role labels, availability booleans, hashes, and WRDS metadata from provenance; never render `manifest["inputs"]` paths into tracked docs.

Update the model overview to say notes enter `all` without a standalone ablation. Update Table/Figure explanations so Table 3/Figure 1 are primary, Table 4/Table 14 are sensitivities, and Table 9/Figure 5 are declared primary alignment rows.

Preserve the six experiment headings from `paper_plan.md` in realized-results form:

```text
1. Label observability and detection timing
2. Concept drift and model shelf-life
3. Opacity and public review/correction risk
4. Public cascade construction
5. Public cascade prediction
6. Detected-misstatement benchmark and public-cascade overlap
```

After them, generate a conventional Discussion spine with `Answers to the research questions`, `Comparison with prior literature`, `Accounting and institutional interpretation`, `Selection and visibility`, `Generalizability`, `Limitations and future work`, and `Claim ledger`. The claim ledger must classify each headline as `reportable`, `supporting`, `diagnostic`, or `deferred`. Render every current package table and figure inline, each with a claim, evidence source, and boundary note; do not silently drop a generated outcome.

- [ ] **Step 6: Run docs tests and commit**

Run:

```bash
uv run pytest -q tests/test_docs.py
```

Expected: PASS.

Commit:

```bash
git add justfile scripts/refresh_results_snapshot.py tests/test_docs.py
git commit -m "feat(reporting): expose canonical provenance in snapshot"
```

---

### Task 4: Add a deterministic canonical-run verifier

**Files:**
- Create: `scripts/verify_canonical_run.py`
- Create: `tests/test_canonical_run.py`
- Modify: `justfile`

**Interfaces:**
- Consumes: study directory, manuscript-package directory, expected as-of date.
- Produces: exit 0 plus `CANONICAL RUN VERIFIED`, or exit 1 with every failed invariant listed.

- [ ] **Step 1: Write failing verifier tests**

Create this complete minimal fixture in `tests/test_canonical_run.py`:

```python
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scripts.verify_canonical_run import verify_canonical_run


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_canonical_fixture(tmp_path: Path) -> dict[str, Path]:
    study_dir = tmp_path / "study"
    package_dir = tmp_path / "package"
    manifest_path = study_dir / "study_run_manifest.json"
    public_path = study_dir / "public_cascade" / "public_cascade_summary.json"
    construct_path = study_dir / "construct_overlap" / "construct_overlap_manifest.json"
    dml_path = study_dir / "public_cascade" / "public_opacity_dml.csv"

    _write_json(
        manifest_path,
        {
            "repo_commit": "a" * 40,
            "git_dirty": False,
            "provenance": {
                "commit_sha": "a" * 40,
                "dirty": False,
                "config_hash": "b" * 64,
                "input_hash": "c" * 64,
                "uv_lock_hash": "d" * 64,
            },
            "public_lake_provenance": {
                "as_of_date": "2026-07-06",
                "fresh_build": True,
                "git_dirty": False,
                "commit_sha": "a" * 40,
                "source_metadata_inventory": [
                    {
                        "metadata_file": "form-ap/FirmFilings.zip.meta.json",
                        "metadata_sha256": "1" * 64,
                        "source_url": "https://example.invalid/FirmFilings.zip",
                        "payload_sha256": "2" * 64,
                    }
                ],
                "form_ap": {
                    "source_kind": "verified_zip_member",
                    "archive_sha256": "e" * 64,
                    "member_sha256": "f" * 64,
                },
            },
            "components": {
                "benchmark": {"status": "complete"},
                "public_cascade": {"status": "complete"},
                "bridge_probe": {"status": "crosswalk_available"},
                "peer_comparison": {"status": "complete"},
                "public_peer_comparison": {"status": "complete"},
                "construct_overlap": {"run_status": "complete"},
            },
            "claim_maturity": {
                "public_prediction": "reportable",
                "feature_and_window_sensitivity": "supporting",
                "construct_alignment": "supporting",
                "opacity_dml": "diagnostic",
            },
        },
    )
    _write_json(
        public_path,
        {
            "primary_specification": {
                "feature_set": "all",
                "train_window": "expanding",
            },
            "primary_specification_status": "revision_frozen",
            "feature_family_summary": {
                "visibility_history": {"n_features": 24}
            },
            "sample_attrition": [
                {"stage": "source_issuer_origin", "n_rows": 205652, "task": "all"},
                {"stage": "fiscal_year_2011_2024", "n_rows": 97027, "task": "all"},
                {"stage": "domestic_us_gaap_proxy", "n_rows": 96827, "task": "all"},
                {"stage": "observable_365_day_horizon", "n_rows": 96733, "task": "all"},
                {"stage": "eligible_comment_thread", "n_rows": 96733, "task": "comment_thread"},
                {"stage": "eligible_amendment", "n_rows": 96733, "task": "amendment"},
                {"stage": "eligible_8k_402", "n_rows": 96733, "task": "8k_402"},
            ],
        },
    )
    _write_json(
        construct_path,
        {
            "interval_scope": "primary_plus_top_5_per_direction",
            "interval_seed": 42,
            "interval_reps": 1000,
            "primary_alignment": {
                "public_to_benchmark": {
                    "model_id": "public_cascade",
                    "task": "8k_402",
                    "feature_set": "all",
                    "train_window": "expanding",
                    "label_mode": "benchmark_naive",
                    "score_aggregation": "mean",
                    "bridge_tier": "high_confidence",
                },
                "benchmark_to_public": {
                    "model_id": "benchmark_xgb",
                    "target_public_label": "label_8k_402_365",
                    "feature_set": "benchmark_all",
                    "train_window": "expanding",
                    "label_mode": "naive",
                    "score_aggregation": "benchmark_score",
                    "bridge_tier": "high_confidence",
                },
                "public_to_benchmark_count": 1,
                "benchmark_to_public_count": 1,
            },
            "primary_alignment_evidence": {
                "public_to_benchmark": {
                    "metric_status": "fit",
                    "top_decile_lift": 2.0,
                    "ci_low": 1.2,
                    "ci_high": 2.8,
                },
                "benchmark_to_public": {
                    "metric_status": "fit",
                    "top_decile_lift": 1.8,
                    "ci_low": 1.1,
                    "ci_high": 2.5,
                },
            },
            "exploratory_maxima": {
                "public_to_benchmark": {
                    "keys": {"train_window": "rolling_7y"},
                    "top_decile_lift": 2.4,
                    "primary_lift": 2.0,
                    "lift_minus_primary": 0.4,
                },
                "benchmark_to_public": {
                    "keys": {"train_window": "rolling_7y"},
                    "top_decile_lift": 2.1,
                    "primary_lift": 1.8,
                    "lift_minus_primary": 0.3,
                },
            },
        },
    )
    dml_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "outcome": ["comment_thread", "amendment"],
            "n_raw_controls": [60, 60],
            "n_encoded_controls": [64, float("nan")],
            "n_controls": [64, float("nan")],
            "n_controls_definition": [
                "encoded_nuisance_columns",
                "encoded_nuisance_columns",
            ],
            "n_opacity_components": [17, 17],
            "status": ["fit", "skipped_one_class_or_too_small"],
        }
    ).to_csv(dml_path, index=False)
    _write_json(
        study_dir / "public_cascade" / "public_opacity_dml_meta.json",
        {
            "n_raw_controls": 60,
            "n_encoded_controls_by_outcome": {"comment_thread": 64},
            "n_opacity_components": 17,
            "n_controls_definition": "encoded_nuisance_columns",
        },
    )
    tables = package_dir / "tables"
    tables.mkdir(parents=True)
    pd.DataFrame(
        {
            "Task": ["comment_thread", "amendment", "8k_402"],
            "Panel_Positives": [100, 80, 20],
            "Mean_Prevalence": [0.02, 0.015, 0.004],
            "Mean_PR_AUC": [0.2, 0.15, 0.05],
            "PR_AUC_Dispersion": [
                "[0.1800, 0.2200]",
                "[0.1300, 0.1700]",
                "[0.0400, 0.0600]",
            ],
            "Mean_ROC_AUC": [0.7, 0.68, 0.65],
            "Mean_Brier": [0.018, 0.014, 0.004],
            "Mean_Brier_Skill": [0.08, 0.06, 0.03],
            "Mean_ECE": [0.01, 0.009, 0.003],
            "Excluding_2020_PR_AUC": [0.21, 0.16, 0.055],
            "Excluding_2020_Delta": [0.01, 0.01, 0.005],
        }
    ).to_csv(
        tables / "table_03_public_task_metrics.csv", index=False
    )
    pd.DataFrame(
        {
            "Outcome": ["comment_thread", "amendment"],
            "Raw_Controls": [60, 60],
            "Encoded_Controls": [64, float("nan")],
            "Opacity_Components": [17, 17],
        }
    ).to_csv(tables / "table_12_public_opacity_dml.csv", index=False)
    pd.DataFrame(
        {
            "Direction": [
                "Public score to benchmark positives",
                "Benchmark score to public positives",
            ],
            "Model": ["public_cascade", "benchmark_xgb"],
            "Target": ["8k_402", "label_8k_402_365"],
            "Feature_Set": ["all", "benchmark_all"],
            "Window": ["expanding", "expanding"],
            "Bridge_Tier": ["high_confidence", "high_confidence"],
            "PR_AUC": [0.04, 0.03],
            "ROC_AUC": [0.70, 0.60],
            "Top_10pct_Precision": [0.06, 0.05],
            "Top_10pct_FDR": [0.94, 0.95],
            "Top_Decile_Lift": [2.0, 1.8],
            "Lift_Bootstrap_Interval": ["[1.2000, 2.8000]", "[1.1000, 2.5000]"],
        }
    ).to_csv(
        tables / "table_09_construct_alignment.csv", index=False
    )
    pd.DataFrame(
        {
            "Scope": ["sequential"] * 4 + ["task"] * 3,
            "Stage": [
                "source_issuer_origin",
                "fiscal_year_2011_2024",
                "domestic_us_gaap_proxy",
                "observable_365_day_horizon",
                "eligible_comment_thread",
                "eligible_amendment",
                "eligible_8k_402",
            ],
            "Task": ["all", "all", "all", "all", "comment_thread", "amendment", "8k_402"],
            "Rows": [205652, 97027, 96827, 96733, 96733, 96733, 96733],
            "Dropped_From_Parent": [0, 108625, 200, 94, 0, 0, 0],
        }
    ).to_csv(
        tables / "table_18_public_sample_attrition.csv", index=False
    )
    _write_json(
        package_dir / "manifest.json",
        {
            "primary_public_specification": {
                "feature_set": "all",
                "train_window": "expanding",
            },
            "tables": {
                "table_03_public_task_metrics": {
                    "csv": str(tables / "table_03_public_task_metrics.csv")
                },
                "table_09_construct_alignment": {
                    "csv": str(tables / "table_09_construct_alignment.csv")
                },
                "table_12_public_opacity_dml": {
                    "csv": str(tables / "table_12_public_opacity_dml.csv")
                },
                "table_18_public_sample_attrition": {
                    "csv": str(tables / "table_18_public_sample_attrition.csv")
                },
            },
            "figures": {},
        },
    )
    return {
        "study_dir": study_dir,
        "package_dir": package_dir,
        "manifest": manifest_path,
        "public": public_path,
        "construct": construct_path,
        "table_09": tables / "table_09_construct_alignment.csv",
    }


def test_verify_canonical_run_accepts_clean_fixture(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )
    assert errors == []


@pytest.mark.parametrize(
    ("target", "key_path", "replacement", "message"),
    [
        ("manifest", ("git_dirty",), True, "study git_dirty"),
        (
            "manifest",
            ("public_lake_provenance", "as_of_date"),
            "2026-07-05",
            "public-data as-of date",
        ),
        (
            "manifest",
            ("public_lake_provenance", "fresh_build"),
            False,
            "public-lake fresh build",
        ),
        (
            "construct",
            ("primary_alignment", "public_to_benchmark_count"),
            0,
            "public-to-benchmark primary count",
        ),
        (
            "manifest",
            ("provenance", "commit_sha"),
            "9" * 40,
            "study/provenance commit identity",
        ),
        ("public", ("sample_attrition",), [], "sample attrition"),
        ("construct", ("interval_seed",), 7, "construct bootstrap seed"),
        (
            "construct",
            ("primary_alignment", "public_to_benchmark", "train_window"),
            "rolling_7y",
            "public-to-benchmark primary keys",
        ),
    ],
)
def test_verify_canonical_run_rejects_broken_json_contracts(
    tmp_path: Path,
    target: str,
    key_path: tuple[str, ...],
    replacement: object,
    message: str,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    path = fixture[target]
    payload = json.loads(path.read_text(encoding="utf-8"))
    cursor = payload
    for key in key_path[:-1]:
        cursor = cursor[key]
    cursor[key_path[-1]] = replacement
    _write_json(path, payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any(message in error for error in errors)


def test_verify_canonical_run_rejects_one_row_table_09(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    pd.DataFrame({"Direction": ["public"]}).to_csv(fixture["table_09"], index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("Table 9" in error for error in errors)


def test_verify_canonical_run_rejects_table_09_without_interval(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    table = pd.read_csv(fixture["table_09"])
    table = table.drop(columns=["Lift_Bootstrap_Interval"])
    table.to_csv(fixture["table_09"], index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("Table 9 primary metrics and intervals" in error for error in errors)


def test_verify_canonical_run_rejects_incomplete_table_03(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    path = fixture["package_dir"] / "tables" / "table_03_public_task_metrics.csv"
    table = pd.read_csv(path).drop(columns=["Mean_ECE"])
    table.to_csv(path, index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("Table 3 primary metrics" in error for error in errors)


def test_verify_canonical_run_rejects_wrong_dml_dimensions(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    pd.DataFrame(
        {
            "n_raw_controls": [60],
            "n_encoded_controls": [65],
            "n_controls": [65],
            "n_controls_definition": ["encoded_nuisance_columns"],
        }
    ).to_csv(
        fixture["study_dir"] / "public_cascade" / "public_opacity_dml.csv",
        index=False,
    )

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("DML CSV/meta/Table 12 consistency" in error for error in errors)


def test_verify_canonical_run_rejects_wrong_attrition_drop(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    path = (
        fixture["package_dir"]
        / "tables"
        / "table_18_public_sample_attrition.csv"
    )
    table = pd.read_csv(path)
    table.loc[1, "Dropped_From_Parent"] = 999
    table.to_csv(path, index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("sample attrition/table 18 consistency" in error for error in errors)
```

- [ ] **Step 2: Run tests and verify the module is absent**

Run:

```bash
uv run pytest -q tests/test_canonical_run.py
```

Expected: import failure.

- [ ] **Step 3: Implement the small verifier**

Implement these complete functions in `scripts/verify_canonical_run.py`:

```python
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def _package_artifacts_exist(
    manuscript_package: Path,
    package_manifest: dict[str, Any],
) -> bool:
    checked = 0
    for group in ("tables", "figures"):
        records = package_manifest.get(group, {})
        if not isinstance(records, dict):
            return False
        for formats in records.values():
            if not isinstance(formats, dict):
                return False
            for recorded_path in formats.values():
                checked += 1
                candidate = manuscript_package / group / Path(str(recorded_path)).name
                if not candidate.is_file():
                    return False
    return checked > 0


PUBLIC_PRIMARY = {
    "model_id": "public_cascade",
    "task": "8k_402",
    "feature_set": "all",
    "train_window": "expanding",
    "label_mode": "benchmark_naive",
    "score_aggregation": "mean",
    "bridge_tier": "high_confidence",
}
RECIPROCAL_PRIMARY = {
    "model_id": "benchmark_xgb",
    "target_public_label": "label_8k_402_365",
    "feature_set": "benchmark_all",
    "train_window": "expanding",
    "label_mode": "naive",
    "score_aggregation": "benchmark_score",
    "bridge_tier": "high_confidence",
}
SEQUENTIAL_ATTRITION_STAGES = [
    "source_issuer_origin",
    "fiscal_year_2011_2024",
    "domestic_us_gaap_proxy",
    "observable_365_day_horizon",
]
TASK_ATTRITION_STAGES = [
    "eligible_comment_thread",
    "eligible_amendment",
    "eligible_8k_402",
]


def _attrition_matches(summary: dict[str, Any], table_18: pd.DataFrame) -> bool:
    try:
        summary_rows = [
            (str(row.get("stage")), int(row.get("n_rows", -1)), str(row.get("task")))
            for row in summary.get("sample_attrition", [])
        ]
    except (AttributeError, TypeError, ValueError):
        return False
    if len(summary_rows) != 7:
        return False
    sequential = summary_rows[:4]
    if [stage for stage, _, _ in sequential] != SEQUENTIAL_ATTRITION_STAGES:
        return False
    if [task for _, _, task in sequential] != ["all"] * 4:
        return False
    counts = [count for _, count, _ in sequential]
    if any(count < 0 for count in counts) or counts != sorted(counts, reverse=True):
        return False
    task_rows = summary_rows[4:]
    if [stage for stage, _, _ in task_rows] != TASK_ATTRITION_STAGES:
        return False
    if [task for _, _, task in task_rows] != [
        "comment_thread",
        "amendment",
        "8k_402",
    ]:
        return False
    if any(count < 0 or count > counts[-1] for _, count, _ in task_rows):
        return False
    required_table_columns = {
        "Scope",
        "Stage",
        "Task",
        "Rows",
        "Dropped_From_Parent",
    }
    if not required_table_columns <= set(table_18) or len(table_18) != 7:
        return False
    table_counts = pd.to_numeric(
        table_18["Rows"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    table_dropped = pd.to_numeric(
        table_18["Dropped_From_Parent"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    if table_counts.isna().any() or table_dropped.isna().any():
        return False
    table_rows = list(
        zip(
            table_18["Stage"].astype(str),
            table_counts.astype(int),
            table_18["Task"].astype(str),
        )
    )
    expected_dropped = [0]
    expected_dropped.extend(counts[index - 1] - counts[index] for index in range(1, 4))
    expected_dropped.extend(counts[-1] - count for _, count, _ in task_rows)
    expected_scopes = ["sequential"] * 4 + ["task"] * 3
    return (
        table_rows == summary_rows
        and table_18["Scope"].astype(str).tolist() == expected_scopes
        and table_dropped.astype(int).tolist() == expected_dropped
    )


def _same_number(left: object, right: object) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if pd.isna(left) or pd.isna(right):
        return False
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def _dml_matches(
    dml: pd.DataFrame,
    dml_meta: dict[str, Any],
    table_12: pd.DataFrame,
) -> bool:
    required = {
        "outcome",
        "n_raw_controls",
        "n_encoded_controls",
        "n_controls",
        "n_controls_definition",
        "n_opacity_components",
    }
    table_required = {
        "Outcome",
        "Raw_Controls",
        "Encoded_Controls",
        "Opacity_Components",
    }
    if (
        dml.empty
        or not required <= set(dml)
        or not table_required <= set(table_12)
        or dml["outcome"].astype(str).duplicated().any()
        or table_12["Outcome"].astype(str).duplicated().any()
    ):
        return False
    if set(dml["n_controls_definition"].astype(str)) != {
        "encoded_nuisance_columns"
    }:
        return False
    if dml_meta.get("n_controls_definition") != "encoded_nuisance_columns":
        return False

    raw = pd.to_numeric(dml["n_raw_controls"], errors="coerce")
    encoded = pd.to_numeric(dml["n_encoded_controls"], errors="coerce")
    alias = pd.to_numeric(dml["n_controls"], errors="coerce")
    opacity = pd.to_numeric(dml["n_opacity_components"], errors="coerce")
    if raw.isna().any() or opacity.isna().any():
        return False
    if not all(_same_number(left, right) for left, right in zip(encoded, alias)):
        return False
    if not all(_same_number(value, dml_meta.get("n_raw_controls")) for value in raw):
        return False
    if not all(
        _same_number(value, dml_meta.get("n_opacity_components")) for value in opacity
    ):
        return False

    try:
        encoded_meta = {
            str(outcome): float(value)
            for outcome, value in dict(
                dml_meta.get("n_encoded_controls_by_outcome", {})
            ).items()
        }
    except (TypeError, ValueError):
        return False
    expected_encoded_outcomes: set[str] = set()
    for outcome, value in zip(dml["outcome"].astype(str), encoded):
        if pd.isna(value):
            if outcome in encoded_meta:
                return False
            continue
        expected_encoded_outcomes.add(outcome)
        if outcome not in encoded_meta or not _same_number(value, encoded_meta[outcome]):
            return False
    if set(encoded_meta) != expected_encoded_outcomes:
        return False

    table_by_outcome = table_12.assign(
        Outcome=table_12["Outcome"].astype(str),
        Raw_Controls=pd.to_numeric(table_12["Raw_Controls"], errors="coerce"),
        Encoded_Controls=pd.to_numeric(table_12["Encoded_Controls"], errors="coerce"),
        Opacity_Components=pd.to_numeric(table_12["Opacity_Components"], errors="coerce"),
    ).set_index("Outcome")
    if set(table_by_outcome.index) != set(dml["outcome"].astype(str)):
        return False
    for outcome, raw_value, encoded_value, opacity_value in zip(
        dml["outcome"].astype(str), raw, encoded, opacity
    ):
        table_row = table_by_outcome.loc[outcome]
        if not all(
            [
                _same_number(table_row["Raw_Controls"], raw_value),
                _same_number(table_row["Encoded_Controls"], encoded_value),
                _same_number(table_row["Opacity_Components"], opacity_value),
            ]
        ):
            return False
    return True


TABLE_03_REQUIRED = {
    "Task",
    "Panel_Positives",
    "Mean_Prevalence",
    "Mean_PR_AUC",
    "PR_AUC_Dispersion",
    "Mean_ROC_AUC",
    "Mean_Brier",
    "Mean_Brier_Skill",
    "Mean_ECE",
    "Excluding_2020_PR_AUC",
    "Excluding_2020_Delta",
}
TABLE_09_REQUIRED = {
    "Direction",
    "Model",
    "Target",
    "Feature_Set",
    "Window",
    "Bridge_Tier",
    "PR_AUC",
    "ROC_AUC",
    "Top_10pct_Precision",
    "Top_10pct_FDR",
    "Top_Decile_Lift",
    "Lift_Bootstrap_Interval",
}


def _table_03_matches(
    table_03: pd.DataFrame,
    package_manifest: dict[str, Any],
) -> bool:
    if (
        len(table_03) != 3
        or not TABLE_03_REQUIRED <= set(table_03)
        or set(table_03["Task"].astype(str))
        != {"comment_thread", "amendment", "8k_402"}
        or package_manifest.get("primary_public_specification")
        != {"feature_set": "all", "train_window": "expanding"}
    ):
        return False
    numeric_columns = [
        "Mean_Prevalence",
        "Mean_PR_AUC",
        "Mean_ROC_AUC",
        "Mean_Brier",
        "Mean_Brier_Skill",
        "Mean_ECE",
        "Excluding_2020_PR_AUC",
        "Excluding_2020_Delta",
    ]
    numeric = table_03[numeric_columns].apply(pd.to_numeric, errors="coerce")
    positives = pd.to_numeric(
        table_03["Panel_Positives"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    if not numeric.notna().all().all() or positives.isna().any():
        return False
    for value in table_03["PR_AUC_Dispersion"].astype(str):
        match = re.fullmatch(r"\[\s*([^,]+),\s*([^\]]+)\s*\]", value)
        if match is None:
            return False
        try:
            low, high = float(match.group(1)), float(match.group(2))
        except ValueError:
            return False
        if not all(math.isfinite(item) for item in [low, high]) or low > high:
            return False
    return True


def _alignment_evidence_matches(
    construct_manifest: dict[str, Any],
    table_09: pd.DataFrame,
) -> bool:
    if len(table_09) != 2 or not TABLE_09_REQUIRED <= set(table_09):
        return False
    evidence = dict(construct_manifest.get("primary_alignment_evidence", {}))
    maxima = dict(construct_manifest.get("exploratory_maxima", {}))
    models = {
        "public_to_benchmark": "public_cascade",
        "benchmark_to_public": "benchmark_xgb",
    }
    for direction, model in models.items():
        selected = table_09.loc[table_09["Model"].astype(str).eq(model)]
        item = dict(evidence.get(direction, {}))
        if len(selected) != 1 or item.get("metric_status") != "fit":
            return False
        row = selected.iloc[0]
        try:
            ranking_metrics = [
                float(row[column])
                for column in [
                    "PR_AUC",
                    "ROC_AUC",
                    "Top_10pct_Precision",
                    "Top_10pct_FDR",
                ]
            ]
        except (TypeError, ValueError):
            return False
        if not all(math.isfinite(value) for value in ranking_metrics):
            return False
        match = re.fullmatch(
            r"\[\s*([^,]+),\s*([^\]]+)\s*\]",
            str(row["Lift_Bootstrap_Interval"]),
        )
        if match is None:
            return False
        try:
            displayed = (
                float(row["Top_Decile_Lift"]),
                float(match.group(1)),
                float(match.group(2)),
            )
            recorded = (
                float(item["top_decile_lift"]),
                float(item["ci_low"]),
                float(item["ci_high"]),
            )
        except (KeyError, TypeError, ValueError):
            return False
        if (
            not all(math.isfinite(value) for value in displayed + recorded)
            or recorded[1] > recorded[2]
            or not all(
                math.isclose(left, right, abs_tol=1e-4, rel_tol=0.0)
                for left, right in zip(displayed, recorded)
            )
        ):
            return False

        maximum = dict(maxima.get(direction, {}))
        try:
            maximum_lift = float(maximum["top_decile_lift"])
            primary_lift = float(maximum["primary_lift"])
            delta = float(maximum["lift_minus_primary"])
        except (KeyError, TypeError, ValueError):
            return False
        if (
            not dict(maximum.get("keys", {}))
            or not all(math.isfinite(value) for value in [maximum_lift, primary_lift, delta])
            or not math.isclose(
                delta,
                maximum_lift - primary_lift,
                abs_tol=1e-12,
                rel_tol=0.0,
            )
            or not math.isclose(
                primary_lift,
                recorded[0],
                abs_tol=1e-12,
                rel_tol=0.0,
            )
        ):
            return False
    return True


def verify_canonical_run(
    study_dir: Path,
    manuscript_package: Path,
    *,
    expected_as_of_date: str,
) -> list[str]:
    errors: list[str] = []
    try:
        manifest = _read_json(study_dir / "study_run_manifest.json")
        public_summary = _read_json(
            study_dir / "public_cascade" / "public_cascade_summary.json"
        )
        construct_manifest = _read_json(
            study_dir / "construct_overlap" / "construct_overlap_manifest.json"
        )
        dml = _read_csv(study_dir / "public_cascade" / "public_opacity_dml.csv")
        dml_meta = _read_json(
            study_dir / "public_cascade" / "public_opacity_dml_meta.json"
        )
        table_03 = _read_csv(
            manuscript_package / "tables" / "table_03_public_task_metrics.csv"
        )
        table_09 = _read_csv(
            manuscript_package / "tables" / "table_09_construct_alignment.csv"
        )
        table_12 = _read_csv(
            manuscript_package / "tables" / "table_12_public_opacity_dml.csv"
        )
        table_18 = _read_csv(
            manuscript_package / "tables" / "table_18_public_sample_attrition.csv"
        )
        package_manifest = _read_json(manuscript_package / "manifest.json")
    except (FileNotFoundError, ValueError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        return [str(exc)]

    public_lake = dict(manifest.get("public_lake_provenance", {}))
    form_ap = dict(public_lake.get("form_ap", {}))
    provenance = dict(manifest.get("provenance", {}))
    primary = dict(construct_manifest.get("primary_alignment", {}))
    components = dict(manifest.get("components", {}))
    claim_maturity = dict(manifest.get("claim_maturity", {}))
    table_09_keys = set(
        table_09[["Model", "Feature_Set", "Window", "Bridge_Tier"]]
        .astype(str)
        .itertuples(index=False, name=None)
    ) if {"Model", "Feature_Set", "Window", "Bridge_Tier"} <= set(table_09) else set()
    checks = {
        "study git_dirty": manifest.get("git_dirty") is False,
        "public-lake git_dirty": public_lake.get("git_dirty") is False,
        "public-lake fresh build": public_lake.get("fresh_build") is True,
        "public-data as-of date": public_lake.get("as_of_date") == expected_as_of_date,
        "Form AP source kind": form_ap.get("source_kind") == "verified_zip_member",
        "Form AP archive hash": bool(form_ap.get("archive_sha256")),
        "Form AP member hash": bool(form_ap.get("member_sha256")),
        "public source inventory": bool(public_lake.get("source_metadata_inventory")),
        "claim maturity": claim_maturity
        == {
            "public_prediction": "reportable",
            "feature_and_window_sensitivity": "supporting",
            "construct_alignment": "supporting",
            "opacity_dml": "diagnostic",
        },
        "study commit": bool(manifest.get("repo_commit")),
        "study/provenance commit identity": manifest.get("repo_commit")
        == provenance.get("commit_sha"),
        "study/public-lake commit identity": manifest.get("repo_commit")
        == public_lake.get("commit_sha"),
        "config hash": bool(provenance.get("config_hash")),
        "input hash": bool(provenance.get("input_hash")),
        "uv.lock hash": bool(provenance.get("uv_lock_hash")),
        "public primary specification": public_summary.get("primary_specification")
        == {"feature_set": "all", "train_window": "expanding"},
        "public primary status": public_summary.get("primary_specification_status")
        == "revision_frozen",
        "visibility family": public_summary.get("feature_family_summary", {})
        .get("visibility_history", {})
        .get("n_features", 0)
        > 0,
        "sample attrition/table 18 consistency": _attrition_matches(
            public_summary, table_18
        ),
        "construct bootstrap scope": construct_manifest.get("interval_scope")
        == "primary_plus_top_5_per_direction",
        "construct bootstrap seed": construct_manifest.get("interval_seed") == 42,
        "construct bootstrap reps": construct_manifest.get("interval_reps") == 1000,
        "public-to-benchmark primary keys": primary.get("public_to_benchmark")
        == PUBLIC_PRIMARY,
        "benchmark-to-public primary keys": primary.get("benchmark_to_public")
        == RECIPROCAL_PRIMARY,
        "public-to-benchmark primary count": primary.get("public_to_benchmark_count") == 1,
        "benchmark-to-public primary count": primary.get("benchmark_to_public_count") == 1,
        "DML CSV/meta/Table 12 consistency": _dml_matches(dml, dml_meta, table_12),
        "Table 3 primary metrics": _table_03_matches(table_03, package_manifest),
        "Table 9 primary metrics and intervals": _alignment_evidence_matches(
            construct_manifest, table_09
        ),
        "Table 9 primary rows": table_09_keys
        == {
            ("public_cascade", "all", "expanding", "high_confidence"),
            ("benchmark_xgb", "benchmark_all", "expanding", "high_confidence"),
        },
        "Table 18": len(table_18) >= 7,
        "benchmark component": components.get("benchmark", {}).get("status") == "complete",
        "public-cascade component": components.get("public_cascade", {}).get("status")
        == "complete",
        "bridge component": components.get("bridge_probe", {}).get("status")
        in {"crosswalk_available", "complete"},
        "benchmark peer component": components.get("peer_comparison", {}).get("status")
        == "complete",
        "public peer component": components.get("public_peer_comparison", {}).get("status")
        == "complete",
        "construct component": components.get("construct_overlap", {}).get("run_status")
        == "complete",
        "package manifest files": _package_artifacts_exist(
            manuscript_package, package_manifest
        ),
    }
    errors.extend(name for name, passed in checks.items() if not passed)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study-dir", type=Path, required=True)
    parser.add_argument("--manuscript-package", type=Path, required=True)
    parser.add_argument("--expected-as-of-date", default="2026-07-06")
    args = parser.parse_args()
    errors = verify_canonical_run(
        args.study_dir,
        args.manuscript_package,
        expected_as_of_date=args.expected_as_of_date,
    )
    if errors:
        for error in errors:
            print(f"FAILED: {error}")
        return 1
    print("CANONICAL RUN VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The function above is the acceptance contract: it checks every required component, DML dimensions, commit/config/input/lock hashes, the three headline table shapes, and all manifest-declared package artifacts with explicit failure messages.

- [ ] **Step 4: Add the just entry point and run tests**

Add:

```make
verify-canonical study_dir="artifacts/full_with_peer" package_dir="artifacts/manuscript_package": _check-data-env
    study_dir_arg="{{ study_dir }}"; study_dir_arg="${study_dir_arg#study_dir=}"; \
    package_dir_arg="{{ package_dir }}"; package_dir_arg="${package_dir_arg#package_dir=}"; \
    uv run python scripts/verify_canonical_run.py \
        --study-dir "$study_dir_arg" \
        --manuscript-package "$package_dir_arg" \
        --expected-as-of-date 2026-07-06
```

Run:

```bash
uv run pytest -q tests/test_canonical_run.py
```

Expected: PASS.

- [ ] **Step 5: Commit the gate**

```bash
git add scripts/verify_canonical_run.py tests/test_canonical_run.py justfile
git commit -m "feat(repro): verify canonical study contracts"
```

---

### Task 5: Build and validate the anonymized reviewer ZIP

**Files:**
- Create: `scripts/build_reviewer_package.py`
- Create: `tests/test_reviewer_package.py`
- Modify: `justfile`

**Interfaces:**
- Consumes: clean study manifest, exact study Git commit, current report Git commit, manuscript package, public-lake provenance.
- Produces: `artifacts/reviewer_package/reporting-risk-cascade-reviewer.zip`, `provenance/package_manifest.json` with separate `study_commit` and `report_commit`, and a content validation result.

- [ ] **Step 1: Write failing archive-content tests**

Create this complete fixture and archive test:

```python
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.build_reviewer_package import build_reviewer_package


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _reviewer_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "reviewer-test@example.invalid")
    _git(repo, "config", "user.name", "Reviewer Test")
    files = {
        "src/example.py": "VALUE = 1\n",
        "config/example.yaml": "seed: 42\n",
        "tests/test_example.py": "def test_value():\n    assert 1 == 1\n",
        "docs/example.md": "# Example\n",
        "README.md": "# Fixture\n",
        ".python-version": "3.13\n",
        "pyproject.toml": "[project]\nname='fixture'\nversion='0.1.0'\n",
        "justfile": "check:\n    python -m pytest\n",
        "uv.lock": "version = 1\n",
    }
    for relative, content in files.items():
        _write(repo / relative, content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    commit = _git(repo, "rev-parse", "HEAD")

    study_dir = tmp_path / "study"
    package_dir = tmp_path / "package"
    user_path = "/" + "Users" + "/example/private/input.csv"
    _write(
        study_dir / "study_run_manifest.json",
        json.dumps(
            {
                "repo_commit": commit,
                "git_dirty": False,
                "public_lake_provenance": {
                    "as_of_date": "2026-07-06",
                    "git_dirty": False,
                    "source_metadata_inventory": [
                        {
                            "metadata_file": "form-ap/FirmFilings.zip.meta.json",
                            "metadata_sha256": "a" * 64,
                            "source_url": "https://example.invalid/FirmFilings.zip",
                            "payload_sha256": "b" * 64,
                        }
                    ],
                },
                "developer_path": user_path,
            }
        ),
    )
    _write(package_dir / "tables" / "table_03.csv", "Task,PR_AUC\na,0.2\n")
    _write(package_dir / "figures" / "figure_01.svg", "<svg></svg>\n")
    _write(package_dir / "results_narrative.md", "Canonical aggregate results.\n")
    _write(
        package_dir / "manifest.json",
        json.dumps(
            {
                "tables": {"table_03": {"csv": "tables/table_03.csv"}},
                "figures": {"figure_01": {"svg": "figures/figure_01.svg"}},
            }
        ),
    )
    return repo, study_dir, package_dir, commit


def test_reviewer_package_is_exact_commit_anonymized_and_data_free(tmp_path: Path) -> None:
    repo, study_dir, package_dir, commit = _reviewer_fixture(tmp_path)
    output = tmp_path / "reviewer.zip"
    user_path = "/" + "Users" + "/example/private/input.csv"
    _write(package_dir / "tables" / "stale_not_declared.csv", "old,value\n1,2\n")

    build_reviewer_package(
        repo_root=repo,
        study_dir=study_dir,
        manuscript_package=package_dir,
        output=output,
    )

    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        assert "source/src/example.py" in names
        assert "source/.python-version" in names
        assert "source/uv.lock" in names
        assert "generated/manuscript_package/manifest.json" in names
        assert "provenance/study_run_manifest.sanitized.json" in names
        assert "provenance/public_lake_provenance.json" in names
        assert "provenance/public_source_inventory.json" in names
        assert "provenance/package_manifest.json" in names
        assert "REPLICATION_README.md" in names
        assert "generated/manuscript_package/tables/stale_not_declared.csv" not in names
        assert not any(name.endswith((".parquet", ".env")) for name in names)
        package_manifest = json.loads(
            zf.read("provenance/package_manifest.json").decode("utf-8")
        )
        assert package_manifest["study_commit"] == commit
        assert package_manifest["report_commit"] == commit
        payload = "\n".join(
            zf.read(name).decode("utf-8", errors="ignore") for name in names
        )
        assert str(tmp_path) not in payload
        assert user_path not in payload
        readme = zf.read("REPLICATION_README.md").decode("utf-8")
        assert "cd source\nuv sync --locked" in readme
        extracted = tmp_path / "extracted"
        zf.extractall(extracted)

    listed = subprocess.run(
        ["just", "--list"],
        cwd=extracted / "source",
        check=False,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, listed.stderr
    assert "check" in listed.stdout
```

Add these direct rejection tests:

```python
def _rewrite_study_manifest(study_dir: Path, **updates: object) -> None:
    path = study_dir / "study_run_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    _write(path, json.dumps(payload))


def test_reviewer_package_rejects_dirty_study(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    _rewrite_study_manifest(study_dir, git_dirty=True)

    with pytest.raises(ValueError, match="dirty"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_forbidden_generated_data(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    (package_dir / "tables" / "forbidden.parquet").write_bytes(b"PAR1")

    with pytest.raises(ValueError, match="forbidden"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_unresolvable_study_commit(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    _rewrite_study_manifest(study_dir, repo_commit="0" * 40)

    with pytest.raises(ValueError, match="cannot resolve"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )
```

- [ ] **Step 2: Run tests and verify the builder is absent**

Run:

```bash
uv run pytest -q tests/test_reviewer_package.py
```

Expected: import failure.

- [ ] **Step 3: Implement exact-commit extraction and sanitization**

Implement these interfaces:

```python
from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ALLOWED_ROOT_FILES = {
    ".python-version",
    "LICENSE",
    "README.md",
    "justfile",
    "mkdocs.yml",
    "pyproject.toml",
    "uv.lock",
}
ALLOWED_PREFIXES = ("config/", "docs/", "scripts/", "src/", "tests/")
EXCLUDED_PREFIXES = (
    "docs/superpowers/plans/",
    "docs/assets/results_snapshot/",
)
EXCLUDED_FILES = {"docs/results_snapshot.md"}
REPORT_FILES = {"docs/results_snapshot.md"}
REPORT_PREFIXES = ("docs/assets/results_snapshot/",)
FORBIDDEN_SUFFIXES = (".parquet", ".pkl")
FORBIDDEN_PARTS = {".env", ".serena", ".venv", "site", "__pycache__"}
BINARY_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
CODE_FENCE = "`" * 3
REPLICATION_README = f"""# Replication

{CODE_FENCE}bash
cd source
uv sync --locked
just check
just task benchmark sample artifacts/reviewer_smoke
just data full fresh
just task study raw artifacts/full_with_peer extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
just manuscript study_dir=artifacts/full_with_peer out_dir=artifacts/manuscript_package
just snapshot study_dir=artifacts/full_with_peer
just verify-canonical study_dir=artifacts/full_with_peer package_dir=artifacts/manuscript_package
{CODE_FENCE}

The raw detected-misstatement benchmark and WRDS crosswalk are not distributed.
Authorized users must supply them at the configured paths before the full run.
"""


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout


def _tracked_paths(repo_root: Path, commit: str) -> list[str]:
    raw = _git_bytes(repo_root, "ls-tree", "-rz", "--name-only", commit)
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def _source_allowed(path: str) -> bool:
    parts = set(PurePosixPath(path).parts)
    if path in EXCLUDED_FILES or any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if parts & FORBIDDEN_PARTS or path.endswith(FORBIDDEN_SUFFIXES):
        return False
    return path in ALLOWED_ROOT_FILES or any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _report_allowed(path: str) -> bool:
    return path in REPORT_FILES or any(path.startswith(prefix) for prefix in REPORT_PREFIXES)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and Path(value).is_absolute():
        return f"<external>/{Path(value).name}"
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _declared_package_files(package_manifest: dict[str, Any]) -> set[str]:
    declared = {"results_narrative.md"}
    for group in ("tables", "figures"):
        records = package_manifest.get(group, {})
        if not isinstance(records, dict):
            raise ValueError(f"invalid package manifest group: {group}")
        for formats in records.values():
            if not isinstance(formats, dict):
                raise ValueError(f"invalid package manifest format map: {group}")
            for recorded_path in formats.values():
                declared.add(f"{group}/{Path(str(recorded_path)).name}")
    return declared


def _validate_entries(entries: dict[str, bytes]) -> None:
    home = str(Path.home())
    markers = (
        home,
        "/" + "Users" + "/",
        "/" + "Volumes" + "/",
        "One" + "Drive",
    )
    for name, payload in entries.items():
        path = PurePosixPath(name)
        if set(path.parts) & FORBIDDEN_PARTS or name.endswith(FORBIDDEN_SUFFIXES):
            raise ValueError(f"forbidden archive entry: {name}")
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        text = payload.decode("utf-8", errors="ignore")
        for marker in markers:
            if marker and marker in text:
                raise ValueError(f"local identity/path marker in archive entry: {name}")


def build_reviewer_package(
    *,
    repo_root: Path,
    study_dir: Path,
    manuscript_package: Path,
    output: Path,
) -> Path:
    study_manifest = json.loads(
        (study_dir / "study_run_manifest.json").read_text(encoding="utf-8")
    )
    public_lake = dict(study_manifest.get("public_lake_provenance", {}))
    if study_manifest.get("git_dirty") is not False or public_lake.get("git_dirty") is not False:
        raise ValueError("dirty study or public-lake manifest")
    source_inventory = list(public_lake.get("source_metadata_inventory", []))
    if not source_inventory:
        raise ValueError("public source metadata inventory is missing")
    study_commit = str(study_manifest.get("repo_commit", ""))
    try:
        _git_bytes(repo_root, "cat-file", "-e", f"{study_commit}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"cannot resolve study commit: {study_commit}") from exc
    report_commit = _git_bytes(repo_root, "rev-parse", "HEAD").decode("utf-8").strip()

    entries: dict[str, bytes] = {}
    for path in _tracked_paths(repo_root, study_commit):
        if _source_allowed(path):
            entries[f"source/{path}"] = _git_bytes(
                repo_root, "show", f"{study_commit}:{path}"
            )
    for path in _tracked_paths(repo_root, report_commit):
        if _report_allowed(path):
            entries[f"report/{path}"] = _git_bytes(
                repo_root, "show", f"{report_commit}:{path}"
            )

    package_manifest = json.loads(
        (manuscript_package / "manifest.json").read_text(encoding="utf-8")
    )
    declared_package_files = _declared_package_files(package_manifest)
    for relative in declared_package_files:
        if not (manuscript_package / relative).is_file():
            raise ValueError(f"declared package artifact is missing: {relative}")
    for candidate in sorted(path for path in manuscript_package.rglob("*") if path.is_file()):
        relative = candidate.relative_to(manuscript_package).as_posix()
        parts = set(PurePosixPath(relative).parts)
        if parts & FORBIDDEN_PARTS or relative.endswith(FORBIDDEN_SUFFIXES):
            raise ValueError(f"forbidden generated package entry: {relative}")
        if relative not in declared_package_files:
            continue
        entries[f"generated/manuscript_package/{relative}"] = candidate.read_bytes()

    entries["generated/manuscript_package/manifest.json"] = _json_bytes(
        _sanitize(package_manifest)
    )
    entries["provenance/study_run_manifest.sanitized.json"] = _json_bytes(
        _sanitize(study_manifest)
    )
    entries["provenance/public_lake_provenance.json"] = _json_bytes(
        _sanitize(public_lake)
    )
    entries["provenance/public_source_inventory.json"] = _json_bytes(
        _sanitize(source_inventory)
    )
    entries["REPLICATION_README.md"] = REPLICATION_README.encode("utf-8")
    entries["provenance/package_manifest.json"] = _json_bytes(
        {
            "study_commit": study_commit,
            "report_commit": report_commit,
            "source_namespace": "source/",
            "report_namespace": "report/",
            "generated_namespace": "generated/manuscript_package/",
        }
    )
    _validate_entries(entries)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--study-dir", type=Path, required=True)
    parser.add_argument("--manuscript-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = build_reviewer_package(
        repo_root=args.repo_root,
        study_dir=args.study_dir,
        manuscript_package=args.manuscript_package,
        output=args.output,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The implementation extracts allowed source/config/tests/docs from `study_commit`, keeps the approved design spec, excludes only internal execution plans and the stale pre-run snapshot namespace, and then extracts the refreshed snapshot/assets from `report_commit`. It adds only table/figure/narrative files declared by the fresh package manifest, ignores nondeclared stale extras, requires every declared file to exist, adds sanitized `manifest.json`, and rejects forbidden suffixes/parts anywhere in the package tree before writing.

Build forbidden markers without embedding them contiguously in the packager's own source, for example `user_prefix = "/" + "Users" + "/"` and `cloud_marker = "One" + "Drive"`. Sanitize JSON recursively; scan text entries for the actual home directory, user-prefix paths, cloud-storage paths, and absolute local paths before closing the ZIP. Detection literals in tests must likewise be constructed from pieces so the archive does not flag its own validation source.

The in-memory `dict[str, bytes]` staging map avoids leaving a partially validated ZIP. `provenance/public_source_inventory.json` carries sanitized source URLs, acquisition metadata, payload hashes, and sidecar hashes needed to reacquire public inputs without distributing their payloads.

Read `study_commit` from the clean study manifest and verify it by passing `f"{study_commit}^{{commit}}"` as the final argument to `_git_bytes(repo_root, "cat-file", "-e", ...)`. Read `report_commit` from `git rev-parse HEAD`; it may differ because the snapshot is committed after the empirical run. Write both hashes to `provenance/package_manifest.json`.

Generate `REPLICATION_README.md` with exact commands:

```text
cd source
uv sync --locked
just check
just task benchmark sample artifacts/reviewer_smoke
just data full fresh
just task study raw artifacts/full_with_peer extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
just manuscript study_dir=artifacts/full_with_peer out_dir=artifacts/manuscript_package
just snapshot study_dir=artifacts/full_with_peer
just verify-canonical study_dir=artifacts/full_with_peer package_dir=artifacts/manuscript_package
```

State that the raw benchmark and WRDS crosswalk are not distributed and must be supplied by an authorized user.

- [ ] **Step 4: Add the entry point**

The existing `/artifacts/` rule already ignores the ZIP; do not add a redundant ignore rule.

Add:

```make
reviewer-package study_dir="artifacts/full_with_peer" package_dir="artifacts/manuscript_package": _check-data-env
    study_dir_arg="{{ study_dir }}"; study_dir_arg="${study_dir_arg#study_dir=}"; \
    package_dir_arg="{{ package_dir }}"; package_dir_arg="${package_dir_arg#package_dir=}"; \
    uv run python scripts/build_reviewer_package.py \
        --study-dir "$study_dir_arg" \
        --manuscript-package "$package_dir_arg" \
        --output artifacts/reviewer_package/reporting-risk-cascade-reviewer.zip
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
uv run pytest -q tests/test_reviewer_package.py
```

Expected: PASS.

Commit:

```bash
git add scripts/build_reviewer_package.py tests/test_reviewer_package.py justfile
git commit -m "feat(repro): build anonymized reviewer archive"
```

---

### Task 6: Stabilize the paper plan and FAQ contracts

**Files:**
- Modify: `docs/paper_plan.md`
- Modify: `docs/faq.md`
- Modify: `tests/test_docs.py`

**Interfaces:**
- Produces: a paper-structured design contract and a stable FAQ that points to generated results.

- [ ] **Step 1: Replace stale literal assertions with structural tests**

Update `test_faq_explains_cross_audience_design_and_current_boundaries` to require:

```python
for phrase in [
    "The paper plan is the design contract",
    "The results snapshot is the artifact-backed current evidence report",
    "revision-frozen `all + expanding`",
    "visibility/history information set",
    "notes/disclosure-breadth variables enter `all`",
    "no standalone text-family ablation",
    "historical conflict counts",
]:
    assert phrase in normalized_faq

for stale in ["0.3679", "0.2557", "0.0508", "`all + rolling_7y`"]:
    assert stale not in faq
```

Keep `372` and `24` only inside a section titled `Historical conflict counts`.

- [ ] **Step 2: Run the docs tests and verify the current FAQ fails**

Run:

```bash
uv run pytest -q tests/test_docs.py -k 'paper_plan or faq'
```

Expected: FAIL on stale empirical literals and missing primary/visibility wording.

- [ ] **Step 3: Update `paper_plan.md` without copying realized values**

Preserve its five top-level sections. Add or revise:

- Materials/Methods: `as_of_date=2026-07-06`, exact 2011-2024 sample window, archive-first Form AP source contract, sequential attrition definition, exact XGBoost parameters, prevalence-based weighting, seeds, expanding/5/7/10-year windows, native missing values plus fold-local categorical processing.
- Primary analysis: revision-frozen `all + expanding`, Table 3/Figure 1 only.
- Visibility/history baseline: exact information-set interpretation and no causal selection claim.
- Metrics: excluding-2020 PR-AUC sensitivity, Brier/Brier Skill/ECE interpretation.
- Construct alignment: the two exact key sets, seed 42, 1,000 bootstrap draws, primary plus top-five exploratory scope.
- Expected experiments: Table 4/Table 14 grid sensitivities, Table 18 attrition, reviewer archive, and canonical manifest gate.
- Reproducibility command: replace the paper-facing `just full` shortcut with the nonduplicating sequence `just data full fresh` followed by the one peer-enabled `just task study ...`; retain `just full` only as a convenience workflow, not the canonical paper run.

Do not insert clean-run counts or performance values.

Use these exact model/preprocessing details rather than “default XGBoost” shorthand:

```text
objective=binary:logistic; eval_metric=logloss; n_estimators=250; max_depth=4;
learning_rate=0.05; subsample=0.8; colsample_bytree=0.8;
min_child_weight=5.0; reg_lambda=1.0; tree_method=hist;
base seed=42 with task-isolated deterministic seeds; configuration default n_jobs=4,
while the canonical paper command overrides realized model threads to 2 and the run
manifest must record 2;
scale_pos_weight=max(1, training negatives/training positives) within each task/fold;
numeric columns cast to float and retain NaN for XGBoost native missing handling;
categoricals are fitted on training years only, constant-imputed to __MISSING__,
then one-hot encoded with unknown test categories ignored;
one-class train or test task/folds are skipped and reported, never silently scored.
```

- [ ] **Step 4: Remove volatile FAQ result tables**

Replace “current result” tables and best-model prose with links to `docs/results_snapshot.md`. Keep stable explanations of research question, data, models, metrics, estimand boundaries, and exact commands. Label 372/24 as dated historical diagnostics rather than current bridge counts.

- [ ] **Step 5: Run docs and strict MkDocs checks**

Run:

```bash
uv run pytest -q tests/test_docs.py
uv run --group docs mkdocs build --strict --clean
```

Expected: PASS.

- [ ] **Step 6: Commit stable documentation**

```bash
git add docs/paper_plan.md docs/faq.md tests/test_docs.py
git commit -m "docs: stabilize research and reporting contracts"
```

---

### Task 7: Verify the reporting/reproducibility sub-project

**Files:**
- Review only: changes from Tasks 1-6
- Review against: approved design spec and the evidence-pipeline handoff

**Interfaces:**
- Produces: a clean source branch ready for one canonical run.

- [ ] **Step 1: Run the complete source quality gate**

Run:

```bash
just check
git diff --check HEAD~6..HEAD
git status --short
```

Expected: all checks PASS and source worktree clean.

- [ ] **Step 2: Scan for post-hoc headline logic and volatile FAQ values**

Run:

```bash
! rg -n 'sort_values\("top_decile_lift".*iloc\[0\]|highest-lift.*primary|preregistered primary|historically pre-specified' \
  scripts src docs --glob '!docs/superpowers/**'
! rg -n '0\.3679|0\.2557|0\.0508|all \+ rolling_7y' docs/faq.md docs/paper_plan.md
! rg -n '_add_bootstrap_intervals_to_top_rows|2026-05-26|65 post-encoding control' \
  src scripts config docs justfile --glob '!docs/superpowers/**'
```

Expected: no primary selection by maximum lift, no historical-registration language, no volatile FAQ/plan values, and no retired top-only bootstrap helper, stale vintage, or hard-coded 65-control prose. Historical empirical artifacts remain untouched in this plan; the canonical-run plan moves and hashes them in its dated archive before creating new outputs.

- [ ] **Step 3: Confirm the canonical commands without running them**

Run:

```bash
just --list | rg 'verify-canonical|reviewer-package|snapshot|manuscript'
uv run python scripts/verify_canonical_run.py --help
uv run python scripts/build_reviewer_package.py --help
```

Expected: all four entry points are listed and both CLIs return help successfully.

- [ ] **Step 4: Integrate the completed source branch before canonical execution**

Use `superpowers:finishing-a-development-branch` to present and perform the user-selected integration path. The canonical-run plan may start only after all source commits are reachable from the real source repository at `../reporting-risk-cascade`, that real worktree is clean, and the isolated implementation worktree is no longer the execution cwd. Do not run the canonical data/study commands from `.worktrees/`; its relative manuscript sibling path and ignored artifact storage are different.
