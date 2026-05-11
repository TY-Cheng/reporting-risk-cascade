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
    "public_cascade/public_cascade_summary.json",
    "public_cascade/public_cascade_metrics.csv",
    "public_cascade/public_cascade_task_status.csv",
    "bridge_probe/bridge_probe_summary.json",
    "bridge_probe/coverage_report.csv",
    "peer_comparison/peer_comparison_summary.md",
    "peer_comparison/legacy_model_family_metrics.csv",
    "peer_comparison/peer_task_status.csv",
    "public_peer_comparison/public_model_family_summary.md",
    "public_peer_comparison/public_model_family_metrics.csv",
    "public_peer_comparison/public_model_family_task_status.csv",
    "construct_overlap/construct_overlap_manifest.json",
    "construct_overlap/construct_overlap_summary.md",
    "construct_overlap/overlap_sample_flow.csv",
    "construct_overlap/public_score_legacy_ranking.csv",
    "construct_overlap/reciprocal_alignment.csv",
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
    public_to_legacy = _read_csv(study_dir / "construct_overlap" / "public_score_legacy_ranking.csv")
    legacy_to_public = _read_csv(study_dir / "construct_overlap" / "reciprocal_alignment.csv")
    rows = []
    if not public_to_legacy.empty and "top_decile_lift" in public_to_legacy.columns:
        best = public_to_legacy.sort_values("top_decile_lift", ascending=False).iloc[0]
        rows.append(
            [
                "Public cascade score -> legacy positives",
                _code(best.get("model_id")),
                _code(best.get("task")),
                _fmt(best.get("pr_auc")),
                _fmt(best.get("roc_auc")),
                _fmt(best.get("top_decile_lift")),
            ]
        )
    if not legacy_to_public.empty and "top_decile_lift" in legacy_to_public.columns:
        best = legacy_to_public.sort_values("top_decile_lift", ascending=False).iloc[0]
        rows.append(
            [
                "Legacy/peer score -> public labels",
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
        "peer_comparison/legacy_model_family_metrics.csv",
        "public_peer_comparison/public_model_family_summary.md",
        "public_peer_comparison/public_model_family_metrics.csv",
        "bridge_probe/bridge_probe_summary.json",
        "bridge_probe/coverage_report.csv",
        "construct_overlap/construct_overlap_summary.md",
        "construct_overlap/public_score_legacy_ranking.csv",
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

    lines = [
        "---",
        "hide:",
        "  - navigation",
        "---",
        "",
        "# Results Snapshot",
        "",
        f"_Generated by `just snapshot` from `{study_rel}` at `{generated_at}`._",
        "",
        "## Discussion",
        "",
        "- **Research question.** Can filing-origin public SEC/PCAOB information predict "
        "whether an issuer later enters observable public review-and-correction channels, "
        "and how does this public reporting-risk construct relate to, but differ from, "
        "legacy detected-misstatement benchmarks?",
        "",
        "- **Data.** The workflow combines the legacy `gvkey x data_year` "
        "detected-misstatement benchmark, the public SEC/PCAOB lake, the gold "
        "`issuer_origin_panel` and `filing_origin_panel`, and an external "
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
        "- **Sellable claim.** The strongest current framing is a measurement-and-ranking "
        "paper on filing-origin public reporting-risk states. It does not support causal "
        "claims, unobserved true-fraud occurrence claims, or same-estimand performance "
        "rankings over prior fraud-prediction papers.",
        "",
        f"- **Current best public-cascade specification.** {best_public_text}.",
        "",
        f"- **Bridge boundary.** Construct overlap is `{validation_tier}`; WRDS or "
        "equivalent institutional bridge evidence remains preferred for final "
        "manuscript-grade integrated claims.",
        "",
        "## Run Metadata",
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
        "## Component Status",
        "",
        _table(["Component", "Status", "Tier", "Output"], _component_rows(manifest)),
        "",
        "## Evidence Map",
        "",
        "```mermaid",
        "flowchart LR",
        '    L["Legacy benchmark<br/>timing, drift, missingness,<br/>peer-compatible metrics"]',
        '    P["Public filing-origin cascade<br/>comment threads, amendments,<br/>8-K Item 4.02, AAER support"]',
        '    B["Bridge gate<br/>gvkey-CIK-year coverage<br/>candidate_farr unless WRDS supplied"]',
        '    V["Construct-overlap checks<br/>co-occurrence, lift,<br/>reciprocal ranking, event time"]',
        '    S["Snapshot docs<br/>generated from artifacts<br/>checked by just snapshot"]',
        "    L --> B",
        "    P --> B",
        "    B --> V",
        "    V --> S",
        "```",
        "",
        "## Public Lake and Gold Panel Scale",
        "",
        _table(["Layer", "Artifact", "Rows", "Notes"], _public_lake_rows(public_lake_report)),
        "",
        "## Public Cascade Readiness",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Main sample rows", _fmt(public_summary.get("n_rows"))],
                ["Fiscal-year span", "-".join(map(str, public_summary.get("sample_years", [])))],
                ["Domestic US GAAP only", _fmt(public_summary.get("domestic_only"))],
                ["Task positive counts", _code(public_summary.get("task_positive_counts"))],
                ["Zero-positive tasks", _code(public_summary.get("zero_positive_tasks"))],
                ["Task status counts", _code(public_summary.get("task_status_counts"))],
                ["Readiness level", _code(public_summary.get("cascade_readiness_level"))],
                ["Best reported feature set", _code(public_summary.get("best_feature_set"))],
                ["Best reported train window", _code(public_summary.get("best_train_window"))],
                ["Best reported mean PR-AUC", _fmt(public_summary.get("best_mean_pr_auc"))],
            ],
        ),
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
        "## Legacy Benchmark Timing Diagnostics",
        "",
        _table(["Field", "Value"], _benchmark_panel_rows(study_dir)),
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
        "## Peer-Compatible Literature Benchmarks",
        "",
        "These rows are present only when the peer-enabled study has run. They are "
        "model-family transfer and metric-language alignment, not exact replications "
        "of the original-paper samples.",
        "",
        _table(
            ["Model", "Rows", "Mean PR-AUC", "Mean ROC-AUC", "Max PR-AUC", "Mean Brier"],
            _peer_model_rows(study_dir / "peer_comparison" / "legacy_model_family_metrics.csv"),
        ),
        "",
        "## Public-Label Peer Transfer",
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
        "## Bridge and Construct-Overlap Validation",
        "",
        _table(["Metric", "Value"], _bridge_coverage_rows(study_dir / "bridge_probe" / "coverage_report.csv")),
        "",
        _table(
            ["Direction", "Model", "Target", "PR-AUC", "ROC-AUC", "Top-decile lift"],
            _construct_alignment_rows(study_dir),
        ),
        "",
        "Key readings:",
        "",
        "- Public labels and legacy detected-misstatement labels are related but "
        "non-identical constructs.",
        "- Public-cascade scores can rank legacy positives in the matched overlap; "
        "legacy/peer scores can also rank severe public correction labels.",
        "- `candidate_farr` bridge evidence is useful for internal validation, but "
        "should be labeled clearly until a WRDS-grade bridge is available.",
        "",
        "## Selected Artifact Index",
        "",
        "This index lists high-signal artifacts referenced by this generated snapshot.",
        "",
        *_artifact_index(study_dir),
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
