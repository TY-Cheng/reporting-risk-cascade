from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_manuscript_package import (  # noqa: E402
    _bound_public_lake_inputs,
    _construct_alignment,
    _public_opacity_dml_table,
    _public_sample_attrition_table,
    _public_task_metrics,
    _select_primary_public_metrics,
    _validate_package_tree,
)
from src.provenance import (  # noqa: E402
    path_record,
    path_set_provenance,
    public_lake_provenance,
    sha256_path,
)


ATTESTATION_SCHEMA = "canonical-attestation-v1"
VERIFIER_VERSION = "5"
RUNTIME_CONTRACT = {
    "parallel_jobs": 4,
    "model_threads": 2,
    "seed_policy": "task-isolated",
    "peer_comparison_mode": "full",
    "peer_target": "both",
    "peer_parallel_jobs": 4,
    "peer_model_threads": 2,
}
RAW_RECONSTRUCTION_OWNERS = (
    "public_cascade/public_cascade_summary.json",
    "public_cascade/public_cascade_metrics.csv",
    "public_cascade/public_cascade_task_status.csv",
    "construct_overlap/public_score_benchmark_ranking.csv",
    "construct_overlap/reciprocal_alignment.csv",
    "public_cascade/public_opacity_dml.csv",
    "public_cascade/public_opacity_dml_meta.json",
    "construct_overlap/construct_overlap_manifest.json",
)


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
    "skipped_insufficient_folds",
}
POST_ENCODING_DML_STATUSES = {
    "fit",
    "skipped_constant_residual_treatment",
}
REQUIRED_DML_OUTCOMES = ["comment_thread", "amendment", "8k_402"]
SOURCE_INVENTORY_BASE_FIELDS = {"metadata_file", "metadata_sha256"}
SOURCE_INVENTORY_SIDECAR_FIELDS = SOURCE_INVENTORY_BASE_FIELDS | {
    "source_name",
    "source_url",
    "downloaded_at_utc",
    "payload_sha256",
    "payload_size_bytes",
    "parser_version",
    "schema_version",
}


