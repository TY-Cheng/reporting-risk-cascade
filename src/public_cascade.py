"""
Filing-native public cascade model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBClassifier


TASKS = {
    "comment_thread": {"label": "label_comment_thread_365", "censor": "censored_365"},
    "amendment": {"label": "label_amendment_365", "censor": "censored_365"},
    "8k_402": {"label": "label_8k_402_365", "censor": "censored_365"},
    "aaer_proxy": {"label": "label_aaer_proxy_730", "censor": "censored_730"},
}

IDENTIFIER_COLS = {
    "issuer_cik",
    "accession",
    "accession_nodash",
    "origin_date",
    "report_date",
    "filing_date",
    "acceptance_datetime",
    "fiscal_period_end",
    "as_of_date",
    "event_report_date",
    "entity_name",
    "entity_name_issuer",
    "sic_description",
    "source_file",
    "file_number",
    "film_number",
    "primary_document",
    "primary_doc_description",
}

MODEL_EXCLUDED_PREFIXES = ("source_available_", "public_date_", "vintage_")
MODEL_EXCLUDED_COLS = {
    "items",
    "issuer_has_fpi_form",
    "issuer_has_fpi_form_year",
    "is_domestic_us_gaap_proxy",
    "tickers_json",
    "exchanges_json",
    "former_names_json",
    "flags",
    "description",
    "phone",
    "ein",
}
CATEGORICAL_FEATURE_COLS = {"sic", "form", "entity_type"}


def _load_config(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _filter_main_sample(
    panel: pd.DataFrame,
    *,
    start_year: int,
    end_year: int,
    domestic_only: bool = True,
) -> pd.DataFrame:
    work = panel.copy()
    work["fiscal_year"] = pd.to_numeric(work["fiscal_year"], errors="coerce").astype("Int64")
    work = work.loc[work["fiscal_year"].between(int(start_year), int(end_year))].copy()
    if domestic_only and "is_domestic_us_gaap_proxy" in work.columns:
        work = work.loc[work["is_domestic_us_gaap_proxy"].eq(1)].copy()
    return work.reset_index(drop=True)


def _infer_feature_families(df: pd.DataFrame) -> Dict[str, List[str]]:
    candidate_cols = [col for col in df.columns if col not in IDENTIFIER_COLS]
    label_cols = {meta["label"] for meta in TASKS.values()} | {
        meta["censor"] for meta in TASKS.values()
    }
    candidate_cols = [col for col in candidate_cols if col not in label_cols]
    candidate_cols = [col for col in candidate_cols if col not in MODEL_EXCLUDED_COLS]
    candidate_cols = [
        col for col in candidate_cols if not col.lower().startswith(MODEL_EXCLUDED_PREFIXES)
    ]
    candidate_cols = [col for col in candidate_cols if not df[col].isna().all()]

    families = {
        "metadata": [],
        "xbrl": [],
        "text": [],
        "auditor": [],
        "oversight": [],
        "all": [],
    }
    for col in candidate_cols:
        lower = col.lower()
        if lower.startswith("xbrl_"):
            families["xbrl"].append(col)
        elif lower.startswith(("note_", "item_")):
            families["text"].append(col)
        elif lower.startswith(("form_ap_", "pcaob_")):
            families["auditor"].append(col)
        elif lower.startswith("prior_"):
            families["oversight"].append(col)
        else:
            families["metadata"].append(col)
    families["all"] = sorted(
        {
            *families["metadata"],
            *families["xbrl"],
            *families["text"],
            *families["auditor"],
            *families["oversight"],
        }
    )
    return families


def _build_preprocessor(df: pd.DataFrame, feature_cols: Sequence[str]) -> ColumnTransformer:
    sample = df[list(feature_cols)].copy()
    categorical = [
        col
        for col in sample.columns
        if col in CATEGORICAL_FEATURE_COLS
        or sample[col].dtype == object
        or str(sample[col].dtype).startswith("category")
    ]
    numeric = [col for col in sample.columns if col not in categorical]
    return ColumnTransformer(
        transformers=[
            ("numeric", SimpleImputer(strategy="median"), numeric),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ],
        sparse_threshold=1.0,
    )


def _build_model(
    *,
    scale_pos_weight: float,
    seed: int,
    params: Dict[str, object],
) -> XGBClassifier:
    clf = XGBClassifier(
        objective="binary:logistic",
        random_state=int(seed),
        eval_metric="logloss",
        scale_pos_weight=max(1.0, float(scale_pos_weight)),
        n_estimators=int(params.get("n_estimators", 250)),
        max_depth=int(params.get("max_depth", 4)),
        learning_rate=float(params.get("learning_rate", 0.05)),
        subsample=float(params.get("subsample", 0.8)),
        colsample_bytree=float(params.get("colsample_bytree", 0.8)),
        min_child_weight=float(params.get("min_child_weight", 5.0)),
        reg_lambda=float(params.get("reg_lambda", 1.0)),
        n_jobs=int(params.get("n_jobs", -1)),
        tree_method=str(params.get("tree_method", "hist")),
    )
    return clf


def _evaluate_binary(y_true: np.ndarray, prob: np.ndarray) -> Dict[str, float]:
    if y_true.sum() == 0:
        roc_auc = np.nan
        pr_auc = np.nan
    else:
        roc_auc = float(roc_auc_score(y_true, prob))
        pr_auc = float(average_precision_score(y_true, prob))
    try:
        brier = float(brier_score_loss(y_true, prob))
    except ValueError:
        brier = np.nan
    return {"roc_auc": roc_auc, "pr_auc": pr_auc, "brier": brier}


def _rolling_year_pairs(
    years: Sequence[int],
    *,
    min_train_years: int,
    candidate_train_windows: Sequence[Optional[int]],
) -> Iterable[Tuple[Optional[int], int, List[int]]]:
    years = sorted(int(y) for y in years)
    for window in candidate_train_windows:
        for i in range(min_train_years, len(years)):
            test_year = years[i]
            train_years = years[:i]
            if window is not None:
                train_years = train_years[-int(window) :]
            yield window, test_year, train_years


def _prepare_xy(
    df: pd.DataFrame,
    *,
    feature_cols: Sequence[str],
    label_col: str,
) -> Tuple[pd.DataFrame, np.ndarray]:
    x = df[list(feature_cols)].copy()
    y = pd.to_numeric(df[label_col], errors="coerce").fillna(0).astype(int).to_numpy()
    for col in x.columns:
        if x[col].dtype != object:
            x[col] = pd.to_numeric(x[col], errors="coerce")
    return x, y


def run_public_cascade(
    *,
    config_path: Path,
    issuer_origin_panel_csv: Path,
    out_dir: Path,
) -> Dict[str, object]:
    config = _load_config(config_path)
    panel = pd.read_csv(
        issuer_origin_panel_csv,
        parse_dates=["origin_date", "filing_date", "report_date", "as_of_date"],
        low_memory=False,
    )
    sample_cfg = config.get("sample", {})
    model_cfg = config.get("model", {})
    analysis_cfg = config.get("analysis", {})

    panel = _filter_main_sample(
        panel,
        start_year=int(sample_cfg.get("start_year", 2011)),
        end_year=int(sample_cfg.get("end_year", 2023)),
        domestic_only=bool(sample_cfg.get("domestic_only", True)),
    )
    families = _infer_feature_families(panel)
    metadata_family = set(families.get("metadata", []))
    feature_family_summary = {
        family: {
            "n_features": int(len(cols)),
            "empty": bool(len(cols) == 0),
            "same_as_metadata": bool(set(cols) == metadata_family),
            "n_xbrl_ratio_features": int(
                sum(col.startswith("xbrl_ratio_") for col in cols)
            ),
            "n_xbrl_coverage_features": int(
                sum(col.startswith("xbrl_coverage_") for col in cols)
            ),
        }
        for family, cols in families.items()
    }
    requested_families = [
        f for f in analysis_cfg.get("feature_sets", ["metadata", "all"]) if f in families
    ]
    train_windows = analysis_cfg.get("candidate_train_windows", [None, 5, 7, 10])
    min_train_years = int(analysis_cfg.get("min_train_years", 5))
    seed = int(model_cfg.get("seed", 42))
    years = panel["fiscal_year"].dropna().astype(int).sort_values().unique().tolist()

    metric_rows: List[Dict[str, object]] = []
    prediction_frames: List[pd.DataFrame] = []
    task_status_rows: List[Dict[str, object]] = []

    for family in requested_families:
        feature_cols = families[family]
        if not feature_cols:
            continue
        for window, test_year, train_years in _rolling_year_pairs(
            years,
            min_train_years=min_train_years,
            candidate_train_windows=train_windows,
        ):
            train_mask = panel["fiscal_year"].astype(int).isin(train_years)
            test_mask = panel["fiscal_year"].astype(int).eq(int(test_year))
            train_df = panel.loc[train_mask].copy()
            test_df = panel.loc[test_mask].copy()
            if train_df.empty or test_df.empty:
                continue
            active_feature_cols = [col for col in feature_cols if not train_df[col].isna().all()]
            if not active_feature_cols:
                continue
            preprocessor = _build_preprocessor(train_df, active_feature_cols)
            preprocessor.fit(train_df[active_feature_cols])

            for task_name, task_meta in TASKS.items():
                task_train = train_df.loc[train_df[task_meta["censor"]].eq(0)].copy()
                task_test = test_df.loc[test_df[task_meta["censor"]].eq(0)].copy()
                if task_train.empty or task_test.empty:
                    task_status_rows.append(
                        {
                            "feature_set": family,
                            "train_window": "expanding" if window is None else f"rolling_{window}y",
                            "test_year": int(test_year),
                            "task": task_name,
                            "status": "skipped_empty_train_or_test",
                            "n_train": int(len(task_train)),
                            "n_test": int(len(task_test)),
                            "positive_train": 0,
                            "positive_test": 0,
                        }
                    )
                    continue
                y_train = (
                    pd.to_numeric(task_train[task_meta["label"]], errors="coerce")
                    .fillna(0)
                    .astype(int)
                )
                y_test = (
                    pd.to_numeric(task_test[task_meta["label"]], errors="coerce")
                    .fillna(0)
                    .astype(int)
                )
                status_base = {
                    "feature_set": family,
                    "train_window": "expanding" if window is None else f"rolling_{window}y",
                    "test_year": int(test_year),
                    "task": task_name,
                    "n_train": int(len(task_train)),
                    "n_test": int(len(task_test)),
                    "positive_train": int(y_train.sum()),
                    "positive_test": int(y_test.sum()),
                }
                if y_train.nunique() < 2:
                    task_status_rows.append(
                        {**status_base, "status": "skipped_one_class_train"}
                    )
                    continue
                if y_test.nunique() < 2:
                    task_status_rows.append({**status_base, "status": "skipped_one_class_test"})
                    continue
                x_task_train = preprocessor.transform(task_train[active_feature_cols])
                x_task_test = preprocessor.transform(task_test[active_feature_cols])
                pos = int(y_train.sum())
                neg = int(len(y_train) - pos)
                scale_pos_weight = neg / pos if pos > 0 else 1.0
                model = _build_model(
                    scale_pos_weight=scale_pos_weight,
                    seed=seed,
                    params=model_cfg.get("xgb", {}),
                )
                model.fit(x_task_train, y_train)
                prob = model.predict_proba(x_task_test)[:, 1]
                metrics = _evaluate_binary(y_test.to_numpy(), prob)
                metric_rows.append(
                    {
                        "feature_set": family,
                        "train_window": "expanding" if window is None else f"rolling_{window}y",
                        "test_year": int(test_year),
                        "task": task_name,
                        "n_train": int(len(task_train)),
                        "n_test": int(len(task_test)),
                        "positive_rate_train": float(y_train.mean()) if len(y_train) else np.nan,
                        "positive_rate_test": float(y_test.mean()) if len(y_test) else np.nan,
                        **metrics,
                    }
                )
                task_status_rows.append({**status_base, "status": "fit"})
                pred_frame = task_test[["issuer_cik", "fiscal_year", "origin_date"]].copy()
                pred_frame["feature_set"] = family
                pred_frame["train_window"] = (
                    "expanding" if window is None else f"rolling_{window}y"
                )
                pred_frame["task"] = task_name
                pred_frame["probability"] = prob
                pred_frame["label"] = y_test.to_numpy()
                prediction_frames.append(pred_frame)

    metric_columns = [
        "feature_set",
        "train_window",
        "test_year",
        "task",
        "n_train",
        "n_test",
        "positive_rate_train",
        "positive_rate_test",
        "roc_auc",
        "pr_auc",
        "brier",
    ]
    metrics_df = pd.DataFrame(metric_rows, columns=metric_columns)
    predictions_df = (
        pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
    )
    status_columns = [
        "feature_set",
        "train_window",
        "test_year",
        "task",
        "status",
        "n_train",
        "n_test",
        "positive_train",
        "positive_test",
    ]
    task_status_df = pd.DataFrame(task_status_rows, columns=status_columns)
    task_positive_counts = {
        task_name: int(pd.to_numeric(panel[meta["label"]], errors="coerce").fillna(0).sum())
        for task_name, meta in TASKS.items()
        if meta["label"] in panel.columns
    }
    zero_positive_tasks = [
        task_name for task_name, positive_count in task_positive_counts.items() if positive_count == 0
    ]
    empty_feature_family_blockers = [
        family
        for family in requested_families
        if family not in {"metadata", "all"} and feature_family_summary[family]["empty"]
    ]
    has_xbrl_ratio_features = feature_family_summary["xbrl"]["n_xbrl_ratio_features"] > 0
    if has_xbrl_ratio_features:
        cascade_readiness_level = "xbrl_ratio_baseline"
    else:
        cascade_readiness_level = "metadata_baseline"
    xbrl_aggregate_only_blocker = bool(
        feature_family_summary["xbrl"]["n_features"] > 0 and not has_xbrl_ratio_features
    )
    summary: Dict[str, object] = {
        "n_rows": int(len(panel)),
        "sample_years": [
            int(panel["fiscal_year"].min()),
            int(panel["fiscal_year"].max()),
        ]
        if not panel.empty
        else [],
        "domestic_only": bool(sample_cfg.get("domestic_only", True)),
        "task_positive_counts": task_positive_counts,
        "zero_positive_tasks": zero_positive_tasks,
        "feature_family_summary": feature_family_summary,
        "empty_feature_family_blockers": empty_feature_family_blockers,
        "has_xbrl_ratio_features": has_xbrl_ratio_features,
        "xbrl_aggregate_only_blocker": xbrl_aggregate_only_blocker,
        "cascade_readiness_level": cascade_readiness_level,
        "task_status_counts": {
            str(status): int(count)
            for status, count in task_status_df["status"].value_counts().items()
        }
        if not task_status_df.empty
        else {},
    }
    if not metrics_df.empty:
        ranking = (
            metrics_df.dropna(subset=["pr_auc"])
            .groupby(["feature_set", "train_window", "task"], as_index=False)["pr_auc"]
            .mean()
            .groupby(["feature_set", "train_window"], as_index=False)["pr_auc"]
            .mean()
            .sort_values("pr_auc", ascending=False)
        )
        if not ranking.empty:
            summary.update(
                {
                    "best_feature_set": str(ranking.iloc[0]["feature_set"]),
                    "best_train_window": str(ranking.iloc[0]["train_window"]),
                    "best_mean_pr_auc": float(ranking.iloc[0]["pr_auc"]),
                }
            )
        else:
            summary["ranking_status"] = "No non-degenerate test folds with positive labels."
    else:
        summary["ranking_status"] = "No model fits were produced."

    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "public_cascade_metrics.csv"
    predictions_path = out_dir / "public_cascade_predictions.csv.gz"
    task_status_path = out_dir / "public_cascade_task_status.csv"
    summary_path = out_dir / "public_cascade_summary.json"
    readiness_md = out_dir / "public_cascade_summary.md"

    metrics_df.to_csv(metrics_path, index=False)
    predictions_df.to_csv(predictions_path, index=False, compression="gzip")
    task_status_df.to_csv(task_status_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# Public Cascade Summary",
        "",
        f"- Rows in main sample: {len(panel):,}",
        f"- Fiscal-year span: {int(panel['fiscal_year'].min())} to {int(panel['fiscal_year'].max())}"
        if not panel.empty
        else "- Fiscal-year span: n/a",
        f"- Domestic US GAAP only: {bool(sample_cfg.get('domestic_only', True))}",
    ]
    if summary:
        lines.append(f"- Task positive counts: `{summary.get('task_positive_counts', {})}`")
        lines.append(f"- Zero-positive tasks: `{summary.get('zero_positive_tasks', [])}`")
        lines.append(f"- Task status counts: `{summary.get('task_status_counts', {})}`")
        lines.append(f"- Feature family summary: `{summary.get('feature_family_summary', {})}`")
        lines.append(
            f"- Empty feature-family blockers: "
            f"`{summary.get('empty_feature_family_blockers', [])}`"
        )
        lines.append(
            f"- XBRL aggregate-only blocker: "
            f"`{summary.get('xbrl_aggregate_only_blocker', False)}`"
        )
        lines.append(f"- Cascade readiness level: `{summary.get('cascade_readiness_level')}`")
        if "best_feature_set" in summary:
            lines.extend(
                [
                    f"- Best feature set: `{summary['best_feature_set']}`",
                    f"- Best train window: `{summary['best_train_window']}`",
                    f"- Best mean PR-AUC: {summary['best_mean_pr_auc']:.4f}",
                ]
            )
        if "ranking_status" in summary:
            lines.append(f"- Ranking status: {summary['ranking_status']}")
    readiness_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "metrics_csv": metrics_path,
        "predictions_csv": predictions_path,
        "task_status_csv": task_status_path,
        "summary_json": summary_path,
        "summary_md": readiness_md,
    }
