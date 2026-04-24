"""
Benchmark pipeline for drift-aware and lag-aware misstatement analysis.

This module implements the near-term empirical spine:

1. Build a firm-year master panel with leakage guards and label-timing metadata.
2. Run naive versus proxy-sensitivity rolling backtests across candidate training windows.
3. Diagnose drift via yearly metrics and feature-family importance stability.
4. Model strategic silence using missing-profile clustering and DML-style adjustment.
5. Emit decision-oriented summaries for retraining and top-K inspection policies.
"""

from __future__ import annotations

import gc
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from joblib import Parallel, delayed
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.mixture import GaussianMixture
from sklearn.model_selection import KFold
from xgboost import XGBClassifier

from . import SEED_DEFAULT
from .table_io import read_table, write_table

try:
    import yaml
except Exception as e:  # pragma: no cover - import guard mirrors the existing data_prep pattern
    raise RuntimeError("PyYAML is required: pip install pyyaml") from e


LEAKAGE_COLS_DEFAULT = ["res_an0", "res_an1", "res_an2", "res_an3"]
AUDIT_COLS = {
    "big4",
    "feeratio",
    "ranknon",
    "rankaud",
    "ranktot",
    "non_audit_fees",
    "audit_fees",
    "total_fee",
    "age",
    "audit_tenure",
    "going_concern",
    "auop",
    "auopic",
    "missing_AF",
    "missing_auopic",
    "missing_going_concern",
}
GOVERNANCE_COLS = {
    "Board_Inside",
    "Boardsize",
    "CCsize",
    "Insider_Chairman",
    "Lead_Director",
    "missing_Board",
    "missing_DD",
}
MARKET_COLS = {
    "ret_t",
    "ret_{t-1}",
    "bm",
    "ep",
    "disper",
    "spread",
    "vol",
    "short",
    "mf",
    "foreign",
    "missing_Rating",
}
ID_COLS = {"gvkey", "data_year"}


@dataclass(frozen=True)
class RollingResult:
    metrics: pd.DataFrame
    feature_importance: pd.DataFrame
    predictions: pd.DataFrame


def stable_task_seed(base_seed: int, *parts: object) -> int:
    key = "|".join([str(int(base_seed)), *(str(part) for part in parts)])
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=4).digest()
    return 1 + int.from_bytes(digest, byteorder="big") % (2**31 - 2)


def load_config(config_path: Path) -> Dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle)
    return cfg or {}


def _safe_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _build_detection_year_proxy(
    df: pd.DataFrame,
    *,
    year_col: str,
    target_col: str,
    leakage_cols: Sequence[str],
    unknown_positive_strategy: str,
) -> pd.DataFrame:
    df = df.copy()
    offsets = {}
    for col in leakage_cols:
        suffix = col.replace("res_an", "")
        if suffix.isdigit():
            offsets[col] = int(suffix)
    detection_offset = pd.Series(pd.NA, index=df.index, dtype="Int64")
    detection_source = pd.Series("none", index=df.index, dtype="object")

    for col, offset in offsets.items():
        if col not in df.columns:
            continue
        active = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int).eq(1)
        take = active & detection_offset.isna()
        detection_offset.loc[take] = offset
        detection_source.loc[take] = f"fallback_{col}"

    positive = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int).eq(1)
    unknown_positive = positive & detection_offset.isna()

    if unknown_positive_strategy not in {"current_year", "drop", "final_label"}:
        raise ValueError(
            "unknown_positive_strategy must be one of {'current_year','drop','final_label'}"
        )

    if unknown_positive_strategy == "current_year":
        detection_offset.loc[unknown_positive] = 0
        detection_source.loc[unknown_positive] = "fallback_current_year"
    elif unknown_positive_strategy == "final_label":
        detection_offset.loc[unknown_positive] = 0
        detection_source.loc[unknown_positive] = "fallback_final_label"
    else:
        detection_source.loc[unknown_positive] = "unknown_positive"

    year_values = pd.to_numeric(df[year_col], errors="coerce").astype("Int64")
    detection_year = year_values + detection_offset
    detection_year = detection_year.astype("Int64")

    df["detection_offset_proxy"] = detection_offset
    df["detection_year_proxy"] = detection_year
    df["detection_source"] = detection_source
    df["positive_without_proxy"] = unknown_positive.astype(int)
    return df


def _merge_external_timing(
    df: pd.DataFrame,
    timing_csv: Optional[Path],
    *,
    firm_col: str,
    year_col: str,
    target_col: str,
    detection_year_col: str,
    filing_date_col: Optional[str],
) -> pd.DataFrame:
    if timing_csv is None:
        return df

    timing_df = pd.read_csv(timing_csv)
    rename = {c: c.strip() for c in timing_df.columns}
    timing_df = timing_df.rename(columns=rename)

    if firm_col not in timing_df.columns or year_col not in timing_df.columns:
        raise ValueError(
            f"Expected external timing file to contain '{firm_col}' and '{year_col}' columns."
        )

    if detection_year_col not in timing_df.columns:
        if filing_date_col is None or filing_date_col not in timing_df.columns:
            raise ValueError(
                "External timing data must contain either detection_year_col or filing_date_col."
            )
        timing_df[detection_year_col] = pd.to_datetime(
            timing_df[filing_date_col], errors="coerce"
        ).dt.year.astype("Int64")
    else:
        timing_df[detection_year_col] = pd.to_numeric(
            timing_df[detection_year_col], errors="coerce"
        ).astype("Int64")

    keep_cols = [firm_col, year_col, detection_year_col]
    if filing_date_col and filing_date_col in timing_df.columns:
        keep_cols.append(filing_date_col)

    merged = df.merge(timing_df[keep_cols], on=[firm_col, year_col], how="left")
    external_hit = merged[detection_year_col].notna()
    merged.loc[external_hit, "detection_year_proxy"] = merged.loc[external_hit, detection_year_col]
    merged.loc[external_hit, "detection_source"] = "external_timing"
    merged.loc[external_hit, "positive_without_proxy"] = 0
    merged["detection_year_proxy"] = pd.to_numeric(
        merged["detection_year_proxy"], errors="coerce"
    ).astype("Int64")

    positive = pd.to_numeric(merged[target_col], errors="coerce").fillna(0).astype(int).eq(1)
    merged["positive_without_proxy"] = (positive & merged["detection_year_proxy"].isna()).astype(
        int
    )
    return merged