def _as_object(value: object, error: str, errors: list[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    errors.append(error)
    return {}


def _is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value) is not None


def _is_exact_integer(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


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
        metadata_file = record.get("metadata_file")
        if not isinstance(metadata_file, str) or not metadata_file.strip():
            return False
        if not _is_hex(record.get("metadata_sha256"), 64):
            return False
        if not metadata_file.endswith(".meta.json"):
            if set(record) != SOURCE_INVENTORY_BASE_FIELDS:
                return False
            continue
        if set(record) != SOURCE_INVENTORY_SIDECAR_FIELDS:
            return False
        if any(
            not isinstance(record.get(field), str) or not record[field].strip()
            for field in (
                "source_name",
                "source_url",
                "downloaded_at_utc",
                "parser_version",
                "schema_version",
            )
        ):
            return False
        if not _is_hex(record.get("payload_sha256"), 64):
            return False
        payload_size = record.get("payload_size_bytes")
        if type(payload_size) is not int or payload_size < 0:
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
        "n_effective_nuisance_folds",
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
    definition = "maximum_fold_local_encoded_nuisance_columns"
    if set(dml["n_controls_definition"].astype(str)) != {definition}:
        return False
    if dml_meta.get("n_controls_definition") != definition:
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
    raw_fold_meta = dml_meta.get("n_encoded_controls_by_fold", {})
    raw_effective_fold_meta = dml_meta.get("n_effective_nuisance_folds_by_outcome", {})
    if not all(
        isinstance(value, dict)
        for value in (raw_encoded_meta, raw_fold_meta, raw_effective_fold_meta)
    ):
        return False
    encoded_meta: dict[str, int] = {}
    for outcome, value in raw_encoded_meta.items():
        count = _nonnegative_integer(value)
        if count is None:
            return False
        encoded_meta[str(outcome)] = count
    effective_fold_meta: dict[str, int] = {}
    for outcome, value in raw_effective_fold_meta.items():
        count = _nonnegative_integer(value)
        if count is None or count < 1:
            return False
        effective_fold_meta[str(outcome)] = count

    expected_encoded_outcomes: set[str] = set()
    encoded_counts: list[int | None] = []
    for outcome, status, encoded_value, alias_value, effective_fold_value in zip(
        dml["outcome"].astype(str),
        dml["status"].astype(str),
        dml["n_encoded_controls"],
        dml["n_controls"],
        dml["n_effective_nuisance_folds"],
    ):
        if status in PRE_ENCODING_DML_SKIP_STATUSES:
            if (
                not _is_missing(encoded_value)
                or not _is_missing(alias_value)
                or not _is_missing(effective_fold_value)
            ):
                return False
            if outcome in encoded_meta:
                return False
            if outcome in raw_fold_meta:
                return False
            if outcome in effective_fold_meta:
                return False
            encoded_counts.append(None)
            continue
        if status not in POST_ENCODING_DML_STATUSES:
            return False
        encoded_count = _nonnegative_integer(encoded_value)
        alias_count = _nonnegative_integer(alias_value)
        effective_fold_count = _nonnegative_integer(effective_fold_value)
        if (
            encoded_count is None
            or alias_count != encoded_count
            or effective_fold_count is None
            or effective_fold_count < 1
        ):
            return False
        encoded_counts.append(encoded_count)
        expected_encoded_outcomes.add(outcome)
        if encoded_meta.get(outcome) != encoded_count:
            return False
        if effective_fold_meta.get(outcome) != effective_fold_count:
            return False
        fold_records = raw_fold_meta.get(outcome)
        if not isinstance(fold_records, list) or len(fold_records) != effective_fold_count:
            return False
        fold_widths: list[int] = []
        for expected_fold_id, record in enumerate(fold_records, start=1):
            if not isinstance(record, dict):
                return False
            fold_id = _nonnegative_integer(record.get("fold_id"))
            fold_width = _nonnegative_integer(record.get("n_encoded_controls"))
            if fold_id != expected_fold_id or fold_width is None:
                return False
            fold_widths.append(fold_width)
        if max(fold_widths) != encoded_count:
            return False
    if set(encoded_meta) != expected_encoded_outcomes:
        return False
    if set(raw_fold_meta) != expected_encoded_outcomes:
        return False
    if set(effective_fold_meta) != expected_encoded_outcomes:
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


def _artifact_dml_evidence(dml: pd.DataFrame) -> dict[str, Any] | None:
    if not {"outcome", "status"} <= set(dml):
        return None
    outcomes = dml["outcome"].astype(str).tolist()
    if outcomes != REQUIRED_DML_OUTCOMES:
        return None
    status_by_outcome = dict(zip(outcomes, dml["status"].astype(str), strict=True))
    return {
        "required_outcomes": REQUIRED_DML_OUTCOMES,
        "status_by_outcome": status_by_outcome,
        "fit_outcomes": [
            outcome for outcome, status in status_by_outcome.items() if status == "fit"
        ],
        "maturity_by_outcome": {
            outcome: "diagnostic" if status == "fit" else "deferred"
            for outcome, status in status_by_outcome.items()
        },
    }


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
    "Bootstrap_Issuers",
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
        bootstrap_issuers = _nonnegative_integer(row["Bootstrap_Issuers"])
        if bootstrap_issuers is None or bootstrap_issuers == 0:
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


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "git command failed"
        raise ValueError(detail) from exc


def _full_commit(value: object, context: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{context} must be a full lowercase 40-hex commit")
    return value


def _validate_recorded_path_set(
    provenance: dict[str, Any],
    *,
    files_field: str,
    hash_field: str,
    context: str,
) -> str:
    records = provenance.get(files_field)
    if type(records) is not list or not records:
        raise ValueError(f"recomputed {context}: {files_field} must be a nonempty array")
    paths: list[Path] = []
    for index, record in enumerate(records):
        if type(record) is not dict or type(record.get("path")) is not str:
            raise ValueError(f"recomputed {context}: malformed {files_field}[{index}]")
        path = Path(record["path"])
        if path.is_symlink() or not path.is_file():
            raise ValueError(
                f"recomputed {context}: {files_field}[{index}] must be an existing regular file"
            )
        paths.append(path)
    recomputed = path_set_provenance(paths)
    if recomputed["files"] != records or provenance.get(hash_field) != recomputed["hash"]:
        raise ValueError(f"recomputed {context}")
    return str(recomputed["hash"])


def _validate_recorded_lock(
    provenance: dict[str, Any],
    *,
    repo_root: Path,
    context: str,
) -> str:
    raw_path = repo_root / "uv.lock"
    if raw_path.is_symlink() or not raw_path.is_file():
        raise ValueError(f"recomputed {context}: uv.lock must be an existing regular file")
    expected_path = raw_path.resolve()
    recorded = provenance.get("uv_lock")
    if type(recorded) is not dict or type(recorded.get("path")) is not str:
        raise ValueError(f"recomputed {context}: malformed uv.lock record")
    recorded_path = Path(recorded["path"])
    if recorded_path.resolve() != expected_path:
        raise ValueError(f"recomputed {context}: uv.lock path is not repository uv.lock")
    current = path_record(recorded_path)
    if recorded != current or provenance.get("uv_lock_hash") != current.get("sha256"):
        raise ValueError(f"recomputed {context}")
    return str(current["sha256"])


def _derive_bronze_root(
    run_provenance: dict[str, Any],
    source_inventory: object,
    override: Path | None,
) -> Path:
    raw_records = run_provenance.get("input_files")
    if type(raw_records) is not list or type(source_inventory) is not list:
        raise ValueError("cannot derive Bronze root from malformed source records")
    candidates: set[Path] = set()
    for inventory_record in source_inventory:
        if type(inventory_record) is not dict:
            continue
        relative_value = inventory_record.get("metadata_file")
        metadata_hash = inventory_record.get("metadata_sha256")
        if type(relative_value) is not str or type(metadata_hash) is not str:
            continue
        relative = Path(relative_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("source inventory metadata_file must be a pathless relative path")
        for raw_record in raw_records:
            if (
                type(raw_record) is not dict
                or raw_record.get("sha256") != metadata_hash
                or type(raw_record.get("path")) is not str
            ):
                continue
            raw_path = Path(raw_record["path"]).resolve()
            if tuple(raw_path.parts[-len(relative.parts) :]) != relative.parts:
                continue
            candidate = raw_path
            for _ in relative.parts:
                candidate = candidate.parent
            candidates.add(candidate)
    resolved_override = override.resolve() if override is not None else None
    if len(candidates) == 1:
        derived = next(iter(candidates))
        if resolved_override is not None and resolved_override != derived:
            raise ValueError("Bronze root override does not match the derived Bronze root")
        return derived
    if resolved_override is not None and (not candidates or resolved_override in candidates):
        return resolved_override
    raise ValueError("cannot uniquely derive Bronze root; pass --bronze-root")


def _validate_runtime(manifest: dict[str, Any]) -> dict[str, Any]:
    runtime = manifest.get("runtime")
    if type(runtime) is not dict:
        raise ValueError("runtime must be an object")
    for field, expected in RUNTIME_CONTRACT.items():
        actual = runtime.get(field)
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError(f"runtime {field}")
    if set(runtime) != set(RUNTIME_CONTRACT):
        raise ValueError("runtime fields must be exact")
    return dict(RUNTIME_CONTRACT)


def _package_artifact_inventory(package_manifest: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for group in ("tables", "figures"):
        for formats in package_manifest[group].values():
            for record in formats.values():
                records.append({"path": record["path"], "sha256": record["sha256"]})
    narrative = package_manifest["narrative"]
    records.append({"path": narrative["path"], "sha256": narrative["sha256"]})
    return sorted(records, key=lambda record: record["path"])


def _report_surface(
    repo_root: Path,
    package_manifest: dict[str, Any],
) -> list[dict[str, str]]:
    asset_root = repo_root / "docs" / "assets" / "results_snapshot"
    snapshot = repo_root / "docs" / "results_snapshot.md"
    if snapshot.is_symlink() or not snapshot.is_file():
        raise ValueError("report surface requires a regular docs/results_snapshot.md")
    png_records = [
        (
            Path(package_manifest["figures"][key]["png"]["path"]).name,
            package_manifest["figures"][key]["png"]["sha256"],
        )
        for key in sorted(package_manifest["figures"])
    ]
    png_names = [name for name, _ in png_records]
    if len(png_names) != 5 or len(set(png_names)) != 5:
        raise ValueError("report surface requires five unique declared PNG basenames")
    if asset_root.is_symlink() or not asset_root.is_dir():
        raise ValueError("results-snapshot asset tree is missing or symlinked")
    entries = list(asset_root.rglob("*"))
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("results-snapshot asset tree must contain only regular declared files")
    expected_assets = {asset_root / name for name in png_names}
    if set(entries) != expected_assets:
        raise ValueError("results-snapshot asset tree does not match declared PNG set")
    for name, expected_hash in png_records:
        if sha256_path(asset_root / name) != expected_hash:
            raise ValueError(f"report surface PNG does not match package PNG: {name}")
    paths = [snapshot, *sorted(expected_assets)]
    return sorted(
        [
            {
                "path": path.relative_to(repo_root).as_posix(),
                "sha256": str(sha256_path(path)),
            }
            for path in paths
        ],
        key=lambda record: record["path"],
    )


def _working_tree_records(repo_root: Path) -> tuple[list[tuple[str, str]], bool]:
    raw = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout
    parts = raw.split(b"\0")
    records: list[tuple[str, str]] = []
    renamed = False
    index = 0
    while index < len(parts) and parts[index]:
        record = parts[index]
        if len(record) < 4:
            raise ValueError("malformed git status record")
        status = record[:2].decode("ascii")
        path = record[3:].decode("utf-8", errors="surrogateescape")
        records.append((status, path))
        index += 1
        if "R" in status or "C" in status:
            renamed = True
            if index < len(parts) and parts[index]:
                records.append((status, parts[index].decode("utf-8", errors="surrogateescape")))
                index += 1
    return records, renamed


def _validate_precommit_git(
    repo_root: Path,
    study_commit: str,
    report_surface: list[dict[str, str]],
) -> None:
    if _git(repo_root, "rev-parse", "HEAD") != study_commit:
        raise ValueError("source HEAD does not equal the recorded study commit")
    status, renamed = _working_tree_records(repo_root)
    allowed = {record["path"] for record in report_surface}
    dirty = {path for _, path in status}
    unmerged = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
    if any(code in unmerged for code, _ in status):
        raise ValueError("working tree report surface contains an unmerged path")
    if renamed or not dirty <= allowed:
        raise ValueError("working tree report surface contains forbidden dirty paths or rename")


def _roundtrip_csv(frame: pd.DataFrame) -> pd.DataFrame:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return pd.read_csv(io.StringIO(buffer.getvalue()), low_memory=False)


def _reconstructed_tables(study_dir: Path) -> dict[str, pd.DataFrame]:
    summary = _read_json(study_dir / "public_cascade" / "public_cascade_summary.json")
    metrics = _read_csv(study_dir / "public_cascade" / "public_cascade_metrics.csv")
    task_status = _read_csv(study_dir / "public_cascade" / "public_cascade_task_status.csv")
    return {
        "table_03": _public_task_metrics(
            _select_primary_public_metrics(metrics, summary),
            task_status,
            summary,
        ),
        "table_09": _construct_alignment(study_dir),
        "table_12": _public_opacity_dml_table(study_dir),
        "table_18": _public_sample_attrition_table(summary),
    }


def _validate_reconstructed_tables(
    study_dir: Path,
    manuscript_package: Path,
    package_manifest: dict[str, Any],
) -> None:
    for key, expected in _reconstructed_tables(study_dir).items():
        relative = package_manifest["tables"][key]["csv"]["path"]
        actual = pd.read_csv(manuscript_package / relative, low_memory=False)
        try:
            pd.testing.assert_frame_equal(
                actual,
                _roundtrip_csv(expected),
                check_dtype=True,
                check_exact=True,
            )
        except AssertionError as exc:
            raise ValueError(f"{key} deterministic reconstruction") from exc


def collect_canonical_evidence(
    *,
    repo_root: Path,
    study_dir: Path,
    manuscript_package: Path,
    expected_as_of_date: str,
    bronze_root: Path | None = None,
    check_precommit: bool = True,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    study_dir = study_dir.resolve()
    manuscript_package = manuscript_package.absolute()
    study_manifest_path = study_dir / "study_run_manifest.json"
    manifest = _read_json(study_manifest_path)
    provenance = manifest.get("provenance")
    public_lake = manifest.get("public_lake_provenance")
    if type(provenance) is not dict or type(public_lake) is not dict:
        raise ValueError("study and public-lake provenance must be objects")
    study_commit = _full_commit(manifest.get("repo_commit"), "study commit")
    provenance_commit = _full_commit(provenance.get("commit_sha"), "provenance commit")
    lake_commit = _full_commit(public_lake.get("commit_sha"), "public-lake commit")
    if study_commit != provenance_commit or study_commit != lake_commit:
        raise ValueError("study, provenance, and public-lake commits must agree")
    resolved_commit = _git(repo_root, "rev-parse", "--verify", f"{study_commit}^{{commit}}")
    if resolved_commit != study_commit:
        raise ValueError("study commit does not resolve to the exact recorded commit")
    if manifest.get("git_dirty") is not False or provenance.get("dirty") is not False:
        raise ValueError("study provenance must record a clean run")
    if public_lake.get("git_dirty") is not False:
        raise ValueError("public-lake provenance must record a clean run")

    runtime = _validate_runtime(manifest)
    study_config_hash = _validate_recorded_path_set(
        provenance,
        files_field="config_files",
        hash_field="config_hash",
        context="study provenance",
    )
    study_input_hash = _validate_recorded_path_set(
        provenance,
        files_field="input_files",
        hash_field="input_hash",
        context="study provenance",
    )
    study_lock_hash = _validate_recorded_lock(
        provenance,
        repo_root=repo_root,
        context="study provenance",
    )

    bound_inputs = _bound_public_lake_inputs(
        manifest,
        study_manifest_path=study_manifest_path,
    )
    run_metadata = _read_json(bound_inputs["public_lake_run_metadata"])
    run_provenance = run_metadata.get("provenance")
    if type(run_provenance) is not dict:
        raise ValueError("public lake run metadata provenance must be an object")
    lake_config_hash = _validate_recorded_path_set(
        run_provenance,
        files_field="config_files",
        hash_field="config_hash",
        context="public-lake provenance",
    )
    lake_input_hash = _validate_recorded_path_set(
        run_provenance,
        files_field="input_files",
        hash_field="input_hash",
        context="public-lake provenance",
    )
    lake_lock_hash = _validate_recorded_lock(
        run_provenance,
        repo_root=repo_root,
        context="public-lake provenance",
    )
    derived_bronze = _derive_bronze_root(
        run_provenance,
        public_lake.get("source_metadata_inventory"),
        bronze_root,
    )
    recomputed_lake = public_lake_provenance(
        bound_inputs["public_lake_run_metadata"],
        bound_inputs["form_ap_source_metadata"],
        bronze_root=derived_bronze,
    )
    if recomputed_lake != public_lake:
        raise ValueError("recomputed public-lake provenance")
    if public_lake.get("as_of_date") != expected_as_of_date:
        raise ValueError("public-data as-of date")

    package_manifest = _validate_package_tree(manuscript_package, study_manifest_path)
    _validate_reconstructed_tables(study_dir, manuscript_package, package_manifest)
    owners = []
    for relative in RAW_RECONSTRUCTION_OWNERS:
        owner = study_dir / relative
        if owner.is_symlink() or not owner.is_file():
            raise ValueError(f"raw reconstruction owner is missing or symlinked: {relative}")
        owners.append({"path": relative, "sha256": str(sha256_path(owner))})
    owners.sort(key=lambda record: record["path"])
    report_surface = _report_surface(repo_root, package_manifest)
    if check_precommit:
        _validate_precommit_git(repo_root, study_commit, report_surface)

    components = manifest.get("components")
    if type(components) is not dict:
        raise ValueError("components must be an object")
    component = components.get("construct_overlap", {})
    if type(component) is not dict:
        raise ValueError("construct component must be an object")
    construct_manifest = _read_json(
        study_dir / "construct_overlap" / "construct_overlap_manifest.json"
    )
    paired_tier = (
        "wrds_validated"
        if component.get("validation_tier")
        == construct_manifest.get("validation_tier")
        == "wrds_validated"
        else "invalid"
    )
    if paired_tier == "invalid":
        raise ValueError("paired bridge tier must be wrds_validated in both owning manifests")
    semantic_errors = _semantic_errors(
        study_dir,
        manuscript_package,
        expected_as_of_date=expected_as_of_date,
    )
    if semantic_errors:
        raise ValueError(semantic_errors[0])
    public_input_hashes = {
        key: manifest["public_lake_inputs"][key]["sha256"]
        for key in sorted(manifest["public_lake_inputs"])
    }
    return {
        "study_commit": study_commit,
        "expected_as_of_date": expected_as_of_date,
        "paired_bridge_tier": paired_tier,
        "runtime": runtime,
        "study_manifest_sha256": str(sha256_path(study_manifest_path)),
        "study_config_hash": study_config_hash,
        "study_input_hash": study_input_hash,
        "study_uv_lock_hash": study_lock_hash,
        "public_lake_inputs": public_input_hashes,
        "public_lake_config_hash": lake_config_hash,
        "public_lake_input_hash": lake_input_hash,
        "public_lake_uv_lock_hash": lake_lock_hash,
        "package_manifest_sha256": str(sha256_path(manuscript_package / "manifest.json")),
        "package_study_manifest_sha256": package_manifest["study_manifest_sha256"],
        "package_artifacts": _package_artifact_inventory(package_manifest),
        "raw_reconstruction_owners": owners,
        "report_surface": report_surface,
    }


def _write_attestation(path: Path, evidence: dict[str, Any]) -> None:
    payload = {
        "schema_version": ATTESTATION_SCHEMA,
        "verifier_version": VERIFIER_VERSION,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **evidence,
    }
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _semantic_errors(
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
    package_reporting_contract = _as_object(
        package_manifest.get("reporting_contract"), "package reporting contract object", errors
    )
    artifact_dml_evidence = _artifact_dml_evidence(dml)
    artifact_dml_maturity = (
        "diagnostic"
        if public_component.get("status") == "complete"
        and artifact_dml_evidence is not None
        and artifact_dml_evidence["fit_outcomes"]
        else "deferred"
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
        "artifact-derived DML evidence": artifact_dml_evidence is not None
        and public_summary.get("opacity_dml_evidence") == artifact_dml_evidence
        and public_component.get("opacity_dml_evidence") == artifact_dml_evidence
        and package_reporting_contract.get("opacity_dml_evidence") == artifact_dml_evidence,
        "artifact-derived DML maturity": artifact_dml_evidence is not None
        and claim_maturity.get("opacity_dml") == artifact_dml_maturity
        and package_reporting_contract.get("claim_maturity") == claim_maturity,
        "claim maturity": claim_maturity
        == {
            "public_prediction": "reportable",
            "feature_and_window_sensitivity": "supporting",
            "construct_alignment": "supporting",
            "opacity_dml": artifact_dml_maturity,
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
        "construct bootstrap method": construct_manifest.get("interval_method")
        == "issuer_cluster_percentile_bootstrap",
        "construct bootstrap seed": _is_exact_integer(construct_manifest.get("interval_seed"), 42),
        "construct bootstrap reps": _is_exact_integer(
            construct_manifest.get("interval_reps"), 1000
        ),
        "public-to-benchmark primary keys": primary.get("public_to_benchmark") == PUBLIC_PRIMARY,
        "benchmark-to-public primary keys": primary.get("benchmark_to_public")
        == RECIPROCAL_PRIMARY,
        "public-to-benchmark primary count": _is_exact_integer(
            primary.get("public_to_benchmark_count"), 1
        ),
        "benchmark-to-public primary count": _is_exact_integer(
            primary.get("benchmark_to_public_count"), 1
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
                "Detected-misstatement score to recorded outcomes",
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
        "construct component validation tier": construct_component.get("validation_tier")
        == "wrds_validated",
        "construct manifest validation tier": construct_manifest.get("validation_tier")
        == "wrds_validated",
    }
    errors.extend(name for name, passed in checks.items() if not passed)
    return errors


def verify_canonical_run(
    study_dir: Path,
    manuscript_package: Path,
    *,
    repo_root: Path,
    expected_as_of_date: str,
    bronze_root: Path | None = None,
    check_precommit: bool = True,
) -> list[str]:
    try:
        collect_canonical_evidence(
            repo_root=repo_root,
            study_dir=study_dir,
            manuscript_package=manuscript_package,
            expected_as_of_date=expected_as_of_date,
            bronze_root=bronze_root,
            check_precommit=check_precommit,
        )
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        pd.errors.ParserError,
        subprocess.CalledProcessError,
    ) as exc:
        return [str(exc)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--bronze-root", type=Path, default=None)
    parser.add_argument("--study-dir", type=Path, required=True)
    parser.add_argument("--manuscript-package", type=Path, required=True)
    parser.add_argument("--expected-as-of-date", default="2026-07-06")
    parser.add_argument("--attestation-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = collect_canonical_evidence(
            repo_root=args.repo_root,
            study_dir=args.study_dir,
            manuscript_package=args.manuscript_package,
            expected_as_of_date=args.expected_as_of_date,
            bronze_root=args.bronze_root,
        )
        _write_attestation(args.attestation_output, evidence)
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        pd.errors.ParserError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"FAILED: {exc}")
        return 1
    print("CANONICAL RUN VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
