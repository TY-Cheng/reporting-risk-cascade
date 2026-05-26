"""Public-label peer-compatible model-family transfer.

This module transfers detected-misstatement peer benchmark language to
filing-origin public review-and-correction labels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from . import SEED_DEFAULT
from .benchmark import compute_metrics
from .peer_comparison import (
    BAO_VARIABLES,
    DECHOW_MODEL1_COEFFICIENTS,
    DECHOW_VARIABLES,
    LITERATURE_ANCHORS,
    MAPPING_QUALITY_VALUES,
    _apply_undersample_equal,
    _as_float_frame,
    _dechow_fixed_predict,
    _fit_peer_model,
    _git_text,
    _mapping_attrition_rate,
    _mapped_columns,
    _model_specs,
    _predict_model,
    _window_label,
    aggregate_mapping_quality,
    validate_parallel_budget,
)
from .public_cascade import (
    TASKS,
    _filter_main_sample,
    _infer_feature_families,
    _rolling_year_pairs,
    _sort_panel_for_model,
    _task_exclusion_mask,
    stable_task_seed,
)
from .ranking_metrics import BAO_TOP_FRACTIONS
from .table_io import read_table, write_table


SCHEMA_VERSION = "public-peer-comparison-pr2-v1"
SPEC_VERSION = "2026-04-26-pr2-public-label-peer-transfer"
PUBLIC_FEATURE_SETS = ["metadata", "xbrl", "auditor", "oversight", "all"]
HEADLINE_TASKS = ["comment_thread", "amendment", "8k_402"]
SEVERITY_TAIL_TASKS: list[str] = []
PUBLIC_INPUT_KIND = "public_issuer_origin"
PUBLIC_DECHOW_PROXY_MODEL_ID = "dechow_public_xbrl_proxy_logit"
PUBLIC_DECHOW_PROXY_FEATURE_SET = "xbrl_proxy"

PUBLIC_MAPPING_COLUMNS = [
    "peer_model_id",
    "peer",
    "source_variable",
    "repo_column",
    "mapping_status",
    "mapping_type",
    "coverage_rate",
    "sign_convention_match",
    "construction_match",
    "scale_match",
    "proxy_source",
    "notes",
]
PUBLIC_STATUS_COLUMNS = [
    "task_space",
    "peer_model_id",
    "task",
    "feature_set",
    "test_year",
    "train_window",
    "status",
    "reason_code",
    "n_train",
    "n_test",
    "pos_train",
    "pos_test",
    "mapping_quality",
    "imbalance_strategy",
]
PUBLIC_PREDICTION_COLUMNS = [
    "issuer_cik",
    "fiscal_year",
    "origin_date",
    "task",
    "feature_set",
    "test_year",
    "train_window",
    "peer_model_id",
    "predicted_prob",
    "observed_label",
]
PUBLIC_IMPORTANCE_COLUMNS = [
    "peer_model_id",
    "task",
    "feature_set",
    "test_year",
    "train_window",
    "feature_name",
    "feature_group",
    "importance_type",
    "importance_value",
]


def _public_feature_group(feature_name: str) -> str:
    lower = str(feature_name).lower()
    if lower.startswith("xbrl_"):
        return "xbrl"
    if lower.startswith(("note_", "item_")):
        return "text"
    if lower.startswith(("form_ap_", "pcaob_", "auditor_partner_prior_")):
        return "auditor"
    if lower.startswith("prior_"):
        return "oversight"
    return "metadata"


def _public_mapping_rows(
    *,
    panel: pd.DataFrame,
    peer_model_id: str,
    peer: str,
    variables: Sequence[Tuple[str, str, str, str, str, str]],
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for source_variable, repo_column, mapping_status, mapping_type, proxy_source, notes in variables:
        available = bool(repo_column) and repo_column in panel.columns
        status = mapping_status if available else "missing"
        coverage = float(panel[repo_column].notna().mean()) if available else np.nan
        weak = mapping_type == "weak_proxy"
        rows.append(
            {
                "peer_model_id": peer_model_id,
                "peer": peer,
                "source_variable": source_variable,
                "repo_column": repo_column if available else "",
                "mapping_status": status,
                "mapping_type": mapping_type if available else "missing",
                "coverage_rate": coverage,
                "sign_convention_match": "unknown" if weak else ("yes" if available else "unknown"),
                "construction_match": "weak" if weak else ("yes" if available else "unknown"),
                "scale_match": "weak" if weak else ("yes" if available else "unknown"),
                "proxy_source": proxy_source if available else "",
                "notes": notes,
            }
        )
    return pd.DataFrame(rows, columns=PUBLIC_MAPPING_COLUMNS)


def _public_mapping_report(panel: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    dechow_public_map = {
        "change_in_receivables": "xbrl_ratio_receivables_to_revenue",
        "change_in_inventory": "xbrl_ratio_inventory_to_assets",
        "change_in_roa": "xbrl_ratio_profitability",
    }
    dechow_variables = [
        (
            source,
            dechow_public_map.get(source, ""),
            "proxy" if source in dechow_public_map else "missing",
            "weak_proxy" if source in dechow_public_map else "missing",
            "public_xbrl",
            "Conservative public XBRL proxy; not same construct as the Compustat variable.",
        )
        for source, _ in DECHOW_VARIABLES
    ]
    dechow_fixed_variables = [
        (
            source,
            dechow_public_map.get(source, ""),
            "proxy" if source in dechow_public_map else "missing",
            "weak_proxy" if source in dechow_public_map else "missing",
            "public_xbrl",
            "Fixed F-score requires exact/full mapping; weak public proxies are not enough.",
        )
        for source in DECHOW_MODEL1_COEFFICIENTS
    ]
    bao_public_map = {
        "wc_accruals": "xbrl_ratio_working_capital_to_assets",
        "change_in_receivables": "xbrl_ratio_receivables_to_revenue",
        "change_in_inventory": "xbrl_ratio_inventory_to_assets",
        "change_in_roa": "xbrl_ratio_profitability",
        "cash_flow_financing": "xbrl_ratio_operating_cash_flow_to_assets",
        "leverage": "xbrl_ratio_leverage",
    }
    bao_variables = [
        (
            source,
            bao_public_map.get(source, ""),
            "proxy" if source in bao_public_map else "missing",
            "weak_proxy" if source in bao_public_map else "missing",
            "public_xbrl",
            "Bao-style raw-number input is not available in the public issuer panel.",
        )
        for source, _ in BAO_VARIABLES
    ]
    dechow = _public_mapping_rows(
        panel=panel,
        peer_model_id=PUBLIC_DECHOW_PROXY_MODEL_ID,
        peer="dechow2011",
        variables=dechow_variables,
    )
    dechow_fixed = _public_mapping_rows(
        panel=panel,
        peer_model_id="dechow_fixed_fscore_model1",
        peer="dechow2011_fixed_model1",
        variables=dechow_fixed_variables,
    )
    bao = _public_mapping_rows(
        panel=panel,
        peer_model_id="bao_inspired_tree_ensemble",
        peer="bao2020",
        variables=bao_variables,
    )
    mapping = pd.concat([dechow, dechow_fixed, bao], ignore_index=True)
    return mapping, {"dechow": dechow, "dechow_fixed": dechow_fixed, "bao": bao}


def _status_row(
    *,
    peer_model_id: str,
    task: str,
    feature_set: str,
    test_year: int,
    train_window: str,
    status: str,
    reason_code: str,
    n_train: int = 0,
    n_test: int = 0,
    pos_train: int = 0,
    pos_test: int = 0,
    mapping_quality: str = "full",
    imbalance_strategy: str = "none",
) -> Dict[str, object]:
    return {
        "task_space": "public_cascade_peer",
        "peer_model_id": peer_model_id,
        "task": task,
        "feature_set": feature_set,
        "test_year": int(test_year),
        "train_window": train_window,
        "status": status,
        "reason_code": reason_code,
        "n_train": int(n_train),
        "n_test": int(n_test),
        "pos_train": int(pos_train),
        "pos_test": int(pos_test),
        "mapping_quality": mapping_quality,
        "imbalance_strategy": imbalance_strategy,
    }


def _feature_columns_for_public_spec(
    spec: Dict[str, object],
    *,
    feature_cols: Sequence[str],
    mapping_by_peer: Dict[str, pd.DataFrame],
) -> Tuple[List[str], str, float]:
    peer_model_id = str(spec["peer_model_id"])
    if peer_model_id == "dechow_fixed_fscore_model1":
        mapping = mapping_by_peer["dechow_fixed"]
        return _mapped_columns(mapping), aggregate_mapping_quality(mapping), _mapping_attrition_rate(mapping)
    if peer_model_id == PUBLIC_DECHOW_PROXY_MODEL_ID:
        mapping = mapping_by_peer["dechow"]
        return _mapped_columns(mapping), aggregate_mapping_quality(mapping), _mapping_attrition_rate(mapping)
    if peer_model_id in {"bao_inspired_tree_ensemble", "bao_style_ensemble"}:
        mapping = mapping_by_peer["bao"]
        return list(feature_cols), aggregate_mapping_quality(mapping), _mapping_attrition_rate(mapping)
    return list(feature_cols), "full", 0.0


def _public_model_specs(*, model_threads: int) -> List[Dict[str, object]]:
    specs = _model_specs(
        mode="full",
        model_threads=model_threads,
        benchmark_input_kind=PUBLIC_INPUT_KIND,
        bao_mapping_quality="skipped",
    )
    public_specs: List[Dict[str, object]] = []
    for spec in specs:
        public_spec = dict(spec)
        if str(public_spec["peer_model_id"]) == "dechow_variable_logit":
            public_spec["peer_model_id"] = PUBLIC_DECHOW_PROXY_MODEL_ID
        public_specs.append(public_spec)
    return public_specs


def _prepare_numeric_xy(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    *,
    feature_cols: Sequence[str],
    label_col: str,
) -> Tuple[pd.DataFrame, np.ndarray, pd.DataFrame, np.ndarray]:
    X_train = _as_float_frame(train_df[list(feature_cols)]).clip(lower=-1e12, upper=1e12)
    X_test = _as_float_frame(test_df[list(feature_cols)]).clip(lower=-1e12, upper=1e12)
    valid_cols = [
        col
        for col in X_train.columns
        if X_train[col].notna().any() and X_train[col].nunique(dropna=True) > 1
    ]
    y_train = pd.to_numeric(train_df[label_col], errors="coerce").fillna(0).astype(int).to_numpy()
    y_test = pd.to_numeric(test_df[label_col], errors="coerce").fillna(0).astype(int).to_numpy()
    return X_train[valid_cols], y_train, X_test[valid_cols], y_test


def _extract_public_importance(
    model: Any,
    *,
    feature_cols: Sequence[str],
    peer_model_id: str,
    task: str,
    feature_set: str,
    test_year: int,
    train_window: str,
) -> List[Dict[str, object]]:
    estimator = model
    if hasattr(model, "named_steps"):
        estimator = model.named_steps.get("model")

    values: Optional[np.ndarray] = None
    importance_type = ""
    if hasattr(estimator, "feature_importances_"):
        values = np.asarray(estimator.feature_importances_, dtype=float)
        importance_type = "feature_importance"
    elif hasattr(estimator, "coef_"):
        values = np.abs(np.asarray(estimator.coef_, dtype=float)).reshape(-1)
        importance_type = "absolute_coefficient"
    elif hasattr(estimator, "estimators_"):
        importances = [
            np.asarray(tree.feature_importances_, dtype=float)
            for tree in estimator.estimators_
            if hasattr(tree, "feature_importances_")
        ]
        if importances:
            values = np.mean(importances, axis=0)
            importance_type = "mean_bagged_feature_importance"

    if values is None or len(values) != len(feature_cols):
        return []
    total = float(np.sum(np.abs(values))) or 1.0
    return [
        {
            "peer_model_id": peer_model_id,
            "task": task,
            "feature_set": feature_set,
            "test_year": int(test_year),
            "train_window": train_window,
            "feature_name": str(feature_name),
            "feature_group": _public_feature_group(str(feature_name)),
            "importance_type": importance_type,
            "importance_value": float(abs(value) / total),
        }
        for feature_name, value in zip(feature_cols, values, strict=False)
    ]


def _task_frame(
    frame: pd.DataFrame,
    *,
    task_name: str,
    label_col: str,
    censor_col: str,
) -> pd.DataFrame:
    uncensored = frame.loc[pd.to_numeric(frame[censor_col], errors="coerce").fillna(0).eq(0)].copy()
    excluded = _task_exclusion_mask(uncensored, task_name=task_name, label_col=label_col)
    return uncensored.loc[~excluded].copy()


def _fit_public_peer_unit(
    *,
    spec: Dict[str, object],
    panel: pd.DataFrame,
    feature_set: str,
    feature_cols: Sequence[str],
    tasks: Sequence[Tuple[Optional[int], int, List[int]]],
    min_train_years: int,
    top_k: Sequence[int],
    seed: int,
    mapping_by_peer: Dict[str, pd.DataFrame],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[pd.DataFrame], List[Dict[str, object]], List[Dict[str, object]]]:
    peer_model_id = str(spec["peer_model_id"])
    active_features, mapping_quality, attrition = _feature_columns_for_public_spec(
        spec,
        feature_cols=feature_cols,
        mapping_by_peer=mapping_by_peer,
    )
    if mapping_quality not in MAPPING_QUALITY_VALUES:
        raise ValueError("mapping_quality must be full|partial|insufficient|skipped")

    status_rows: List[Dict[str, object]] = []
    metric_rows: List[Dict[str, object]] = []
    prediction_frames: List[pd.DataFrame] = []
    importance_rows: List[Dict[str, object]] = []
    imbalance_rows: List[Dict[str, object]] = []

    fiscal_year = panel["fiscal_year"].astype(int)
    if peer_model_id == "dechow_fixed_fscore_model1" and mapping_quality != "full":
        for window, test_year, _ in tasks:
            train_window = _window_label(window)
            for task_name in [*HEADLINE_TASKS, *SEVERITY_TAIL_TASKS]:
                reason = (
                    "severity_tail_sparse_not_headline"
                    if task_name in SEVERITY_TAIL_TASKS
                    else "missing_required_mapping"
                )
                status_rows.append(
                    _status_row(
                        peer_model_id=peer_model_id,
                        task=task_name,
                        feature_set=feature_set,
                        test_year=test_year,
                        train_window=train_window,
                        status="skipped",
                        reason_code=reason,
                        mapping_quality="skipped",
                        imbalance_strategy="none",
                    )
                )
        return status_rows, metric_rows, prediction_frames, importance_rows, imbalance_rows

    for window, test_year, train_years in tasks:
        train_window = _window_label(window)
        train_df = panel.loc[fiscal_year.isin([int(year) for year in train_years])].copy()
        test_df = panel.loc[fiscal_year.eq(int(test_year))].copy()
        if train_df["fiscal_year"].nunique() < min_train_years or test_df.empty:
            for task_name in [*HEADLINE_TASKS, *SEVERITY_TAIL_TASKS]:
                status_rows.append(
                    _status_row(
                        peer_model_id=peer_model_id,
                        task=task_name,
                        feature_set=feature_set,
                        test_year=test_year,
                        train_window=train_window,
                        status="skipped",
                        reason_code="insufficient_train_or_test_years",
                        n_train=len(train_df),
                        n_test=len(test_df),
                        mapping_quality=mapping_quality,
                        imbalance_strategy=str(spec.get("imbalance_strategy", "none")),
                    )
                )
            continue

        for task_name in SEVERITY_TAIL_TASKS:
            label_col = TASKS[task_name]["label"]
            censor_col = TASKS[task_name]["censor"]
            task_train = _task_frame(train_df, task_name=task_name, label_col=label_col, censor_col=censor_col)
            task_test = _task_frame(test_df, task_name=task_name, label_col=label_col, censor_col=censor_col)
            status_rows.append(
                _status_row(
                    peer_model_id=peer_model_id,
                    task=task_name,
                    feature_set=feature_set,
                    test_year=test_year,
                    train_window=train_window,
                    status="skipped",
                    reason_code="severity_tail_sparse_not_headline",
                    n_train=len(task_train),
                    n_test=len(task_test),
                    pos_train=int(pd.to_numeric(task_train[label_col], errors="coerce").fillna(0).sum()),
                    pos_test=int(pd.to_numeric(task_test[label_col], errors="coerce").fillna(0).sum()),
                    mapping_quality=mapping_quality,
                    imbalance_strategy=str(spec.get("imbalance_strategy", "none")),
                )
            )

        for task_name in HEADLINE_TASKS:
            label_col = TASKS[task_name]["label"]
            censor_col = TASKS[task_name]["censor"]
            task_train = _task_frame(train_df, task_name=task_name, label_col=label_col, censor_col=censor_col)
            task_test = _task_frame(test_df, task_name=task_name, label_col=label_col, censor_col=censor_col)
            pos_train = int(pd.to_numeric(task_train[label_col], errors="coerce").fillna(0).sum())
            pos_test = int(pd.to_numeric(task_test[label_col], errors="coerce").fillna(0).sum())
            base = {
                "peer_model_id": peer_model_id,
                "task": task_name,
                "feature_set": feature_set,
                "test_year": test_year,
                "train_window": train_window,
                "n_train": len(task_train),
                "n_test": len(task_test),
                "pos_train": pos_train,
                "pos_test": pos_test,
                "mapping_quality": mapping_quality,
                "imbalance_strategy": str(spec.get("imbalance_strategy", "none")),
            }
            if not active_features:
                status_rows.append(
                    _status_row(**base, status="skipped", reason_code="no_active_features")
                )
                continue
            if task_train.empty or task_test.empty:
                status_rows.append(
                    _status_row(**base, status="skipped", reason_code="empty_train_or_test")
                )
                continue
            X_train, y_train, X_test, y_test = _prepare_numeric_xy(
                task_train,
                task_test,
                feature_cols=active_features,
                label_col=label_col,
            )
            if len(np.unique(y_train)) < 2 or X_train.empty:
                status_rows.append(
                    _status_row(
                        **base,
                        status="skipped",
                        reason_code="one_class_train_or_empty_features",
                    )
                )
                continue
            if len(np.unique(y_test)) < 2:
                status_rows.append(
                    _status_row(**base, status="skipped", reason_code="one_class_test")
                )
                continue

            model_seed = stable_task_seed(
                seed, "public_peer", peer_model_id, feature_set, train_window, test_year, task_name
            )
            fit_X = X_train
            fit_y = np.asarray(y_train, dtype=int)
            original_n_train = len(fit_y)
            original_pos_train = int(fit_y.sum())
            imbalance_strategy = str(spec.get("imbalance_strategy", "none"))
            if imbalance_strategy == "undersample_equal":
                fit_X, fit_y = _apply_undersample_equal(X_train, fit_y, seed=model_seed)
            imbalance_rows.append(
                {
                    "peer_model_id": peer_model_id,
                    "task": task_name,
                    "feature_set": feature_set,
                    "test_year": int(test_year),
                    "train_window": train_window,
                    "imbalance_strategy": imbalance_strategy,
                    "n_train_before": int(original_n_train),
                    "pos_train_before": int(original_pos_train),
                    "n_train_after": int(len(fit_y)),
                    "pos_train_after": int(np.sum(fit_y)),
                    "test_prevalence": float(np.mean(y_test)) if len(y_test) else np.nan,
                }
            )
            try:
                if str(spec["kind"]) == "dechow_fixed":
                    prob = _dechow_fixed_predict(X_train=fit_X, X_test=X_test)
                    model = None
                    calibration_method = "fixed_logit_probability"
                else:
                    model = _fit_peer_model(spec, X_train=fit_X, y_train=fit_y, seed=model_seed)
                    prob = _predict_model(model, X_test)
                    calibration_method = (
                        "none_after_undersampling"
                        if imbalance_strategy == "undersample_equal"
                        else "native_or_class_weighted"
                    )
            except Exception as exc:
                status_rows.append(
                    _status_row(
                        **base,
                        status="skipped",
                        reason_code=f"fit_error:{type(exc).__name__}",
                    )
                )
                continue

            metrics = compute_metrics(np.asarray(y_test, dtype=int), prob, top_k=top_k)
            metric_row = {
                "task_space": "public_cascade_peer",
                "peer_model_id": peer_model_id,
                "task": task_name,
                "feature_set": feature_set,
                "test_year": int(test_year),
                "train_window": train_window,
                "input_kind": PUBLIC_INPUT_KIND,
                "n_train": int(len(y_train)),
                "n_test": int(len(y_test)),
                "n_pos_test": pos_test,
                "prevalence": float(np.mean(y_test)) if len(y_test) else np.nan,
                "roc_auc": metrics.get("roc_auc", np.nan),
                "pr_auc": metrics.get("pr_auc", np.nan),
                "brier": metrics.get("brier", np.nan),
                "brier_null": metrics.get("brier_null", np.nan),
                "brier_skill_score": metrics.get("brier_skill_score", np.nan),
                "ece": metrics.get("ece", np.nan),
                "ece_quantile": metrics.get("ece_quantile", np.nan),
                "ece_method": metrics.get("ece_method", "uniform_width_and_quantile"),
                "top_50_precision": metrics.get("top_50_precision", np.nan),
                "top_100_precision": metrics.get("top_100_precision", np.nan),
                "top_200_precision": metrics.get("top_200_precision", np.nan),
                "imbalance_strategy": imbalance_strategy,
                "calibration_method": calibration_method,
                "calibration_warning": bool(imbalance_strategy == "undersample_equal"),
                "mapping_quality": mapping_quality,
                "mapping_attrition_rate": attrition,
            }
            for key, value in metrics.items():
                if str(key).startswith("bao_top_"):
                    metric_row[key] = value
            metric_rows.append(metric_row)

            pred = task_test[["issuer_cik", "fiscal_year", "origin_date"]].copy()
            pred["task"] = task_name
            pred["feature_set"] = feature_set
            pred["test_year"] = np.int16(test_year)
            pred["train_window"] = train_window
            pred["peer_model_id"] = peer_model_id
            pred["predicted_prob"] = np.asarray(prob, dtype=np.float32)
            pred["observed_label"] = np.asarray(y_test, dtype=np.int8)
            prediction_frames.append(pred)
            status_rows.append(_status_row(**base, status="fit", reason_code="fit"))
            if model is not None:
                importance_rows.extend(
                    _extract_public_importance(
                        model,
                        feature_cols=X_train.columns.tolist(),
                        peer_model_id=peer_model_id,
                        task=task_name,
                        feature_set=feature_set,
                        test_year=int(test_year),
                        train_window=train_window,
                    )
                )
    return status_rows, metric_rows, prediction_frames, importance_rows, imbalance_rows


def _compact_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return predictions.reindex(columns=PUBLIC_PREDICTION_COLUMNS)
    work = predictions.reindex(columns=PUBLIC_PREDICTION_COLUMNS).copy()
    work["issuer_cik"] = work["issuer_cik"].astype("string")
    work["fiscal_year"] = pd.to_numeric(work["fiscal_year"], errors="coerce").astype("int16")
    work["test_year"] = pd.to_numeric(work["test_year"], errors="coerce").astype("int16")
    work["predicted_prob"] = pd.to_numeric(work["predicted_prob"], errors="coerce").astype("float32")
    work["observed_label"] = pd.to_numeric(work["observed_label"], errors="coerce").fillna(0).astype("int8")
    for col in ["task", "feature_set", "train_window", "peer_model_id"]:
        work[col] = work[col].astype("category")
    return work


def _bao_metric_columns() -> List[str]:
    cols: List[str] = []
    for fraction in BAO_TOP_FRACTIONS:
        pct = int(round(float(fraction) * 100))
        for suffix in ["bac", "k", "ndcg", "precision", "sensitivity", "specificity"]:
            cols.append(f"bao_top_{pct}pct_{suffix}")
    return cols


def _metric_columns() -> List[str]:
    return [
        "task_space",
        "peer_model_id",
        "task",
        "feature_set",
        "test_year",
        "train_window",
        "input_kind",
        "n_train",
        "n_test",
        "n_pos_test",
        "prevalence",
        "roc_auc",
        "pr_auc",
        "brier",
        "brier_null",
        "brier_skill_score",
        "ece",
        "ece_quantile",
        "ece_method",
        "top_50_precision",
        "top_100_precision",
        "top_200_precision",
        *_bao_metric_columns(),
        "imbalance_strategy",
        "calibration_method",
        "calibration_warning",
        "mapping_quality",
        "mapping_attrition_rate",
    ]


def _empty_outputs(out_dir: Path, *, mode: str, reason: str) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=_metric_columns()).to_csv(
        out_dir / "public_model_family_metrics.csv", index=False
    )
    write_table(
        pd.DataFrame(columns=PUBLIC_PREDICTION_COLUMNS),
        out_dir / "public_model_family_predictions.parquet",
    )
    pd.DataFrame(columns=PUBLIC_STATUS_COLUMNS).to_csv(
        out_dir / "public_model_family_task_status.csv", index=False
    )
    pd.DataFrame(columns=PUBLIC_IMPORTANCE_COLUMNS).to_csv(
        out_dir / "public_model_family_feature_importance.csv", index=False
    )
    pd.DataFrame(columns=PUBLIC_MAPPING_COLUMNS).to_csv(
        out_dir / "public_model_family_mapping_attrition.csv", index=False
    )
    blockers = {"status": "skipped", "reason": reason}
    (out_dir / "public_model_family_blockers.json").write_text(
        json.dumps(blockers, indent=2), encoding="utf-8"
    )
    manifest = _manifest(mode=mode, status="skipped", reason=reason)
    (out_dir / "public_model_family_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "public_model_family_summary.md").write_text(
        f"# Public Peer Comparison Summary\n\n- Status: skipped\n- Reason: {reason}\n",
        encoding="utf-8",
    )
    return {
        "out_dir": out_dir,
        "manifest_json": out_dir / "public_model_family_manifest.json",
        "summary_md": out_dir / "public_model_family_summary.md",
        "metrics_csv": out_dir / "public_model_family_metrics.csv",
        "predictions_table": out_dir / "public_model_family_predictions.parquet",
        "task_status_csv": out_dir / "public_model_family_task_status.csv",
    }


def _manifest(*, mode: str, status: str, reason: str = "") -> Dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "spec_version": SPEC_VERSION,
        "repo_commit": _git_text(["rev-parse", "HEAD"]),
        "git_dirty": bool(_git_text(["status", "--short"])),
        "peer_mode": mode,
        "paper" + "_anchors": LITERATURE_ANCHORS,
        "peer_variant": "public_label_pr2",
        "sample_scope": "public_issuer_origin",
        "task_estimand": "filing_origin_public_review_and_correction",
        "headline_tasks": HEADLINE_TASKS,
        "severity_tail_tasks": SEVERITY_TAIL_TASKS,
        "input_kind": PUBLIC_INPUT_KIND,
        "random_seed": SEED_DEFAULT,
        "status": status,
        "reason": reason,
    }


def _summary_markdown(
    *,
    mode: str,
    status_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
) -> str:
    lines = [
        "# Public Peer Comparison Summary",
        "",
        "- Scope: public-label peer-compatible model-family transfer.",
        "- This is not same-estimand performance-ranking evidence against prior fraud papers.",
        "- AAER is excluded from the public-label peer suite.",
        f"- Mode: `{mode}`",
        "",
        "## Status Counts",
    ]
    if status_df.empty:
        lines.append("- No public peer tasks were run.")
    else:
        for status, count in status_df["status"].value_counts().sort_index().items():
            lines.append(f"- `{status}`: {int(count)}")
    lines.extend(["", "## Mapping Quality"])
    if mapping_df.empty:
        lines.append("- No mapping rows were produced.")
    else:
        for peer_model_id, subdf in mapping_df.groupby("peer_model_id"):
            lines.append(f"- `{peer_model_id}`: `{aggregate_mapping_quality(subdf)}`")
    lines.extend(["", "## Best Metric Rows"])
    if metrics_df.empty:
        lines.append("- No fitted public peer model metrics were produced.")
    else:
        best = metrics_df.dropna(subset=["pr_auc"]).sort_values("pr_auc", ascending=False).head(8)
        for _, row in best.iterrows():
            lines.append(
                f"- `{row['peer_model_id']}` | {row['task']} | {row['feature_set']} | "
                f"{row['train_window']} | {int(row['test_year'])} | PR-AUC={row['pr_auc']:.4f}"
            )
    lines.append("")
    return "\n".join(lines)


def _assert_public_grain(panel: pd.DataFrame) -> None:
    duplicated = panel.duplicated(subset=["issuer_cik", "fiscal_year"]).sum()
    if duplicated:
        raise ValueError(
            "issuer_origin_panel must be unique at issuer_cik x fiscal_year; "
            f"found {int(duplicated)} duplicate rows"
        )


def run_public_peer_comparison(
    *,
    config_path: Path,
    issuer_origin_panel_path: Path,
    out_dir: Path,
    mode: str,
    peer_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Path]:
    peer_config = peer_config or {}
    if mode != "full":
        return _empty_outputs(out_dir, mode=mode, reason=f"public_peer_skipped_in_{mode}_mode")

    parallel_jobs = int(peer_config.get("parallel_jobs", 1))
    model_threads = int(peer_config.get("model_threads", 1))
    validate_parallel_budget(parallel_jobs=parallel_jobs, model_threads=model_threads)

    import yaml

    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    sample_cfg = config.get("sample", {})
    analysis = config.get("analysis", {})
    model_cfg = config.get("model", {})
    panel = read_table(
        issuer_origin_panel_path,
        date_cols=["origin_date", "filing_date", "report_date", "as_of_date"],
        low_memory=False,
    )
    panel = _filter_main_sample(
        panel,
        start_year=int(sample_cfg.get("start_year", 2011)),
        end_year=int(sample_cfg.get("end_year", 2023)),
        domestic_only=bool(sample_cfg.get("domestic_only", True)),
    )
    panel = _sort_panel_for_model(panel)
    _assert_public_grain(panel)

    families = _infer_feature_families(panel)
    feature_sets = [family for family in PUBLIC_FEATURE_SETS if family in families]
    years = panel["fiscal_year"].dropna().astype(int).sort_values().unique().tolist()
    tasks = list(
        _rolling_year_pairs(
            years,
            min_train_years=int(analysis.get("min_train_years", 5)),
            candidate_train_windows=analysis.get("candidate_train_windows", [None, 5, 7, 10]),
        )
    )
    mapping_df, mapping_by_peer = _public_mapping_report(panel)
    specs = _public_model_specs(model_threads=model_threads)
    units = []
    for spec in specs:
        if str(spec["peer_model_id"]) == PUBLIC_DECHOW_PROXY_MODEL_ID:
            units.append(
                {
                    "spec": spec,
                    "feature_set": PUBLIC_DECHOW_PROXY_FEATURE_SET,
                    "feature_cols": [],
                }
            )
            continue
        units.extend(
            {"spec": spec, "feature_set": feature_set, "feature_cols": families.get(feature_set, [])}
            for feature_set in feature_sets
        )
    fit_kwargs = {
        "panel": panel,
        "tasks": tasks,
        "min_train_years": int(analysis.get("min_train_years", 5)),
        "top_k": analysis.get("top_k", [50, 100, 200]),
        "seed": int(model_cfg.get("seed", SEED_DEFAULT)),
        "mapping_by_peer": mapping_by_peer,
    }
    if parallel_jobs == 1:
        fit_results = [
            _fit_public_peer_unit(
                spec=unit["spec"],
                feature_set=str(unit["feature_set"]),
                feature_cols=unit["feature_cols"],
                **fit_kwargs,
            )
            for unit in units
        ]
    else:
        fit_results = Parallel(n_jobs=parallel_jobs, prefer="processes")(
            delayed(_fit_public_peer_unit)(
                spec=unit["spec"],
                feature_set=str(unit["feature_set"]),
                feature_cols=unit["feature_cols"],
                **fit_kwargs,
            )
            for unit in units
        )

    status_rows: List[Dict[str, object]] = []
    metric_rows: List[Dict[str, object]] = []
    prediction_frames: List[pd.DataFrame] = []
    importance_rows: List[Dict[str, object]] = []
    imbalance_rows: List[Dict[str, object]] = []
    for rows, metrics, preds, importances, imbalances in fit_results:
        status_rows.extend(rows)
        metric_rows.extend(metrics)
        prediction_frames.extend(preds)
        importance_rows.extend(importances)
        imbalance_rows.extend(imbalances)

    out_dir.mkdir(parents=True, exist_ok=True)
    status_df = pd.DataFrame(status_rows, columns=PUBLIC_STATUS_COLUMNS)
    metrics_df = pd.DataFrame(metric_rows).reindex(columns=_metric_columns())
    predictions_df = (
        pd.concat(prediction_frames, ignore_index=True)
        if prediction_frames
        else pd.DataFrame(columns=PUBLIC_PREDICTION_COLUMNS)
    )
    predictions_df = _compact_predictions(predictions_df).sort_values(
        ["peer_model_id", "feature_set", "task", "train_window", "test_year", "issuer_cik", "fiscal_year"]
    )
    unique_key = [
        "issuer_cik",
        "fiscal_year",
        "task",
        "feature_set",
        "test_year",
        "train_window",
        "peer_model_id",
    ]
    if not predictions_df.empty and predictions_df.duplicated(subset=unique_key).any():
        raise ValueError("public_model_family_predictions has duplicate unique-key rows")
    importance_df = pd.DataFrame(importance_rows, columns=PUBLIC_IMPORTANCE_COLUMNS)
    imbalance_df = pd.DataFrame(imbalance_rows)

    status_df.to_csv(out_dir / "public_model_family_task_status.csv", index=False)
    metrics_df.to_csv(out_dir / "public_model_family_metrics.csv", index=False)
    write_table(predictions_df, out_dir / "public_model_family_predictions.parquet")
    importance_df.to_csv(out_dir / "public_model_family_feature_importance.csv", index=False)
    mapping_df.to_csv(out_dir / "public_model_family_mapping_attrition.csv", index=False)
    imbalance_df.to_csv(out_dir / "public_model_family_imbalance_strategy_report.csv", index=False)
    blockers = {
        "skipped_tasks": int(status_df["status"].eq("skipped").sum()) if not status_df.empty else 0,
        "reason_counts": status_df["reason_code"].value_counts().to_dict()
        if not status_df.empty
        else {},
    }
    (out_dir / "public_model_family_blockers.json").write_text(
        json.dumps(blockers, indent=2, sort_keys=True), encoding="utf-8"
    )
    manifest = _manifest(mode=mode, status="complete")
    (out_dir / "public_model_family_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "public_model_family_summary.md").write_text(
        _summary_markdown(
            mode=mode,
            status_df=status_df,
            metrics_df=metrics_df,
            mapping_df=mapping_df,
        ),
        encoding="utf-8",
    )
    return {
        "out_dir": out_dir,
        "manifest_json": out_dir / "public_model_family_manifest.json",
        "summary_md": out_dir / "public_model_family_summary.md",
        "metrics_csv": out_dir / "public_model_family_metrics.csv",
        "predictions_table": out_dir / "public_model_family_predictions.parquet",
        "task_status_csv": out_dir / "public_model_family_task_status.csv",
    }