def build_timing_coverage_report(
    panel: pd.DataFrame,
    *,
    target_col: str,
    leakage_cols: Sequence[str],
) -> Tuple[pd.DataFrame, str]:
    target = pd.to_numeric(panel[target_col], errors="coerce").fillna(0).astype(int)
    positive = target.eq(1)
    timing_flags = pd.DataFrame(index=panel.index)
    for col in leakage_cols:
        if col in panel.columns:
            timing_flags[col] = pd.to_numeric(panel[col], errors="coerce").fillna(0).astype(int)
    any_same_row_proxy = (
        timing_flags.eq(1).any(axis=1)
        if not timing_flags.empty
        else pd.Series(False, index=panel.index)
    )
    positive_with_proxy = positive & panel["detection_year_proxy"].notna()
    positive_without_proxy = positive & panel["detection_year_proxy"].isna()
    external_positive = positive & panel["detection_source"].eq("external_timing")

    summary_rows: List[Dict[str, object]] = [
        {"section": "summary", "metric": "rows", "value": int(len(panel))},
        {"section": "summary", "metric": "positive_rows", "value": int(positive.sum())},
        {
            "section": "summary",
            "metric": "same_row_positive_with_any_res_an",
            "value": int((positive & any_same_row_proxy).sum()),
        },
        {
            "section": "summary",
            "metric": "same_row_positive_without_any_res_an",
            "value": int((positive & ~any_same_row_proxy).sum()),
        },
        {
            "section": "summary",
            "metric": "positive_with_detection_proxy",
            "value": int(positive_with_proxy.sum()),
        },
        {
            "section": "summary",
            "metric": "positive_without_detection_proxy",
            "value": int(positive_without_proxy.sum()),
        },
        {
            "section": "summary",
            "metric": "external_timing_positive_rows",
            "value": int(external_positive.sum()),
        },
    ]
    rows = [
        {
            "section": row["section"],
            "metric": row["metric"],
            "target_value": "",
            "flag_value": "",
            "count": "",
            "value": row["value"],
        }
        for row in summary_rows
    ]
    for col in leakage_cols:
        if col not in timing_flags.columns:
            rows.append(
                {
                    "section": "res_an_crosstab",
                    "metric": col,
                    "target_value": "",
                    "flag_value": "",
                    "count": "",
                    "value": "missing_column",
                }
            )
            continue
        flag = timing_flags[col]
        for target_value in (0, 1):
            for flag_value in (0, 1):
                rows.append(
                    {
                        "section": "res_an_crosstab",
                        "metric": col,
                        "target_value": target_value,
                        "flag_value": flag_value,
                        "count": int((target.eq(target_value) & flag.eq(flag_value)).sum()),
                        "value": "",
                    }
                )

    if int(external_positive.sum()) > 0 and int(positive_without_proxy.sum()) == 0:
        claim_status = "external_timing"
    elif int(positive_with_proxy.sum()) > 0:
        claim_status = "proxy_sensitivity"
    else:
        claim_status = "blocked"
    return pd.DataFrame(rows), claim_status


def infer_feature_family(column: str) -> str:
    if column in LEAKAGE_COLS_DEFAULT:
        return "timing_proxy"
    if column.startswith("raw_missing_") or column.startswith("missing_"):
        return "missingness"
    if column.startswith("ind"):
        suffix = column.replace("ind", "")
        if suffix.isdigit():
            return "industry"
    if column in AUDIT_COLS:
        return "audit"
    if column in GOVERNANCE_COLS:
        return "governance"
    if column in MARKET_COLS:
        return "market"
    if column in ID_COLS or column in {"misstatement firm-year"}:
        return "id"
    return "accounting"


def load_master_panel(
    raw_csv: Path,
    *,
    firm_col: str,
    year_col: str,
    target_col: str,
    leakage_cols: Sequence[str],
    raw_missing_threshold: float,
    unknown_positive_strategy: str,
    timing_csv: Optional[Path],
    detection_year_col: str,
    filing_date_col: Optional[str],
) -> pd.DataFrame:
    df = read_table(raw_csv, low_memory=False)
    df[firm_col] = df[firm_col].astype(str)
    df[year_col] = pd.to_numeric(df[year_col], errors="coerce").astype("Int64")
    df[target_col] = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)

    exclude = {firm_col, year_col, target_col, *leakage_cols}
    raw_missing_cols = [
        col
        for col, ratio in df.isna().mean().items()
        if col not in exclude and ratio >= raw_missing_threshold
    ]
    for col in raw_missing_cols:
        df[f"raw_missing_{col}"] = df[col].isna().astype(int)

    missing_cols = [
        col for col in df.columns if col.startswith("missing_") or col.startswith("raw_missing_")
    ]
    df["missing_profile_width"] = df[missing_cols].sum(axis=1)
    df["missing_profile_rate"] = df["missing_profile_width"] / max(len(missing_cols), 1)

    df = _build_detection_year_proxy(
        df,
        year_col=year_col,
        target_col=target_col,
        leakage_cols=leakage_cols,
        unknown_positive_strategy=unknown_positive_strategy,
    )
    df = _merge_external_timing(
        df,
        timing_csv=timing_csv,
        firm_col=firm_col,
        year_col=year_col,
        target_col=target_col,
        detection_year_col=detection_year_col,
        filing_date_col=filing_date_col,
    )

    return df.sort_values([year_col, firm_col]).reset_index(drop=True)


