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
    if set(dml["n_controls_definition"].astype(str)) != {"encoded_nuisance_columns"}:
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
    if not all(_same_number(value, dml_meta.get("n_opacity_components")) for value in opacity):
        return False

    try:
        encoded_meta = {
            str(outcome): float(value)
            for outcome, value in dict(dml_meta.get("n_encoded_controls_by_outcome", {})).items()
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
        or set(table_03["Task"].astype(str)) != {"comment_thread", "amendment", "8k_402"}
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
        public_summary = _read_json(study_dir / "public_cascade" / "public_cascade_summary.json")
        construct_manifest = _read_json(
            study_dir / "construct_overlap" / "construct_overlap_manifest.json"
        )
        dml = _read_csv(study_dir / "public_cascade" / "public_opacity_dml.csv")
        dml_meta = _read_json(study_dir / "public_cascade" / "public_opacity_dml_meta.json")
        table_03 = _read_csv(manuscript_package / "tables" / "table_03_public_task_metrics.csv")
        table_09 = _read_csv(manuscript_package / "tables" / "table_09_construct_alignment.csv")
        table_12 = _read_csv(manuscript_package / "tables" / "table_12_public_opacity_dml.csv")
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
    table_09_keys = (
        set(
            table_09[["Model", "Feature_Set", "Window", "Bridge_Tier"]]
            .astype(str)
            .itertuples(index=False, name=None)
        )
        if {"Model", "Feature_Set", "Window", "Bridge_Tier"} <= set(table_09)
        else set()
    )
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
        "sample attrition/table 18 consistency": _attrition_matches(public_summary, table_18),
        "construct bootstrap scope": construct_manifest.get("interval_scope")
        == "primary_plus_top_5_per_direction",
        "construct bootstrap seed": construct_manifest.get("interval_seed") == 42,
        "construct bootstrap reps": construct_manifest.get("interval_reps") == 1000,
        "public-to-benchmark primary keys": primary.get("public_to_benchmark") == PUBLIC_PRIMARY,
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
        "package manifest files": _package_artifacts_exist(manuscript_package, package_manifest),
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
