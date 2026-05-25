"""
Filing-native public cascade model.
"""

from __future__ import annotations

import gc
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from joblib import Parallel, delayed
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder
from xgboost import XGBClassifier

from .benchmark import compute_metrics
from .ranking_metrics import BAO_TOP_FRACTIONS
from .table_io import read_table, write_table


TASKS = {
    "comment_thread": {"label": "label_comment_thread_365", "censor": "censored_365"},
    "amendment": {"label": "label_amendment_365", "censor": "censored_365"},
    "8k_402": {"label": "label_8k_402_365", "censor": "censored_365"},
}
TASK_EXCLUSION_COLS = {
    "8k_402": ("k402_item_metadata_unknown_365",),
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

MODEL_EXCLUDED_PREFIXES = ("source_available_", "public_date_", "vintage_", "label_", "censored_")
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


def stable_task_seed(base_seed: int, *parts: object) -> int:
    key = "|".join([str(int(base_seed)), *(str(part) for part in parts)])
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=4).digest()
    return 1 + int.from_bytes(digest, byteorder="big") % (2**31 - 2)


def _load_config(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _as_object_array(values: object) -> object:
    return values.astype(object)


def _as_string_array(values: object) -> object:
    return values.astype(str)


def _as_float_array(values: object) -> object:
    if isinstance(values, pd.DataFrame):
        return values.apply(pd.to_numeric, errors="coerce").astype("float64")
    return pd.to_numeric(values, errors="coerce").astype("float64")


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


def _sort_panel_for_model(panel: pd.DataFrame) -> pd.DataFrame:
    sort_cols = [
        col for col in ["issuer_cik", "fiscal_year", "origin_date", "accession"] if col in panel
    ]
    if not sort_cols:
        return panel.reset_index(drop=True)
    return panel.sort_values(sort_cols, kind="mergesort", na_position="last").reset_index(
        drop=True
    )


def _infer_feature_families(df: pd.DataFrame) -> Dict[str, List[str]]:
    candidate_cols = [col for col in df.columns if col not in IDENTIFIER_COLS]
    label_cols = {meta["label"] for meta in TASKS.values()} | {
        meta["censor"] for meta in TASKS.values()
    }
    label_cols |= {col for cols in TASK_EXCLUSION_COLS.values() for col in cols}
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
        elif lower.startswith(("form_ap_", "pcaob_", "auditor_partner_prior_")):
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
            ("numeric", FunctionTransformer(_as_float_array), numeric),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("as_object", FunctionTransformer(_as_object_array)),
                        ("impute", SimpleImputer(strategy="constant", fill_value="__MISSING__")),
                        ("as_string", FunctionTransformer(_as_string_array)),
                        ("encode", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ],
        sparse_threshold=1.0,
    )


def _task_exclusion_mask(df: pd.DataFrame, *, task_name: str, label_col: str) -> pd.Series:
    mask = pd.Series(False, index=df.index)
    for col in TASK_EXCLUSION_COLS.get(task_name, ()):
        if col in df.columns:
            mask = mask | pd.to_numeric(df[col], errors="coerce").fillna(0).ne(0)
    if label_col in df.columns:
        mask = mask | pd.to_numeric(df[label_col], errors="coerce").isna()
    return mask


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
        missing=np.nan,
    )
    return clf


def _evaluate_binary(
    y_true: np.ndarray,
    prob: np.ndarray,
    *,
    top_k: Sequence[int] = (50, 100, 200),
) -> Dict[str, float]:
    metrics = compute_metrics(np.asarray(y_true, dtype=int), np.asarray(prob, dtype=float), top_k=top_k)
    if len(np.unique(y_true)) < 2:
        metrics["roc_auc"] = np.nan
        metrics["pr_auc"] = np.nan
    return metrics


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