def summarize_panel(
    panel: pd.DataFrame,
    *,
    firm_col: str,
    year_col: str,
    target_col: str,
    leakage_cols: Sequence[str],
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    year_summary = (
        panel.groupby(year_col)[target_col]
        .agg(["sum", "count", "mean"])
        .rename(columns={"sum": "positives", "count": "firm_years", "mean": "positive_rate"})
        .reset_index()
    )
    year_summary["positive_rate"] = year_summary["positive_rate"].round(6)
    timing_coverage, timing_claim_status = build_timing_coverage_report(
        panel, target_col=target_col, leakage_cols=leakage_cols
    )
    summary_metrics = timing_coverage.loc[timing_coverage["section"].eq("summary")]
    summary_values = {
        str(row["metric"]): int(row["value"])
        for _, row in summary_metrics.iterrows()
        if str(row["value"]).isdigit()
    }
    timing_summary = {
        "rows": int(len(panel)),
        "firms": int(panel[firm_col].nunique()),
        "years": [int(panel[year_col].min()), int(panel[year_col].max())],
        "positive_rate": float(panel[target_col].mean()),
        "detection_source_counts": panel["detection_source"].value_counts(dropna=False).to_dict(),
        "positive_without_proxy": int(panel["positive_without_proxy"].sum()),
        "timing_claim_status": timing_claim_status,
        "same_row_positive_with_any_res_an": summary_values.get(
            "same_row_positive_with_any_res_an", 0
        ),
        "same_row_positive_without_any_res_an": summary_values.get(
            "same_row_positive_without_any_res_an", 0
        ),
        "raw_missing_columns": sorted([c for c in panel.columns if c.startswith("raw_missing_")]),
    }
    return year_summary, timing_summary, timing_coverage


def get_feature_columns(
    panel: pd.DataFrame,
    *,
    firm_col: str,
    year_col: str,
    target_col: str,
    leakage_cols: Sequence[str],
) -> List[str]:
    drop_cols = {
        firm_col,
        year_col,
        target_col,
        *leakage_cols,
        "detection_offset_proxy",
        "detection_year_proxy",
        "detection_source",
        "positive_without_proxy",
    }
    feature_cols = [col for col in panel.columns if col not in drop_cols]
    keep = []
    for col in feature_cols:
        series = pd.to_numeric(panel[col], errors="coerce")
        if series.notna().any():
            keep.append(col)
    return keep


def _prepare_xy(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    *,
    feature_cols: Sequence[str],
    target_col: str,
    train_origin_year: int,
    label_mode: str,
    unknown_positive_strategy: str,
) -> Tuple[pd.DataFrame, np.ndarray, pd.DataFrame, np.ndarray]:
    y_train = train_df[target_col].astype(int).copy()

    if label_mode in {"matured", "proxy_sensitivity"}:
        detection_year = pd.to_numeric(train_df["detection_year_proxy"], errors="coerce")
        future_positive = (
            y_train.eq(1)
            & train_df["detection_year_proxy"].notna()
            & (detection_year > train_origin_year)
        )
        y_train.loc[future_positive] = 0
        if unknown_positive_strategy == "drop":
            drop_mask = y_train.eq(1) & train_df["detection_year_proxy"].isna()
            train_df = train_df.loc[~drop_mask].copy()
            y_train = y_train.loc[train_df.index]
    elif label_mode != "naive":
        raise ValueError("label_mode must be 'naive', 'proxy_sensitivity', or 'matured'")

    X_train = train_df[list(feature_cols)].apply(pd.to_numeric, errors="coerce")
    X_test = test_df[list(feature_cols)].apply(pd.to_numeric, errors="coerce")
    X_train = X_train.replace([np.inf, -np.inf], np.nan).clip(lower=-1e12, upper=1e12)
    X_test = X_test.replace([np.inf, -np.inf], np.nan).clip(lower=-1e12, upper=1e12)

    valid_cols = [
        col
        for col in X_train.columns
        if X_train[col].notna().any() and X_train[col].nunique(dropna=True) > 1
    ]
    X_train = X_train[valid_cols]
    X_test = X_test[valid_cols]
    y_test = test_df[target_col].astype(int).to_numpy()
    return X_train, y_train.to_numpy(), X_test, y_test


def fit_xgb_classifier(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    *,
    seed: int,
    model_cfg: Dict[str, Any],
) -> XGBClassifier:
    positives = max(int(y_train.sum()), 1)
    negatives = max(int(len(y_train) - positives), 1)
    scale_pos_weight = negatives / positives
    params = {
        "n_estimators": int(model_cfg.get("n_estimators", 250)),
        "max_depth": int(model_cfg.get("max_depth", 4)),
        "learning_rate": float(model_cfg.get("learning_rate", 0.05)),
        "subsample": float(model_cfg.get("subsample", 0.8)),
        "colsample_bytree": float(model_cfg.get("colsample_bytree", 0.8)),
        "min_child_weight": float(model_cfg.get("min_child_weight", 5.0)),
        "reg_lambda": float(model_cfg.get("reg_lambda", 1.0)),
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "scale_pos_weight": float(model_cfg.get("scale_pos_weight", scale_pos_weight)),
        "random_state": seed,
        "n_jobs": int(model_cfg.get("n_jobs", -1)),
        "tree_method": model_cfg.get("tree_method", "hist"),
        "missing": np.nan,
    }
    model = XGBClassifier(**params)
    model.fit(X_train, y_train)
    return model


def expected_calibration_error(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    *,
    n_bins: int = 10,
) -> float:
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bucket = np.digitize(y_prob, bins=bins[1:-1], right=False)
    ece = 0.0
    for b in range(n_bins):
        mask = bucket == b
        if not np.any(mask):
            continue
        obs = y_true[mask].mean()
        pred = y_prob[mask].mean()
        ece += np.abs(obs - pred) * mask.mean()
    return float(ece)


def compute_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    *,
    top_k: Sequence[int],
) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "pr_auc": float(average_precision_score(y_true, y_prob)),
        "brier": float(brier_score_loss(y_true, y_prob)),
        "ece": expected_calibration_error(y_true, y_prob),
        "pos_rate": float(np.mean(y_true)),
        "n_obs": int(len(y_true)),
    }
    if len(np.unique(y_true)) > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))
    else:
        metrics["roc_auc"] = float("nan")

    ranked = np.argsort(-y_prob)
    for k in top_k:
        k_eff = min(int(k), len(y_true))
        if k_eff <= 0:
            continue
        selected = ranked[:k_eff]
        sel_true = y_true[selected]
        metrics[f"top_{k}_precision"] = float(sel_true.mean())
        metrics[f"top_{k}_recall"] = float(sel_true.sum() / max(y_true.sum(), 1))
    threshold = np.quantile(y_prob, 0.9) if len(y_prob) else 0.5
    pred_label = (y_prob >= threshold).astype(int)
    metrics["top_decile_threshold"] = float(threshold)
    metrics["top_decile_precision"] = float(precision_score(y_true, pred_label, zero_division=0))
    metrics["top_decile_recall"] = float(recall_score(y_true, pred_label, zero_division=0))
    return metrics


