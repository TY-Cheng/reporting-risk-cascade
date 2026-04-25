"""Benchmark-only peer-compatible model-family comparison.

This PR1 module deliberately stays inside the legacy benchmark task. It transfers
peer model families into the repo's own folds and labels; it does not replicate
original-paper samples or run public-cascade overlap analysis.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import BaggingClassifier, StackingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier

from . import SEED_DEFAULT
from .benchmark import (
    LEAKAGE_COLS_DEFAULT,
    _prepare_xy,
    compute_metrics,
    expand_label_modes,
    get_feature_columns,
    infer_feature_family,
    load_config,
    load_master_panel,
    stable_task_seed,
)
from .table_io import write_table


LITERATURE_ANCHORS = ["dechow2011", "perols2011", "bao2020", "bertomeu2021"]
SCHEMA_VERSION = "peer-comparison-pr1-v1"
SPEC_VERSION = "2026-04-25-pr1-final-contract"
MAPPING_QUALITY_VALUES = {"full", "partial", "insufficient", "skipped"}
MAPPING_STATUSES = {"exact", "proxy", "missing", "unsupported"}

PREDICTION_COLUMNS = [
    "gvkey",
    "data_year",
    "label_mode",
    "test_year",
    "train_window",
    "peer_model_id",
    "predicted_prob",
    "observed_label",
]
STATUS_COLUMNS = [
    "task_space",
    "peer_model_id",
    "label_mode",
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
MAPPING_COLUMNS = [
    "peer",
    "source_variable",
    "repo_column",
    "mapping_status",
    "mapping_type",
    "coverage_rate",
    "sign_convention_match",
    "construction_match",
    "scale_match",
    "notes",
]
IMPORTANCE_COLUMNS = [
    "peer_model_id",
    "label_mode",
    "test_year",
    "train_window",
    "feature_name",
    "feature_group",
    "importance_type",
    "importance_value",
]


# Published Dechow et al. fixed F-score Model 1 coefficient vector commonly
# reported from the paper's table of F-score prediction models. The fold-local
# model below is intentionally named separately.
DECHOW_MODEL1_INTERCEPT = -7.893
DECHOW_MODEL1_COEFFICIENTS = {
    "rsst_accruals": ("rsst_ac", 0.790),
    "change_in_receivables": ("ch_rec", 2.518),
    "change_in_inventory": ("ch_inv", 1.191),
    "soft_assets": ("soft_assets", 1.979),
    "change_in_cash_sales": ("ch_cs", 0.171),
    "change_in_roa": ("ch_roa", -0.932),
    "security_issue": ("issue", 1.029),
}

DECHOW_VARIABLES = [
    ("rsst_accruals", "rsst_ac"),
    ("change_in_receivables", "ch_rec"),
    ("change_in_inventory", "ch_inv"),
    ("soft_assets", "soft_assets"),
    ("change_in_cash_sales", "ch_cs"),
    ("change_in_roa", "ch_roa"),
    ("security_issue", "issue"),
    ("change_in_employees", "ch_emp"),
    ("change_in_backlog", "ch_backlog"),
    ("lease_indicator", "leasedum"),
    ("operating_lease", "oplease"),
]

BAO_VARIABLES = [
    ("wc_accruals", "WC_acc"),
    ("rsst_accruals", "rsst_ac"),
    ("change_in_receivables", "ch_rec"),
    ("change_in_inventory", "ch_inv"),
    ("soft_assets", "soft_assets"),
    ("discretionary_accruals", "da"),
    ("discretionary_accruals_diff", "dadif"),
    ("jones_residual", "resid"),
    ("signed_residual", "sresid"),
    ("change_in_cash_sales", "ch_cs"),
    ("change_in_cash_margin", "ch_cm"),
    ("change_in_roa", "ch_roa"),
    ("change_in_free_cash_flow", "ch_fcf"),
    ("tax_indicator", "tax"),
    ("lease_indicator", "leasedum"),
    ("operating_lease", "oplease"),
    ("pension_indicator", "pension"),
    ("change_in_pension", "ch_pension"),
    ("change_in_employees", "ch_emp"),
    ("change_in_backlog", "ch_backlog"),
    ("security_issue", "issue"),
    ("external_financing", "exfin"),
    ("cash_flow_financing", "cff"),
    ("leverage", "leverage"),
    ("current_return", "ret_t"),
    ("lagged_return", "ret_{t-1}"),
    ("book_to_market", "bm"),
    ("earnings_to_price", "ep"),
]


def _git_text(args: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception:
        return "unknown"
    return completed.stdout.strip()


def _window_label(window: Optional[int]) -> str:
    return "expanding" if window is None else f"rolling_{int(window)}y"


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _as_float_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _mapping_rows(
    *,
    panel: pd.DataFrame,
    peer: str,
    variables: Sequence[Tuple[str, str]],
    mapping_type: str = "exact",
    construction_match: str = "unknown",
    scale_match: str = "unknown",
    notes: str = "",
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for source_variable, repo_column in variables:
        available = repo_column in panel.columns
        coverage = float(panel[repo_column].notna().mean()) if available else np.nan
        rows.append(
            {
                "peer": peer,
                "source_variable": source_variable,
                "repo_column": repo_column if available else "",
                "mapping_status": "exact" if available else "missing",
                "mapping_type": mapping_type if available else "missing",
                "coverage_rate": coverage,
                "sign_convention_match": "yes" if available else "unknown",
                "construction_match": construction_match if available else "unknown",
                "scale_match": scale_match if available else "unknown",
                "notes": notes,
            }
        )
    return pd.DataFrame(rows, columns=MAPPING_COLUMNS)


def aggregate_mapping_quality(mapping: pd.DataFrame) -> str:
    """Aggregate variable-level mappings into the PR1 run-level quality enum."""
    if mapping.empty:
        return "skipped"
    if not set(mapping["mapping_status"]).issubset(MAPPING_STATUSES):
        raise ValueError("mapping_status must be one of exact|proxy|missing|unsupported")
    usable = mapping["mapping_status"].isin(["exact", "proxy"])
    coverage = pd.to_numeric(mapping["coverage_rate"], errors="coerce")
    if bool((mapping["mapping_status"].eq("exact") & (coverage >= 0.70)).all()):
        return "full"
    usable_share = float(usable.mean())
    used_coverage = coverage.loc[usable]
    if usable_share >= 0.70 and not used_coverage.empty and bool((used_coverage >= 0.50).all()):
        return "partial"
    if usable.any():
        return "insufficient"
    return "skipped"


def _mapped_columns(
    mapping: pd.DataFrame,
    *,
    min_coverage: float = 0.50,
) -> List[str]:
    coverage = pd.to_numeric(mapping["coverage_rate"], errors="coerce")
    usable = mapping["mapping_status"].isin(["exact", "proxy"]) & (coverage >= min_coverage)
    return [str(col) for col in mapping.loc[usable, "repo_column"].tolist() if str(col)]


def _mapping_attrition_rate(mapping: pd.DataFrame) -> float:
    if mapping.empty:
        return 1.0
    usable = mapping["mapping_status"].isin(["exact", "proxy"])
    return float(1.0 - usable.mean())


def _status_row(
    *,
    peer_model_id: str,
    label_mode: str,
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
        "task_space": "legacy_benchmark",
        "peer_model_id": peer_model_id,
        "label_mode": label_mode,
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


def _light_disabled_status_rows(
    *,
    model_id: str,
    tasks: Sequence[Tuple[Optional[int], int, str]],
) -> List[Dict[str, object]]:
    return [
        _status_row(
            peer_model_id=model_id,
            label_mode=label_mode,
            test_year=test_year,
            train_window=_window_label(window),
            status="skipped",
            reason_code="light_mode_disabled",
            mapping_quality="skipped",
            imbalance_strategy="class_weight_balanced",
        )
        for window, test_year, label_mode in tasks
    ]


def _apply_undersample_equal(
    X: pd.DataFrame,
    y: np.ndarray,
    *,
    seed: int,
) -> Tuple[pd.DataFrame, np.ndarray]:
    y_arr = np.asarray(y, dtype=int)
    pos_idx = np.flatnonzero(y_arr == 1)
    neg_idx = np.flatnonzero(y_arr == 0)
    if len(pos_idx) == 0 or len(neg_idx) == 0:
        return X, y_arr
    n_take = min(len(pos_idx), len(neg_idx))
    rng = np.random.default_rng(seed)
    chosen = np.concatenate(
        [
            rng.choice(pos_idx, size=n_take, replace=False),
            rng.choice(neg_idx, size=n_take, replace=False),
        ]
    )
    chosen = np.sort(chosen)
    return X.iloc[chosen].copy(), y_arr[chosen]


def _linear_pipeline(*, class_weight: Optional[str], max_iter: int) -> Pipeline:
    return Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    max_iter=max_iter,
                    class_weight=class_weight,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def _tree_pipeline(*, seed: int, max_depth: int, class_weight: Optional[str]) -> Pipeline:
    return Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            (
                "model",
                DecisionTreeClassifier(
                    criterion="entropy",
                    max_depth=max_depth,
                    min_samples_leaf=5,
                    class_weight=class_weight,
                    random_state=seed,
                ),
            ),
        ]
    )


def _bagged_pipeline(
    *,
    seed: int,
    n_estimators: int,
    n_jobs: int,
    class_weight: Optional[str],
) -> Pipeline:
    tree = DecisionTreeClassifier(
        criterion="entropy",
        max_depth=4,
        min_samples_leaf=5,
        class_weight=class_weight,
        random_state=seed,
    )
    return Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            (
                "model",
                BaggingClassifier(
                    estimator=tree,
                    n_estimators=n_estimators,
                    n_jobs=n_jobs,
                    random_state=seed,
                ),
            ),
        ]
    )


def _xgb_model(*, seed: int, n_estimators: int, max_depth: int, n_jobs: int) -> XGBClassifier:
    return XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5.0,
        reg_lambda=1.0,
        n_jobs=n_jobs,
        random_state=seed,
        tree_method="hist",
        missing=np.nan,
    )


def _svm_pipeline(*, seed: int) -> Pipeline:
    svm = LinearSVC(class_weight="balanced", max_iter=2000, random_state=seed)
    return Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", CalibratedClassifierCV(svm, cv=3)),
        ]
    )


def _mlp_pipeline(*, seed: int) -> Pipeline:
    return Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            (
                "model",
                MLPClassifier(
                    hidden_layer_sizes=(16,),
                    max_iter=200,
                    random_state=seed,
                    early_stopping=True,
                ),
            ),
        ]
    )


def _stacking_pipeline(*, seed: int) -> Pipeline:
    estimators = [
        (
            "logit",
            LogisticRegression(max_iter=300, class_weight="balanced", random_state=seed),
        ),
        (
            "tree",
            DecisionTreeClassifier(
                criterion="entropy",
                max_depth=4,
                min_samples_leaf=5,
                class_weight="balanced",
                random_state=seed,
            ),
        ),
    ]
    return Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            (
                "model",
                StackingClassifier(
                    estimators=estimators,
                    final_estimator=LogisticRegression(max_iter=300),
                    cv=3,
                    n_jobs=1,
                ),
            ),
        ]
    )


def _predict_model(model: Any, X_test: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return np.asarray(model.predict_proba(X_test)[:, 1], dtype=float)
    if hasattr(model, "decision_function"):
        return _sigmoid(np.asarray(model.decision_function(X_test), dtype=float))
    pred = np.asarray(model.predict(X_test), dtype=float)
    return np.clip(pred, 0.0, 1.0)


def _extract_importance(
    model: Any,
    *,
    feature_cols: Sequence[str],
    peer_model_id: str,
    label_mode: str,
    test_year: int,
    train_window: str,
) -> List[Dict[str, object]]:
    estimator = model
    if isinstance(model, Pipeline):
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
    rows = []
    for feature_name, value in zip(feature_cols, values, strict=False):
        rows.append(
            {
                "peer_model_id": peer_model_id,
                "label_mode": label_mode,
                "test_year": int(test_year),
                "train_window": train_window,
                "feature_name": str(feature_name),
                "feature_group": infer_feature_family(str(feature_name)),
                "importance_type": importance_type,
                "importance_value": float(abs(value) / total),
            }
        )
    return rows


def _model_specs(
    *,
    mode: str,
    model_threads: int,
    benchmark_input_kind: str = "mixed",
    bao_mapping_quality: str = "skipped",
) -> List[Dict[str, object]]:
    light = mode == "light"
    bao_style_ready = benchmark_input_kind == "raw_numbers" and bao_mapping_quality in {
        "full",
        "partial",
    }
    bao_model_id = "bao_style_ensemble" if bao_style_ready else "bao_inspired_tree_ensemble"
    bao_input_kind = "raw_numbers" if bao_style_ready else benchmark_input_kind
    return [
        {
            "peer_model_id": "dechow_fixed_fscore_model1",
            "peer": "dechow2011",
            "kind": "dechow_fixed",
            "input_kind": "ratios",
            "imbalance_strategy": "none",
        },
        {
            "peer_model_id": "dechow_variable_logit",
            "peer": "dechow2011",
            "kind": "logit",
            "input_kind": "ratios",
            "imbalance_strategy": "class_weight_balanced",
            "class_weight": "balanced",
            "max_iter": 200 if light else 500,
        },
        {
            "peer_model_id": "perols_logit",
            "peer": "perols2011",
            "kind": "logit",
            "input_kind": "mixed",
            "imbalance_strategy": "class_weight_balanced" if light else "undersample_equal",
            "class_weight": "balanced" if light else None,
            "max_iter": 200 if light else 500,
        },
        {
            "peer_model_id": "perols_entropy_tree",
            "peer": "perols2011",
            "kind": "tree",
            "input_kind": "mixed",
            "imbalance_strategy": "class_weight_balanced" if light else "undersample_equal",
            "class_weight": "balanced" if light else None,
            "max_depth": 3 if light else 5,
        },
        {
            "peer_model_id": "perols_bagged",
            "peer": "perols2011",
            "kind": "bagged",
            "input_kind": "mixed",
            "imbalance_strategy": "class_weight_balanced" if light else "undersample_equal",
            "class_weight": "balanced" if light else None,
            "n_estimators": 10 if light else 50,
            "n_jobs": 1 if light else model_threads,
        },
        {
            "peer_model_id": "perols_linear_svm",
            "peer": "perols2011",
            "kind": "svm",
            "input_kind": "mixed",
            "imbalance_strategy": "undersample_equal",
            "disabled_in_light": True,
        },
        {
            "peer_model_id": "perols_stacking",
            "peer": "perols2011",
            "kind": "stacking",
            "input_kind": "mixed",
            "imbalance_strategy": "undersample_equal",
            "disabled_in_light": True,
        },
        {
            "peer_model_id": "perols_mlp",
            "peer": "perols2011",
            "kind": "mlp",
            "input_kind": "mixed",
            "imbalance_strategy": "undersample_equal",
            "disabled_in_light": True,
        },
        {
            "peer_model_id": bao_model_id,
            "peer": "bao2020",
            "kind": "xgb",
            "input_kind": bao_input_kind,
            "imbalance_strategy": "class_weight_balanced" if light else "none",
            "n_estimators": 50 if light else 250,
            "max_depth": 3 if light else 4,
            "n_jobs": 1 if light else model_threads,
        },
        {
            "peer_model_id": "bertomeu_style_xgb",
            "peer": "bertomeu2021",
            "kind": "xgb",
            "input_kind": "mixed",
            "imbalance_strategy": "class_weight_balanced" if light else "none",
            "n_estimators": 50 if light else 250,
            "max_depth": 3 if light else 4,
            "n_jobs": 1 if light else model_threads,
        },
    ]


def _feature_columns_for_spec(
    spec: Dict[str, object],
    *,
    default_feature_cols: Sequence[str],
    mapping_by_peer: Dict[str, pd.DataFrame],
) -> Tuple[List[str], str, float]:
    peer_model_id = str(spec["peer_model_id"])
    if peer_model_id == "dechow_fixed_fscore_model1":
        mapping = mapping_by_peer["dechow_fixed"]
        return [repo_col for repo_col, _ in DECHOW_MODEL1_COEFFICIENTS.values()], (
            aggregate_mapping_quality(mapping)
        ), _mapping_attrition_rate(mapping)
    if peer_model_id == "dechow_variable_logit":
        mapping = mapping_by_peer["dechow"]
        return _mapped_columns(mapping), aggregate_mapping_quality(mapping), _mapping_attrition_rate(
            mapping
        )
    if peer_model_id in {"bao_inspired_tree_ensemble", "bao_style_ensemble"}:
        mapping = mapping_by_peer["bao"]
        return _mapped_columns(mapping), aggregate_mapping_quality(mapping), _mapping_attrition_rate(
            mapping
        )
    return list(default_feature_cols), "full", 0.0


def _fit_peer_model(
    spec: Dict[str, object],
    *,
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    seed: int,
) -> Any:
    kind = str(spec["kind"])
    if kind == "logit":
        return _linear_pipeline(
            class_weight=spec.get("class_weight"),
            max_iter=int(spec.get("max_iter", 200)),
        ).fit(X_train, y_train)
    if kind == "tree":
        return _tree_pipeline(
            seed=seed,
            max_depth=int(spec.get("max_depth", 3)),
            class_weight=spec.get("class_weight"),
        ).fit(X_train, y_train)
    if kind == "bagged":
        return _bagged_pipeline(
            seed=seed,
            n_estimators=int(spec.get("n_estimators", 10)),
            n_jobs=int(spec.get("n_jobs", 1)),
            class_weight=spec.get("class_weight"),
        ).fit(X_train, y_train)
    if kind == "xgb":
        return _xgb_model(
            seed=seed,
            n_estimators=int(spec.get("n_estimators", 50)),
            max_depth=int(spec.get("max_depth", 3)),
            n_jobs=int(spec.get("n_jobs", 1)),
        ).fit(X_train, y_train)
    if kind == "svm":
        return _svm_pipeline(seed=seed).fit(X_train, y_train)
    if kind == "mlp":
        return _mlp_pipeline(seed=seed).fit(X_train, y_train)
    if kind == "stacking":
        return _stacking_pipeline(seed=seed).fit(X_train, y_train)
    raise ValueError(f"Unknown peer model kind: {kind}")


def _dechow_fixed_predict(
    *,
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
) -> np.ndarray:
    imputer = SimpleImputer(strategy="median")
    train = pd.DataFrame(
        imputer.fit_transform(X_train),
        columns=X_train.columns,
        index=X_train.index,
    )
    test = pd.DataFrame(
        imputer.transform(X_test),
        columns=X_test.columns,
        index=X_test.index,
    )
    del train
    score = np.full(len(test), DECHOW_MODEL1_INTERCEPT, dtype=float)
    for _, (repo_column, coef) in DECHOW_MODEL1_COEFFICIENTS.items():
        score = score + float(coef) * test[repo_column].to_numpy(dtype=float)
    return _sigmoid(score)


def _fit_one_spec(
    *,
    spec: Dict[str, object],
    panel: pd.DataFrame,
    tasks: Sequence[Tuple[Optional[int], int, str]],
    firm_col: str,
    year_col: str,
    target_col: str,
    feature_cols: Sequence[str],
    min_train_years: int,
    top_k: Sequence[int],
    unknown_positive_strategy: str,
    seed: int,
    mode: str,
    mapping_by_peer: Dict[str, pd.DataFrame],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[pd.DataFrame], List[Dict[str, object]], List[Dict[str, object]]]:
    peer_model_id = str(spec["peer_model_id"])
    if mode == "light" and bool(spec.get("disabled_in_light", False)):
        return _light_disabled_status_rows(model_id=peer_model_id, tasks=tasks), [], [], [], []

    active_features, mapping_quality, attrition = _feature_columns_for_spec(
        spec,
        default_feature_cols=feature_cols,
        mapping_by_peer=mapping_by_peer,
    )
    if mapping_quality not in MAPPING_QUALITY_VALUES:
        raise ValueError("mapping_quality must be full|partial|insufficient|skipped")

    status_rows: List[Dict[str, object]] = []
    metric_rows: List[Dict[str, object]] = []
    prediction_frames: List[pd.DataFrame] = []
    importance_rows: List[Dict[str, object]] = []
    imbalance_rows: List[Dict[str, object]] = []

    if peer_model_id == "dechow_fixed_fscore_model1" and mapping_quality != "full":
        for window, test_year, label_mode in tasks:
            status_rows.append(
                _status_row(
                    peer_model_id=peer_model_id,
                    label_mode=label_mode,
                    test_year=test_year,
                    train_window=_window_label(window),
                    status="skipped",
                    reason_code="missing_required_mapping",
                    mapping_quality="skipped",
                    imbalance_strategy="none",
                )
            )
        return status_rows, metric_rows, prediction_frames, importance_rows, imbalance_rows

    if not active_features:
        for window, test_year, label_mode in tasks:
            status_rows.append(
                _status_row(
                    peer_model_id=peer_model_id,
                    label_mode=label_mode,
                    test_year=test_year,
                    train_window=_window_label(window),
                    status="skipped",
                    reason_code="no_active_features",
                    mapping_quality="skipped",
                    imbalance_strategy=str(spec.get("imbalance_strategy", "none")),
                )
            )
        return status_rows, metric_rows, prediction_frames, importance_rows, imbalance_rows

    year_values = panel[year_col].astype(int)
    for window, test_year, label_mode in tasks:
        train_window = _window_label(window)
        if window is None:
            train_mask = year_values < int(test_year)
        else:
            train_mask = year_values.between(int(test_year) - int(window), int(test_year) - 1)
        test_mask = year_values.eq(int(test_year))
        train_df = panel.loc[train_mask].copy()
        test_df = panel.loc[test_mask].copy()
        if train_df[year_col].nunique() < min_train_years or test_df.empty:
            status_rows.append(
                _status_row(
                    peer_model_id=peer_model_id,
                    label_mode=label_mode,
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

        X_train, y_train, X_test, y_test = _prepare_xy(
            train_df,
            test_df,
            feature_cols=active_features,
            target_col=target_col,
            train_origin_year=int(test_year) - 1,
            label_mode=label_mode,
            unknown_positive_strategy=unknown_positive_strategy,
        )
        pos_train = int(np.sum(y_train))
        pos_test = int(np.sum(y_test))
        if len(np.unique(y_train)) < 2 or X_train.empty:
            status_rows.append(
                _status_row(
                    peer_model_id=peer_model_id,
                    label_mode=label_mode,
                    test_year=test_year,
                    train_window=train_window,
                    status="skipped",
                    reason_code="one_class_train_or_empty_features",
                    n_train=len(y_train),
                    n_test=len(y_test),
                    pos_train=pos_train,
                    pos_test=pos_test,
                    mapping_quality=mapping_quality,
                    imbalance_strategy=str(spec.get("imbalance_strategy", "none")),
                )
            )
            continue

        X_train = _as_float_frame(X_train)
        X_test = _as_float_frame(X_test)
        model_seed = stable_task_seed(seed, "peer", peer_model_id, train_window, test_year, label_mode)
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
                "label_mode": label_mode,
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
                    peer_model_id=peer_model_id,
                    label_mode=label_mode,
                    test_year=test_year,
                    train_window=train_window,
                    status="skipped",
                    reason_code=f"fit_error:{type(exc).__name__}",
                    n_train=len(y_train),
                    n_test=len(y_test),
                    pos_train=pos_train,
                    pos_test=pos_test,
                    mapping_quality=mapping_quality,
                    imbalance_strategy=imbalance_strategy,
                )
            )
            continue

        metrics = compute_metrics(np.asarray(y_test, dtype=int), prob, top_k=top_k)
        metric_row = {
            "task_space": "legacy_benchmark",
            "peer_model_id": peer_model_id,
            "label_mode": label_mode,
            "test_year": int(test_year),
            "train_window": train_window,
            "input_kind": str(spec.get("input_kind", "mixed")),
            "n_train": int(len(y_train)),
            "n_test": int(len(y_test)),
            "n_pos_test": pos_test,
            "prevalence": float(np.mean(y_test)) if len(y_test) else np.nan,
            "roc_auc": metrics.get("roc_auc", np.nan),
            "pr_auc": metrics.get("pr_auc", np.nan),
            "brier": metrics.get("brier", np.nan),
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
            "mapping_attrition_rate": attrition,
        }
        for key, value in metrics.items():
            if str(key).startswith("bao_top_"):
                metric_row[key] = value
        metric_rows.append(metric_row)
        pred = test_df[[firm_col, year_col]].copy()
        pred["label_mode"] = label_mode
        pred["test_year"] = int(test_year)
        pred["train_window"] = train_window
        pred["peer_model_id"] = peer_model_id
        pred["predicted_prob"] = prob
        pred["observed_label"] = np.asarray(y_test, dtype=int)
        prediction_frames.append(pred.rename(columns={firm_col: "gvkey", year_col: "data_year"}))
        status_rows.append(
            _status_row(
                peer_model_id=peer_model_id,
                label_mode=label_mode,
                test_year=test_year,
                train_window=train_window,
                status="fit",
                reason_code="fit",
                n_train=len(y_train),
                n_test=len(y_test),
                pos_train=pos_train,
                pos_test=pos_test,
                mapping_quality=mapping_quality,
                imbalance_strategy=imbalance_strategy,
            )
        )
        if model is not None:
            importance_rows.extend(
                _extract_importance(
                    model,
                    feature_cols=X_train.columns.tolist(),
                    peer_model_id=peer_model_id,
                    label_mode=label_mode,
                    test_year=int(test_year),
                    train_window=train_window,
                )
            )
    return status_rows, metric_rows, prediction_frames, importance_rows, imbalance_rows


def _empty_outputs(out_dir: Path, *, mode: str, reason: str) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=STATUS_COLUMNS).to_csv(out_dir / "peer_task_status.csv", index=False)
    pd.DataFrame(columns=MAPPING_COLUMNS).to_csv(
        out_dir / "feature_mapping_attrition.csv", index=False
    )
    pd.DataFrame().to_csv(out_dir / "imbalance_strategy_report.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "legacy_model_family_metrics.csv", index=False)
    write_table(pd.DataFrame(columns=PREDICTION_COLUMNS), out_dir / "legacy_model_family_predictions.parquet")
    pd.DataFrame(columns=IMPORTANCE_COLUMNS).to_csv(out_dir / "legacy_feature_importance.csv", index=False)
    blockers = {"status": "skipped", "reason": reason}
    (out_dir / "peer_blockers.json").write_text(json.dumps(blockers, indent=2), encoding="utf-8")
    manifest = _manifest(
        mode=mode,
        mapping_quality="skipped",
        imbalance_strategy="none",
        calibration_method="not_applicable",
        sample_scope="legacy_benchmark",
        implementation_differences=[reason],
    )
    (out_dir / "peer_comparison_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "peer_comparison_summary.md").write_text(
        f"# Peer Comparison Summary\n\n- Status: skipped\n- Reason: {reason}\n",
        encoding="utf-8",
    )
    return {
        "out_dir": out_dir,
        "manifest_json": out_dir / "peer_comparison_manifest.json",
        "summary_md": out_dir / "peer_comparison_summary.md",
    }


def _manifest(
    *,
    mode: str,
    mapping_quality: str,
    imbalance_strategy: str,
    calibration_method: str,
    sample_scope: str,
    implementation_differences: Sequence[str],
) -> Dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "spec_version": SPEC_VERSION,
        "repo_commit": _git_text(["rev-parse", "HEAD"]),
        "git_dirty": bool(_git_text(["status", "--short"])),
        "peer_mode": mode,
        "paper" + "_anchors": LITERATURE_ANCHORS,
        "peer_variant": "benchmark_pr1",
        "mapping_quality": mapping_quality,
        "imbalance_strategy": imbalance_strategy,
        "calibration_method": calibration_method,
        "crosswalk_version": "not_applicable",
        "sample_scope": sample_scope,
        "task_estimand": "legacy_detected_misstatement_benchmark",
        "random_seed": SEED_DEFAULT,
        "implementation_differences": list(implementation_differences),
    }


def _summary_markdown(
    *,
    mode: str,
    status_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
) -> str:
    lines = [
        "# Peer Comparison Summary",
        "",
        "- Scope: benchmark-only PR1 peer-compatible comparison.",
        "- This is not original-paper numeric replication and not same-estimand leaderboard evidence.",
        "- `bao_style_ensemble` is reserved for raw-number-compatible inputs. The legacy benchmark "
        "defaults to `bao_inspired_tree_ensemble` when the raw-number gate does not pass.",
        f"- Mode: `{mode}`",
        "",
        "## Status Counts",
    ]
    if status_df.empty:
        lines.append("- No peer tasks were run.")
    else:
        for status, count in status_df["status"].value_counts().sort_index().items():
            lines.append(f"- `{status}`: {int(count)}")
    lines.extend(["", "## Mapping Quality"])
    if mapping_df.empty:
        lines.append("- No mapping rows were produced.")
    else:
        for peer, subdf in mapping_df.groupby("peer"):
            quality = aggregate_mapping_quality(subdf)
            lines.append(f"- `{peer}`: `{quality}`")
    lines.extend(["", "## Metrics"])
    if metrics_df.empty:
        lines.append("- No fitted peer model metrics were produced.")
    else:
        best = metrics_df.dropna(subset=["pr_auc"]).sort_values("pr_auc", ascending=False).head(5)
        for _, row in best.iterrows():
            lines.append(
                f"- `{row['peer_model_id']}` | {row['label_mode']} | "
                f"{row['train_window']} | {int(row['test_year'])} | "
                f"PR-AUC={row['pr_auc']:.4f}"
            )
    lines.append("")
    return "\n".join(lines)


def validate_parallel_budget(*, parallel_jobs: int, model_threads: int) -> None:
    available = os.cpu_count() or 1
    requested = int(parallel_jobs) * int(model_threads)
    if requested > available:
        raise ValueError(
            "peer_comparison parallel budget exceeds available cores: "
            f"parallel_jobs({parallel_jobs}) * model_threads({model_threads}) = "
            f"{requested} > available_cores({available})"
        )


def run_peer_comparison(
    *,
    config_path: Path,
    raw_data_path: Path,
    out_dir: Path,
    mode: str,
    peer_config: Optional[Dict[str, Any]] = None,
    timing_csv: Optional[Path] = None,
) -> Dict[str, Path]:
    """Run PR1 benchmark peer-compatible comparisons and write fixed artifacts."""
    peer_config = peer_config or {}
    if mode not in {"none", "light", "full"}:
        raise ValueError("peer comparison mode must be one of: none, light, full")
    if mode == "none":
        return _empty_outputs(out_dir, mode=mode, reason="peer_comparison_mode_none")

    parallel_jobs = int(peer_config.get("parallel_jobs", 1))
    model_threads = int(peer_config.get("model_threads", 1))
    benchmark_input_kind = str(
        peer_config.get("benchmark_input_kind", peer_config.get("input_kind", "mixed"))
    )
    validate_parallel_budget(parallel_jobs=parallel_jobs, model_threads=model_threads)

    cfg = load_config(config_path)
    columns = cfg.get("columns", {})
    analysis = cfg.get("analysis", {})
    firm_col = columns.get("firm_col", "gvkey")
    year_col = columns.get("year_col", "data_year")
    target_col = columns.get("target", "misstatement firm-year")
    leakage_cols = columns.get("leakage_cols", LEAKAGE_COLS_DEFAULT)
    panel = load_master_panel(
        raw_data_path,
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
    feature_cols = get_feature_columns(
        panel,
        firm_col=firm_col,
        year_col=year_col,
        target_col=target_col,
        leakage_cols=leakage_cols,
    )
    dechow_mapping = _mapping_rows(
        panel=panel,
        peer="dechow2011",
        variables=DECHOW_VARIABLES,
        construction_match="proxy",
        scale_match="proxy",
        notes="Repo-native Dechow-family variable map; fixed coefficients require full mapping.",
    )
    dechow_fixed_mapping = _mapping_rows(
        panel=panel,
        peer="dechow2011_fixed_model1",
        variables=[(source, repo_col) for source, (repo_col, _) in DECHOW_MODEL1_COEFFICIENTS.items()],
        construction_match="proxy",
        scale_match="proxy",
        notes="Published fixed coefficient vector; skipped unless mapping_quality is full.",
    )
    bao_mapping = _mapping_rows(
        panel=panel,
        peer="bao2020",
        variables=BAO_VARIABLES,
        construction_match="proxy",
        scale_match="proxy",
        notes="Legacy benchmark is engineered/mixed input, not presumed raw-number compatible.",
    )
    mapping_df = pd.concat([dechow_mapping, dechow_fixed_mapping, bao_mapping], ignore_index=True)
    mapping_by_peer = {
        "dechow": dechow_mapping,
        "dechow_fixed": dechow_fixed_mapping,
        "bao": bao_mapping,
    }

    years = sorted(pd.to_numeric(panel[year_col], errors="coerce").dropna().astype(int).unique())
    min_train_years = int(analysis.get("min_train_years", 5))
    tasks: List[Tuple[Optional[int], int, str]] = []
    label_modes = expand_label_modes(
        analysis.get("label_modes", ["naive", "proxy_drop_observed"]),
        proxy_imputed_lags=analysis.get("proxy_imputed_lags", [1, 2, 3, 5]),
    )
    for window in analysis.get("candidate_train_windows", [None, 5, 7, 10]):
        for test_year in years[min_train_years:]:
            for label_mode in label_modes:
                tasks.append((window, int(test_year), str(label_mode)))

    status_rows: List[Dict[str, object]] = []
    metric_rows: List[Dict[str, object]] = []
    prediction_frames: List[pd.DataFrame] = []
    importance_rows: List[Dict[str, object]] = []
    imbalance_rows: List[Dict[str, object]] = []
    implementation_differences = [
        "Peer families run on repo-native benchmark folds, not original-paper samples.",
        "Dechow fixed-score skips unless published coefficients and mappings are usable.",
        "Bao legacy benchmark adapter is named inspired unless raw-number gate passes.",
    ]

    specs = _model_specs(
        mode=mode,
        model_threads=model_threads,
        benchmark_input_kind=benchmark_input_kind,
        bao_mapping_quality=aggregate_mapping_quality(bao_mapping),
    )
    fit_kwargs = {
        "panel": panel,
        "tasks": tasks,
        "firm_col": firm_col,
        "year_col": year_col,
        "target_col": target_col,
        "feature_cols": feature_cols,
        "min_train_years": min_train_years,
        "top_k": analysis.get("top_k", [50, 100, 200, 500]),
        "unknown_positive_strategy": analysis.get("unknown_positive_strategy", "drop"),
        "seed": int(analysis.get("seed", SEED_DEFAULT)),
        "mode": mode,
        "mapping_by_peer": mapping_by_peer,
    }
    if parallel_jobs == 1:
        fit_results = [_fit_one_spec(spec=spec, **fit_kwargs) for spec in specs]
    else:
        fit_results = Parallel(n_jobs=parallel_jobs, prefer="processes")(
            delayed(_fit_one_spec)(spec=spec, **fit_kwargs) for spec in specs
        )

    for rows, metrics, preds, importances, imbalances in fit_results:
        status_rows.extend(rows)
        metric_rows.extend(metrics)
        prediction_frames.extend(preds)
        importance_rows.extend(importances)
        imbalance_rows.extend(imbalances)

    out_dir.mkdir(parents=True, exist_ok=True)
    status_df = pd.DataFrame(status_rows, columns=STATUS_COLUMNS)
    metrics_df = pd.DataFrame(metric_rows)
    predictions_df = (
        pd.concat(prediction_frames, ignore_index=True)
        if prediction_frames
        else pd.DataFrame(columns=PREDICTION_COLUMNS)
    )
    if not predictions_df.empty:
        predictions_df = predictions_df[PREDICTION_COLUMNS].sort_values(
            ["peer_model_id", "label_mode", "train_window", "test_year", "gvkey", "data_year"]
        )
        if predictions_df.duplicated(
            subset=["gvkey", "data_year", "label_mode", "test_year", "train_window", "peer_model_id"]
        ).any():
            raise ValueError("legacy_model_family_predictions has duplicate unique-key rows")
    importance_df = pd.DataFrame(importance_rows, columns=IMPORTANCE_COLUMNS)
    imbalance_df = pd.DataFrame(imbalance_rows)

    bao_cols = sorted([col for col in metrics_df.columns if str(col).startswith("bao_top_")])
    metric_columns = [
        "task_space",
        "peer_model_id",
        "label_mode",
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
        "brier_skill_score",
        "ece",
        "ece_quantile",
        "ece_method",
        "top_50_precision",
        "top_100_precision",
        "top_200_precision",
        *bao_cols,
        "imbalance_strategy",
        "calibration_method",
        "calibration_warning",
        "mapping_attrition_rate",
    ]
    metrics_df = metrics_df.reindex(columns=metric_columns)

    status_df.to_csv(out_dir / "peer_task_status.csv", index=False)
    mapping_df.to_csv(out_dir / "feature_mapping_attrition.csv", index=False)
    imbalance_df.to_csv(out_dir / "imbalance_strategy_report.csv", index=False)
    metrics_df.to_csv(out_dir / "legacy_model_family_metrics.csv", index=False)
    write_table(predictions_df, out_dir / "legacy_model_family_predictions.parquet")
    importance_df.to_csv(out_dir / "legacy_feature_importance.csv", index=False)
    blockers = {
        "skipped_tasks": int(status_df["status"].eq("skipped").sum()) if not status_df.empty else 0,
        "reason_counts": status_df["reason_code"].value_counts().to_dict()
        if not status_df.empty
        else {},
    }
    (out_dir / "peer_blockers.json").write_text(
        json.dumps(blockers, indent=2, sort_keys=True), encoding="utf-8"
    )

    fitted_quality = (
        status_df.loc[status_df["status"].eq("fit"), "mapping_quality"].mode().iloc[0]
        if not status_df.loc[status_df["status"].eq("fit")].empty
        else "skipped"
    )
    manifest = _manifest(
        mode=mode,
        mapping_quality=str(fitted_quality),
        imbalance_strategy="mixed_peer_specific",
        calibration_method="uniform_ece_plus_quantile_ece",
        sample_scope="legacy_benchmark",
        implementation_differences=implementation_differences,
    )
    (out_dir / "peer_comparison_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "peer_comparison_summary.md").write_text(
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
        "manifest_json": out_dir / "peer_comparison_manifest.json",
        "summary_md": out_dir / "peer_comparison_summary.md",
        "metrics_csv": out_dir / "legacy_model_family_metrics.csv",
        "predictions_table": out_dir / "legacy_model_family_predictions.parquet",
        "task_status_csv": out_dir / "peer_task_status.csv",
    }