def _public_opacity_components(panel: pd.DataFrame) -> pd.DataFrame:
    components: Dict[str, pd.Series] = {}
    for col in panel.columns:
        lower = col.lower()
        if lower.startswith(("missing_", "raw_missing_")):
            components[col] = pd.to_numeric(panel[col], errors="coerce").fillna(0).clip(0, 1)
        elif lower.startswith("xbrl_coverage_"):
            coverage = pd.to_numeric(panel[col], errors="coerce").clip(0, 1)
            components[f"opacity_{col}"] = 1.0 - coverage.fillna(0)
    for col in ["note_text_count", "note_text_char_count"]:
        if col in panel.columns:
            values = pd.to_numeric(panel[col], errors="coerce")
            components[f"opacity_{col}_absent"] = (values.fillna(0) <= 0).astype(float)
    if not components:
        return pd.DataFrame(index=panel.index)
    return pd.DataFrame(components, index=panel.index).astype(float)


def build_public_missingness_density_score(
    panel: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[str]]:
    """Add the public-side opacity treatment used by Experiment 3."""
    work = panel.copy()
    components = _public_opacity_components(work)
    if components.empty:
        work["missingness_density_score"] = 0.0
        return work, []
    work["missingness_density_score"] = components.mean(axis=1).astype(float)
    return work, list(components.columns)


def _public_dml_control_columns(
    panel: pd.DataFrame,
    *,
    opacity_component_names: Sequence[str],
) -> List[str]:
    families = _infer_feature_families(panel)
    opacity_source_cols = {
        name.replace("opacity_", "").replace("_absent", "") for name in opacity_component_names
    }
    excluded = {
        "missingness_density_score",
        *opacity_component_names,
        *opacity_source_cols,
    }
    controls: List[str] = []
    for col in families["all"]:
        lower = col.lower()
        if col in excluded:
            continue
        if lower.startswith(("missing_", "raw_missing_", "xbrl_coverage_")):
            continue
        if lower.startswith(MODEL_EXCLUDED_PREFIXES):
            continue
        if col in MODEL_EXCLUDED_COLS or col in IDENTIFIER_COLS:
            continue
        controls.append(col)
    return controls


def _public_dml_matrix(
    work: pd.DataFrame,
    controls: Sequence[str],
    *,
    max_categories: int = 50,
) -> Tuple[np.ndarray, List[str]]:
    if not controls:
        return np.zeros((len(work), 1), dtype=float), ["constant_control"]
    frame = work[list(controls)].copy()
    categorical = [
        col
        for col in frame.columns
        if col in {"form", "entity_type"}
        or frame[col].dtype == object
        or str(frame[col].dtype).startswith("category")
    ]
    categorical = [
        col
        for col in categorical
        if frame[col].nunique(dropna=True) <= int(max_categories)
    ]
    numeric = [col for col in frame.columns if col not in categorical]
    parts: List[pd.DataFrame] = []
    used: List[str] = []
    if numeric:
        numeric_frame = frame[numeric].apply(pd.to_numeric, errors="coerce")
        numeric_frame = numeric_frame.replace([np.inf, -np.inf], np.nan).clip(
            lower=-1e12, upper=1e12
        )
        parts.append(numeric_frame)
        used.extend(numeric)
    if categorical:
        cat_frame = frame[categorical].astype("object").fillna("__MISSING__")
        dummies = pd.get_dummies(cat_frame, columns=categorical, dummy_na=False, dtype=float)
        parts.append(dummies)
        used.extend(list(dummies.columns))
    if not parts:
        return np.zeros((len(work), 1), dtype=float), ["constant_control"]
    X = pd.concat(parts, axis=1)
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    return imputer.fit_transform(X), used