def _run_rolling_task(
    *,
    panel: pd.DataFrame,
    task_order: int,
    train_window: Optional[int],
    test_year: int,
    label_mode: str,
    firm_col: str,
    year_col: str,
    target_col: str,
    feature_cols: Sequence[str],
    min_train_years: int,
    top_k: Sequence[int],
    unknown_positive_strategy: str,
    model_cfg: Dict[str, Any],
    seed: int,
    seed_policy: str,
) -> Optional[Dict[str, object]]:
    window_label = "expanding" if train_window is None else f"rolling_{int(train_window)}y"
    year_values = panel[year_col].astype(int)
    if train_window is None:
        train_mask = year_values < int(test_year)
    else:
        start_year = int(test_year) - int(train_window)
        train_mask = year_values.between(start_year, int(test_year) - 1)
    test_mask = year_values.eq(int(test_year))

    train_df = panel.loc[train_mask].copy()
    test_df = panel.loc[test_mask].copy()
    if train_df[year_col].nunique() < min_train_years or test_df.empty:
        return None

    X_train, y_train, X_test, y_test = _prepare_xy(
        train_df,
        test_df,
        feature_cols=feature_cols,
        target_col=target_col,
        train_origin_year=int(test_year) - 1,
        label_mode=label_mode,
        unknown_positive_strategy=unknown_positive_strategy,
    )
    if len(np.unique(y_train)) < 2 or X_train.empty:
        return None

    if seed_policy == "task_isolated":
        task_seed = stable_task_seed(seed, "benchmark", window_label, test_year, label_mode)
    elif seed_policy == "legacy":
        task_seed = int(seed) + int(test_year)
    else:
        raise ValueError("seed_policy must be 'task_isolated' or 'legacy'")

    model = fit_xgb_classifier(X_train, y_train, seed=task_seed, model_cfg=model_cfg)
    y_prob = model.predict_proba(X_test)[:, 1]

    metric_row = {
        "_task_order": int(task_order),
        "window": window_label,
        "label_mode": label_mode,
        "test_year": int(test_year),
        "train_start_year": int(train_df[year_col].min()),
        "train_end_year": int(train_df[year_col].max()),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "train_positive_rate": float(np.mean(y_train)),
    }
    metric_row.update(compute_metrics(y_test, y_prob, top_k=top_k))

    importance_rows: List[Dict[str, Any]] = []
    importance = model.feature_importances_
    imp_total = float(np.sum(importance)) or 1.0
    for col, imp in zip(X_train.columns, importance, strict=False):
        importance_rows.append(
            {
                "_task_order": int(task_order),
                "window": window_label,
                "label_mode": label_mode,
                "test_year": int(test_year),
                "feature": col,
                "importance": float(imp),
                "importance_share": float(imp / imp_total),
                "family": infer_feature_family(col),
            }
        )

    pred_df = test_df[[firm_col, year_col, target_col, "detection_year_proxy"]].copy()
    pred_df["_task_order"] = int(task_order)
    pred_df["_row_order"] = pred_df.index.to_numpy()
    pred_df["window"] = window_label
    pred_df["label_mode"] = label_mode
    pred_df["pred_prob"] = y_prob

    del model, X_train, X_test, y_train, y_test, y_prob, train_df, test_df
    gc.collect()
    return {"metric": metric_row, "importance": importance_rows, "predictions": pred_df}


