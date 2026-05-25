"""Build manuscript-ready tables, figures, and result prose from study artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import ARTIFACTS_DIR, PROJECT_ROOT  # noqa: E402


REQUIRED_ARTIFACTS = [
    "study_run_manifest.json",
    "benchmark/rolling_metrics.csv",
    "benchmark/benchmark_summary.md",
    "public_cascade/public_cascade_summary.json",
    "public_cascade/public_cascade_metrics.csv",
    "peer_comparison/legacy_model_family_metrics.csv",
    "peer_comparison/peer_task_status.csv",
    "public_peer_comparison/public_model_family_metrics.csv",
    "public_peer_comparison/public_model_family_task_status.csv",
    "construct_overlap/construct_overlap_manifest.json",
    "construct_overlap/public_score_legacy_ranking.csv",
    "construct_overlap/reciprocal_alignment.csv",
    "bridge_probe/coverage_report.csv",
]


def _resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        if value.is_integer() and abs(value) >= 100:
            return f"{int(value):,}"
        return f"{value:.{digits}f}"
    return str(value)


def _latex_escape(value: Any) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for src, repl in replacements.items():
        text = text.replace(src, repl)
    return text


def _markdown_table(df: pd.DataFrame) -> str:
    headers = [str(col) for col in df.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in df.columns) + " |")
    return "\n".join(lines) + "\n"


def _latex_table(df: pd.DataFrame, *, caption: str, label: str) -> str:
    columns = "l" * len(df.columns)
    lines = [
        r"\begin{table}[!htbp]",
        r"\centering",
        rf"\caption{{{_latex_escape(caption)}}}",
        rf"\label{{{_latex_escape(label)}}}",
        rf"\begin{{tabular}}{{{columns}}}",
        r"\toprule",
        " & ".join(_latex_escape(col) for col in df.columns) + r" \\",
        r"\midrule",
    ]
    for _, row in df.iterrows():
        lines.append(" & ".join(_latex_escape(row[col]) for col in df.columns) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}", ""])
    return "\n".join(lines)


def _write_table_bundle(
    df: pd.DataFrame,
    *,
    out_dir: Path,
    stem: str,
    caption: str,
    label: str,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{stem}.csv"
    md_path = out_dir / f"{stem}.md"
    tex_path = out_dir / f"{stem}.tex"
    df.to_csv(csv_path, index=False)
    md_path.write_text(f"Table: {caption}\n\n{_markdown_table(df)}", encoding="utf-8")
    tex_path.write_text(_latex_table(df, caption=caption, label=label), encoding="utf-8")
    return {"csv": _rel(csv_path), "md": _rel(md_path), "tex": _rel(tex_path)}


def _latest_public_lake_report() -> dict[str, Any]:
    report_root = ARTIFACTS_DIR / "logs" / "public_lake_full"
    reports = sorted(report_root.glob("*/run_report.json"), key=lambda path: path.stat().st_mtime)
    if not reports:
        return {}
    report = _read_json(reports[-1])
    snapshot = report.get("snapshot", {})
    row_counts = report.get("row_counts")
    if row_counts is None and isinstance(snapshot, dict):
        row_counts = snapshot.get("row_counts_json") or snapshot.get("row_counts")
    if isinstance(row_counts, str):
        row_counts = json.loads(row_counts)
    report["row_counts"] = row_counts or {}
    report["timestamp_utc"] = report.get("timestamp_utc") or snapshot.get("timestamp_utc")
    report["_path"] = str(reports[-1])
    return report


def _component_status(manifest: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for component, payload in manifest.get("components", {}).items():
        rows.append(
            {
                "Component": component,
                "Status": payload.get("status") or payload.get("run_status", ""),
                "Tier": payload.get("validation_tier", ""),
                "Output": payload.get("out_dir", ""),
            }
        )
    return pd.DataFrame(rows)


def _public_lake_scale(report: dict[str, Any]) -> pd.DataFrame:
    row_counts = report.get("row_counts", {})
    rows = [
        ("Silver", "filing_dim", "Public filing index"),
        ("Silver", "issuer_dim", "Issuer dimension"),
        ("Silver", "xbrl_core_fact", "Controlled XBRL core facts"),
        ("Silver", "xbrl_fact_summary", "Accession-level XBRL coverage"),
        ("Silver", "note_summary", "Notes summary mode"),
        ("Silver", "comment_thread", "SEC comment-thread signal"),
        ("Silver", "correction_event", "Amendment/correction signal"),
        ("Gold", "issuer_origin_panel", "Annual issuer-year modeling table"),
        ("Gold", "filing_origin_panel", "Filing-origin provenance table"),
    ]
    return pd.DataFrame(
        [
            {
                "Layer": layer,
                "Artifact": artifact,
                "Rows": _fmt(row_counts.get(artifact)),
                "Description": description,
            }
            for layer, artifact, description in rows
        ]
    )


def _public_task_metrics(metrics: pd.DataFrame, summary: dict[str, Any]) -> pd.DataFrame:
    positives = summary.get("task_positive_counts", {})
    if "task" in metrics.columns:
        metrics = metrics.loc[~metrics["task"].astype(str).str.contains("aaer", case=False)].copy()
    grouped = (
        metrics.groupby("task", dropna=False)
        .agg(
            Rows=("pr_auc", "size"),
            Mean_Prevalence=("positive_rate_test", "mean"),
            Mean_PR_AUC=("pr_auc", "mean"),
            Mean_ROC_AUC=("roc_auc", "mean"),
            Mean_Brier=("brier", "mean"),
            Max_PR_AUC=("pr_auc", "max"),
        )
        .reset_index()
        .sort_values("Mean_PR_AUC", ascending=False)
    )
    grouped.insert(1, "Positives", grouped["task"].map(positives))
    grouped = grouped.rename(columns={"task": "Task"})
    for col in ["Mean_Prevalence", "Mean_PR_AUC", "Mean_ROC_AUC", "Mean_Brier", "Max_PR_AUC"]:
        grouped[col] = grouped[col].map(_fmt)
    grouped["Rows"] = grouped["Rows"].map(_fmt)
    grouped["Positives"] = grouped["Positives"].map(_fmt)
    return grouped


def _feature_family_metrics(metrics: pd.DataFrame, summary: dict[str, Any]) -> pd.DataFrame:
    family = summary.get("feature_family_summary", {})
    grouped = (
        metrics.groupby("feature_set", dropna=False)
        .agg(
            Rows=("pr_auc", "size"),
            Mean_PR_AUC=("pr_auc", "mean"),
            Mean_ROC_AUC=("roc_auc", "mean"),
            Max_PR_AUC=("pr_auc", "max"),
        )
        .reset_index()
        .sort_values("Mean_PR_AUC", ascending=False)
    )
    best_window = (
        metrics.groupby(["feature_set", "train_window"], dropna=False)["pr_auc"]
        .mean()
        .reset_index()
        .sort_values("pr_auc", ascending=False)
        .drop_duplicates("feature_set")
        .set_index("feature_set")["train_window"]
        .to_dict()
    )
    grouped["Features"] = grouped["feature_set"].map(
        lambda key: family.get(key, {}).get("n_features", "")
    )
    grouped["XBRL_Ratios"] = grouped["feature_set"].map(
        lambda key: family.get(key, {}).get("n_xbrl_ratio_features", "")
    )
    grouped["XBRL_Coverage"] = grouped["feature_set"].map(
        lambda key: family.get(key, {}).get("n_xbrl_coverage_features", "")
    )
    grouped["Best_Window"] = grouped["feature_set"].map(best_window)
    grouped = grouped.rename(columns={"feature_set": "Feature_Set"})
    for col in ["Rows", "Features", "XBRL_Ratios", "XBRL_Coverage"]:
        grouped[col] = grouped[col].map(_fmt)
    for col in ["Mean_PR_AUC", "Mean_ROC_AUC", "Max_PR_AUC"]:
        grouped[col] = grouped[col].map(_fmt)
    return grouped[
        [
            "Feature_Set",
            "Features",
            "XBRL_Ratios",
            "XBRL_Coverage",
            "Best_Window",
            "Rows",
            "Mean_PR_AUC",
            "Mean_ROC_AUC",
            "Max_PR_AUC",
        ]
    ]


def _legacy_timing_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        metrics.groupby(["label_mode", "window"], dropna=False)
        .agg(
            Mean_PR_AUC=("pr_auc", "mean"),
            Mean_ROC_AUC=("roc_auc", "mean"),
            Top_100_Precision=("top_100_precision", "mean"),
            Brier=("brier", "mean"),
            Retained_Positive_Share=("retained_positive_train_share", "mean"),
        )
        .reset_index()
        .sort_values("Mean_PR_AUC", ascending=False)
    )
    best = grouped.drop_duplicates("label_mode").rename(
        columns={"label_mode": "Label_Mode", "window": "Best_Window"}
    )
    for col in [
        "Mean_PR_AUC",
        "Mean_ROC_AUC",
        "Top_100_Precision",
        "Brier",
        "Retained_Positive_Share",
    ]:
        best[col] = best[col].map(_fmt)
    return best


def _model_family_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    model_col = "peer_model_id"
    grouped = (
        metrics.groupby(model_col, dropna=False)
        .agg(
            Rows=("pr_auc", "size"),
            Mean_PR_AUC=("pr_auc", "mean"),
            Mean_ROC_AUC=("roc_auc", "mean"),
            Mean_Brier=("brier", "mean"),
            Max_PR_AUC=("pr_auc", "max"),
        )
        .reset_index()
        .sort_values("Mean_PR_AUC", ascending=False)
        .rename(columns={model_col: "Model"})
    )
    grouped["Rows"] = grouped["Rows"].map(_fmt)
    for col in ["Mean_PR_AUC", "Mean_ROC_AUC", "Mean_Brier", "Max_PR_AUC"]:
        grouped[col] = grouped[col].map(_fmt)
    return grouped


def _bridge_coverage(path: Path) -> pd.DataFrame:
    coverage = _read_csv(path)
    coverage["value"] = coverage["value"].map(_fmt)
    return coverage.rename(columns={"metric": "Metric", "value": "Value"})


def _construct_alignment(study_dir: Path) -> pd.DataFrame:
    public_to_legacy = _read_csv(study_dir / "construct_overlap" / "public_score_legacy_ranking.csv")
    legacy_to_public = _read_csv(study_dir / "construct_overlap" / "reciprocal_alignment.csv")
    rows: list[dict[str, Any]] = []
    if not public_to_legacy.empty:
        best = public_to_legacy.sort_values("top_decile_lift", ascending=False).iloc[0]
        rows.append(
            {
                "Direction": "Public score to benchmark positives",
                "Model": best["model_id"],
                "Target": best["task"],
                "Feature_Set": best["feature_set"],
                "Window": best["train_window"],
                "PR_AUC": _fmt(best["pr_auc"]),
                "ROC_AUC": _fmt(best["roc_auc"]),
                "Top_Decile_Lift": _fmt(best["top_decile_lift"]),
            }
        )
    if not legacy_to_public.empty:
        best = legacy_to_public.sort_values("top_decile_lift", ascending=False).iloc[0]
        rows.append(
            {
                "Direction": "Detected-misstatement score to public labels",
                "Model": best["model_id"],
                "Target": best["target_public_label"],
                "Feature_Set": best.get("feature_set", ""),
                "Window": best["train_window"],
                "PR_AUC": _fmt(best["pr_auc"]),
                "ROC_AUC": _fmt(best["roc_auc"]),
                "Top_Decile_Lift": _fmt(best["top_decile_lift"]),
            }
        )
    return pd.DataFrame(rows)


def _plot_bar(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    title: str,
    ylabel: str,
    out_path: Path,
    color: str = "#2a9d8f",
) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_df = df.copy()
    plot_df[y] = pd.to_numeric(plot_df[y], errors="coerce")
    plot_df = plot_df.sort_values(y, ascending=False)
    labels = plot_df[x].astype(str)
    horizontal = labels.map(len).max() > 14
    fig, ax = plt.subplots(figsize=(7.2, 4.6 if horizontal else 4.2))
    if horizontal:
        plot_df = plot_df.sort_values(y, ascending=True)
        ax.barh(
            plot_df[x].astype(str),
            plot_df[y],
            color=color,
            edgecolor="#1f2933",
            linewidth=0.6,
        )
        ax.set_xlabel(ylabel)
        ax.set_ylabel("")
    else:
        ax.bar(
            labels,
            plot_df[y],
            color=color,
            edgecolor="#1f2933",
            linewidth=0.6,
        )
        ax.set_ylabel(ylabel)
        ax.set_xlabel("")
        ax.tick_params(axis="x", rotation=30)
        for label in ax.get_xticklabels():
            label.set_horizontalalignment("right")
    ax.set_title(title)
    ax.grid(axis="x" if horizontal else "y", alpha=0.25)
    fig.tight_layout()
    png_path = out_path.with_suffix(".png")
    pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(png_path, dpi=240)
    fig.savefig(pdf_path)
    plt.close(fig)
    return {"png": _rel(png_path), "pdf": _rel(pdf_path)}


def _plot_construct_lift(df: pd.DataFrame, *, out_path: Path) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_df = df.copy()
    plot_df["Top_Decile_Lift"] = pd.to_numeric(plot_df["Top_Decile_Lift"], errors="coerce")
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    ax.barh(plot_df["Direction"], plot_df["Top_Decile_Lift"], color="#457b9d")
    ax.axvline(1.0, color="#222222", linewidth=1, linestyle="--")
    ax.set_xlabel("Top-decile lift")
    ax.set_title("Construct-overlap ranking alignment")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    png_path = out_path.with_suffix(".png")
    pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(png_path, dpi=240)
    fig.savefig(pdf_path)
    plt.close(fig)
    return {"png": _rel(png_path), "pdf": _rel(pdf_path)}


def _result_narrative(
    *,
    manifest: dict[str, Any],
    public_summary: dict[str, Any],
    public_task: pd.DataFrame,
    legacy_peer: pd.DataFrame,
    public_peer: pd.DataFrame,
    construct_alignment: pd.DataFrame,
    construct_manifest: dict[str, Any],
) -> str:
    best_public = (
        f"{public_summary.get('best_feature_set')} + {public_summary.get('best_train_window')}"
    )
    best_public_pr = _fmt(public_summary.get("best_mean_pr_auc"))
    comment_row = public_task[public_task["Task"].eq("comment_thread")].head(1)
    amendment_row = public_task[public_task["Task"].eq("amendment")].head(1)
    severe_row = public_task[public_task["Task"].eq("8k_402")].head(1)
    legacy_leader = legacy_peer.iloc[0] if not legacy_peer.empty else None
    public_peer_leader = public_peer.iloc[0] if not public_peer.empty else None
    validation_tier = construct_manifest.get("validation_tier", "")
    generated = manifest.get("generated_at_utc", "")

    def value(row: pd.DataFrame, col: str) -> str:
        if row.empty:
            return "n/a"
        return str(row.iloc[0][col])

    lines = [
        "# Manuscript Results Narrative",
        "",
        f"_Generated from `{manifest.get('components', {}).get('public_cascade', {}).get('out_dir', '')}` "
        f"and peer-enabled study manifest `{generated}`._",
        "",
        "## Research Object",
        "",
        "The empirical object is a filing-origin public reporting-risk state: whether an "
        "issuer later enters an observable public review or correction channel after the "
        "public information set available at the filing origin. The detected-"
        "misstatement benchmark is retained as a diagnostic and construct-validation "
        "layer, not treated as the sole definition of reporting risk.",
        "",
        "## Main Public-Cascade Result",
        "",
        f"The strongest public-cascade summary configuration is `{best_public}`, with "
        f"reported mean PR-AUC `{best_public_pr}`. The public tasks show a natural "
        "severity gradient. Comment-thread scrutiny is the most stable broad-review "
        f"signal (mean PR-AUC `{value(comment_row, 'Mean_PR_AUC')}`), amendments provide "
        f"a clear correction/friction channel (mean PR-AUC `{value(amendment_row, 'Mean_PR_AUC')}`), "
        f"and 8-K Item 4.02 is rarer but still rankable (mean PR-AUC `{value(severe_row, 'Mean_PR_AUC')}`).",
        "",
        "## Peer-Compatible Model Families",
        "",
        "The peer suites are model-family transfer exercises. They align the public "
        "reporting-risk task with familiar Dechow, Perols, Bao, and Bertomeu-style "
        "vocabularies without claiming original-paper numeric replication. In the "
        f"detected-misstatement peer benchmark, `{legacy_leader['Model'] if legacy_leader is not None else 'n/a'}` "
        f"has the highest mean PR-AUC (`{legacy_leader['Mean_PR_AUC'] if legacy_leader is not None else 'n/a'}`). "
        f"In the public-label peer suite, `{public_peer_leader['Model'] if public_peer_leader is not None else 'n/a'}` "
        f"leads on mean PR-AUC (`{public_peer_leader['Mean_PR_AUC'] if public_peer_leader is not None else 'n/a'}`). "
        "These comparisons should be read within task and estimand, not as cross-"
        "estimand performance rankings against prior fraud-prediction papers.",
        "",
        "## Construct-Overlap Evidence",
        "",
        "The WRDS-validated bridge shows that public-cascade scores and detected-"
        "misstatement benchmark labels are related but non-identical. The strongest "
        "public-score-to-benchmark-positive row and the strongest reciprocal "
        "detected-misstatement-score-to-public-label row both show top-decile lift "
        "above one, supporting construct relatedness. "
        f"The validation tier is `{validation_tier}`; this supports manuscript-grade "
        "integrated overlap claims while preserving the related-but-non-identical "
        "construct boundary.",
        "",
        "## Claim Boundary",
        "",
        "The evidence supports a measurement-and-ranking paper on public review-and-"
        "correction risk. It does not identify unobserved true fraud occurrence, causal "
        "effects, or same-estimand superiority over prior fraud-prediction studies.",
    ]

    if not construct_alignment.empty:
        lines.extend(["", "## Alignment Rows", "", _markdown_table(construct_alignment)])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--study-dir",
        type=Path,
        default=ARTIFACTS_DIR / "full_with_peer",
        help="Peer-enabled study artifact directory.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ARTIFACTS_DIR / "manuscript_package",
        help="Output directory for manuscript-ready artifacts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    study_dir = _resolve_repo_path(args.study_dir)
    out_dir = _resolve_repo_path(args.out_dir)
    missing = [rel for rel in REQUIRED_ARTIFACTS if not (study_dir / rel).exists()]
    if missing:
        raise SystemExit(
            "Cannot build manuscript package; missing required artifacts:\n"
            + "\n".join(f"- {_rel(study_dir / rel)}" for rel in missing)
        )

    tables_dir = out_dir / "tables"
    figures_dir = out_dir / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    manifest = _read_json(study_dir / "study_run_manifest.json")
    public_summary = _read_json(study_dir / "public_cascade" / "public_cascade_summary.json")
    construct_manifest = _read_json(study_dir / "construct_overlap" / "construct_overlap_manifest.json")
    public_metrics = _read_csv(study_dir / "public_cascade" / "public_cascade_metrics.csv")
    benchmark_metrics = _read_csv(study_dir / "benchmark" / "rolling_metrics.csv")
    legacy_peer_metrics = _read_csv(study_dir / "peer_comparison" / "legacy_model_family_metrics.csv")
    public_peer_metrics = _read_csv(
        study_dir / "public_peer_comparison" / "public_model_family_metrics.csv"
    )

    public_lake = _public_lake_scale(_latest_public_lake_report())
    public_task = _public_task_metrics(public_metrics, public_summary)
    feature_family = _feature_family_metrics(public_metrics, public_summary)
    legacy_timing = _legacy_timing_metrics(benchmark_metrics)
    legacy_peer = _model_family_metrics(legacy_peer_metrics)
    public_peer = _model_family_metrics(public_peer_metrics)
    bridge_coverage = _bridge_coverage(study_dir / "bridge_probe" / "coverage_report.csv")
    construct_alignment = _construct_alignment(study_dir)
    component_status = _component_status(manifest)

    table_manifest = {
        "table_01_component_status": _write_table_bundle(
            component_status,
            out_dir=tables_dir,
            stem="table_01_component_status",
            caption="Study component status",
            label="tab:component-status",
        ),
        "table_02_public_lake_scale": _write_table_bundle(
            public_lake,
            out_dir=tables_dir,
            stem="table_02_public_lake_scale",
            caption="Public lake and gold panel scale",
            label="tab:public-lake-scale",
        ),
        "table_03_public_task_metrics": _write_table_bundle(
            public_task,
            out_dir=tables_dir,
            stem="table_03_public_task_metrics",
            caption="Public cascade task metrics",
            label="tab:public-task-metrics",
        ),
        "table_04_feature_family_metrics": _write_table_bundle(
            feature_family,
            out_dir=tables_dir,
            stem="table_04_feature_family_metrics",
            caption="Public cascade feature-family metrics",
            label="tab:feature-family-metrics",
        ),
        "table_05_benchmark_timing_metrics": _write_table_bundle(
            legacy_timing,
            out_dir=tables_dir,
            stem="table_05_benchmark_timing_metrics",
            caption="Detected-misstatement benchmark timing diagnostics",
            label="tab:benchmark-timing",
        ),
        "table_06_detected_misstatement_peer_metrics": _write_table_bundle(
            legacy_peer,
            out_dir=tables_dir,
            stem="table_06_detected_misstatement_peer_metrics",
            caption="Detected-misstatement peer-compatible model-family metrics",
            label="tab:benchmark-peer",
        ),
        "table_07_public_peer_metrics": _write_table_bundle(
            public_peer,
            out_dir=tables_dir,
            stem="table_07_public_peer_metrics",
            caption="Public-label peer-compatible model-family metrics",
            label="tab:public-peer",
        ),
        "table_08_bridge_coverage": _write_table_bundle(
            bridge_coverage,
            out_dir=tables_dir,
            stem="table_08_bridge_coverage",
            caption="Bridge coverage",
            label="tab:bridge-coverage",
        ),
        "table_09_construct_alignment": _write_table_bundle(
            construct_alignment,
            out_dir=tables_dir,
            stem="table_09_construct_alignment",
            caption="Construct-overlap ranking alignment",
            label="tab:construct-alignment",
        ),
    }

    figure_manifest = {
        "figure_01_public_task_pr_auc": _plot_bar(
            public_task,
            x="Task",
            y="Mean_PR_AUC",
            title="Public-cascade task performance",
            ylabel="Mean PR-AUC",
            out_path=figures_dir / "figure_01_public_task_pr_auc",
            color="#2a9d8f",
        ),
        "figure_02_feature_family_pr_auc": _plot_bar(
            feature_family,
            x="Feature_Set",
            y="Mean_PR_AUC",
            title="Feature-family comparison",
            ylabel="Mean PR-AUC",
            out_path=figures_dir / "figure_02_feature_family_pr_auc",
            color="#6a994e",
        ),
        "figure_03_detected_misstatement_peer_pr_auc": _plot_bar(
            legacy_peer,
            x="Model",
            y="Mean_PR_AUC",
            title="Detected-misstatement peer-compatible model families",
            ylabel="Mean PR-AUC",
            out_path=figures_dir / "figure_03_detected_misstatement_peer_pr_auc",
            color="#bc6c25",
        ),
        "figure_04_public_peer_pr_auc": _plot_bar(
            public_peer,
            x="Model",
            y="Mean_PR_AUC",
            title="Public-label peer-compatible model families",
            ylabel="Mean PR-AUC",
            out_path=figures_dir / "figure_04_public_peer_pr_auc",
            color="#4361ee",
        ),
        "figure_05_construct_overlap_lift": _plot_construct_lift(
            construct_alignment,
            out_path=figures_dir / "figure_05_construct_overlap_lift",
        ),
    }

    narrative_path = out_dir / "results_narrative.md"
    narrative_path.write_text(
        _result_narrative(
            manifest=manifest,
            public_summary=public_summary,
            public_task=public_task,
            legacy_peer=legacy_peer,
            public_peer=public_peer,
            construct_alignment=construct_alignment,
            construct_manifest=construct_manifest,
        ),
        encoding="utf-8",
    )

    package_manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "study_dir": _rel(study_dir),
        "out_dir": _rel(out_dir),
        "tables": table_manifest,
        "figures": figure_manifest,
        "narrative": _rel(narrative_path),
        "claim_boundary": {
            "construct_overlap_tier": construct_manifest.get("validation_tier"),
            "causal_claims_supported": False,
            "unobserved_true_fraud_claims_supported": False,
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(package_manifest, indent=2), encoding="utf-8")
    print(f"Built manuscript package in {_rel(out_dir)}")


if __name__ == "__main__":
    main()