def fit_public_opacity_dml(
    panel: pd.DataFrame,
    *,
    outcomes: Sequence[str],
    seed: int,
    n_splits: int = 3,
    max_iter: int = 100,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    panel_with_score, opacity_components = build_public_missingness_density_score(panel)
    controls = _public_dml_control_columns(
        panel_with_score,
        opacity_component_names=opacity_components,
    )
    rows: List[Dict[str, object]] = []
    for outcome in outcomes:
        if outcome not in TASKS:
            rows.append(
                {
                    "outcome": outcome,
                    "label_col": "",
                    "censor_col": "",
                    "treatment": "missingness_density_score",
                    "status": "skipped_unknown_outcome",
                    "n_obs": 0,
                    "prevalence": np.nan,
                    "mean_treatment": np.nan,
                    "coef": np.nan,
                    "std_err": np.nan,
                    "p_value": np.nan,
                    "n_controls": int(len(controls)),
                    "n_opacity_components": int(len(opacity_components)),
                }
            )
            continue
        label_col = TASKS[outcome]["label"]
        censor_col = TASKS[outcome]["censor"]
        if label_col not in panel_with_score.columns or censor_col not in panel_with_score.columns:
            rows.append(
                {
                    "outcome": outcome,
                    "label_col": label_col,
                    "censor_col": censor_col,
                    "treatment": "missingness_density_score",
                    "status": "skipped_missing_label_or_censor",
                    "n_obs": 0,
                    "prevalence": np.nan,
                    "mean_treatment": np.nan,
                    "coef": np.nan,
                    "std_err": np.nan,
                    "p_value": np.nan,
                    "n_controls": int(len(controls)),
                    "n_opacity_components": int(len(opacity_components)),
                }
            )
            continue
        uncensored = pd.to_numeric(panel_with_score[censor_col], errors="coerce").fillna(0).eq(0)
        work = panel_with_score.loc[uncensored].copy()
        work = work.dropna(subset=[label_col, "missingness_density_score"])
        y = pd.to_numeric(work[label_col], errors="coerce").fillna(0).astype(int).to_numpy()
        t = pd.to_numeric(work["missingness_density_score"], errors="coerce").to_numpy(dtype=float)
        base_row = {
            "outcome": outcome,
            "label_col": label_col,
            "censor_col": censor_col,
            "treatment": "missingness_density_score",
            "n_obs": int(len(work)),
            "prevalence": float(np.mean(y)) if len(y) else np.nan,
            "mean_treatment": float(np.mean(t)) if len(t) else np.nan,
            "n_controls": int(len(controls)),
            "n_opacity_components": int(len(opacity_components)),
        }
        if len(opacity_components) == 0:
            rows.append({**base_row, "status": "skipped_no_opacity_components", "coef": np.nan, "std_err": np.nan, "p_value": np.nan})
            continue
        if len(work) < 20 or len(np.unique(y)) < 2:
            rows.append({**base_row, "status": "skipped_one_class_or_too_small", "coef": np.nan, "std_err": np.nan, "p_value": np.nan})
            continue
        if float(np.nanstd(t)) == 0:
            rows.append({**base_row, "status": "skipped_constant_treatment", "coef": np.nan, "std_err": np.nan, "p_value": np.nan})
            continue
        X, used_controls = _public_dml_matrix(work, controls)
        splits = min(int(n_splits), len(work))
        if splits < 2:
            rows.append({**base_row, "status": "skipped_insufficient_folds", "coef": np.nan, "std_err": np.nan, "p_value": np.nan})
            continue
        y_hat = np.zeros(len(work), dtype=float)
        t_hat = np.zeros(len(work), dtype=float)
        splitter = KFold(n_splits=splits, shuffle=True, random_state=int(seed))
        for fold, (train_idx, test_idx) in enumerate(splitter.split(X), start=1):
            if len(np.unique(y[train_idx])) < 2:
                y_hat[test_idx] = float(np.mean(y[train_idx]))
            else:
                y_model = HistGradientBoostingClassifier(
                    random_state=int(seed) + fold,
                    max_iter=int(max_iter),
                )
                y_model.fit(X[train_idx], y[train_idx])
                y_hat[test_idx] = y_model.predict_proba(X[test_idx])[:, 1]
            if float(np.nanstd(t[train_idx])) == 0:
                t_hat[test_idx] = float(np.mean(t[train_idx]))
            else:
                t_model = HistGradientBoostingRegressor(
                    random_state=int(seed) + 100 + fold,
                    max_iter=int(max_iter),
                )
                t_model.fit(X[train_idx], t[train_idx])
                t_hat[test_idx] = t_model.predict(X[test_idx])
        y_res = y - y_hat
        t_res = t - t_hat
        if float(np.nanstd(t_res)) == 0:
            rows.append({**base_row, "status": "skipped_constant_residual_treatment", "coef": np.nan, "std_err": np.nan, "p_value": np.nan})
            continue
        fitted = sm.OLS(y_res, sm.add_constant(t_res)).fit(cov_type="HC3")
        rows.append(
            {
                **base_row,
                "status": "fit",
                "coef": float(fitted.params[1]),
                "std_err": float(fitted.bse[1]),
                "p_value": float(fitted.pvalues[1]),
                "n_controls": int(len(used_controls)),
            }
        )
    meta = {
        "treatment": "missingness_density_score",
        "opacity_components": opacity_components,
        "control_columns": controls,
        "n_opacity_components": int(len(opacity_components)),
        "n_controls": int(len(controls)),
    }
    return pd.DataFrame(rows), meta


def _run_public_cascade_unit(
    *,
    panel: pd.DataFrame,
    task_order: int,
    family: str,
    feature_cols: Sequence[str],
    window: Optional[int],
    test_year: int,
    train_years: Sequence[int],
    seed: int,
    model_cfg: Dict[str, object],
    seed_policy: str,
) -> Optional[Dict[str, object]]:
    train_window_label = "expanding" if window is None else f"rolling_{window}y"
    fiscal_year = panel["fiscal_year"].astype(int)
    train_mask = fiscal_year.isin([int(year) for year in train_years])
    test_mask = fiscal_year.eq(int(test_year))
    train_df = panel.loc[train_mask].copy()
    test_df = panel.loc[test_mask].copy()
    if train_df.empty or test_df.empty:
        return None

    active_feature_cols = [col for col in feature_cols if not train_df[col].isna().all()]
    if not active_feature_cols:
        return None

    preprocessor = _build_preprocessor(train_df, active_feature_cols)
    preprocessor.fit(train_df[active_feature_cols])

    metric_rows: List[Dict[str, object]] = []
    prediction_frames: List[pd.DataFrame] = []
    task_status_rows: List[Dict[str, object]] = []

    for task_suborder, (task_name, task_meta) in enumerate(TASKS.items()):
        uncensored_train = train_df.loc[train_df[task_meta["censor"]].eq(0)].copy()
        uncensored_test = test_df.loc[test_df[task_meta["censor"]].eq(0)].copy()
        excluded_train_mask = _task_exclusion_mask(
            uncensored_train,
            task_name=task_name,
            label_col=str(task_meta["label"]),
        )
        excluded_test_mask = _task_exclusion_mask(
            uncensored_test,
            task_name=task_name,
            label_col=str(task_meta["label"]),
        )
        excluded_train = int(excluded_train_mask.sum())
        excluded_test = int(excluded_test_mask.sum())
        task_train = uncensored_train.loc[~excluded_train_mask].copy()
        task_test = uncensored_test.loc[~excluded_test_mask].copy()
        if task_train.empty or task_test.empty:
            task_status_rows.append(
                {
                    "_task_order": int(task_order),
                    "_task_suborder": int(task_suborder),
                    "feature_set": family,
                    "train_window": train_window_label,
                    "test_year": int(test_year),
                    "task": task_name,
                    "status": "skipped_empty_train_or_test",
                    "n_train": int(len(task_train)),
                    "n_test": int(len(task_test)),
                    "excluded_train": excluded_train,
                    "excluded_test": excluded_test,
                    "positive_train": 0,
                    "positive_test": 0,
                }
            )
            continue

        y_train = (
            pd.to_numeric(task_train[task_meta["label"]], errors="coerce").fillna(0).astype(int)
        )
        y_test = (
            pd.to_numeric(task_test[task_meta["label"]], errors="coerce").fillna(0).astype(int)
        )
        status_base = {
            "_task_order": int(task_order),
            "_task_suborder": int(task_suborder),
            "feature_set": family,
            "train_window": train_window_label,
            "test_year": int(test_year),
            "task": task_name,
            "n_train": int(len(task_train)),
            "n_test": int(len(task_test)),
            "excluded_train": excluded_train,
            "excluded_test": excluded_test,
            "positive_train": int(y_train.sum()),
            "positive_test": int(y_test.sum()),
        }
        if y_train.nunique() < 2:
            task_status_rows.append({**status_base, "status": "skipped_one_class_train"})
            continue
        if y_test.nunique() < 2:
            task_status_rows.append({**status_base, "status": "skipped_one_class_test"})
            continue

        if seed_policy == "task_isolated":
            model_seed = stable_task_seed(
                seed, "public_cascade", family, train_window_label, test_year, task_name
            )
        elif seed_policy == "legacy":
            model_seed = int(seed)
        else:
            raise ValueError("seed_policy must be 'task_isolated' or 'legacy'")

        x_task_train = preprocessor.transform(task_train[active_feature_cols])
        x_task_test = preprocessor.transform(task_test[active_feature_cols])
        pos = int(y_train.sum())
        neg = int(len(y_train) - pos)
        scale_pos_weight = neg / pos if pos > 0 else 1.0
        model = _build_model(
            scale_pos_weight=scale_pos_weight,
            seed=model_seed,
            params=model_cfg.get("xgb", {}),
        )
        model.fit(x_task_train, y_train)
        prob = model.predict_proba(x_task_test)[:, 1]
        metrics = _evaluate_binary(y_test.to_numpy(), prob, top_k=[50, 100, 200])
        metric_rows.append(
            {
                "_task_order": int(task_order),
                "_task_suborder": int(task_suborder),
                "feature_set": family,
                "train_window": train_window_label,
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
        pred_frame["_task_order"] = int(task_order)
        pred_frame["_task_suborder"] = int(task_suborder)
        pred_frame["_row_order"] = pred_frame.index.to_numpy()
        pred_frame["feature_set"] = family
        pred_frame["train_window"] = train_window_label
        pred_frame["task"] = task_name
        pred_frame["probability"] = prob
        pred_frame["label"] = y_test.to_numpy()
        prediction_frames.append(pred_frame)

        del model, x_task_train, x_task_test, prob, y_train, y_test, task_train, task_test
        gc.collect()

    return {
        "metrics": metric_rows,
        "predictions": prediction_frames,
        "task_status": task_status_rows,
    }


def _run_public_cascade_unit_batch(
    *,
    panel: pd.DataFrame,
    units: Sequence[Dict[str, object]],
    seed: int,
    model_cfg: Dict[str, object],
    seed_policy: str,
) -> List[Optional[Dict[str, object]]]:
    return [
        _run_public_cascade_unit(
            panel=panel,
            task_order=int(unit["task_order"]),
            family=str(unit["family"]),
            feature_cols=unit["feature_cols"],
            window=unit["window"],
            test_year=int(unit["test_year"]),
            train_years=unit["train_years"],
            seed=seed,
            model_cfg=model_cfg,
            seed_policy=seed_policy,
        )
        for unit in units
    ]


def run_public_cascade(
    *,
    config_path: Path,
    issuer_origin_panel_path: Optional[Path] = None,
    out_dir: Path,
    issuer_origin_panel_csv: Optional[Path] = None,
    parallel_jobs: Optional[int] = None,
    model_threads: Optional[int] = None,
    seed_policy: Optional[str] = None,
) -> Dict[str, object]:
    config = _load_config(config_path)
    if issuer_origin_panel_path is not None and issuer_origin_panel_csv is not None:
        if Path(issuer_origin_panel_path) != Path(issuer_origin_panel_csv):
            raise ValueError(
                "Pass only one of issuer_origin_panel_path or deprecated "
                "issuer_origin_panel_csv."
            )
    issuer_origin_panel_path = issuer_origin_panel_path or issuer_origin_panel_csv
    if issuer_origin_panel_path is None:
        raise ValueError("issuer_origin_panel_path is required.")
    panel = read_table(
        issuer_origin_panel_path,
        date_cols=["origin_date", "filing_date", "report_date", "as_of_date"],
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
    panel = _sort_panel_for_model(panel)
    families = _infer_feature_families(panel)
    metadata_family = set(families.get("metadata", []))
    feature_family_summary = {
        family: {
            "n_features": int(len(cols)),
            "empty": bool(len(cols) == 0),
            "same_as_metadata": bool(set(cols) == metadata_family),
            "n_xbrl_ratio_features": int(sum(col.startswith("xbrl_ratio_") for col in cols)),
            "n_xbrl_coverage_features": int(sum(col.startswith("xbrl_coverage_") for col in cols)),
        }
        for family, cols in families.items()
    }
    requested_families = [
        f for f in analysis_cfg.get("feature_sets", ["metadata", "all"]) if f in families
    ]
    train_windows = analysis_cfg.get("candidate_train_windows", [None, 5, 7, 10])
    min_train_years = int(analysis_cfg.get("min_train_years", 5))
    seed = int(model_cfg.get("seed", 42))
    model_cfg = dict(model_cfg)
    model_cfg["xgb"] = dict(model_cfg.get("xgb", {}))
    if model_threads is not None:
        model_cfg["xgb"]["n_jobs"] = int(model_threads)
    parallel_jobs = max(1, int(parallel_jobs or analysis_cfg.get("parallel_jobs", 1)))
    seed_policy = str(seed_policy or analysis_cfg.get("seed_policy", "legacy"))
    if seed_policy not in {"task_isolated", "legacy"}:
        raise ValueError("seed_policy must be 'task_isolated' or 'legacy'")
    years = panel["fiscal_year"].dropna().astype(int).sort_values().unique().tolist()
    opacity_dml_cfg = dict(analysis_cfg.get("opacity_dml", {}))

    metric_rows: List[Dict[str, object]] = []
    prediction_frames: List[pd.DataFrame] = []
    task_status_rows: List[Dict[str, object]] = []

    units: List[Dict[str, object]] = []
    task_order = 0
    for family in requested_families:
        feature_cols = families[family]
        if not feature_cols:
            continue
        for window, test_year, train_years in _rolling_year_pairs(
            years,
            min_train_years=min_train_years,
            candidate_train_windows=train_windows,
        ):
            units.append(
                {
                    "task_order": task_order,
                    "family": family,
                    "feature_cols": feature_cols,
                    "window": window,
                    "test_year": int(test_year),
                    "train_years": train_years,
                }
            )
            task_order += 1

    units_by_family: Dict[str, List[Dict[str, object]]] = {}
    for unit in units:
        units_by_family.setdefault(str(unit["family"]), []).append(unit)
    unit_batches = [units_by_family[family] for family in requested_families if family in units_by_family]

    if parallel_jobs == 1:
        batched_results = [
            _run_public_cascade_unit_batch(
                panel=panel,
                units=batch,
                seed=seed,
                model_cfg=model_cfg,
                seed_policy=seed_policy,
            )
            for batch in unit_batches
        ]
    else:
        batched_results = Parallel(n_jobs=parallel_jobs, prefer="processes")(
            delayed(_run_public_cascade_unit_batch)(
                panel=panel,
                units=batch,
                seed=seed,
                model_cfg=model_cfg,
                seed_policy=seed_policy,
            )
            for batch in unit_batches
        )
    results = [result for batch in batched_results for result in batch]

    for result in results:
        if result is None:
            continue
        metric_rows.extend(result["metrics"])
        prediction_frames.extend(result["predictions"])
        task_status_rows.extend(result["task_status"])

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
        "brier_null",
        "brier_skill_score",
        "ece",
        "ece_quantile",
        "ece_method",
        "top_50_precision",
        "top_100_precision",
        "top_200_precision",
    ]
    for fraction in BAO_TOP_FRACTIONS:
        pct = int(round(float(fraction) * 100))
        for suffix in ["k", "precision", "sensitivity", "specificity", "bac", "ndcg"]:
            metric_columns.append(f"bao_top_{pct}pct_{suffix}")
    metrics_df = pd.DataFrame(metric_rows, columns=metric_columns)
    prediction_columns = [
        "issuer_cik",
        "accession",
        "fiscal_year",
        "feature_set",
        "train_window",
        "task",
        "probability",
        "label",
    ]
    predictions_df = (
        pd.concat(prediction_frames, ignore_index=True)
        if prediction_frames
        else pd.DataFrame(columns=prediction_columns)
    )
    status_columns = [
        "feature_set",
        "train_window",
        "test_year",
        "task",
        "status",
        "n_train",
        "n_test",
        "excluded_train",
        "excluded_test",
        "positive_train",
        "positive_test",
    ]
    task_status_df = pd.DataFrame(task_status_rows, columns=status_columns)
    sort_internal = ["_task_order", "_task_suborder"]
    if not metrics_df.empty:
        metrics_df = (
            pd.DataFrame(metric_rows)
            .sort_values(sort_internal)
            .drop(columns=sort_internal)
            .reindex(columns=metric_columns)
        )
    if not predictions_df.empty:
        predictions_df = predictions_df.sort_values(
            ["_task_order", "_task_suborder", "_row_order"]
        ).drop(columns=["_task_order", "_task_suborder", "_row_order"])
    if not task_status_df.empty:
        task_status_df = (
            pd.DataFrame(task_status_rows)
            .sort_values(sort_internal)
            .drop(columns=sort_internal)
            .reindex(columns=status_columns)
        )
    task_positive_counts = {
        task_name: int(pd.to_numeric(panel[meta["label"]], errors="coerce").fillna(0).sum())
        for task_name, meta in TASKS.items()
        if meta["label"] in panel.columns
    }
    task_exclusion_counts = {
        task_name: int(_task_exclusion_mask(panel, task_name=task_name, label_col=meta["label"]).sum())
        for task_name, meta in TASKS.items()
        if meta["label"] in panel.columns
    }
    zero_positive_tasks = [
        task_name
        for task_name, positive_count in task_positive_counts.items()
        if positive_count == 0
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
        "task_exclusion_counts": task_exclusion_counts,
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

    if bool(opacity_dml_cfg.get("enabled", True)):
        opacity_dml_df, opacity_dml_meta = fit_public_opacity_dml(
            panel,
            outcomes=opacity_dml_cfg.get(
                "outcomes",
                ["comment_thread", "amendment", "8k_402"],
            ),
            seed=int(opacity_dml_cfg.get("seed", seed)),
            n_splits=int(opacity_dml_cfg.get("folds", 3)),
            max_iter=int(opacity_dml_cfg.get("max_iter", 100)),
        )
    else:
        opacity_dml_df = pd.DataFrame()
        opacity_dml_meta = {
            "treatment": "missingness_density_score",
            "opacity_components": [],
            "control_columns": [],
            "n_opacity_components": 0,
            "n_controls": 0,
            "status": "disabled",
        }
    summary["public_opacity_dml_status_counts"] = (
        {
            str(status): int(count)
            for status, count in opacity_dml_df["status"].value_counts().items()
        }
        if not opacity_dml_df.empty and "status" in opacity_dml_df.columns
        else {}
    )
    summary["public_opacity_dml_n_opacity_components"] = int(
        opacity_dml_meta.get("n_opacity_components", 0)
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "public_cascade_metrics.csv"
    predictions_path = out_dir / "public_cascade_predictions.parquet"
    task_status_path = out_dir / "public_cascade_task_status.csv"
    opacity_dml_path = out_dir / "public_opacity_dml.csv"
    opacity_dml_meta_path = out_dir / "public_opacity_dml_meta.json"
    summary_path = out_dir / "public_cascade_summary.json"
    readiness_md = out_dir / "public_cascade_summary.md"

    metrics_df.to_csv(metrics_path, index=False)
    write_table(predictions_df, predictions_path)
    task_status_df.to_csv(task_status_path, index=False)
    opacity_dml_df.to_csv(opacity_dml_path, index=False)
    opacity_dml_meta_path.write_text(json.dumps(opacity_dml_meta, indent=2), encoding="utf-8")
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
        lines.append(f"- Task exclusion counts: `{summary.get('task_exclusion_counts', {})}`")
        lines.append(f"- Zero-positive tasks: `{summary.get('zero_positive_tasks', [])}`")
        lines.append(f"- Task status counts: `{summary.get('task_status_counts', {})}`")
        lines.append(f"- Feature family summary: `{summary.get('feature_family_summary', {})}`")
        lines.append(
            f"- Empty feature-family blockers: "
            f"`{summary.get('empty_feature_family_blockers', [])}`"
        )
        lines.append(
            f"- XBRL aggregate-only blocker: `{summary.get('xbrl_aggregate_only_blocker', False)}`"
        )
        lines.append(f"- Cascade readiness level: `{summary.get('cascade_readiness_level')}`")
        lines.append(
            f"- Public opacity DML status counts: "
            f"`{summary.get('public_opacity_dml_status_counts', {})}`"
        )
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
        "predictions_table": predictions_path,
        "predictions_csv": predictions_path,
        "task_status_csv": task_status_path,
        "public_opacity_dml_csv": opacity_dml_path,
        "public_opacity_dml_meta_json": opacity_dml_meta_path,
        "summary_json": summary_path,
        "summary_md": readiness_md,
    }