def _run_rolling_task_batch(
    *,
    panel: pd.DataFrame,
    tasks: Sequence[Tuple[int, Optional[int], int, str]],
    firm_col: str,
    year_col: str,
    target_col: str,
    feature_cols: Sequence[str],
    min_train_years: int,
    top_k: Sequence[int],
    unknown_positive_strategy: str,
    model_cfg: Dict[str, Any],
    seed: int,
    seed_policy: str,
) -> List[Optional[Dict[str, object]]]:
    return [
        _run_rolling_task(
            panel=panel,
            task_order=order,
            train_window=train_window,
            test_year=test_year,
            label_mode=label_mode,
            firm_col=firm_col,
            year_col=year_col,
            target_col=target_col,
            feature_cols=feature_cols,
            min_train_years=min_train_years,
            top_k=top_k,
            unknown_positive_strategy=unknown_positive_strategy,
            model_cfg=model_cfg,
            seed=seed,
            seed_policy=seed_policy,
        )
        for order, train_window, test_year, label_mode in tasks
    ]


def run_rolling_backtest(
    panel: pd.DataFrame,
    *,
    firm_col: str,
    year_col: str,
    target_col: str,
    feature_cols: Sequence[str],
    label_modes: Sequence[str],
    candidate_windows: Sequence[Optional[int]],
    min_train_years: int,
    top_k: Sequence[int],
    unknown_positive_strategy: str,
    model_cfg: Dict[str, Any],
    seed: int,
    parallel_jobs: int = 1,
    seed_policy: str = "legacy",
) -> RollingResult:
    metrics_rows: List[Dict[str, Any]] = []
    importance_rows: List[Dict[str, Any]] = []
    prediction_rows: List[pd.DataFrame] = []

    years = sorted(pd.to_numeric(panel[year_col], errors="coerce").dropna().astype(int).unique())
    if len(years) <= min_train_years:
        raise ValueError("Not enough years to run rolling backtests.")

    if seed_policy not in {"task_isolated", "legacy"}:
        raise ValueError("seed_policy must be 'task_isolated' or 'legacy'")

    tasks: List[Tuple[int, Optional[int], int, str]] = []
    task_order = 0
    for train_window in candidate_windows:
        for test_year in years[min_train_years:]:
            for label_mode in label_modes:
                tasks.append((task_order, train_window, int(test_year), str(label_mode)))
                task_order += 1

    parallel_jobs = max(1, int(parallel_jobs))
    task_batches: List[List[Tuple[int, Optional[int], int, str]]] = []
    for train_window in candidate_windows:
        for test_year in years[min_train_years:]:
            task_batches.append(
                [
                    task
                    for task in tasks
                    if task[1] == train_window and task[2] == int(test_year)
                ]
            )

    if parallel_jobs == 1:
        batched_results = [
            _run_rolling_task_batch(
                panel=panel,
                tasks=batch,
                firm_col=firm_col,
                year_col=year_col,
                target_col=target_col,
                feature_cols=feature_cols,
                min_train_years=min_train_years,
                top_k=top_k,
                unknown_positive_strategy=unknown_positive_strategy,
                model_cfg=model_cfg,
                seed=seed,
                seed_policy=seed_policy,
            )
            for batch in task_batches
        ]
    else:
        batched_results = Parallel(n_jobs=parallel_jobs, prefer="processes")(
            delayed(_run_rolling_task_batch)(
                panel=panel,
                tasks=batch,
                firm_col=firm_col,
                year_col=year_col,
                target_col=target_col,
                feature_cols=feature_cols,
                min_train_years=min_train_years,
                top_k=top_k,
                unknown_positive_strategy=unknown_positive_strategy,
                model_cfg=model_cfg,
                seed=seed,
                seed_policy=seed_policy,
            )
            for batch in task_batches
        )
    results = [result for batch in batched_results for result in batch]

    for result in results:
        if result is None:
            continue
        metrics_rows.append(result["metric"])
        importance_rows.extend(result["importance"])
        prediction_rows.append(result["predictions"])

    metrics_df = pd.DataFrame(metrics_rows)
    if not metrics_df.empty and "_task_order" in metrics_df.columns:
        metrics_df = metrics_df.sort_values("_task_order").drop(columns=["_task_order"])
    importance_df = pd.DataFrame(importance_rows)
    if importance_df.empty:
        family_importance = importance_df
    else:
        family_importance = (
            importance_df.groupby(
                ["_task_order", "window", "label_mode", "test_year", "family"], as_index=False
            )["importance_share"]
            .sum()
            .sort_values(["_task_order", "family"])
            .drop(columns=["_task_order"])
        )
    predictions_df = (
        pd.concat(prediction_rows, ignore_index=True) if prediction_rows else pd.DataFrame()
    )
    if not predictions_df.empty:
        predictions_df = predictions_df.sort_values(["_task_order", "_row_order"]).drop(
            columns=["_task_order", "_row_order"]
        )
    return RollingResult(
        metrics=metrics_df,
        feature_importance=family_importance,
        predictions=predictions_df,
    )


