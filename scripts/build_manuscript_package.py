"""Build manuscript-ready tables, figures, and result prose from study artifacts."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import ARTIFACTS_DIR, LAKE_GOLD_DIR, PROJECT_ROOT  # noqa: E402


REQUIRED_ARTIFACTS = [
    "study_run_manifest.json",
    "benchmark/rolling_metrics.csv",
    "benchmark/benchmark_summary.md",
    "public_cascade/public_cascade_summary.json",
    "public_cascade/public_cascade_metrics.csv",
    "peer_comparison/detected_misstatement_model_family_metrics.csv",
    "peer_comparison/peer_task_status.csv",
    "public_peer_comparison/public_model_family_metrics.csv",
    "public_peer_comparison/public_model_family_task_status.csv",
    "construct_overlap/construct_overlap_manifest.json",
    "construct_overlap/public_score_benchmark_ranking.csv",
    "construct_overlap/reciprocal_alignment.csv",
    "construct_overlap/benchmark_positive_public_label_cooccurrence.csv",
    "construct_overlap/label_contingency_lift.csv",
    "construct_overlap/overlap_sample_flow.csv",
    "bridge_probe/coverage_report.csv",
    "bridge_probe/unmatched_raw_characteristics.csv",
]

MIN_VALID_FOLDS_FOR_CI = 5
SPARSE_POSITIVE_THRESHOLD = 10

ANNUAL_INTERVAL_NOTE = (
    "PR-AUC dispersion entries are descriptive fold-dispersion intervals over "
    "annual out-of-time test folds after excluding sparse folds with fewer "
    "than 10 positives. "
    "Rolling and expanding training windows overlap, so the intervals describe "
    "evaluation-period dispersion rather than independent sampling uncertainty, "
    "superpopulation confidence intervals, or causal inference uncertainty."
)
CONSTRUCT_LIFT_NOTE = (
    "Lift bootstrap intervals are row-level percentile bootstrap intervals "
    "from the bridge-gated artifacts, not annual fold-dispersion intervals. "
    "Bridge tier is wrds_validated, and displayed rows are restricted to "
    "high-confidence bridge rows. Top-10% precision and FDR report the absolute "
    "base-rate burden behind lift; the implicit bridge-sample base rate can differ "
    "from the full public-cascade task prevalence because of the high-confidence "
    "bridge restriction. These Item 4.02 rows are severe-tail "
    "diagnostics within the broader construct-validation case; they support "
    "related-construct enrichment rather than label equivalence."
)
PEER_TRANSFER_NOTE = (
    ANNUAL_INTERVAL_NOTE
    + " Peer-compatible families are ranking checks under transferred model "
    "vocabularies, not calibrated probability comparisons or original-paper "
    "replications. Peer-model folds and public-cascade folds can cover "
    "different historical sequences, so dispersion widths should not be "
    "compared across evidence layers."
)
DML_INTERVAL_NOTE = (
    "Raw controls are source variables before encoding; encoded controls are nuisance-model "
    "columns reported at the maximum fold-local width after training-fold categorical "
    "expansion and imputation; opacity components form the missingness-density treatment. "
    "Intervals use HC3 residual OLS after cross-fitting. The estimates are adjusted "
    "associations, not identified structural effects."
)
PUBLIC_TASK_NOTE = (
    ANNUAL_INTERVAL_NOTE
    + " Table 3 and Figure 1 report only the revision-frozen all + expanding primary "
    "specification. The excluding-2020 sensitivity excludes the 2020 test fold; "
    "training specifications are unchanged."
    + " The evaluation unit is a public-cascade task summarized over annual "
    "out-of-time folds at the issuer-CIK fiscal-year origin grain. "
    + "Panel positives sum exact positive_test support over the one-to-one fit-owner rows, while "
    "mean "
    "prevalence is averaged over the reported task-window-feature evaluations; "
    "it should not be read as positives divided by a single manuscript-wide denominator. "
    + " Brier Skill Score is measured relative to the corresponding prevalence-only "
    "Brier baseline. ECE is a 10-bin uniform-width calibration diagnostic from raw "
    "probability scores. Weak calibration should be read as evidence against using "
    "the scores as calibrated decision rules, not against the paper's ranking estimand."
)
FEATURE_FAMILY_NOTE = (
    ANNUAL_INTERVAL_NOTE
    + " Entries are feature-family summaries over public-cascade task-window "
    "evaluations, not issuer-year sample sizes. Task-specific base-rate context "
    "is reported in the task tables. Note/disclosure-breadth variables enter "
    "the all-feature information set but are not reported as a standalone family row. "
    "Best-window entries are descriptive "
    "configuration summaries, not headline model-selection claims."
)
BENCHMARK_TIMING_NOTE = (
    ANNUAL_INTERVAL_NOTE
    + " Entries are detected-misstatement label-mode timing diagnostics. Best-window "
    "entries are descriptive label-observability sensitivity checks, not "
    "headline model-selection claims."
)
FOLD_SUPPORT_NOTE = (
    "Entries report annual out-of-time test support collapsed across configurations "
    "because test rows and positive counts are task-year properties. Sparse folds "
    f"are those with fewer than {SPARSE_POSITIVE_THRESHOLD} positives; such folds "
    "are excluded from formal fold-dispersion intervals."
)
TASK_FEATURE_NOTE = (
    ANNUAL_INTERVAL_NOTE
    + " Entries are task-by-feature-family averages over the configured public-cascade "
    "training windows. They clarify the aggregation behind the feature-family "
    "summary and should be read as information-set evidence, not causal decomposition."
)
BRIDGE_OVERLAP_NOTE = (
    "Bridge_Rows are bridge-gated label-overlap diagnostics. The table reports "
    "absolute public and benchmark rates and lift for each public label by bridge tier. These "
    "descriptive rates broaden construct-validation evidence beyond the sparse "
    "Item 4.02 severe-tail ranking rows; they do not imply label equivalence."
)
BRIDGE_COVERAGE_NOTE = (
    "These rates describe raw CIK-GVKEY bridge availability. Construct-overlap "
    "claims use the narrower high-confidence sample reported in the bridge-overlap "
    "sample-boundaries appendix table."
)
BRIDGE_BOUNDARY_NOTE = (
    "This table reports the construct-overlap sample boundary after bridge accounting, "
    "not the raw CIK-GVKEY coverage rate reported in the bridge-coverage table. "
    "Construct-overlap claims are bounded to high-confidence rows. Dropped rows define "
    "the generalizability boundary of the overlap exercise."
)
SELECTION_PROFILE_NOTE = (
    "Issuer_Years are descriptive strata from the existing public issuer-origin panel. "
    "They show how public-label rates vary with filing visibility, history, and "
    "issuer profile variables. Parenthetical values in group labels are split thresholds, "
    "not sample sizes; XBRL log-asset strata are limited to observations with available "
    "XBRL asset values; days since prior filing refers to any prior EDGAR filing, "
    "not only a prior annual report. The table is selection-aware evidence, not a causal "
    "adjustment model or proof that SEC scrutiny selection has been solved."
)
PUBLIC_ATTRITION_NOTE = (
    "Sequential rows compare with the preceding sample-construction stage. Task rows "
    "branch from observable_365_day_horizon and therefore compare with that common "
    "observable parent rather than with one another."
)


def _resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def _rel(path: str | Path) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return f"<external>/{resolved.name}"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, np.integer)):
        return f"{value:,}"
    if isinstance(value, (float, np.floating)):
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


def _latex_table(df: pd.DataFrame, *, caption: str, label: str, note: str | None = None) -> str:
    columns = "l" * len(df.columns)
    lines = [
        r"\begin{table}[!htbp]",
        r"\centering",
        rf"\caption{{{_latex_escape(caption)}}}",
        rf"\label{{{_latex_escape(label)}}}",
        r"\resizebox{\textwidth}{!}{%",
        rf"\begin{{tabular}}{{{columns}}}",
        r"\toprule",
        " & ".join(_latex_escape(col) for col in df.columns) + r" \\",
        r"\midrule",
    ]
    for _, row in df.iterrows():
        lines.append(" & ".join(_latex_escape(row[col]) for col in df.columns) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}%", r"}"])
    if note:
        lines.extend(
            [
                r"\begin{minipage}{0.98\textwidth}",
                r"\footnotesize",
                rf"\emph{{Note:}} {_latex_escape(note)}",
                r"\end{minipage}",
            ]
        )
    lines.extend([r"\end{table}", ""])
    return "\n".join(lines)


def _write_table_bundle(
    df: pd.DataFrame,
    *,
    out_dir: Path,
    stem: str,
    caption: str,
    label: str,
    display_df: pd.DataFrame | None = None,
    note: str | None = None,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{stem}.csv"
    md_path = out_dir / f"{stem}.md"
    tex_path = out_dir / f"{stem}.tex"
    rendered = display_df if display_df is not None else df
    df.to_csv(csv_path, index=False)
    note_text = f"\n\nNote: {note}\n" if note else ""
    md_path.write_text(f"Table: {caption}\n\n{_markdown_table(rendered)}{note_text}", encoding="utf-8")
    tex_path.write_text(_latex_table(rendered, caption=caption, label=label, note=note), encoding="utf-8")
    return {"csv": _rel(csv_path), "md": _rel(md_path), "tex": _rel(tex_path)}


def _positive_counts(frame: pd.DataFrame) -> pd.Series:
    if "n_pos_test" in frame.columns:
        return pd.to_numeric(frame["n_pos_test"], errors="coerce")
    if {"positive_rate_test", "n_test"}.issubset(frame.columns):
        rate = pd.to_numeric(frame["positive_rate_test"], errors="coerce")
        n_test = pd.to_numeric(frame["n_test"], errors="coerce")
        return (rate * n_test).round()
    if {"pos_rate", "n_obs"}.issubset(frame.columns):
        rate = pd.to_numeric(frame["pos_rate"], errors="coerce")
        n_obs = pd.to_numeric(frame["n_obs"], errors="coerce")
        return (rate * n_obs).round()
    return pd.Series(np.nan, index=frame.index, dtype=float)


def _annual_fold_frame(
    metrics: pd.DataFrame,
    group_cols: list[str],
    *,
    metric_col: str = "pr_auc",
) -> pd.DataFrame:
    needed = [*group_cols, "test_year", metric_col]
    if not set(needed).issubset(metrics.columns):
        return pd.DataFrame(
            columns=[
                *group_cols,
                "test_year",
                "fold_value",
                "n_pos",
                "metric_rows",
                "valid_metric",
                "sparse_excluded",
                "valid_for_interval",
            ]
        )
    work = metrics.copy()
    work["_metric_value"] = pd.to_numeric(work[metric_col], errors="coerce")
    work["_n_pos"] = _positive_counts(work)
    folds = (
        work.groupby([*group_cols, "test_year"], dropna=False)
        .agg(
            fold_value=("_metric_value", "mean"),
            n_pos=("_n_pos", "min"),
            metric_rows=("_metric_value", "size"),
        )
        .reset_index()
    )
    folds["valid_metric"] = np.isfinite(pd.to_numeric(folds["fold_value"], errors="coerce"))
    folds["sparse_excluded"] = (
        folds["n_pos"].notna() & (pd.to_numeric(folds["n_pos"], errors="coerce") < SPARSE_POSITIVE_THRESHOLD)
    )
    folds["valid_for_interval"] = folds["valid_metric"] & ~folds["sparse_excluded"]
    return folds


def _format_excluded_years(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    parts: list[str] = []
    for _, row in frame.sort_values("test_year").iterrows():
        year = row.get("test_year", "")
        pos = row.get("n_pos")
        try:
            pos_text = str(int(float(pos)))
        except (TypeError, ValueError):
            pos_text = ""
        parts.append(f"{year}:{pos_text}")
    return "; ".join(parts)


def _annual_metric_summary(
    metrics: pd.DataFrame,
    group_cols: list[str],
    *,
    metric_col: str = "pr_auc",
) -> pd.DataFrame:
    folds = _annual_fold_frame(metrics, group_cols, metric_col=metric_col)
    rows: list[dict[str, Any]] = []
    if folds.empty:
        return pd.DataFrame(columns=[*group_cols])

    grouped = folds.groupby(group_cols, dropna=False) if group_cols else [((), folds)]
    for key, group in grouped:
        key_values = key if isinstance(key, tuple) else (key,)
        valid = group.loc[group["valid_for_interval"], "fold_value"].astype(float).to_numpy()
        n_valid = int(len(valid))
        sd = float(np.std(valid, ddof=1)) if n_valid >= 2 else np.nan
        se = float(sd / math.sqrt(n_valid)) if n_valid >= 2 and np.isfinite(sd) else np.nan
        mean = float(np.mean(valid)) if n_valid else np.nan
        if n_valid >= MIN_VALID_FOLDS_FOR_CI and np.isfinite(se):
            t_crit = float(stats.t.ppf(0.975, df=n_valid - 1))
            ci_low = mean - t_crit * se
            ci_high = mean + t_crit * se
            method = "annual_fold_dispersion_t95"
        else:
            ci_low = np.nan
            ci_high = np.nan
            method = "annual_fold_dispersion_insufficient_folds"
        sparse = group.loc[group["sparse_excluded"]]
        row = {
            col: value for col, value in zip(group_cols, key_values, strict=False)
        }
        row.update(
            {
                "metric_rows": int(group["metric_rows"].sum()),
                "n_folds": int(group["test_year"].nunique()),
                "valid_folds": n_valid,
                "excluded_sparse_folds": int(group["sparse_excluded"].sum()),
                "excluded_sparse_years": _format_excluded_years(sparse),
                "mean": mean,
                "sd": sd,
                "se": se,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "fold_min": float(np.min(valid)) if n_valid else np.nan,
                "fold_max": float(np.max(valid)) if n_valid else np.nan,
                "interval_method": method,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _dispersion_text(row: pd.Series) -> str:
    low = row.get("ci_low")
    high = row.get("ci_high")
    if pd.notna(low) and pd.notna(high):
        return f"[{float(low):.4f}, {float(high):.4f}]"
    valid_folds = row.get("valid_folds")
    if pd.notna(valid_folds) and int(valid_folds) > 0:
        return f"diagnostic only (<{MIN_VALID_FOLDS_FOR_CI} valid folds)"
    return ""


def _table_view(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return df[[col for col in columns if col in df.columns]].copy()


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
    roles = {
        "benchmark": "Detected-misstatement timing and model-family diagnostics",
        "bridge_probe": "CIK-GVKEY coverage and multiplicity checks",
        "construct_overlap": "Bridge-gated related-construct evidence",
        "peer_comparison": "Benchmark model-family transfer checks",
        "public_cascade": "Filing-origin public-label ranking evidence",
        "public_peer_comparison": "Public-label model-family transfer checks",
    }
    rows = []
    for component, payload in manifest.get("components", {}).items():
        rows.append(
            {
                "Component": component,
                "Status": payload.get("status") or payload.get("run_status", ""),
                "Tier": payload.get("validation_tier", ""),
                "Manuscript role": roles.get(component, payload.get("out_dir", "")),
            }
        )
    return pd.DataFrame(rows)


def _public_lake_scale(report: dict[str, Any]) -> pd.DataFrame:
    row_counts = report.get("row_counts", {})
    rows = [
        ("Normalized", "filing_dim", "Public filing index"),
        ("Normalized", "issuer_dim", "Issuer dimension"),
        ("Normalized", "xbrl_core_fact", "Controlled XBRL core facts"),
        ("Normalized", "xbrl_fact_summary", "Accession-level XBRL coverage"),
        ("Normalized", "note_summary", "Notes summary mode"),
        ("Normalized", "comment_thread", "SEC comment-thread signal"),
        ("Normalized", "correction_event", "Amendment/correction signal"),
        ("Analytical", "issuer_origin_panel", "Annual issuer-year modeling table"),
        ("Analytical", "filing_origin_panel", "Filing-origin provenance table"),
    ]
    return pd.DataFrame(
        [
            {
                "Layer": layer,
                "Artifact": artifact,
                "Artifact_Rows": _fmt(row_counts.get(artifact)),
                "Description": description,
            }
            for layer, artifact, description in rows
        ]
    )


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


def _public_sample_attrition_table(summary: dict[str, Any]) -> pd.DataFrame:
    attrition = summary["sample_attrition"]
    observable_parent = next(
        int(row["n_rows"])
        for row in attrition
        if row["stage"] == "observable_365_day_horizon"
    )
    rows: list[dict[str, Any]] = []
    previous_sequential: int | None = None
    for row in attrition:
        count = int(row["n_rows"])
        task = str(row["task"])
        if task == "all":
            dropped = 0 if previous_sequential is None else previous_sequential - count
            previous_sequential = count
            scope = "sequential"
        else:
            dropped = observable_parent - count
            scope = "task"
        rows.append(
            {
                "Scope": scope,
                "Stage": str(row["stage"]),
                "Task": task,
                "Rows": count,
                "Dropped_From_Parent": dropped,
            }
        )
    return pd.DataFrame(rows)


def _public_task_metrics(
    metrics: pd.DataFrame,
    task_status: pd.DataFrame,
    summary: dict[str, Any],
) -> pd.DataFrame:
    keys = ["feature_set", "train_window", "test_year", "task"]
    required_status = {*keys, "status", "positive_test"}
    primary = dict(summary.get("primary_specification", {}))
    ownership_error = "Table 3 requires one-to-one fit ownership for primary metric rows"
    if (
        set(primary) != {"feature_set", "train_window"}
        or not set(keys) <= set(metrics)
        or not required_status <= set(task_status)
    ):
        raise ValueError(ownership_error)
    owners = task_status.loc[
        task_status["feature_set"].eq(primary["feature_set"])
        & task_status["train_window"].eq(primary["train_window"])
        & task_status["status"].eq("fit"),
        [*keys, "positive_test"],
    ]
    if metrics.duplicated(keys).any() or owners.duplicated(keys).any():
        raise ValueError(ownership_error)
    ownership = metrics[keys].merge(
        owners,
        on=keys,
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    if not ownership["_merge"].eq("both").all():
        raise ValueError(ownership_error)
    owned_positives = pd.to_numeric(ownership["positive_test"], errors="coerce")
    if (
        owned_positives.isna().any()
        or (owned_positives < 0).any()
        or not owned_positives.mod(1).eq(0).all()
    ):
        raise ValueError("Table 3 fit owners require exact nonnegative integer positive_test")
    positives = ownership.assign(positive_test=owned_positives).groupby("task")[
        "positive_test"
    ].sum()
    uncertainty = _annual_metric_summary(metrics, ["task"])
    excluding_2020_summary = _annual_metric_summary(
        metrics.loc[pd.to_numeric(metrics["test_year"], errors="coerce").ne(2020)],
        ["task"],
    )
    excluding_2020 = (
        excluding_2020_summary.set_index("task")["mean"].to_dict()
        if "mean" in excluding_2020_summary
        else {}
    )
    grouped = (
        metrics.groupby("task", dropna=False)
        .agg(
            Mean_Prevalence=("positive_rate_test", "mean"),
            Mean_ROC_AUC=("roc_auc", "mean"),
            Mean_Brier=("brier", "mean"),
            Mean_Brier_Skill=("brier_skill_score", "mean"),
            Mean_ECE=("ece", "mean"),
        )
        .reset_index()
    )
    grouped = grouped.merge(uncertainty, on="task", how="left")
    grouped = grouped.sort_values("mean", ascending=False)
    grouped["Mean_PR_AUC"] = grouped["mean"]
    grouped["Excluding_2020_PR_AUC"] = grouped["task"].map(excluding_2020)
    grouped["Excluding_2020_Delta"] = (
        grouped["Excluding_2020_PR_AUC"] - grouped["Mean_PR_AUC"]
    )
    grouped.insert(1, "Panel_Positives", grouped["task"].map(positives.to_dict()))
    grouped = grouped.rename(columns={"task": "Task"})
    grouped["PR_AUC_Dispersion"] = grouped.apply(_dispersion_text, axis=1)
    for col in [
        "Mean_Prevalence",
        "Mean_PR_AUC",
        "Excluding_2020_PR_AUC",
        "Excluding_2020_Delta",
        "Mean_ROC_AUC",
        "Mean_Brier",
        "Mean_Brier_Skill",
        "Mean_ECE",
    ]:
        grouped[col] = grouped[col].map(_fmt)
    for col in ["metric_rows", "n_folds", "valid_folds", "excluded_sparse_folds"]:
        grouped[col] = grouped[col].map(_fmt)
    grouped["Panel_Positives"] = grouped["Panel_Positives"].map(_fmt)
    return grouped


def _public_fold_support(task_status: pd.DataFrame) -> pd.DataFrame:
    if task_status.empty:
        return pd.DataFrame()
    needed = {"task", "test_year", "n_test", "positive_test"}
    if not needed.issubset(task_status.columns):
        return pd.DataFrame()
    work = task_status.copy()
    work["n_test_num"] = pd.to_numeric(work["n_test"], errors="coerce")
    work["positive_test_num"] = pd.to_numeric(work["positive_test"], errors="coerce")
    grouped = (
        work.groupby(["task", "test_year"], dropna=False)
        .agg(
            Configs=("status", "size"),
            Test_Rows=("n_test_num", "max"),
            Positives=("positive_test_num", "max"),
        )
        .reset_index()
        .rename(columns={"task": "Task", "test_year": "Test_Year"})
    )
    grouped["Prevalence"] = grouped["Positives"] / grouped["Test_Rows"]
    grouped["Sparse_Excluded"] = grouped["Positives"].lt(SPARSE_POSITIVE_THRESHOLD)
    grouped = grouped.sort_values(["Task", "Test_Year"]).reset_index(drop=True)
    for col in ["Configs", "Test_Rows", "Positives"]:
        grouped[col] = grouped[col].map(_fmt)
    grouped["Test_Year"] = grouped["Test_Year"].map(
        lambda value: str(int(float(value))) if pd.notna(value) else ""
    )
    grouped["Prevalence"] = grouped["Prevalence"].map(_fmt)
    grouped["Sparse_Excluded"] = grouped["Sparse_Excluded"].map(lambda value: "Yes" if value else "No")
    return grouped


def _feature_family_metrics(metrics: pd.DataFrame, summary: dict[str, Any]) -> pd.DataFrame:
    family = summary.get("feature_family_summary", {})
    uncertainty = _annual_metric_summary(metrics, ["feature_set"])
    grouped = (
        metrics.groupby("feature_set", dropna=False)
        .agg(
            Mean_ROC_AUC=("roc_auc", "mean"),
        )
        .reset_index()
    )
    grouped = grouped.merge(uncertainty, on="feature_set", how="left")
    grouped = grouped.sort_values("mean", ascending=False)
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
    grouped["Mean_PR_AUC"] = grouped["mean"]
    grouped["PR_AUC_Dispersion"] = grouped.apply(_dispersion_text, axis=1)
    for col in [
        "metric_rows",
        "n_folds",
        "valid_folds",
        "excluded_sparse_folds",
        "Features",
        "XBRL_Ratios",
        "XBRL_Coverage",
    ]:
        grouped[col] = grouped[col].map(_fmt)
    for col in ["Mean_PR_AUC", "Mean_ROC_AUC"]:
        grouped[col] = grouped[col].map(_fmt)
    return grouped


def _task_feature_family_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    if metrics.empty or not {"task", "feature_set"}.issubset(metrics.columns):
        return pd.DataFrame()
    uncertainty = _annual_metric_summary(metrics, ["task", "feature_set"])
    grouped = (
        metrics.groupby(["task", "feature_set"], dropna=False)
        .agg(
            Mean_Prevalence=("positive_rate_test", "mean"),
            Mean_ROC_AUC=("roc_auc", "mean"),
            Mean_Brier_Skill=("brier_skill_score", "mean"),
            Mean_ECE=("ece", "mean"),
        )
        .reset_index()
        .merge(uncertainty, on=["task", "feature_set"], how="left")
        .sort_values(["task", "mean"], ascending=[True, False])
        .rename(columns={"task": "Task", "feature_set": "Feature_Set"})
    )
    grouped["Mean_PR_AUC"] = grouped["mean"]
    grouped["PR_AUC_Dispersion"] = grouped.apply(_dispersion_text, axis=1)
    for col in ["Mean_Prevalence", "Mean_PR_AUC", "Mean_ROC_AUC", "Mean_Brier_Skill", "Mean_ECE"]:
        grouped[col] = grouped[col].map(_fmt)
    for col in ["metric_rows", "n_folds", "valid_folds", "excluded_sparse_folds"]:
        grouped[col] = grouped[col].map(_fmt)
    return grouped


def _benchmark_timing_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    uncertainty = _annual_metric_summary(metrics, ["label_mode", "window"])
    grouped = (
        metrics.groupby(["label_mode", "window"], dropna=False)
        .agg(
            Mean_ROC_AUC=("roc_auc", "mean"),
            Top_100_Precision=("top_100_precision", "mean"),
            Brier=("brier", "mean"),
            Retained_Positive_Share=("retained_positive_train_share", "mean"),
        )
        .reset_index()
    )
    grouped = grouped.merge(uncertainty, on=["label_mode", "window"], how="left")
    grouped = grouped.sort_values("mean", ascending=False)
    best = grouped.drop_duplicates("label_mode").rename(
        columns={"label_mode": "Label_Mode", "window": "Best_Window"}
    )
    best["Mean_PR_AUC"] = best["mean"]
    best["PR_AUC_Dispersion"] = best.apply(_dispersion_text, axis=1)
    for col in [
        "Mean_PR_AUC",
        "Mean_ROC_AUC",
        "Top_100_Precision",
        "Brier",
        "Retained_Positive_Share",
    ]:
        best[col] = best[col].map(_fmt)
    for col in ["metric_rows", "n_folds", "valid_folds", "excluded_sparse_folds"]:
        best[col] = best[col].map(_fmt)
    return best


def _model_family_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    model_col = "peer_model_id"
    uncertainty = _annual_metric_summary(metrics, [model_col])
    grouped = (
        metrics.groupby(model_col, dropna=False)
        .agg(
            Mean_ROC_AUC=("roc_auc", "mean"),
            Mean_Brier=("brier", "mean"),
        )
        .reset_index()
    )
    grouped = grouped.merge(uncertainty, on=model_col, how="left")
    grouped = grouped.sort_values("mean", ascending=False).rename(columns={model_col: "Model"})
    grouped["Mean_PR_AUC"] = grouped["mean"]
    grouped["PR_AUC_Dispersion"] = grouped.apply(_dispersion_text, axis=1)
    for col in ["Mean_PR_AUC", "Mean_ROC_AUC", "Mean_Brier"]:
        grouped[col] = grouped[col].map(_fmt)
    for col in ["metric_rows", "n_folds", "valid_folds", "excluded_sparse_folds"]:
        grouped[col] = grouped[col].map(_fmt)
    return grouped


def _bridge_coverage(path: Path) -> pd.DataFrame:
    coverage = _read_csv(path)
    coverage["value"] = coverage["value"].map(_fmt)
    return coverage.rename(columns={"metric": "Metric", "value": "Value"})


def _top_decile_support(n_pos: Any, n_neg: Any, precision: Any) -> dict[str, Any]:
    positives = pd.to_numeric(pd.Series([n_pos]), errors="coerce").iloc[0]
    negatives = pd.to_numeric(pd.Series([n_neg]), errors="coerce").iloc[0]
    top_precision = pd.to_numeric(pd.Series([precision]), errors="coerce").iloc[0]
    if pd.isna(positives) or pd.isna(negatives):
        return {"N": "", "Positives": "", "Top_10pct_K": "", "Top_10pct_Hits": ""}
    total = int(positives + negatives)
    top_k = min(max(int(math.floor(total * 0.10 + 0.5)), 1), total)
    hits = int(round(float(top_precision) * top_k)) if pd.notna(top_precision) else ""
    return {
        "N": _fmt(total),
        "Positives": _fmt(int(positives)),
        "Top_10pct_K": _fmt(top_k),
        "Top_10pct_Hits": _fmt(hits) if hits != "" else "",
    }


def _primary_alignment_row(frame: pd.DataFrame, *, direction: str) -> pd.Series:
    if "is_primary" not in frame:
        raise ValueError(f"{direction} alignment is missing is_primary")
    selected = frame.loc[frame["is_primary"].astype(bool)]
    if len(selected) != 1:
        raise ValueError(f"{direction} alignment requires exactly one primary row")
    return selected.iloc[0]


def _construct_alignment(study_dir: Path) -> pd.DataFrame:
    public_to_benchmark = _read_csv(study_dir / "construct_overlap" / "public_score_benchmark_ranking.csv")
    benchmark_to_public = _read_csv(study_dir / "construct_overlap" / "reciprocal_alignment.csv")
    public_primary = _primary_alignment_row(
        public_to_benchmark,
        direction="public-to-benchmark",
    )
    benchmark_primary = _primary_alignment_row(
        benchmark_to_public,
        direction="benchmark-to-public",
    )
    rows: list[dict[str, Any]] = []
    if not public_to_benchmark.empty:
        best = public_primary
        support = _top_decile_support(
            best.get("n_benchmark_positives_in_overlap"),
            best.get("n_benchmark_negatives_in_overlap"),
            best.get("top_10pct_precision"),
        )
        rows.append(
            {
                "Direction": "Public score to benchmark positives",
                "Model": best["model_id"],
                "Target": "Item 4.02",
                "Feature_Set": best["feature_set"],
                "Window": best["train_window"],
                **support,
                "PR_AUC": _fmt(best["pr_auc"]),
                "ROC_AUC": _fmt(best["roc_auc"]),
                "Top_Decile_Lift": _fmt(best["top_decile_lift"]),
                "Top_10pct_Precision": _fmt(best.get("top_10pct_precision")),
                "Top_10pct_FDR": _fmt(1 - float(best.get("top_10pct_precision"))),
                "Lift_Bootstrap_Interval": f"[{_fmt(best.get('top_decile_lift_ci_low'))}, {_fmt(best.get('top_decile_lift_ci_high'))}]",
                "top_decile_lift": float(best["top_decile_lift"]),
                "ci_low": float(best.get("top_decile_lift_ci_low")),
                "ci_high": float(best.get("top_decile_lift_ci_high")),
                "Metric_Status": best.get("metric_status", ""),
                "Bridge_Tier": best.get("bridge_tier", ""),
            }
        )
    if not benchmark_to_public.empty:
        best = benchmark_primary
        support = _top_decile_support(
            best.get("n_public_positives_in_overlap"),
            best.get("n_public_negatives_in_overlap"),
            best.get("top_10pct_precision"),
        )
        rows.append(
            {
                "Direction": "Detected-misstatement score to public labels",
                "Model": best["model_id"],
                "Target": "Item 4.02",
                "Feature_Set": best.get("feature_set", ""),
                "Window": best["train_window"],
                **support,
                "PR_AUC": _fmt(best["pr_auc"]),
                "ROC_AUC": _fmt(best["roc_auc"]),
                "Top_Decile_Lift": _fmt(best["top_decile_lift"]),
                "Top_10pct_Precision": _fmt(best.get("top_10pct_precision")),
                "Top_10pct_FDR": _fmt(1 - float(best.get("top_10pct_precision"))),
                "Lift_Bootstrap_Interval": f"[{_fmt(best.get('top_decile_lift_ci_low'))}, {_fmt(best.get('top_decile_lift_ci_high'))}]",
                "top_decile_lift": float(best["top_decile_lift"]),
                "ci_low": float(best.get("top_decile_lift_ci_low")),
                "ci_high": float(best.get("top_decile_lift_ci_high")),
                "Metric_Status": best.get("metric_status", ""),
                "Bridge_Tier": best.get("bridge_tier", ""),
            }
        )
    return pd.DataFrame(rows)


def _bridge_overlap_matrix(study_dir: Path) -> pd.DataFrame:
    path = study_dir / "construct_overlap" / "label_contingency_lift.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = _read_csv(path)
    if frame.empty:
        return frame
    labels = {
        "label_comment_thread_365": "comment_thread",
        "label_amendment_365": "amendment",
        "label_8k_402_365": "8k_402",
    }
    keep_cols = [
        "public_label",
        "bridge_tier",
        "n",
        "benchmark_positive_rows",
        "public_positive_rows",
        "both_positive_rows",
        "benchmark_prevalence",
        "public_prevalence",
        "public_rate_given_benchmark_pos",
        "benchmark_rate_given_public_pos",
        "lift_public_given_benchmark",
        "lift_benchmark_given_public",
    ]
    out = frame.loc[frame["public_label"].isin(labels), keep_cols].copy()
    tier_order = {"high_confidence": 0, "ambiguous": 1, "all_matched": 2}
    out["_label_order"] = out["public_label"].map({key: idx for idx, key in enumerate(labels)})
    out["_tier_order"] = out["bridge_tier"].map(tier_order).fillna(99)
    out = out.sort_values(["_label_order", "_tier_order"]).drop(columns=["_label_order", "_tier_order"])
    out = out.rename(
        columns={
            "public_label": "Public_Label",
            "bridge_tier": "Bridge_Tier",
            "n": "Bridge_Rows",
            "benchmark_positive_rows": "Benchmark_Positives",
            "public_positive_rows": "Public_Positives",
            "both_positive_rows": "Both_Positive",
            "benchmark_prevalence": "Benchmark_Rate",
            "public_prevalence": "Public_Rate",
            "public_rate_given_benchmark_pos": "Public_Rate_If_Benchmark_Pos",
            "benchmark_rate_given_public_pos": "Benchmark_Rate_If_Public_Pos",
            "lift_public_given_benchmark": "Public_Lift_If_Benchmark_Pos",
            "lift_benchmark_given_public": "Benchmark_Lift_If_Public_Pos",
        }
    )
    out["Public_Label"] = out["Public_Label"].map(labels)
    for col in ["Bridge_Rows", "Benchmark_Positives", "Public_Positives", "Both_Positive"]:
        out[col] = out[col].map(_fmt)
    for col in [
        "Benchmark_Rate",
        "Public_Rate",
        "Public_Rate_If_Benchmark_Pos",
        "Benchmark_Rate_If_Public_Pos",
        "Public_Lift_If_Benchmark_Pos",
        "Benchmark_Lift_If_Public_Pos",
    ]:
        out[col] = out[col].map(_fmt)
    return out


def _bridge_sample_boundaries(study_dir: Path) -> pd.DataFrame:
    flow_path = study_dir / "construct_overlap" / "overlap_sample_flow.csv"
    unmatched_path = study_dir / "bridge_probe" / "unmatched_raw_characteristics.csv"
    rows: list[dict[str, Any]] = []
    if flow_path.exists():
        flow = _read_csv(flow_path)
        raw = flow.loc[flow["bridge_tier"].eq("full_raw")]
        total_rows = float(raw["rows"].iloc[0]) if not raw.empty else float(pd.to_numeric(flow["rows"], errors="coerce").max())
        total_pos = (
            float(raw["benchmark_positives"].iloc[0])
            if not raw.empty
            else float(pd.to_numeric(flow["benchmark_positives"], errors="coerce").max())
        )
        interpretations = {
            "full_raw": "Benchmark rows entering the bridge-overlap accounting screen",
            "ambiguous": "Mapped rows retained for sensitivity diagnostics, not headline overlap",
            "dropped": "Rows without a usable high-confidence public-side overlap match",
            "high_confidence": "Rows used for headline bridge-gated construct-alignment statistics",
        }
        for _, row in flow.iterrows():
            bridge_tier = row.get("bridge_tier", "")
            benchmark_rows = pd.to_numeric(row.get("rows"), errors="coerce")
            benchmark_pos = pd.to_numeric(row.get("benchmark_positives"), errors="coerce")
            rows.append(
                {
                    "Boundary": bridge_tier,
                    "Benchmark_Rows": benchmark_rows,
                    "Row_Share": benchmark_rows / total_rows if total_rows else "",
                    "Benchmark_Positives": benchmark_pos,
                    "Positive_Share": benchmark_pos / total_pos if total_pos else "",
                    "Interpretation": interpretations.get(str(bridge_tier), "Bridge-overlap tier"),
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    if unmatched_path.exists():
        unmatched = _read_csv(unmatched_path)
        if not unmatched.empty and "unmatched_rows" in unmatched.columns:
            out.attrs["unmatched_raw_rows"] = int(
                pd.to_numeric(unmatched["unmatched_rows"], errors="coerce").fillna(0).sum()
            )
    for col in ["Benchmark_Rows", "Benchmark_Positives"]:
        out[col] = out[col].map(_fmt)
    for col in ["Row_Share", "Positive_Share"]:
        out[col] = out[col].map(_fmt)
    return out


def _selection_profile_table(panel_path: Path | None = None) -> pd.DataFrame:
    path = panel_path or LAKE_GOLD_DIR / "issuer_origin_panel.parquet"
    if not path.exists():
        return pd.DataFrame()
    try:
        import duckdb
    except ImportError:
        return pd.DataFrame()
    cols = [
        "form",
        "entity_type",
        "size",
        "xbrl_ratio_log_assets",
        "days_since_previous_filing",
        "prior_filing_count",
        "public_history_comment_thread_3y_count",
        "issuer_has_fpi_form_year",
        "censored_365",
        "label_comment_thread_365",
        "label_amendment_365",
        "label_8k_402_365",
    ]
    query = "SELECT " + ", ".join(cols) + " FROM read_parquet(?)"
    try:
        panel = duckdb.connect(database=":memory:").execute(query, [str(path)]).fetchdf()
    except Exception:
        return pd.DataFrame()
    if panel.empty:
        return pd.DataFrame()
    panel = panel.loc[pd.to_numeric(panel["censored_365"], errors="coerce").fillna(0).eq(0)].copy()
    if panel.empty:
        return pd.DataFrame()
    for col in [
        "size",
        "xbrl_ratio_log_assets",
        "days_since_previous_filing",
        "prior_filing_count",
        "public_history_comment_thread_3y_count",
        "issuer_has_fpi_form_year",
        "label_comment_thread_365",
        "label_amendment_365",
        "label_8k_402_365",
    ]:
        panel[col] = pd.to_numeric(panel[col], errors="coerce")

    rows: list[dict[str, Any]] = []

    def add_profile(stratum: str, group: str, mask: pd.Series) -> None:
        subset = panel.loc[mask.fillna(False)]
        if subset.empty:
            return
        rows.append(
            {
                "Stratum": stratum,
                "Group": group,
                "Issuer_Years": len(subset),
                "Comment_Rate": subset["label_comment_thread_365"].mean(),
                "Amendment_Rate": subset["label_amendment_365"].mean(),
                "Item_4_02_Rate": subset["label_8k_402_365"].mean(),
            }
        )

    for col, stratum in [
        ("size", "Filing size"),
        ("xbrl_ratio_log_assets", "XBRL log assets"),
        ("prior_filing_count", "Prior filing count"),
        ("days_since_previous_filing", "Days since prior filing"),
    ]:
        median = panel[col].median(skipna=True)
        if pd.notna(median):
            add_profile(stratum, f"Below median ({_fmt(float(median))})", panel[col].lt(median))
            add_profile(stratum, f"At/above median ({_fmt(float(median))})", panel[col].ge(median))

    add_profile(
        "Prior public comment-thread history",
        "No prior 3y public thread",
        panel["public_history_comment_thread_3y_count"].fillna(0).eq(0),
    )
    add_profile(
        "Prior public comment-thread history",
        "Any prior 3y public thread",
        panel["public_history_comment_thread_3y_count"].fillna(0).gt(0),
    )
    add_profile("Annual form", "10-K", panel["form"].astype("string").eq("10-K"))
    add_profile("Annual form", "10-K/A", panel["form"].astype("string").eq("10-K/A"))
    add_profile("Foreign issuer proxy", "No FPI-year flag", panel["issuer_has_fpi_form_year"].fillna(0).eq(0))
    add_profile("Foreign issuer proxy", "FPI-year flag", panel["issuer_has_fpi_form_year"].fillna(0).eq(1))

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    for col in ["Issuer_Years"]:
        out[col] = out[col].map(_fmt)
    for col in ["Comment_Rate", "Amendment_Rate", "Item_4_02_Rate"]:
        out[col] = out[col].map(_fmt)
    return out


def _public_opacity_dml_table(study_dir: Path) -> pd.DataFrame:
    path = study_dir / "public_cascade" / "public_opacity_dml.csv"
    if not path.exists():
        return pd.DataFrame()
    dml = _read_csv(path)
    if dml.empty:
        return dml
    dml["coef_num"] = pd.to_numeric(dml.get("coef"), errors="coerce")
    dml["std_err_num"] = pd.to_numeric(dml.get("std_err"), errors="coerce")
    dml["ci_low"] = dml["coef_num"] - 1.96 * dml["std_err_num"]
    dml["ci_high"] = dml["coef_num"] + 1.96 * dml["std_err_num"]
    dml["interval_method"] = "cross_fit_residual_ols_hc3_95"
    dml["Coef"] = dml["coef_num"].map(_fmt)
    dml["Std_Err"] = dml["std_err_num"].map(_fmt)
    dml["CI_95"] = dml.apply(
        lambda row: f"[{_fmt(row['ci_low'])}, {_fmt(row['ci_high'])}]"
        if pd.notna(row["ci_low"]) and pd.notna(row["ci_high"])
        else "",
        axis=1,
    )
    dml["P_Value"] = pd.to_numeric(dml.get("p_value"), errors="coerce").map(_fmt)
    dml["N_Obs"] = pd.to_numeric(dml.get("n_obs"), errors="coerce").map(_fmt)
    dml["Prevalence"] = pd.to_numeric(dml.get("prevalence"), errors="coerce").map(_fmt)
    for source, target in [
        ("n_raw_controls", "Raw_Controls"),
        ("n_encoded_controls", "Encoded_Controls"),
        ("n_opacity_components", "Opacity_Components"),
    ]:
        values = pd.to_numeric(dml[source], errors="coerce")
        dml[target] = values.map(lambda value: str(int(value)) if pd.notna(value) else "")
    dml["Outcome"] = dml["outcome"]
    dml["Status"] = dml["status"]
    return dml


def _plot_metric_with_uncertainty(
    df: pd.DataFrame,
    *,
    fold_df: pd.DataFrame,
    summary_group_col: str,
    fold_group_col: str,
    title: str,
    ylabel: str,
    out_path: Path,
    color: str = "#2a9d8f",
    plot_style: str = "bar",
) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_df = df.copy()
    plot_df["mean_num"] = pd.to_numeric(plot_df["mean"], errors="coerce")
    plot_df["ci_low_num"] = pd.to_numeric(plot_df["ci_low"], errors="coerce")
    plot_df["ci_high_num"] = pd.to_numeric(plot_df["ci_high"], errors="coerce")
    plot_df = plot_df.sort_values("mean_num", ascending=False)
    labels = plot_df[summary_group_col].astype(str)
    horizontal = labels.map(len).max() > 14
    rng = np.random.default_rng(20260526)
    fig, ax = plt.subplots(figsize=(7.2, 4.6 if horizontal else 4.2))
    if horizontal:
        plot_df = plot_df.sort_values("mean_num", ascending=True).reset_index(drop=True)
        y_pos = np.arange(len(plot_df))
        if plot_style == "dot":
            ax.scatter(
                plot_df["mean_num"],
                y_pos,
                s=42,
                color=color,
                edgecolor="#1f2933",
                linewidth=0.6,
                zorder=5,
            )
        else:
            ax.barh(y_pos, plot_df["mean_num"], color=color, edgecolor="#1f2933", linewidth=0.6)
        ax.set_yticks(y_pos, plot_df[summary_group_col].astype(str))
        for idx, row in plot_df.iterrows():
            if pd.notna(row["ci_low_num"]) and pd.notna(row["ci_high_num"]):
                ax.errorbar(
                    row["mean_num"],
                    idx,
                    xerr=[[row["mean_num"] - row["ci_low_num"]], [row["ci_high_num"] - row["mean_num"]]],
                    fmt="none",
                    ecolor="#222222",
                    elinewidth=1,
                    capsize=3,
                    zorder=3,
                )
            dots = fold_df.loc[
                fold_df[fold_group_col].astype(str).eq(str(row[summary_group_col]))
                & fold_df["valid_metric"]
            ]
            jitter = rng.uniform(-0.08, 0.08, size=len(dots))
            ax.scatter(dots["fold_value"], idx + jitter, s=15, color="#555555", alpha=0.55, zorder=4)
        ax.set_xlabel(ylabel)
        ax.set_ylabel("")
    else:
        plot_df = plot_df.reset_index(drop=True)
        x_pos = np.arange(len(plot_df))
        if plot_style == "dot":
            ax.scatter(
                x_pos,
                plot_df["mean_num"],
                s=42,
                color=color,
                edgecolor="#1f2933",
                linewidth=0.6,
                zorder=5,
            )
        else:
            ax.bar(x_pos, plot_df["mean_num"], color=color, edgecolor="#1f2933", linewidth=0.6)
        ax.set_xticks(x_pos, plot_df[summary_group_col].astype(str))
        for idx, row in plot_df.iterrows():
            if pd.notna(row["ci_low_num"]) and pd.notna(row["ci_high_num"]):
                ax.errorbar(
                    idx,
                    row["mean_num"],
                    yerr=[[row["mean_num"] - row["ci_low_num"]], [row["ci_high_num"] - row["mean_num"]]],
                    fmt="none",
                    ecolor="#222222",
                    elinewidth=1,
                    capsize=3,
                    zorder=3,
                )
            dots = fold_df.loc[
                fold_df[fold_group_col].astype(str).eq(str(row[summary_group_col]))
                & fold_df["valid_metric"]
            ]
            jitter = rng.uniform(-0.08, 0.08, size=len(dots))
            ax.scatter(idx + jitter, dots["fold_value"], s=15, color="#555555", alpha=0.55, zorder=4)
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
    fig.savefig(png_path, dpi=300)
    fig.savefig(pdf_path)
    plt.close(fig)
    return {"png": _rel(png_path), "pdf": _rel(pdf_path)}


def _plot_construct_lift(df: pd.DataFrame, *, out_path: Path) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_df = df.copy()
    plot_df["Top_Decile_Lift"] = pd.to_numeric(plot_df["top_decile_lift"], errors="coerce")
    plot_df["ci_low"] = pd.to_numeric(plot_df["ci_low"], errors="coerce")
    plot_df["ci_high"] = pd.to_numeric(plot_df["ci_high"], errors="coerce")
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    y_pos = np.arange(len(plot_df))
    ax.barh(y_pos, plot_df["Top_Decile_Lift"], color="#457b9d")
    ax.set_yticks(y_pos, plot_df["Direction"])
    for idx, row in plot_df.iterrows():
        if pd.notna(row["ci_low"]) and pd.notna(row["ci_high"]):
            ax.errorbar(
                row["Top_Decile_Lift"],
                idx,
                xerr=[[row["Top_Decile_Lift"] - row["ci_low"]], [row["ci_high"] - row["Top_Decile_Lift"]]],
                fmt="none",
                ecolor="#222222",
                elinewidth=1,
                capsize=3,
                    zorder=3,
                )
        precision = pd.to_numeric(pd.Series([row.get("Top_10pct_Precision")]), errors="coerce").iloc[0]
        fdr = pd.to_numeric(pd.Series([row.get("Top_10pct_FDR")]), errors="coerce").iloc[0]
        if pd.notna(precision) and pd.notna(fdr):
            ax.text(
                row["Top_Decile_Lift"] + 0.05,
                idx,
                f"P={precision:.3f}; FDR={fdr:.3f}",
                va="center",
                fontsize=8,
                color="#1f2933",
            )
    ax.axvline(1.0, color="#222222", linewidth=1, linestyle="--")
    finite_x = pd.concat([plot_df["ci_high"], plot_df["Top_Decile_Lift"]], ignore_index=True).dropna()
    if not finite_x.empty:
        ax.set_xlim(left=0, right=float(finite_x.max()) * 1.28)
    ax.set_xlabel("Top-decile lift")
    ax.set_title("Severe-tail diagnostic lift")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    png_path = out_path.with_suffix(".png")
    pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(png_path, dpi=300)
    fig.savefig(pdf_path)
    plt.close(fig)
    return {"png": _rel(png_path), "pdf": _rel(pdf_path)}


def _result_narrative(
    *,
    manifest: dict[str, Any],
    public_summary: dict[str, Any],
    public_task: pd.DataFrame,
    benchmark_peer: pd.DataFrame,
    public_peer: pd.DataFrame,
    construct_alignment: pd.DataFrame,
    construct_manifest: dict[str, Any],
) -> str:
    primary_public = _package_primary_identity(public_summary)[
        "primary_public_specification"
    ]
    primary_public_label = (
        f"{primary_public['feature_set']} + {primary_public['train_window']}"
    )
    comment_row = public_task[public_task["Task"].eq("comment_thread")].head(1)
    amendment_row = public_task[public_task["Task"].eq("amendment")].head(1)
    severe_row = public_task[public_task["Task"].eq("8k_402")].head(1)
    benchmark_leader = benchmark_peer.iloc[0] if not benchmark_peer.empty else None
    public_peer_leader = public_peer.iloc[0] if not public_peer.empty else None
    validation_tier = construct_manifest.get("validation_tier", "")
    generated = manifest.get("generated_at_utc", "")
    public_out_dir = manifest.get("components", {}).get("public_cascade", {}).get("out_dir", "")
    public_out_dir_display = _rel(public_out_dir) if public_out_dir else ""

    def value(row: pd.DataFrame, col: str) -> str:
        if row.empty:
            return "n/a"
        return str(row.iloc[0][col])

    lines = [
        "# Manuscript Results Narrative",
        "",
        f"_Generated from `{public_out_dir_display}` "
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
        f"The revision-frozen primary specification for public-cascade headlines is "
        f"`{primary_public_label}`. Its task-level results are distinct from feature-family "
        "summaries that average over tasks and training windows. The public tasks show a "
        "natural severity gradient. "
        "Comment-thread scrutiny is the broadest public-scrutiny "
        f"signal (mean PR-AUC `{value(comment_row, 'Mean_PR_AUC')}`), amendments provide "
        f"a clear correction/friction channel (mean PR-AUC `{value(amendment_row, 'Mean_PR_AUC')}`), "
        f"and 8-K Item 4.02 is rarer but still rankable (mean PR-AUC `{value(severe_row, 'Mean_PR_AUC')}`).",
        "",
        "## Peer-Compatible Model Families",
        "",
        "The peer suites are model-family transfer exercises. They align the public "
        "reporting-risk task with familiar Dechow, Perols, Bao, and Bertomeu-style "
        "vocabularies without claiming original-paper numeric replication. In the "
        f"detected-misstatement peer benchmark, `{benchmark_leader['Model'] if benchmark_leader is not None else 'n/a'}` "
        f"has the highest mean PR-AUC (`{benchmark_leader['Mean_PR_AUC'] if benchmark_leader is not None else 'n/a'}`). "
        f"In the public-label peer suite, `{public_peer_leader['Model'] if public_peer_leader is not None else 'n/a'}` "
        f"leads on mean PR-AUC (`{public_peer_leader['Mean_PR_AUC'] if public_peer_leader is not None else 'n/a'}`). "
        "These comparisons should be read within task and estimand, not as cross-"
        "estimand performance rankings against prior fraud-prediction papers.",
        "",
        "## Construct-Overlap Evidence",
        "",
        "The WRDS-validated bridge shows that public-cascade scores and detected-"
        "misstatement benchmark labels are related but non-identical. The revision-frozen "
        "primary public-score-to-benchmark-positive row and reciprocal detected-"
        "misstatement-score-to-public-label row are the two directional diagnostics "
        "reported in Table 9 and Figure 5. "
        f"The validation tier is `{validation_tier}`; this supports manuscript-grade "
        "integrated overlap claims while preserving the related-but-non-identical "
        "construct boundary.",
        "",
        "## Claim Boundary",
        "",
        "The evidence supports a measurement-and-ranking paper on public review-and-"
        "correction risk. It does not identify hidden misconduct, causal "
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
    public_task_status = _read_csv(study_dir / "public_cascade" / "public_cascade_task_status.csv")
    benchmark_metrics = _read_csv(study_dir / "benchmark" / "rolling_metrics.csv")
    benchmark_peer_metrics = _read_csv(study_dir / "peer_comparison" / "detected_misstatement_model_family_metrics.csv")
    public_peer_metrics = _read_csv(
        study_dir / "public_peer_comparison" / "public_model_family_metrics.csv"
    )
    public_primary_metrics = _select_primary_public_metrics(public_metrics, public_summary)

    public_lake = _public_lake_scale(_latest_public_lake_report())
    public_task = _public_task_metrics(
        public_primary_metrics,
        public_task_status,
        public_summary,
    )
    public_sample_attrition = _public_sample_attrition_table(public_summary)
    public_fold_support = _public_fold_support(public_task_status)
    feature_family = _feature_family_metrics(public_metrics, public_summary)
    task_feature_family = _task_feature_family_metrics(public_metrics)
    benchmark_timing = _benchmark_timing_metrics(benchmark_metrics)
    benchmark_peer = _model_family_metrics(benchmark_peer_metrics)
    public_peer = _model_family_metrics(public_peer_metrics)
    bridge_coverage = _bridge_coverage(study_dir / "bridge_probe" / "coverage_report.csv")
    construct_alignment = _construct_alignment(study_dir)
    bridge_overlap = _bridge_overlap_matrix(study_dir)
    bridge_boundaries = _bridge_sample_boundaries(study_dir)
    selection_profile = _selection_profile_table()
    public_opacity_dml = _public_opacity_dml_table(study_dir)
    component_status = _component_status(manifest)

    public_task_folds = _annual_fold_frame(public_primary_metrics, ["task"])
    feature_family_folds = _annual_fold_frame(public_metrics, ["feature_set"])
    benchmark_peer_folds = _annual_fold_frame(benchmark_peer_metrics, ["peer_model_id"])
    public_peer_folds = _annual_fold_frame(public_peer_metrics, ["peer_model_id"])

    table_manifest = {
        "table_01_component_status": _write_table_bundle(
            component_status,
            out_dir=tables_dir,
            stem="table_01_component_status",
            caption="Study component status for manuscript evidence",
            label="tab:component-status",
        ),
        "table_02_public_lake_scale": _write_table_bundle(
            public_lake,
            out_dir=tables_dir,
            stem="table_02_public_lake_scale",
            caption="Public data architecture and analytical panel scale",
            label="tab:public-lake-scale",
        ),
        "table_03_public_task_metrics": _write_table_bundle(
            public_task,
            out_dir=tables_dir,
            stem="table_03_public_task_metrics",
            caption="Public cascade task metrics",
            label="tab:public-task-metrics",
            note=PUBLIC_TASK_NOTE,
            display_df=_table_view(
                public_task,
                [
                    "Task",
                    "Panel_Positives",
                    "n_folds",
                    "valid_folds",
                    "Mean_Prevalence",
                    "Mean_PR_AUC",
                    "Excluding_2020_PR_AUC",
                    "Excluding_2020_Delta",
                    "PR_AUC_Dispersion",
                    "Mean_ROC_AUC",
                    "Mean_Brier",
                    "Mean_Brier_Skill",
                    "Mean_ECE",
                ],
            ),
        ),
        "table_04_feature_family_metrics": _write_table_bundle(
            feature_family,
            out_dir=tables_dir,
            stem="table_04_feature_family_metrics",
            caption="Public cascade feature-family metrics",
            label="tab:feature-family-metrics",
            note=FEATURE_FAMILY_NOTE,
            display_df=_table_view(
                feature_family,
                [
                    "Feature_Set",
                    "Features",
                    "XBRL_Ratios",
                    "XBRL_Coverage",
                    "Best_Window",
                    "n_folds",
                    "valid_folds",
                    "Mean_PR_AUC",
                    "PR_AUC_Dispersion",
                    "Mean_ROC_AUC",
                ],
            ),
        ),
        "table_05_benchmark_timing_metrics": _write_table_bundle(
            benchmark_timing,
            out_dir=tables_dir,
            stem="table_05_benchmark_timing_metrics",
            caption="Detected-misstatement benchmark timing diagnostics",
            label="tab:benchmark-timing",
            note=BENCHMARK_TIMING_NOTE,
            display_df=_table_view(
                benchmark_timing,
                [
                    "Label_Mode",
                    "Best_Window",
                    "n_folds",
                    "valid_folds",
                    "Mean_PR_AUC",
                    "PR_AUC_Dispersion",
                    "Mean_ROC_AUC",
                    "Top_100_Precision",
                    "Retained_Positive_Share",
                ],
            ),
        ),
        "table_06_detected_misstatement_peer_metrics": _write_table_bundle(
            benchmark_peer,
            out_dir=tables_dir,
            stem="table_06_detected_misstatement_peer_metrics",
            caption="Detected-misstatement peer-compatible model-family metrics",
            label="tab:benchmark-peer",
            note=PEER_TRANSFER_NOTE,
            display_df=_table_view(
                benchmark_peer,
                [
                    "Model",
                    "n_folds",
                    "valid_folds",
                    "Mean_PR_AUC",
                    "PR_AUC_Dispersion",
                    "Mean_ROC_AUC",
                ],
            ),
        ),
        "table_07_public_peer_metrics": _write_table_bundle(
            public_peer,
            out_dir=tables_dir,
            stem="table_07_public_peer_metrics",
            caption="Public-label peer-compatible model-family metrics",
            label="tab:public-peer",
            note=PEER_TRANSFER_NOTE,
            display_df=_table_view(
                public_peer,
                [
                    "Model",
                    "n_folds",
                    "valid_folds",
                    "Mean_PR_AUC",
                    "PR_AUC_Dispersion",
                    "Mean_ROC_AUC",
                ],
            ),
        ),
        "table_08_bridge_coverage": _write_table_bundle(
            bridge_coverage,
            out_dir=tables_dir,
            stem="table_08_bridge_coverage",
            caption="Bridge coverage",
            label="tab:bridge-coverage",
            note=BRIDGE_COVERAGE_NOTE,
        ),
        "table_09_construct_alignment": _write_table_bundle(
            construct_alignment,
            out_dir=tables_dir,
            stem="table_09_construct_alignment",
            caption="Construct-overlap ranking alignment",
            label="tab:construct-alignment",
            note=CONSTRUCT_LIFT_NOTE,
            display_df=_table_view(
                construct_alignment,
                [
                    "Direction",
                    "Model",
                    "Target",
                    "Feature_Set",
                    "Window",
                    "N",
                    "Positives",
                    "Top_10pct_K",
                    "Top_10pct_Hits",
                    "PR_AUC",
                    "Top_Decile_Lift",
                    "Top_10pct_Precision",
                    "Top_10pct_FDR",
                    "Lift_Bootstrap_Interval",
                    "Bridge_Tier",
                ],
            ).rename(columns={"Bridge_Tier": "Confidence_Tier"}),
        ),
    }
    if not public_fold_support.empty:
        table_manifest["table_13_public_fold_support"] = _write_table_bundle(
            public_fold_support,
            out_dir=tables_dir,
            stem="table_13_public_fold_support",
            caption="Annual public-label fold support",
            label="tab:public-fold-support",
            note=FOLD_SUPPORT_NOTE,
        )
    if not task_feature_family.empty:
        table_manifest["table_14_task_feature_family_metrics"] = _write_table_bundle(
            task_feature_family,
            out_dir=tables_dir,
            stem="table_14_task_feature_family_metrics",
            caption="Task-by-feature-family public-cascade metrics",
            label="tab:task-feature-family",
            note=TASK_FEATURE_NOTE,
            display_df=_table_view(
                task_feature_family,
                [
                    "Task",
                    "Feature_Set",
                    "n_folds",
                    "valid_folds",
                    "Mean_Prevalence",
                    "Mean_PR_AUC",
                    "PR_AUC_Dispersion",
                    "Mean_ROC_AUC",
                    "Mean_Brier_Skill",
                    "Mean_ECE",
                ],
            ),
        )
    if not bridge_overlap.empty:
        table_manifest["table_15_bridge_overlap_matrix"] = _write_table_bundle(
            bridge_overlap,
            out_dir=tables_dir,
            stem="table_15_bridge_overlap_matrix",
            caption="Bridge-gated public-label overlap matrix",
            label="tab:bridge-overlap-matrix",
            note=BRIDGE_OVERLAP_NOTE,
        )
    if not bridge_boundaries.empty:
        table_manifest["table_16_bridge_sample_boundaries"] = _write_table_bundle(
            bridge_boundaries,
            out_dir=tables_dir,
            stem="table_16_bridge_sample_boundaries",
            caption="Bridge-overlap sample boundaries",
            label="tab:bridge-sample-boundaries",
            note=(
                BRIDGE_BOUNDARY_NOTE
                + (
                    f" An additional {_fmt(bridge_boundaries.attrs['unmatched_raw_rows'])} "
                    "raw benchmark rows lack a usable public-side identifier and are "
                    "outside all overlap statistics."
                    if bridge_boundaries.attrs.get("unmatched_raw_rows")
                    else ""
                )
            ),
        )
    if not selection_profile.empty:
        table_manifest["table_17_selection_profile"] = _write_table_bundle(
            selection_profile,
            out_dir=tables_dir,
            stem="table_17_selection_profile",
            caption="Selection-aware public-label profile",
            label="tab:selection-profile",
            note=SELECTION_PROFILE_NOTE,
        )
    table_manifest["table_18_public_sample_attrition"] = _write_table_bundle(
        public_sample_attrition,
        out_dir=tables_dir,
        stem="table_18_public_sample_attrition",
        caption="Public sample attrition and task eligibility",
        label="tab:public-sample-attrition",
        note=PUBLIC_ATTRITION_NOTE,
    )
    if not public_opacity_dml.empty:
        table_manifest["table_12_public_opacity_dml"] = _write_table_bundle(
            public_opacity_dml,
            out_dir=tables_dir,
            stem="table_12_public_opacity_dml",
            caption="Public opacity DML-style adjusted associations",
            label="tab:public-opacity-dml",
            note=DML_INTERVAL_NOTE,
            display_df=_table_view(
                public_opacity_dml,
                [
                    "Outcome",
                    "Status",
                    "N_Obs",
                    "Prevalence",
                    "Raw_Controls",
                    "Encoded_Controls",
                    "Opacity_Components",
                    "Coef",
                    "Std_Err",
                    "CI_95",
                    "P_Value",
                ],
            ),
        )

    figure_manifest = {
        "figure_01_public_task_pr_auc": _plot_metric_with_uncertainty(
            public_task,
            fold_df=public_task_folds,
            summary_group_col="Task",
            fold_group_col="task",
            title="Public-cascade task performance",
            ylabel="Mean PR-AUC",
            out_path=figures_dir / "figure_01_public_task_pr_auc",
            color="#2a9d8f",
        ),
        "figure_02_feature_family_pr_auc": _plot_metric_with_uncertainty(
            feature_family,
            fold_df=feature_family_folds,
            summary_group_col="Feature_Set",
            fold_group_col="feature_set",
            title="Feature-family comparison",
            ylabel="Mean PR-AUC",
            out_path=figures_dir / "figure_02_feature_family_pr_auc",
            color="#6a994e",
        ),
        "figure_03_detected_misstatement_peer_pr_auc": _plot_metric_with_uncertainty(
            benchmark_peer,
            fold_df=benchmark_peer_folds,
            summary_group_col="Model",
            fold_group_col="peer_model_id",
            title="Detected-misstatement peer-compatible model families",
            ylabel="Mean PR-AUC",
            out_path=figures_dir / "figure_03_detected_misstatement_peer_pr_auc",
            color="#bc6c25",
            plot_style="dot",
        ),
        "figure_04_public_peer_pr_auc": _plot_metric_with_uncertainty(
            public_peer,
            fold_df=public_peer_folds,
            summary_group_col="Model",
            fold_group_col="peer_model_id",
            title="Public-label peer-compatible model families",
            ylabel="Mean PR-AUC",
            out_path=figures_dir / "figure_04_public_peer_pr_auc",
            color="#4361ee",
            plot_style="dot",
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
            benchmark_peer=benchmark_peer,
            public_peer=public_peer,
            construct_alignment=construct_alignment,
            construct_manifest=construct_manifest,
        ),
        encoding="utf-8",
    )

    package_manifest = {
        **_package_primary_identity(public_summary),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "study_dir": _rel(study_dir),
        "out_dir": _rel(out_dir),
        "tables": table_manifest,
        "figures": figure_manifest,
        "narrative": _rel(narrative_path),
        "uncertainty": {
            "annual_metric_interval": "descriptive fold-dispersion interval over valid annual out-of-time fold means when valid_folds >= 5",
            "sparse_fold_rule": f"folds with positive count < {SPARSE_POSITIVE_THRESHOLD} are excluded from dispersion calculations and listed in excluded_sparse_years",
            "fold_dependence_caveat": "rolling and expanding training windows overlap, so fold-dispersion intervals describe evaluation-period variation rather than independent sampling error",
            "construct_overlap_interval": "row-level percentile bootstrap top-decile lift interval from construct-overlap artifacts",
            "construct_overlap_interval_method": construct_manifest.get("interval_method"),
            "construct_overlap_interval_seed": construct_manifest.get("interval_seed"),
            "construct_overlap_interval_reps": construct_manifest.get("interval_reps"),
            "construct_overlap_interval_scope": construct_manifest.get("interval_scope"),
            "dml_interval": "coef +/- 1.96 * HC3 OLS SE after cross-fitted residualization",
        },
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
