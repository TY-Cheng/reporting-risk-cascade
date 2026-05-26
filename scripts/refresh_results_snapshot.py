"""Refresh the docs results snapshot from a completed study artifact directory."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import ARTIFACTS_DIR, DOCS_DIR, PROJECT_ROOT  # noqa: E402


FULL_REQUIRED_ARTIFACTS = [
    "study_run_manifest.json",
    "benchmark/benchmark_summary.md",
    "benchmark/rolling_metrics.csv",
    "benchmark/window_summary.csv",
    "benchmark/structural_breaks.csv",
    "benchmark/feature_family_importance.csv",
    "benchmark/timing_coverage.csv",
    "public_cascade/public_cascade_summary.json",
    "public_cascade/public_cascade_metrics.csv",
    "public_cascade/public_cascade_task_status.csv",
    "public_cascade/public_opacity_dml.csv",
    "bridge_probe/bridge_probe_summary.json",
    "bridge_probe/coverage_report.csv",
    "bridge_probe/multiplicity_report.csv",
    "peer_comparison/peer_comparison_summary.md",
    "peer_comparison/detected_misstatement_model_family_metrics.csv",
    "peer_comparison/peer_task_status.csv",
    "public_peer_comparison/public_model_family_summary.md",
    "public_peer_comparison/public_model_family_metrics.csv",
    "public_peer_comparison/public_model_family_task_status.csv",
    "construct_overlap/construct_overlap_manifest.json",
    "construct_overlap/construct_overlap_summary.md",
    "construct_overlap/overlap_sample_flow.csv",
    "construct_overlap/public_score_benchmark_ranking.csv",
    "construct_overlap/reciprocal_alignment.csv",
    "construct_overlap/label_contingency_lift.csv",
    "construct_overlap/event_time_concentration.csv",
    "construct_overlap/benchmark_positive_public_label_cooccurrence.csv",
    "construct_overlap/aggregation_sensitivity.csv",
]


PARTIAL_REQUIRED_ARTIFACTS = [
    "study_run_manifest.json",
    "benchmark/benchmark_summary.md",
    "benchmark/rolling_metrics.csv",
    "public_cascade/public_cascade_summary.json",
    "public_cascade/public_cascade_metrics.csv",
    "public_cascade/public_cascade_task_status.csv",
]


def _resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, list | tuple | set):
        return ", ".join(_fmt(item, digits=digits) for item in value) or "none"
    if pd.isna(value):
        return ""
    if isinstance(value, bool):
        return "`True`" if value else "`False`"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer() and abs(value) >= 100:
            return f"{int(value):,}"
        return f"{value:.{digits}f}"
    return str(value)


def _code(value: Any) -> str:
    text = _fmt(value)
    return f"`{text}`" if text else ""


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        rows = [["" for _ in headers]]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _missing_artifacts(study_dir: Path, *, allow_partial: bool) -> list[Path]:
    required = PARTIAL_REQUIRED_ARTIFACTS if allow_partial else FULL_REQUIRED_ARTIFACTS
    return [study_dir / rel_path for rel_path in required if not (study_dir / rel_path).exists()]


def _latest_public_lake_report() -> dict[str, Any]:
    report_root = ARTIFACTS_DIR / "logs" / "public_lake_full"
    reports = sorted(report_root.glob("*/run_report.json"), key=lambda path: path.stat().st_mtime)
    if not reports:
        return {}
    report = _read_json(reports[-1])
    report["_path"] = str(reports[-1])
    snapshot = report.get("snapshot", {})
    if isinstance(snapshot, dict) and not report.get("timestamp_utc"):
        report["timestamp_utc"] = snapshot.get("timestamp_utc")
    row_counts = report.get("row_counts_json") or report.get("row_counts")
    if row_counts is None and isinstance(snapshot, dict):
        row_counts = snapshot.get("row_counts_json") or snapshot.get("row_counts")
    if isinstance(row_counts, str):
        report["row_counts"] = json.loads(row_counts)
    else:
        report["row_counts"] = row_counts or {}
    manifest_rows = report.get("manifest_rows_json")
    if manifest_rows is None and isinstance(snapshot, dict):
        manifest_rows = snapshot.get("manifest_rows_json") or snapshot.get("manifest_rows")
    if isinstance(manifest_rows, str):
        report["manifest_rows"] = json.loads(manifest_rows)
    else:
        report["manifest_rows"] = manifest_rows or {}
    return report


def _component_rows(manifest: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for name, payload in manifest.get("components", {}).items():
        if not isinstance(payload, dict):
            rows.append([name, str(payload), ""])
            continue
        status = payload.get("status") or payload.get("run_status") or ""
        tier = payload.get("validation_tier") or ""
        out_dir = payload.get("out_dir") or ""
        rows.append([name, _code(status), _code(tier), str(out_dir)])
    return rows


def _public_lake_rows(report: dict[str, Any]) -> list[list[str]]:
    row_counts = report.get("row_counts", {})
    if not isinstance(row_counts, dict):
        row_counts = {}
    wanted = [
        ("Silver", "filing_dim", "normalized public filing index"),
        ("Silver", "issuer_dim", "normalized issuer dimension"),
        ("Silver", "xbrl_core_fact", "controlled XBRL core facts"),
        ("Silver", "xbrl_fact_summary", "accession-level fact coverage"),
        ("Silver", "note_summary", "Notes summary mode"),
        ("Silver", "comment_thread", "SEC comment-thread signal"),
        ("Silver", "correction_event", "amended-filing/correction signal"),
        ("Gold", "issuer_origin_panel", "annual issuer-year modeling table"),
        ("Gold", "filing_origin_panel", "filing-origin provenance table"),
    ]
    rows = []
    for layer, artifact, note in wanted:
        rows.append([layer, f"`{artifact}`", _fmt(row_counts.get(artifact)), note])
    return rows


def _best_equal_task_config(metrics: pd.DataFrame) -> pd.Series | None:
    if metrics.empty:
        return None
    required = {"feature_set", "train_window", "task", "pr_auc"}
    if not required.issubset(metrics.columns):
        return None
    headline = metrics[~metrics["task"].astype(str).str.contains("aaer", case=False)].copy()
    if headline.empty:
        headline = metrics.copy()
    task_level = (
        headline.groupby(["feature_set", "train_window", "task"], dropna=False)["pr_auc"]
        .mean()
        .reset_index()
    )
    equal_task = (
        task_level.groupby(["feature_set", "train_window"], dropna=False)["pr_auc"]
        .mean()
        .reset_index(name="mean_pr_auc")
        .sort_values("mean_pr_auc", ascending=False)
    )
    if equal_task.empty:
        return None
    return equal_task.iloc[0]


def _public_task_rows(metrics: pd.DataFrame, summary: dict[str, Any]) -> list[list[str]]:
    if metrics.empty or "task" not in metrics.columns:
        return []
    metrics = metrics.loc[~metrics["task"].astype(str).str.contains("aaer", case=False)].copy()
    if metrics.empty:
        return []
    grouped = (
        metrics.groupby("task", dropna=False)
        .agg(
            rows=("pr_auc", "size"),
            mean_prevalence=("positive_rate_test", "mean"),
            mean_pr_auc=("pr_auc", "mean"),
            mean_roc_auc=("roc_auc", "mean"),
        )
        .reset_index()
    )
    positives = summary.get("task_positive_counts", {})
    rows = []
    for _, row in grouped.sort_values("mean_pr_auc", ascending=False).iterrows():
        task = str(row["task"])
        rows.append(
            [
                _code(task),
                _fmt(positives.get(task)),
                _fmt(row["mean_prevalence"]),
                _fmt(row["mean_pr_auc"]),
                _fmt(row["mean_roc_auc"]),
                _fmt(row["rows"], digits=0),
            ]
        )
    return rows


def _public_feature_rows(metrics: pd.DataFrame, summary: dict[str, Any]) -> list[list[str]]:
    if metrics.empty or "feature_set" not in metrics.columns:
        return []
    if "task" in metrics.columns:
        metrics = metrics.loc[~metrics["task"].astype(str).str.contains("aaer", case=False)].copy()
    if metrics.empty:
        return []
    grouped = (
        metrics.groupby("feature_set", dropna=False)
        .agg(rows=("pr_auc", "size"), mean_pr_auc=("pr_auc", "mean"), mean_roc_auc=("roc_auc", "mean"))
        .reset_index()
        .sort_values("mean_pr_auc", ascending=False)
    )
    family = summary.get("feature_family_summary", {})
    rows = []
    for _, row in grouped.iterrows():
        feature_set = str(row["feature_set"])
        meta = family.get(feature_set, {}) if isinstance(family, dict) else {}
        rows.append(
            [
                _code(feature_set),
                _fmt(meta.get("n_features")),
                _fmt(meta.get("n_xbrl_ratio_features")),
                _fmt(meta.get("n_xbrl_coverage_features")),
                _fmt(row["mean_pr_auc"]),
                _fmt(row["mean_roc_auc"]),
                _fmt(row["rows"], digits=0),
            ]
        )
    return rows


def _benchmark_panel_rows(study_dir: Path) -> list[list[str]]:
    summary = _read_text(study_dir / "benchmark" / "benchmark_summary.md")
    if not summary:
        return []
    rows = []
    for label in [
        "Rows",
        "Firms",
        "Years",
        "Positive rate",
        "Positive rows without timing proxy",
        "Timing claim status",
    ]:
        match = re.search(rf"^- {re.escape(label)}: (.+)$", summary, flags=re.MULTILINE)
        if match:
            rows.append([label, match.group(1)])
    return rows


def _benchmark_timing_rows(metrics: pd.DataFrame) -> list[list[str]]:
    if metrics.empty or not {"label_mode", "window", "pr_auc"}.issubset(metrics.columns):
        return []
    grouped = (
        metrics.groupby(["label_mode", "window"], dropna=False)
        .agg(
            pr_auc=("pr_auc", "mean"),
            roc_auc=("roc_auc", "mean"),
            top_100_precision=("top_100_precision", "mean"),
            retained_positive_share=("retained_positive_train_share", "mean"),
        )
        .reset_index()
    )
    best = grouped.sort_values("pr_auc", ascending=False).groupby("label_mode", as_index=False).head(1)
    rows = []
    for _, row in best.sort_values("pr_auc", ascending=False).iterrows():
        rows.append(
            [
                _code(row["label_mode"]),
                _code(row["window"]),
                _fmt(row["pr_auc"]),
                _fmt(row["roc_auc"]),
                _fmt(row["top_100_precision"]),
                _fmt(row["retained_positive_share"]),
            ]
        )
    return rows


def _peer_model_rows(path: Path) -> list[list[str]]:
    metrics = _read_csv(path)
    if metrics.empty:
        return []
    model_col = "peer_model_id" if "peer_model_id" in metrics.columns else "model_id"
    if model_col not in metrics.columns:
        return []
    agg_spec = {
        "rows": ("pr_auc", "size"),
        "mean_pr_auc": ("pr_auc", "mean"),
        "mean_roc_auc": ("roc_auc", "mean"),
        "max_pr_auc": ("pr_auc", "max"),
    }
    if "brier" in metrics.columns:
        agg_spec["mean_brier"] = ("brier", "mean")
    grouped = metrics.groupby(model_col, dropna=False).agg(**agg_spec).reset_index()
    rows = []
    for _, row in grouped.sort_values("mean_pr_auc", ascending=False).iterrows():
        rows.append(
            [
                _code(row[model_col]),
                _fmt(row["rows"], digits=0),
                _fmt(row["mean_pr_auc"]),
                _fmt(row["mean_roc_auc"]),
                _fmt(row["max_pr_auc"]),
                _fmt(row.get("mean_brier")),
            ]
        )
    return rows


def _public_peer_task_rows(path: Path) -> list[list[str]]:
    metrics = _read_csv(path)
    if metrics.empty or "task" not in metrics.columns:
        return []
    grouped = (
        metrics.groupby("task", dropna=False)
        .agg(
            rows=("pr_auc", "size"),
            mean_prevalence=("prevalence", "mean")
            if "prevalence" in metrics.columns
            else ("pr_auc", "size"),
            mean_pr_auc=("pr_auc", "mean"),
            mean_roc_auc=("roc_auc", "mean"),
            max_pr_auc=("pr_auc", "max"),
        )
        .reset_index()
    )
    rows = []
    for _, row in grouped.sort_values("mean_pr_auc", ascending=False).iterrows():
        rows.append(
            [
                _code(row["task"]),
                _fmt(row["rows"], digits=0),
                _fmt(row["mean_prevalence"]),
                _fmt(row["mean_pr_auc"]),
                _fmt(row["mean_roc_auc"]),
                _fmt(row["max_pr_auc"]),
            ]
        )
    return rows


def _status_count_rows(path: Path) -> list[list[str]]:
    frame = _read_csv(path)
    if frame.empty or "status" not in frame.columns:
        return []
    if "task" in frame.columns:
        frame = frame.loc[~frame["task"].astype(str).str.contains("aaer", case=False)].copy()
    if frame.empty:
        return []
    group_cols = ["status"]
    if "reason_code" in frame.columns:
        group_cols.append("reason_code")
    grouped = frame.groupby(group_cols, dropna=False).size().reset_index(name="rows")
    rows = []
    for _, row in grouped.sort_values("rows", ascending=False).iterrows():
        reason = row.get("reason_code", "")
        rows.append([_code(row["status"]), _code(reason), _fmt(row["rows"], digits=0)])
    return rows


def _benchmark_window_rows(study_dir: Path) -> list[list[str]]:
    frame = _read_csv(study_dir / "benchmark" / "rolling_metrics.csv")
    required = {
        "label_mode",
        "window",
        "pr_auc",
        "roc_auc",
        "brier_skill_score",
        "ece",
        "top_100_precision",
        "top_decile_precision",
    }
    if frame.empty or not required.issubset(frame.columns):
        return []
    grouped = (
        frame.groupby(["label_mode", "window"], dropna=False)
        .agg(
            pr_auc=("pr_auc", "mean"),
            roc_auc=("roc_auc", "mean"),
            brier_skill_score=("brier_skill_score", "mean"),
            ece=("ece", "mean"),
            top_100_precision=("top_100_precision", "mean"),
            top_decile_precision=("top_decile_precision", "mean"),
        )
        .reset_index()
    )
    rows = []
    for _, row in grouped.sort_values(["label_mode", "pr_auc"], ascending=[True, False]).iterrows():
        rows.append(
            [
                _code(row["label_mode"]),
                _code(row["window"]),
                _fmt(row["pr_auc"]),
                _fmt(row["roc_auc"]),
                _fmt(row["brier_skill_score"]),
                _fmt(row["ece"]),
                _fmt(row["top_100_precision"]),
                _fmt(row["top_decile_precision"]),
            ]
        )
    return rows


def _structural_break_rows(study_dir: Path, *, max_rows: int = 12) -> list[list[str]]:
    frame = _read_csv(study_dir / "benchmark" / "structural_breaks.csv")
    if frame.empty or not {"window", "label_mode", "family", "break_year", "f_stat", "p_value"}.issubset(frame.columns):
        return []
    frame = frame.copy()
    frame["p_value_num"] = pd.to_numeric(frame["p_value"], errors="coerce")
    rows = []
    for _, row in frame.sort_values("p_value_num").head(max_rows).iterrows():
        rows.append(
            [
                _code(row["window"]),
                _code(row["label_mode"]),
                _code(row["family"]),
                _fmt(row["break_year"]),
                _fmt(row["f_stat"]),
                _fmt(row["p_value"]),
            ]
        )
    return rows


def _feature_importance_rows(study_dir: Path, *, max_rows: int = 12) -> list[list[str]]:
    frame = _read_csv(study_dir / "benchmark" / "feature_family_importance.csv")
    if frame.empty or not {"label_mode", "family", "importance_share"}.issubset(frame.columns):
        return []
    grouped = (
        frame.groupby(["label_mode", "family"], dropna=False)["importance_share"]
        .mean()
        .reset_index()
        .sort_values("importance_share", ascending=False)
    )
    rows = []
    for _, row in grouped.head(max_rows).iterrows():
        rows.append([_code(row["label_mode"]), _code(row["family"]), _fmt(row["importance_share"])])
    return rows


def _opacity_rows(study_dir: Path) -> list[list[str]]:
    path = study_dir / "opacity_validation_refresh" / "opacity_diagnostics_summary.csv"
    if not path.exists():
        path = study_dir / "public_cascade" / "public_opacity_dml.csv"
    frame = _read_csv(path)
    if frame.empty:
        return []
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _code(row.get("outcome")),
                _fmt(row.get("n_obs")),
                _fmt(row.get("prevalence")),
                _fmt(row.get("mean_treatment")),
                _fmt(row.get("coef")),
                _fmt(row.get("std_err")),
                _fmt(row.get("p_value")),
                _code(row.get("status")),
            ]
        )
    return rows


def _simple_csv_rows(path: Path, columns: list[str], *, max_rows: int | None = None) -> list[list[str]]:
    frame = _read_csv(path)
    if frame.empty or not set(columns).issubset(frame.columns):
        return []
    if max_rows is not None:
        frame = frame.head(max_rows)
    rows = []
    for _, row in frame.iterrows():
        rows.append([_fmt(row.get(col)) if col not in {"public_label", "bridge_tier", "label_pattern", "metric_status"} else _code(row.get(col)) for col in columns])
    return rows


def _overlap_sample_flow_rows(study_dir: Path) -> list[list[str]]:
    return _simple_csv_rows(
        study_dir / "construct_overlap" / "overlap_sample_flow.csv",
        ["bridge_tier", "rows", "benchmark_positives"],
    )


def _label_contingency_rows(study_dir: Path) -> list[list[str]]:
    frame = _read_csv(study_dir / "construct_overlap" / "label_contingency_lift.csv")
    if frame.empty:
        return []
    columns = [
        "public_label",
        "bridge_tier",
        "n",
        "benchmark_positive_rows",
        "public_positive_rows",
        "both_positive_rows",
        "lift_public_given_benchmark",
        "lift_benchmark_given_public",
    ]
    if not set(columns).issubset(frame.columns):
        return []
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _code(row["public_label"]),
                _code(row["bridge_tier"]),
                _fmt(row["n"]),
                _fmt(row["benchmark_positive_rows"]),
                _fmt(row["public_positive_rows"]),
                _fmt(row["both_positive_rows"]),
                _fmt(row["lift_public_given_benchmark"]),
                _fmt(row["lift_benchmark_given_public"]),
            ]
        )
    return rows


def _event_time_rows(study_dir: Path) -> list[list[str]]:
    frame = _read_csv(study_dir / "construct_overlap" / "event_time_concentration.csv")
    if frame.empty:
        return []
    if "public_label" in frame.columns:
        frame = frame.loc[~frame["public_label"].astype(str).str.contains("aaer", case=False)].copy()
    if frame.empty:
        return []
    columns = [
        "relative_year",
        "public_label",
        "n_benchmark_positive",
        "n_benchmark_negative",
        "public_label_rate_benchmark_positive",
        "public_label_rate_benchmark_negative",
        "raw_difference",
        "balanced_window",
    ]
    if not set(columns).issubset(frame.columns):
        return []
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _fmt(row["relative_year"]),
                _code(row["public_label"]),
                _fmt(row["n_benchmark_positive"]),
                _fmt(row["n_benchmark_negative"]),
                _fmt(row["public_label_rate_benchmark_positive"]),
                _fmt(row["public_label_rate_benchmark_negative"]),
                _fmt(row["raw_difference"]),
                _fmt(bool(row["balanced_window"])),
            ]
        )
    return rows


def _manifest_inventory(root: Path) -> list[str]:
    if not root.exists():
        return [f"- `{_rel(root)}` (missing)"]
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != ".DS_Store" and "__pycache__" not in path.parts
    ]
    return [f"- `{_rel(path)}`" for path in files]


def _table_figure_rows(package_dir: Path) -> list[list[str]]:
    rows = []
    for kind, subdir in [("Table", "tables"), ("Figure", "figures")]:
        root = package_dir / subdir
        if not root.exists():
            rows.append([kind, _code(subdir), "missing"])
            continue
        files = sorted(path for path in root.iterdir() if path.is_file() and path.name != ".DS_Store")
        for path in files:
            rows.append([kind, _code(path.name), _rel(path)])
    return rows


def _bridge_coverage_rows(path: Path) -> list[list[str]]:
    coverage = _read_csv(path)
    if coverage.empty or not {"metric", "value"}.issubset(coverage.columns):
        return []
    wanted = [
        "raw_rows",
        "raw_firms",
        "matched_raw_rows",
        "matched_raw_firms",
        "row_coverage_rate",
        "firm_coverage_rate",
        "raw_positive_rows",
        "matched_positive_rows",
    ]
    values = dict(zip(coverage["metric"], coverage["value"], strict=False))
    return [[metric, _fmt(values.get(metric))] for metric in wanted if metric in values]


def _construct_alignment_rows(study_dir: Path) -> list[list[str]]:
    public_to_benchmark = _read_csv(study_dir / "construct_overlap" / "public_score_benchmark_ranking.csv")
    benchmark_to_public = _read_csv(study_dir / "construct_overlap" / "reciprocal_alignment.csv")
    rows = []
    if not public_to_benchmark.empty and "top_decile_lift" in public_to_benchmark.columns:
        best = public_to_benchmark.sort_values("top_decile_lift", ascending=False).iloc[0]
        rows.append(
            [
                "Public cascade score -> benchmark positives",
                _code(best.get("model_id")),
                _code(best.get("task")),
                _fmt(best.get("pr_auc")),
                _fmt(best.get("roc_auc")),
                _fmt(best.get("top_decile_lift")),
            ]
        )
    if not benchmark_to_public.empty and "top_decile_lift" in benchmark_to_public.columns:
        best = benchmark_to_public.sort_values("top_decile_lift", ascending=False).iloc[0]
        rows.append(
            [
                "Detected-misstatement score -> public labels",
                _code(best.get("model_id")),
                _code(best.get("target_public_label")),
                _fmt(best.get("pr_auc")),
                _fmt(best.get("roc_auc")),
                _fmt(best.get("top_decile_lift")),
            ]
        )
    return rows


def _artifact_index(study_dir: Path) -> list[str]:
    wanted = [
        "study_summary.md",
        "study_run_manifest.json",
        "benchmark/benchmark_summary.md",
        "benchmark/rolling_metrics.csv",
        "public_cascade/public_cascade_summary.md",
        "public_cascade/public_cascade_metrics.csv",
        "peer_comparison/peer_comparison_summary.md",
        "peer_comparison/detected_misstatement_model_family_metrics.csv",
        "public_peer_comparison/public_model_family_summary.md",
        "public_peer_comparison/public_model_family_metrics.csv",
        "bridge_probe/bridge_probe_summary.json",
        "bridge_probe/coverage_report.csv",
        "construct_overlap/construct_overlap_summary.md",
        "construct_overlap/public_score_benchmark_ranking.csv",
        "construct_overlap/reciprocal_alignment.csv",
        "opacity_validation_refresh/opacity_diagnostics_summary.csv",
    ]
    lines = []
    for rel_path in wanted:
        path = study_dir / rel_path
        marker = "present" if path.exists() else "missing"
        lines.append(f"- `{_rel(path)}` ({marker})")
    return lines


def build_snapshot(study_dir: Path, *, allow_partial: bool) -> str:
    manifest = _read_json(study_dir / "study_run_manifest.json")
    public_summary = _read_json(study_dir / "public_cascade" / "public_cascade_summary.json")
    bridge_summary = _read_json(study_dir / "bridge_probe" / "bridge_probe_summary.json")
    construct_manifest = _read_json(study_dir / "construct_overlap" / "construct_overlap_manifest.json")
    public_lake_report = _latest_public_lake_report()
    public_metrics = _read_csv(study_dir / "public_cascade" / "public_cascade_metrics.csv")
    benchmark_metrics = _read_csv(study_dir / "benchmark" / "rolling_metrics.csv")
    public_task_positive_counts = {
        key: value
        for key, value in (public_summary.get("task_positive_counts") or {}).items()
        if "aaer" not in str(key).lower()
    }
    public_task_exclusion_counts = {
        key: value
        for key, value in (public_summary.get("task_exclusion_counts") or {}).items()
        if "aaer" not in str(key).lower()
    }
    zero_positive_tasks = [
        task
        for task in (public_summary.get("zero_positive_tasks") or [])
        if "aaer" not in str(task).lower()
    ]

    best_public = _best_equal_task_config(public_metrics)
    if public_summary.get("best_feature_set") and public_summary.get("best_train_window"):
        best_public_text = (
            f"`{public_summary['best_feature_set']} + {public_summary['best_train_window']}` "
            f"with reported mean PR-AUC `{_fmt(public_summary.get('best_mean_pr_auc'))}`"
        )
    elif best_public is not None:
        best_public_text = (
            f"`{best_public['feature_set']} + {best_public['train_window']}` "
            f"with equal-task mean PR-AUC `{_fmt(best_public['mean_pr_auc'])}`"
        )
    else:
        best_public_text = "not available"

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    study_rel = _rel(study_dir)
    validation_tier = construct_manifest.get("validation_tier") or "not available"
    bridge_status = bridge_summary.get("status") or manifest.get("bridge", {}).get("status") or ""
    peer_status = manifest.get("runtime", {}).get("peer_comparison_mode") or ""

    manuscript_package = ARTIFACTS_DIR / "manuscript_package"

    lines = [
        "---",
        "hide:",
        "  - navigation",
        "---",
        "",
        "# Results and Discussion",
        "",
        f"_Generated by `just snapshot` from `{study_rel}` at `{generated_at}`._",
        "",
        "## Results Overview",
        "",
        "- **Research question.** Can filing-origin public SEC/PCAOB information predict "
        "whether an issuer later enters observable public review-and-correction channels, "
        "and how does this public reporting-risk construct relate to, but differ from, "
        "the detected-misstatement benchmark?",
        "",
        "- **Data.** The workflow combines the `gvkey x data_year` "
        "detected-misstatement benchmark, the public SEC/PCAOB lake, the gold "
        "`issuer_origin_panel` and `filing_origin_panel`, and a raw-only "
        "`gvkey-CIK-year` bridge for overlap validation.",
        "",
        "- **Models.** The core public cascade uses XGBoost over metadata, XBRL, "
        "text/notes, auditor, oversight, and all-feature sets. Peer-compatible "
        "Dechow, Perols, Bao, and Bertomeu-style suites are included when the "
        "peer-enabled study directory is present.",
        "",
        "- **Metrics.** The common metric vocabulary is PR-AUC relative to prevalence, "
        "ROC-AUC, Brier, Brier Skill Score, ECE, top-k precision, top-decile lift, "
        "and Bao-style top-fraction precision, sensitivity, specificity, BAC, and NDCG.",
        "",
        "- **Current best public-cascade specification.** " + best_public_text + ".",
        "",
        f"- **Bridge boundary.** Construct overlap is `{validation_tier}` using the "
        "confirmed WRDS SEC Analytics Suite CIK-GVKEY bridge.",
        "",
        "- **Sellable claim.** The strongest current framing is a measurement-and-ranking "
        "paper on filing-origin public reporting-risk states. It does not support causal "
        "claims, unobserved true-fraud occurrence claims, or same-estimand performance "
        "rankings over prior fraud-prediction papers.",
        "",
        "## Reproducibility Metadata",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Study directory", _code(study_rel)],
                ["Snapshot mode", _code("partial" if allow_partial else "full")],
                ["Study manifest timestamp", _code(manifest.get("generated_at_utc"))],
                ["Public-lake report timestamp", _code(public_lake_report.get("timestamp_utc"))],
                ["Peer comparison mode", _code(peer_status)],
                ["Bridge status", _code(bridge_status)],
                ["Construct-overlap validation tier", _code(validation_tier)],
                ["Raw benchmark input", _code(manifest.get("inputs", {}).get("raw_data"))],
                ["Public issuer panel", _code(manifest.get("inputs", {}).get("issuer_origin_panel"))],
                ["Bridge crosswalk", _code(manifest.get("inputs", {}).get("crosswalk"))],
            ],
        ),
        "",
        "### Component Status",
        "",
        _table(["Component", "Status", "Tier", "Output"], _component_rows(manifest)),
        "",
        "### Evidence Map",
        "",
        "```mermaid",
        "flowchart LR",
        '    L["Experiment 1-2<br/>benchmark timing and drift"]',
        '    O["Experiment 3<br/>opacity and public labels"]',
        '    P["Experiment 4-5<br/>public cascade construction and prediction"]',
        '    B["Experiment 6<br/>raw-only bridge and construct overlap"]',
        '    D["Discussion<br/>claim boundary and manuscript tables/figures"]',
        "    L --> D",
        "    O --> D",
        "    P --> D",
        "    B --> D",
        "```",
        "",
        "## Experiment 1: Label Observability and Detection Timing",
        "",
        "This experiment reads detected-misstatement benchmark performance as an "
        "observability diagnostic rather than a true-fraud detection result.",
        "",
        "### Detected-Misstatement Benchmark Panel",
        "",
        _table(["Field", "Value"], _benchmark_panel_rows(study_dir)),
        "",
        "### Best Timing-Sensitivity Rows by Label Mode",
        "",
        _table(
            [
                "Label mode",
                "Best window",
                "Mean PR-AUC",
                "Mean ROC-AUC",
                "Top-100 precision",
                "Retained positive share",
            ],
            _benchmark_timing_rows(benchmark_metrics),
        ),
        "",
        "### Full Window Summary",
        "",
        _table(
            [
                "Label mode",
                "Window",
                "PR-AUC",
                "ROC-AUC",
                "Brier Skill Score",
                "ECE",
                "Top-100 precision",
                "Top-decile precision",
            ],
            _benchmark_window_rows(study_dir),
        ),
        "",
        "## Experiment 2: Concept Drift and Model Shelf-Life",
        "",
        "This experiment compares rolling and expanding windows and checks whether "
        "feature-family importance shifts around candidate regime breaks.",
        "",
        "### Strongest Structural-Break Diagnostics",
        "",
        _table(
            ["Window", "Label mode", "Feature family", "Break year", "F-stat", "p-value"],
            _structural_break_rows(study_dir),
        ),
        "",
        "### Mean Feature-Family Importance",
        "",
        _table(
            ["Label mode", "Feature family", "Mean importance share"],
            _feature_importance_rows(study_dir),
        ),
        "",
        "## Experiment 3: Opacity and Public Review/Correction Risk",
        "",
        "The opacity analysis reports adjusted associations from DML partially linear "
        "regressions. These estimates are not causal effects.",
        "",
        _table(
            [
                "Outcome",
                "Rows",
                "Prevalence",
                "Mean treatment",
                "Coef",
                "Std err",
                "p-value",
                "Status",
            ],
            _opacity_rows(study_dir),
        ),
        "",
        "## Experiment 4: Public Cascade Construction",
        "",
        "This experiment validates whether public SEC/PCAOB data can support the "
        "filing-origin review-and-correction measurement surface.",
        "",
        "### Public Lake and Gold Panel Scale",
        "",
        _table(["Layer", "Artifact", "Rows", "Notes"], _public_lake_rows(public_lake_report)),
        "",
        "### Public Cascade Readiness",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Main sample rows", _fmt(public_summary.get("n_rows"))],
                ["Fiscal-year span", "-".join(map(str, public_summary.get("sample_years", [])))],
                ["Domestic US GAAP only", _fmt(public_summary.get("domestic_only"))],
                ["Task positive counts", _code(public_task_positive_counts)],
                ["Task exclusion counts", _code(public_task_exclusion_counts)],
                ["Zero-positive tasks", _code(zero_positive_tasks or "none")],
                ["Task status counts", _code(public_summary.get("task_status_counts"))],
                ["Readiness level", _code(public_summary.get("cascade_readiness_level"))],
            ],
        ),
        "",
        "### Public Cascade Fit and Skip Status",
        "",
        _table(
            ["Status", "Reason", "Rows"],
            _status_count_rows(study_dir / "public_cascade" / "public_cascade_task_status.csv"),
        ),
        "",
        "## Experiment 5: Public Cascade Prediction",
        "",
        "This experiment estimates the pre-disclosure public reporting-risk state and "
        "compares feature families and peer-compatible model families.",
        "",
        "### Public Task Metrics",
        "",
        _table(
            ["Task", "Positives", "Mean prevalence", "Mean PR-AUC", "Mean ROC-AUC", "Rows"],
            _public_task_rows(public_metrics, public_summary),
        ),
        "",
        "### Public Feature-Family Metrics",
        "",
        _table(
            [
                "Feature set",
                "Features",
                "XBRL ratios",
                "XBRL coverage",
                "Mean PR-AUC",
                "Mean ROC-AUC",
                "Rows",
            ],
            _public_feature_rows(public_metrics, public_summary),
        ),
        "",
        "### Detected-Misstatement Peer-Compatible Literature Benchmarks",
        "",
        "These rows are present only when the peer-enabled study has run. They are "
        "model-family transfer and metric-language alignment, not exact replications "
        "of the original-paper samples.",
        "",
        _table(
            ["Model", "Rows", "Mean PR-AUC", "Mean ROC-AUC", "Max PR-AUC", "Mean Brier"],
            _peer_model_rows(study_dir / "peer_comparison" / "detected_misstatement_model_family_metrics.csv"),
        ),
        "",
        "### Detected-Misstatement Peer Fit and Skip Status",
        "",
        _table(
            ["Status", "Reason", "Rows"],
            _status_count_rows(study_dir / "peer_comparison" / "peer_task_status.csv"),
        ),
        "",
        "### Public-Label Peer Transfer",
        "",
        _table(
            ["Model", "Rows", "Mean PR-AUC", "Mean ROC-AUC", "Max PR-AUC", "Mean Brier"],
            _peer_model_rows(
                study_dir / "public_peer_comparison" / "public_model_family_metrics.csv"
            ),
        ),
        "",
        "### Public Peer Task Summary",
        "",
        _table(
            ["Task", "Rows", "Mean prevalence", "Mean PR-AUC", "Mean ROC-AUC", "Max PR-AUC"],
            _public_peer_task_rows(
                study_dir / "public_peer_comparison" / "public_model_family_metrics.csv"
            ),
        ),
        "",
        "### Public Peer Fit and Skip Status",
        "",
        _table(
            ["Status", "Reason", "Rows"],
            _status_count_rows(
                study_dir / "public_peer_comparison" / "public_model_family_task_status.csv"
            ),
        ),
        "",
        "## Experiment 6: Detected-Misstatement Benchmark and Public Cascade Overlap",
        "",
        "This experiment is the integrated-paper gate. The current bridge is the "
        "confirmed WRDS SEC Analytics Suite CIK-GVKEY link export, used as a "
        "raw-only `gvkey-CIK-year` bridge.",
        "",
        "### Bridge Coverage",
        "",
        _table(
            ["Metric", "Value"],
            _bridge_coverage_rows(study_dir / "bridge_probe" / "coverage_report.csv"),
        ),
        "",
        "### Overlap Sample Flow",
        "",
        _table(["Bridge tier", "Rows", "Benchmark positives"], _overlap_sample_flow_rows(study_dir)),
        "",
        "### Construct-Overlap Ranking Alignment",
        "",
        _table(
            ["Direction", "Model", "Target", "PR-AUC", "ROC-AUC", "Top-decile lift"],
            _construct_alignment_rows(study_dir),
        ),
        "",
        "### Label Contingency and Lift",
        "",
        _table(
            [
                "Public label",
                "Bridge tier",
                "Rows",
                "Benchmark positives",
                "Public positives",
                "Both positive",
                "Lift public given benchmark",
                "Lift benchmark given public",
            ],
            _label_contingency_rows(study_dir),
        ),
        "",
        "### Aggregation Sensitivity",
        "",
        _table(
            [
                "Public label",
                "Bridge tier",
                "Aggregation rule",
                "Rows",
                "Pre-agg rate",
                "Post-agg rate",
                "Rate delta",
                "Sensitive",
            ],
            _simple_csv_rows(
                study_dir / "construct_overlap" / "aggregation_sensitivity.csv",
                [
                    "public_label",
                    "bridge_tier",
                    "aggregation_rule",
                    "rows",
                    "pre_agg_pos_rate",
                    "post_agg_pos_rate",
                    "pos_rate_delta",
                    "aggregation_sensitive",
                ],
            ),
        ),
        "",
        "### Benchmark-Positive Public-Label Co-occurrence",
        "",
        _table(
            [
                "Pattern",
                "Comment",
                "Amendment",
                "8-K 4.02",
                "Benchmark positives",
                "Share",
                "Display count",
            ],
            _simple_csv_rows(
                study_dir / "construct_overlap" / "benchmark_positive_public_label_cooccurrence.csv",
                [
                    "label_pattern",
                    "label_comment_thread_365",
                    "label_amendment_365",
                    "label_8k_402_365",
                    "n_benchmark_positives",
                    "pct_of_benchmark_positives",
                    "display_count",
                ],
            ),
        ),
        "",
        "### Event-Time Concentration",
        "",
        _table(
            [
                "Relative year",
                "Public label",
                "Benchmark pos rows",
                "Benchmark neg rows",
                "Rate if benchmark pos",
                "Rate if benchmark neg",
                "Difference",
                "Balanced window",
            ],
            _event_time_rows(study_dir),
        ),
        "",
        "## Discussion",
        "",
        "### Key Readings",
        "",
        "- Public labels and detected-misstatement benchmark labels are related but "
        "non-identical constructs.",
        "- Public-cascade scores can rank benchmark positives in the matched overlap; "
        "detected-misstatement scores can also rank severe public correction labels.",
        f"- `{validation_tier}` bridge evidence supports the integrated "
        "benchmark-to-public construct-overlap interpretation.",
        "",
        "### Claim Boundaries",
        "",
        "- The evidence supports measurement and decision-useful prediction claims, not "
        "causal proof of fraud occurrence.",
        "- Comment letters are public scrutiny signals, not the complete SEC review "
        "universe.",
        "- WRDS-validated raw-only overlap can support a related-but-non-identical "
        "construct argument, while still not supporting causal fraud-occurrence claims.",
        "",
        "## Tables, Figures, and Artifact Index",
        "",
        "### Manuscript Package Tables and Figures",
        "",
        _table(["Kind", "File", "Path"], _table_figure_rows(manuscript_package)),
        "",
        "### Selected Artifact Index",
        "",
        "This index lists high-signal artifacts referenced by this generated snapshot.",
        "",
        *_artifact_index(study_dir),
        "",
        "### Full Study Artifact Inventory",
        "",
        *_manifest_inventory(study_dir),
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--study-dir",
        default=ARTIFACTS_DIR / "full_with_peer",
        type=Path,
        help="Completed study artifact directory to summarize.",
    )
    parser.add_argument(
        "--docs-file",
        default=DOCS_DIR / "results_snapshot.md",
        type=Path,
        help="Markdown file to refresh.",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow a non-peer study directory and mark missing peer outputs in the docs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    study_dir = _resolve_repo_path(args.study_dir)
    docs_file = _resolve_repo_path(args.docs_file)
    missing = _missing_artifacts(study_dir, allow_partial=args.allow_partial)
    if missing:
        missing_list = "\n".join(f"- {_rel(path)}" for path in missing)
        mode = "partial" if args.allow_partial else "full peer-enabled"
        raise SystemExit(
            f"Cannot refresh {mode} results snapshot; missing required artifacts:\n"
            f"{missing_list}\n\n"
            "Run the peer-enabled study first, or pass --allow-partial for the current "
            "core study state."
        )

    docs_file.parent.mkdir(parents=True, exist_ok=True)
    docs_file.write_text(
        build_snapshot(study_dir, allow_partial=args.allow_partial),
        encoding="utf-8",
    )
    print(f"Refreshed {_rel(docs_file)} from {_rel(study_dir)}")


if __name__ == "__main__":
    main()