def compute_window_summary(metrics_df: pd.DataFrame) -> pd.DataFrame:
    if metrics_df.empty:
        return pd.DataFrame()
    agg_cols = ["pr_auc", "brier", "ece", "top_decile_precision", "top_decile_recall"]
    top_k_cols = [
        col for col in metrics_df.columns if col.startswith("top_") and col.endswith("_precision")
    ]
    agg_cols.extend([col for col in top_k_cols if col not in agg_cols])
    summary = (
        metrics_df.groupby(["window", "label_mode"], as_index=False)[agg_cols]
        .mean(numeric_only=True)
        .sort_values(["label_mode", "pr_auc"], ascending=[True, False])
    )
    return summary


def compute_structural_breaks(
    family_importance_df: pd.DataFrame,
    *,
    break_years: Sequence[int],
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    if family_importance_df.empty:
        return pd.DataFrame(rows)

    for (window, label_mode, family), subdf in family_importance_df.groupby(
        ["window", "label_mode", "family"]
    ):
        subdf = subdf.sort_values("test_year").copy()
        if subdf["test_year"].nunique() < 6:
            continue
        for breakpoint in break_years:
            work = subdf.copy()
            work["post_break"] = (work["test_year"] >= breakpoint).astype(int)
            work["year_centered"] = work["test_year"] - work["test_year"].mean()
            work["interaction"] = work["post_break"] * work["year_centered"]
            X = sm.add_constant(work[["year_centered", "post_break", "interaction"]])
            y = work["importance_share"]
            fitted = sm.OLS(y, X).fit()
            test = fitted.f_test("post_break = 0, interaction = 0")
            rows.append(
                {
                    "window": window,
                    "label_mode": label_mode,
                    "family": family,
                    "break_year": int(breakpoint),
                    "f_stat": float(np.squeeze(test.fvalue)),
                    "p_value": float(np.squeeze(test.pvalue)),
                    "n_years": int(work["test_year"].nunique()),
                }
            )
    return pd.DataFrame(rows)


def fit_missing_profile_model(
    panel: pd.DataFrame,
    *,
    target_col: str,
    k_values: Sequence[int],
    seed: int,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    feature_cols = [
        col
        for col in panel.columns
        if col.startswith("missing_") or col.startswith("raw_missing_")
    ]
    if not feature_cols:
        raise ValueError("No missing-profile columns were found.")

    X = panel[feature_cols].fillna(0).astype(float).to_numpy()
    best_model: Optional[GaussianMixture] = None
    best_bic = float("inf")
    best_k = None

    for k in k_values:
        model = GaussianMixture(
            n_components=int(k),
            covariance_type="diag",
            random_state=seed,
            n_init=5,
        )
        model.fit(X)
        bic = model.bic(X)
        if bic < best_bic:
            best_bic = bic
            best_model = model
            best_k = int(k)

    assert best_model is not None and best_k is not None
    cluster = best_model.predict(X)
    panel_with_cluster = panel.copy()
    panel_with_cluster["missing_profile_cluster"] = cluster

    cluster_summary = (
        panel_with_cluster.groupby("missing_profile_cluster")
        .agg(
            n_obs=(target_col, "size"),
            misstatement_rate=(target_col, "mean"),
            avg_missing_width=("missing_profile_width", "mean"),
            avg_missing_rate=("missing_profile_rate", "mean"),
        )
        .reset_index()
        .sort_values("avg_missing_rate", ascending=False)
    )
    opaque_cluster = int(cluster_summary.iloc[0]["missing_profile_cluster"])
    panel_with_cluster["opaque_cluster"] = (
        panel_with_cluster["missing_profile_cluster"].eq(opaque_cluster).astype(int)
    )
    density = pd.to_numeric(panel_with_cluster["missing_profile_rate"], errors="coerce")
    density_std = float(density.std(ddof=0))
    if density_std > 0:
        panel_with_cluster["missingness_density_score"] = (
            density - float(density.mean())
        ) / density_std
    else:
        panel_with_cluster["missingness_density_score"] = 0.0

    model_meta = {
        "best_k": best_k,
        "best_bic": float(best_bic),
        "feature_columns": feature_cols,
        "opaque_cluster": opaque_cluster,
    }
    return panel_with_cluster, cluster_summary, model_meta


def fit_dml_adjustment(
    panel: pd.DataFrame,
    *,
    target_col: str,
    treatment_col: str,
    feature_cols: Sequence[str],
    seed: int,
    n_splits: int = 5,
) -> Dict[str, Any]:
    controls = [
        col
        for col in feature_cols
        if not col.startswith("missing_")
        and not col.startswith("raw_missing_")
        and col
        not in {
            "missing_profile_width",
            "missing_profile_rate",
            "missingness_density_score",
            treatment_col,
        }
    ]
    work = panel[controls + [target_col, treatment_col]].copy()
    work = work.dropna(subset=[target_col, treatment_col])
    X = work[controls].apply(pd.to_numeric, errors="coerce")
    X = X.replace([np.inf, -np.inf], np.nan).clip(lower=-1e12, upper=1e12)
    y = work[target_col].astype(int).to_numpy()
    t = pd.to_numeric(work[treatment_col], errors="coerce").to_numpy(dtype=float)

    imputer = SimpleImputer(strategy="median")
    X_imp = imputer.fit_transform(X)

    y_hat = np.zeros(len(work))
    t_hat = np.zeros(len(work))
    splitter = KFold(n_splits=n_splits, shuffle=True, random_state=seed)

    for fold, (train_idx, test_idx) in enumerate(splitter.split(X_imp), start=1):
        if len(np.unique(y[train_idx])) < 2:
            y_hat[test_idx] = float(np.mean(y[train_idx]))
        else:
            y_model = HistGradientBoostingClassifier(random_state=seed + fold)
            y_model.fit(X_imp[train_idx], y[train_idx])
            y_hat[test_idx] = y_model.predict_proba(X_imp[test_idx])[:, 1]
        if np.nanstd(t[train_idx]) == 0:
            t_hat[test_idx] = float(np.mean(t[train_idx]))
        else:
            t_model = HistGradientBoostingRegressor(random_state=seed + 100 + fold)
            t_model.fit(X_imp[train_idx], t[train_idx])
            t_hat[test_idx] = t_model.predict(X_imp[test_idx])

    y_res = y - y_hat
    t_res = t - t_hat
    fitted = sm.OLS(y_res, sm.add_constant(t_res)).fit(cov_type="HC3")
    coef = float(fitted.params[1])
    se = float(fitted.bse[1])
    p_value = float(fitted.pvalues[1])

    return {
        "n_obs": int(len(work)),
        "treatment": treatment_col,
        "outcome": target_col,
        "treatment_kind": "continuous",
        "coef": coef,
        "std_err": se,
        "p_value": p_value,
        "controls": controls,
        "mean_treatment": float(np.mean(t)),
        "mean_outcome": float(np.mean(y)),
    }


def build_recommendation(
    window_summary: pd.DataFrame,
    *,
    focus_label_mode: str,
) -> Dict[str, Any]:
    if window_summary.empty:
        return {}
    focus = window_summary.loc[window_summary["label_mode"].eq(focus_label_mode)].copy()
    if focus.empty:
        focus = window_summary.copy()
    sort_cols = ["pr_auc"]
    ascending = [False]
    if "top_100_precision" in focus.columns:
        sort_cols.append("top_100_precision")
        ascending.append(False)
    focus = focus.sort_values(sort_cols, ascending=ascending)
    best = focus.iloc[0].to_dict()
    return {
        "recommended_window": best["window"],
        "label_mode": best["label_mode"],
        "decision_metric": {
            "pr_auc": float(best.get("pr_auc", np.nan)),
            "top_100_precision": float(best.get("top_100_precision", np.nan)),
            "brier": float(best.get("brier", np.nan)),
        },
    }


def render_summary_markdown(
    *,
    timing_summary: Dict[str, Any],
    window_summary: pd.DataFrame,
    cluster_summary: pd.DataFrame,
    dml_result: Dict[str, Any],
    recommendation: Dict[str, Any],
) -> str:
    lines = [
        "# Benchmark Summary",
        "",
        "## Panel",
        f"- Rows: {timing_summary['rows']:,}",
        f"- Firms: {timing_summary['firms']:,}",
        f"- Years: {timing_summary['years'][0]}-{timing_summary['years'][1]}",
        f"- Positive rate: {timing_summary['positive_rate']:.4f}",
        f"- Positive rows without timing proxy: {timing_summary['positive_without_proxy']:,}",
        f"- Timing claim status: `{timing_summary['timing_claim_status']}`",
        "",
        "## Timing Coverage",
        f"- Detection sources: `{_safe_json(timing_summary['detection_source_counts'])}`",
        "- The proxy-visible benchmark is a timing-sensitivity diagnostic, not a "
        "paper-grade label-maturation result unless external timing is available.",
        f"- Same-row positive rows with any `res_an*`: "
        f"{timing_summary['same_row_positive_with_any_res_an']:,}",
        f"- Same-row positive rows without any `res_an*`: "
        f"{timing_summary['same_row_positive_without_any_res_an']:,}",
        "",
        "## Rolling Backtests",
    ]
    if window_summary.empty:
        lines.append("- No rolling metrics were produced.")
    else:
        for _, row in window_summary.iterrows():
            lines.append(
                f"- {row['label_mode']} | {row['window']} | PR-AUC={row['pr_auc']:.4f} | "
                f"Brier={row['brier']:.4f} | Top-100 precision={row.get('top_100_precision', np.nan):.4f}"
            )
    lines.extend(["", "## Missing-Profile Clusters"])
    if cluster_summary.empty:
        lines.append("- No missing-profile clusters were produced.")
    else:
        for _, row in cluster_summary.iterrows():
            lines.append(
                f"- Cluster {int(row['missing_profile_cluster'])}: n={int(row['n_obs'])}, "
                f"misstatement_rate={row['misstatement_rate']:.4f}, "
                f"avg_missing_rate={row['avg_missing_rate']:.4f}"
            )
    lines.extend(["", "## DML-Style Adjustment"])
    if dml_result:
        lines.append(
            f"- {dml_result['treatment']} effect: coef={dml_result['coef']:.4f}, "
            f"SE={dml_result['std_err']:.4f}, p={dml_result['p_value']:.4f}"
        )
    else:
        lines.append("- DML result unavailable.")
    lines.extend(["", "## Recommendation"])
    if recommendation:
        lines.append(
            f"- Recommended retraining window: `{recommendation['recommended_window']}` "
            f"under `{recommendation['label_mode']}` evaluation."
        )
    else:
        lines.append("- No recommendation generated.")
    lines.append("")
    return "\n".join(lines)


def run_benchmark(
    *,
    config_path: Path,
    raw_csv: Path,
    out_dir: Path,
    timing_csv: Optional[Path] = None,
    parallel_jobs: Optional[int] = None,
    model_threads: Optional[int] = None,
    seed_policy: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_config(config_path)
    columns = cfg.get("columns", {})
    analysis = cfg.get("analysis", {})

    firm_col = columns.get("firm_col", "gvkey")
    year_col = columns.get("year_col", "data_year")
    target_col = columns.get("target", "misstatement firm-year")
    leakage_cols = columns.get("leakage_cols", LEAKAGE_COLS_DEFAULT)

    out_dir.mkdir(parents=True, exist_ok=True)

    panel = load_master_panel(
        raw_csv,
        firm_col=firm_col,
        year_col=year_col,
        target_col=target_col,
        leakage_cols=leakage_cols,
        raw_missing_threshold=float(analysis.get("raw_missing_threshold", 0.30)),
        unknown_positive_strategy=analysis.get("unknown_positive_strategy", "drop"),
        timing_csv=timing_csv,
        detection_year_col=columns.get("external_detection_year_col", "detection_year"),
        filing_date_col=columns.get("external_filing_date_col"),
    )
    year_summary, timing_summary, timing_coverage = summarize_panel(
        panel,
        firm_col=firm_col,
        year_col=year_col,
        target_col=target_col,
        leakage_cols=leakage_cols,
    )
    feature_cols = get_feature_columns(
        panel,
        firm_col=firm_col,
        year_col=year_col,
        target_col=target_col,
        leakage_cols=leakage_cols,
    )
    model_cfg = dict(analysis.get("xgb", {}))
    if model_threads is not None:
        model_cfg["n_jobs"] = int(model_threads)

    rolling = run_rolling_backtest(
        panel,
        firm_col=firm_col,
        year_col=year_col,
        target_col=target_col,
        feature_cols=feature_cols,
        label_modes=analysis.get("label_modes", ["naive", "proxy_sensitivity"]),
        candidate_windows=analysis.get("candidate_train_windows", [None, 5, 7, 10]),
        min_train_years=int(analysis.get("min_train_years", 5)),
        top_k=analysis.get("top_k", [50, 100, 200, 500]),
        unknown_positive_strategy=analysis.get("unknown_positive_strategy", "drop"),
        model_cfg=model_cfg,
        seed=int(analysis.get("seed", SEED_DEFAULT)),
        parallel_jobs=int(parallel_jobs or analysis.get("parallel_jobs", 1)),
        seed_policy=str(seed_policy or analysis.get("seed_policy", "legacy")),
    )
    window_summary = compute_window_summary(rolling.metrics)
    structural_breaks = compute_structural_breaks(
        rolling.feature_importance,
        break_years=analysis.get("break_years", [2005, 2010, 2017]),
    )

    panel_with_cluster, cluster_summary, cluster_meta = fit_missing_profile_model(
        panel,
        target_col=target_col,
        k_values=analysis.get("mixture_k_values", [3, 4, 5]),
        seed=int(analysis.get("seed", SEED_DEFAULT)),
    )
    dml_result = fit_dml_adjustment(
        panel_with_cluster,
        target_col=target_col,
        treatment_col=analysis.get("dml_treatment_col", "missingness_density_score"),
        feature_cols=feature_cols + ["missingness_density_score"],
        seed=int(analysis.get("seed", SEED_DEFAULT)),
        n_splits=int(analysis.get("dml_folds", 5)),
    )
    recommendation = build_recommendation(
        window_summary,
        focus_label_mode=analysis.get("recommendation_label_mode", "proxy_sensitivity"),
    )

    panel_path = out_dir / "master_panel.parquet"
    write_table(panel_with_cluster, panel_path)
    year_summary.to_csv(out_dir / "year_summary.csv", index=False)
    timing_coverage.to_csv(out_dir / "timing_coverage.csv", index=False)
    rolling.metrics.to_csv(out_dir / "rolling_metrics.csv", index=False)
    rolling.feature_importance.to_csv(out_dir / "feature_family_importance.csv", index=False)
    write_table(rolling.predictions, out_dir / "rolling_predictions.parquet")
    window_summary.to_csv(out_dir / "window_summary.csv", index=False)
    structural_breaks.to_csv(out_dir / "structural_breaks.csv", index=False)
    cluster_summary.to_csv(out_dir / "missing_profile_clusters.csv", index=False)
    (out_dir / "timing_summary.json").write_text(json.dumps(timing_summary, indent=2))
    (out_dir / "cluster_meta.json").write_text(json.dumps(cluster_meta, indent=2))
    (out_dir / "dml_result.json").write_text(json.dumps(dml_result, indent=2))
    (out_dir / "recommendation.json").write_text(json.dumps(recommendation, indent=2))
    summary_md = render_summary_markdown(
        timing_summary=timing_summary,
        window_summary=window_summary,
        cluster_summary=cluster_summary,
        dml_result=dml_result,
        recommendation=recommendation,
    )
    (out_dir / "benchmark_summary.md").write_text(summary_md, encoding="utf-8")

    print("=== BENCHMARK ===")
    print(f"Master panel: {panel_path}")
    print(f"Rolling metrics rows: {len(rolling.metrics):,}")
    print(f"Best retraining window: {recommendation.get('recommended_window', 'n/a')}")
    print(summary_md)

    return {
        "timing_summary": timing_summary,
        "timing_coverage_csv": out_dir / "timing_coverage.csv",
        "recommendation": recommendation,
        "dml_result": dml_result,
        "cluster_meta": cluster_meta,
    }
