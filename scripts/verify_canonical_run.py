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
PRE_ENCODING_DML_SKIP_STATUSES = {
    "skipped_unknown_outcome",
    "skipped_missing_label_or_censor",
    "skipped_no_opacity_components",
    "skipped_one_class_or_too_small",
    "skipped_constant_treatment",
}
POST_ENCODING_DML_STATUSES = {
    "fit",
    "skipped_insufficient_folds",
    "skipped_constant_residual_treatment",
}


def _as_object(value: object, error: str, errors: list[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    errors.append(error)
    return {}


def _is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value) is not None


def _is_exact_one(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 1


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _is_missing(value: object) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _source_inventory_is_valid(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for record in value:
        if not isinstance(record, dict):
            return False
        if not isinstance(record.get("metadata_file"), str) or not record["metadata_file"].strip():
            return False
        if not _is_hex(record.get("metadata_sha256"), 64):
            return False
        if "payload_sha256" in record and not _is_hex(record.get("payload_sha256"), 64):
            return False
    return True


def _attrition_matches(summary: dict[str, Any], table_18: pd.DataFrame) -> bool:
    raw_summary_rows = summary.get("sample_attrition", [])
    if not isinstance(raw_summary_rows, list):
        return False
    summary_rows: list[tuple[str, int, str]] = []
    for row in raw_summary_rows:
        if not isinstance(row, dict):
            return False
        count = _nonnegative_integer(row.get("n_rows"))
        if count is None:
            return False
        summary_rows.append((str(row.get("stage")), count, str(row.get("task"))))
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
    parsed_table_counts = [_nonnegative_integer(value) for value in table_counts]
    parsed_table_dropped = [_nonnegative_integer(value) for value in table_dropped]
    if any(value is None for value in parsed_table_counts + parsed_table_dropped):
        return False
    valid_table_counts = [int(value) for value in parsed_table_counts if value is not None]
    valid_table_dropped = [int(value) for value in parsed_table_dropped if value is not None]
    table_rows = list(
        zip(
            table_18["Stage"].astype(str),
            valid_table_counts,
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
        and valid_table_dropped == expected_dropped
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
        "status",
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

    raw = [_nonnegative_integer(value) for value in dml["n_raw_controls"]]
    opacity = [_nonnegative_integer(value) for value in dml["n_opacity_components"]]
    meta_raw = _nonnegative_integer(dml_meta.get("n_raw_controls"))
    meta_opacity = _nonnegative_integer(dml_meta.get("n_opacity_components"))
    if any(value is None for value in raw + opacity) or meta_raw is None or meta_opacity is None:
        return False
    if any(value != meta_raw for value in raw):
        return False
    if any(value != meta_opacity for value in opacity):
        return False

    raw_encoded_meta = dml_meta.get("n_encoded_controls_by_outcome", {})
    if not isinstance(raw_encoded_meta, dict):
        return False
    encoded_meta: dict[str, int] = {}
    for outcome, value in raw_encoded_meta.items():
        count = _nonnegative_integer(value)
        if count is None:
            return False
        encoded_meta[str(outcome)] = count

    expected_encoded_outcomes: set[str] = set()
    encoded_counts: list[int | None] = []
    for outcome, status, encoded_value, alias_value in zip(
        dml["outcome"].astype(str),
        dml["status"].astype(str),
        dml["n_encoded_controls"],
        dml["n_controls"],
    ):
        if status in PRE_ENCODING_DML_SKIP_STATUSES:
            if not _is_missing(encoded_value) or not _is_missing(alias_value):
                return False
            if outcome in encoded_meta:
                return False
            encoded_counts.append(None)
            continue
        if status not in POST_ENCODING_DML_STATUSES:
            return False
        encoded_count = _nonnegative_integer(encoded_value)
        alias_count = _nonnegative_integer(alias_value)
        if encoded_count is None or alias_count != encoded_count:
            return False
        encoded_counts.append(encoded_count)
        expected_encoded_outcomes.add(outcome)
        if encoded_meta.get(outcome) != encoded_count:
            return False
    if set(encoded_meta) != expected_encoded_outcomes:
        return False

    table_by_outcome = table_12.assign(Outcome=table_12["Outcome"].astype(str)).set_index(
        "Outcome"
    )
    if set(table_by_outcome.index) != set(dml["outcome"].astype(str)):
        return False
    for outcome, raw_value, encoded_value, opacity_value in zip(
        dml["outcome"].astype(str), raw, encoded_counts, opacity
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
    if (
        not numeric.notna().all().all()
        or not all(math.isfinite(float(value)) for value in numeric.to_numpy().ravel())
        or any(_nonnegative_integer(value) is None for value in positives)
    ):
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
    evidence = construct_manifest.get("primary_alignment_evidence", {})
    maxima = construct_manifest.get("exploratory_maxima", {})
    if not isinstance(evidence, dict) or not isinstance(maxima, dict):
        return False
    models = {
        "public_to_benchmark": "public_cascade",
        "benchmark_to_public": "benchmark_xgb",
    }
    for direction, model in models.items():
        selected = table_09.loc[table_09["Model"].astype(str).eq(model)]
        item = evidence.get(direction, {})
        if not isinstance(item, dict):
            return False
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

        maximum = maxima.get(direction, {})
        if not isinstance(maximum, dict):
            return False
        try:
            maximum_lift = float(maximum["top_decile_lift"])
            primary_lift = float(maximum["primary_lift"])
            delta = float(maximum["lift_minus_primary"])
        except (KeyError, TypeError, ValueError):
            return False
        if (
            not isinstance(maximum.get("keys"), dict)
            or not maximum["keys"]
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

    public_lake = _as_object(
        manifest.get("public_lake_provenance"),
        "public-lake provenance object",
        errors,
    )
    form_ap = _as_object(public_lake.get("form_ap"), "Form AP object", errors)
    provenance = _as_object(manifest.get("provenance"), "provenance object", errors)
    primary = _as_object(
        construct_manifest.get("primary_alignment"),
        "construct primary alignment object",
        errors,
    )
    components = _as_object(manifest.get("components"), "components object", errors)
    claim_maturity = _as_object(manifest.get("claim_maturity"), "claim maturity object", errors)
    feature_families = _as_object(
        public_summary.get("feature_family_summary"),
        "feature family summary object",
        errors,
    )
    visibility_history = _as_object(
        feature_families.get("visibility_history"),
        "visibility history object",
        errors,
    )
    visibility_count = _nonnegative_integer(visibility_history.get("n_features"))
    benchmark_component = _as_object(
        components.get("benchmark"), "benchmark component object", errors
    )
    public_component = _as_object(
        components.get("public_cascade"), "public-cascade component object", errors
    )
    bridge_component = _as_object(
        components.get("bridge_probe"), "bridge component object", errors
    )
    benchmark_peer_component = _as_object(
        components.get("peer_comparison"), "benchmark peer component object", errors
    )
    public_peer_component = _as_object(
        components.get("public_peer_comparison"), "public peer component object", errors
    )
    construct_component = _as_object(
        components.get("construct_overlap"), "construct component object", errors
    )
    table_09_identity_columns = [
        "Direction",
        "Model",
        "Target",
        "Feature_Set",
        "Window",
        "Bridge_Tier",
    ]
    table_09_keys = (
        set(table_09[table_09_identity_columns].astype(str).itertuples(index=False, name=None))
        if set(table_09_identity_columns) <= set(table_09)
        else set()
    )
    checks = {
        "study git_dirty": manifest.get("git_dirty") is False,
        "provenance dirty": provenance.get("dirty") is False,
        "public-lake git_dirty": public_lake.get("git_dirty") is False,
        "public-lake fresh build": public_lake.get("fresh_build") is True,
        "public-data as-of date": public_lake.get("as_of_date") == expected_as_of_date,
        "Form AP source kind": form_ap.get("source_kind") == "verified_zip_member",
        "Form AP archive hash": _is_hex(form_ap.get("archive_sha256"), 64),
        "Form AP member hash": _is_hex(form_ap.get("member_sha256"), 64),
        "public source inventory": _source_inventory_is_valid(
            public_lake.get("source_metadata_inventory")
        ),
        "claim maturity": claim_maturity
        == {
            "public_prediction": "reportable",
            "feature_and_window_sensitivity": "supporting",
            "construct_alignment": "supporting",
            "opacity_dml": "diagnostic",
        },
        "study commit": _is_hex(manifest.get("repo_commit"), 40),
        "provenance commit": _is_hex(provenance.get("commit_sha"), 40),
        "public-lake commit": _is_hex(public_lake.get("commit_sha"), 40),
        "public-lake config hash": _is_hex(public_lake.get("config_hash"), 64),
        "public-lake input hash": _is_hex(public_lake.get("input_hash"), 64),
        "public-lake uv.lock hash": _is_hex(public_lake.get("uv_lock_hash"), 64),
        "study/provenance commit identity": manifest.get("repo_commit")
        == provenance.get("commit_sha"),
        "study/public-lake commit identity": manifest.get("repo_commit")
        == public_lake.get("commit_sha"),
        "config hash": _is_hex(provenance.get("config_hash"), 64),
        "input hash": _is_hex(provenance.get("input_hash"), 64),
        "uv.lock hash": _is_hex(provenance.get("uv_lock_hash"), 64),
        "public primary specification": public_summary.get("primary_specification")
        == {"feature_set": "all", "train_window": "expanding"},
        "public primary status": public_summary.get("primary_specification_status")
        == "revision_frozen",
        "visibility family": visibility_count is not None and visibility_count > 0,
        "sample attrition/table 18 consistency": _attrition_matches(public_summary, table_18),
        "construct bootstrap scope": construct_manifest.get("interval_scope")
        == "primary_plus_top_5_per_direction",
        "construct bootstrap seed": construct_manifest.get("interval_seed") == 42,
        "construct bootstrap reps": construct_manifest.get("interval_reps") == 1000,
        "public-to-benchmark primary keys": primary.get("public_to_benchmark") == PUBLIC_PRIMARY,
        "benchmark-to-public primary keys": primary.get("benchmark_to_public")
        == RECIPROCAL_PRIMARY,
        "public-to-benchmark primary count": _is_exact_one(
            primary.get("public_to_benchmark_count")
        ),
        "benchmark-to-public primary count": _is_exact_one(
            primary.get("benchmark_to_public_count")
        ),
        "DML CSV/meta/Table 12 consistency": _dml_matches(dml, dml_meta, table_12),
        "Table 3 primary metrics": _table_03_matches(table_03, package_manifest),
        "Table 9 primary metrics and intervals": _alignment_evidence_matches(
            construct_manifest, table_09
        ),
        "Table 9 primary rows": table_09_keys
        == {
            (
                "Public score to benchmark positives",
                "public_cascade",
                "Item 4.02",
                "all",
                "expanding",
                "high_confidence",
            ),
            (
                "Detected-misstatement score to public labels",
                "benchmark_xgb",
                "Item 4.02",
                "benchmark_all",
                "expanding",
                "high_confidence",
            ),
        },
        "Table 18": len(table_18) >= 7,
        "benchmark component": benchmark_component.get("status") == "complete",
        "public-cascade component": public_component.get("status") == "complete",
        "bridge component": isinstance(bridge_component.get("status"), str)
        and bridge_component.get("status") in {"crosswalk_available", "complete"},
        "benchmark peer component": benchmark_peer_component.get("status") == "complete",
        "public peer component": public_peer_component.get("status") == "complete",
        "construct component": construct_component.get("run_status") == "complete",
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
