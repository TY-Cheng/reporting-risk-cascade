"""
Config-driven data loading, preprocessing, splitting, and CV utilities for firm-year misstatement classification.

Key features
- Reads YAML config (see sample at bottom comment) and a raw table.
- Enforces MultiIndex (firm, year) and keeps identifiers out of features.
- Time-aware **out-of-time test** split (last N years / fraction / cutoff).
- Multiple CV options in training years, selectable via YAML:
    * year_blocked  (default): contiguous year blocks with optional purge
    * stratified_group_kfold
    * repeated_stratified_kfold
- Robust, schema-free preprocessing: detects numeric/categorical, buckets rare
  categories, imputes, (optionally) scales numeric, and drops ultra-missing cols.
- Smoke test: **no model fitting**; computes constant-probability "prior" baseline
  (class prevalence) for quick PR-AUC/ROC-AUC/Brier.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# sklearn pieces (no classifier imports for smoke test)
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.model_selection import RepeatedStratifiedKFold, StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, RobustScaler, StandardScaler

try:
    import yaml
except Exception as e:
    raise RuntimeError("PyYAML is required: pip install pyyaml") from e

try:
    from . import SEED_DEFAULT
    from .table_io import read_table
except Exception:
    SEED_DEFAULT = 2025

    def read_table(path: Path, **kwargs):
        return pd.read_csv(path, low_memory=kwargs.get("low_memory", False))


# =============================================================================
# * Small utilities
# =============================================================================


def _autodetect(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


# =============================================================================
# * Rare category bucketing (sklearn-compatible)
# =============================================================================
class RareCategoryGrouper(BaseEstimator, TransformerMixin):
    """Map infrequent categories to a single token to control OHE width."""

    def __init__(
        self,
        min_count: int = 25,
        rare_token: str = "__RARE__",
        cols: Optional[Sequence[str]] = None,
    ):
        self.min_count = int(min_count)
        self.rare_token = rare_token
        self.cols = cols
        self.keep_: Dict[str, set] = {}

    def fit(self, X: pd.DataFrame, y=None):  # type: ignore
        df = X if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
        cols = self.cols or df.select_dtypes(include=["object", "category"]).columns.tolist()
        self.keep_ = {}
        for c in cols:
            vc = df[c].astype("object").value_counts(dropna=False)
            keep = set(vc[vc >= self.min_count].index.tolist())
            if np.nan in keep:
                keep.remove(np.nan)
            self.keep_[c] = keep
        return self

    def transform(self, X):  # type: ignore
        df = X.copy() if isinstance(X, pd.DataFrame) else pd.DataFrame(X)
        for c, keep in self.keep_.items():
            if c not in df.columns:
                continue
            ser = df[c].astype("object")
            mask = ~ser.isin(keep) & ser.notna()
            df.loc[mask, c] = self.rare_token
        return df


# =============================================================================
# * Numeric cleaners (handle inf/overflow + optional winsorization)
# =============================================================================
class FiniteCleaner(BaseEstimator, TransformerMixin):
    """Replace ±inf with NaN and (optionally) clip by quantiles and/or absolute max."""

    def __init__(
        self,
        clip_quantiles: Optional[Tuple[float, float]] = None,
        abs_max: Optional[float] = None,
        as_dataframe: bool = False,
    ):
        self.clip_quantiles = clip_quantiles
        self.abs_max = abs_max
        self.as_dataframe = as_dataframe
        self.lo_: Optional[pd.Series] = None
        self.hi_: Optional[pd.Series] = None

    def fit(self, X, y=None):  # X may be ndarray
        df = pd.DataFrame(X).replace([np.inf, -np.inf], np.nan)
        if self.clip_quantiles is not None:
            q_lo, q_hi = self.clip_quantiles
            self.lo_ = df.quantile(q_lo)
            self.hi_ = df.quantile(q_hi)
        return self

    def transform(self, X):
        df = pd.DataFrame(X).astype(float).replace([np.inf, -np.inf], np.nan)
        if self.abs_max is not None:
            df = df.clip(lower=-self.abs_max, upper=self.abs_max)
        if self.lo_ is not None:
            df = df.clip(lower=self.lo_, axis=1)
        if self.hi_ is not None:
            df = df.clip(upper=self.hi_, axis=1)
        return df if self.as_dataframe else df.to_numpy()


# =============================================================================
# * Year-blocked (time-aware) CV with optional purge
# =============================================================================
@dataclass
class Fold:
    train_idx: np.ndarray
    val_idx: np.ndarray
    val_years: np.ndarray


class YearBlockedCV:
    """Create K folds using **contiguous year blocks** as validation."""

    def __init__(self, n_splits: int = 5, purge_years: int = 0, year_level: int = 1):
        assert n_splits >= 2
        self.n_splits = n_splits
        self.purge_years = int(purge_years)
        self.year_level = year_level

    def split(self, X: pd.DataFrame) -> Iterator[Fold]:
        assert isinstance(X.index, pd.MultiIndex), "YearBlockedCV expects MultiIndex (firm, year)."
        years_all = np.array(sorted(X.index.get_level_values(self.year_level).unique()))
        blocks = np.array_split(years_all, self.n_splits)
        year_arr = X.index.get_level_values(self.year_level).to_numpy()
        for val_years in blocks:
            val_mask = np.isin(year_arr, val_years)
            train_mask = ~val_mask
            if self.purge_years > 0:
                lo, hi = val_years.min(), val_years.max()
                embargo = (year_arr >= lo - self.purge_years) & (year_arr <= hi + self.purge_years)
                train_mask = train_mask & ~embargo
            yield Fold(np.where(train_mask)[0], np.where(val_mask)[0], val_years)


# =============================================================================
# * Loading & preprocessing
# =============================================================================


def load_dataset(
    csv_path: Path, target: str, firm_col: Optional[str], year_col: Optional[str]
) -> pd.DataFrame:
    df = read_table(csv_path, low_memory=False)
    if firm_col is None:
        firm_col = _autodetect(df, ["gvkey", "Firm", "firm", "tic", "permno"]) or "gvkey"
    if year_col is None:
        year_col = _autodetect(df, ["data_year", "fyear", "year", "fiscal_year"]) or "data_year"
    if target not in df.columns:
        raise ValueError(f"Target column '{target}' not in CSV.")
    df[year_col] = pd.to_numeric(df[year_col], errors="coerce").astype("Int64")
    df[target] = pd.to_numeric(df[target], errors="coerce").fillna(0).astype(int)
    df = df.dropna(subset=[firm_col, year_col])
    df = df.set_index([firm_col, year_col]).sort_index()
    return df


def coerce_numeric_like_columns(
    df: pd.DataFrame, percent_as_fraction: bool = False, threshold: float = 0.9
) -> pd.DataFrame:
    obj_cols = df.select_dtypes(include=["object"]).columns.tolist()
    for c in obj_cols:
        s = df[c].astype(str)
        had_pct = s.str.contains("%", regex=False, na=False)
        s2 = s.str.replace(",", "", regex=False).str.replace("%", "", regex=False)
        cand = pd.to_numeric(s2, errors="coerce")
        if cand.notna().mean() >= threshold:
            if percent_as_fraction and had_pct.any():
                cand = cand / 100.0
            df[c] = cand
    return df


def drop_identifier_like_columns(df: pd.DataFrame, identifiers: Sequence[str]) -> pd.DataFrame:
    cols = [c for c in identifiers if c in df.columns]
    return df.drop(columns=cols) if cols else df


def auto_schema(
    df: pd.DataFrame,
    target: str,
    *,
    numeric_to_categorical: bool = False,
    max_unique_for_cat: int = 2,
) -> Tuple[List[str], List[str]]:
    """Infer numeric vs categorical; optionally recast low-cardinality numeric as categorical."""
    X = df.drop(columns=[target])
    # Convert obvious bool-like strings to numeric 0/1
    for c in X.columns:
        if X[c].dtype == object:
            vals = set(pd.Series(X[c].dropna().unique()).astype(str).str.lower())
            if 1 <= len(vals) <= 2 and vals.issubset({"0", "1", "true", "false"}):
                X[c] = (
                    X[c]
                    .map({"0": 0, "1": 1, "true": 1, "false": 0, "True": 1, "False": 0})
                    .astype("float64")
                )
    num_cols = X.select_dtypes(include=[np.number]).columns.tolist()
    cat_cols = [c for c in X.columns if c not in num_cols]
    if numeric_to_categorical:
        recast: List[str] = []
        for c in list(num_cols):
            s = pd.to_numeric(X[c], errors="coerce")
            finite = s[np.isfinite(s)]
            if finite.nunique(dropna=True) <= max_unique_for_cat:
                recast.append(c)
        if recast:
            for c in recast:
                num_cols.remove(c)
            cat_cols.extend(recast)
    return num_cols, cat_cols


def build_preprocessor(
    num_cols: List[str],
    cat_cols: List[str],
    *,
    scale_numeric: bool = False,
    scaler_kind: str = "standard",
    min_cat_freq: int = 25,
    numeric_cleaning: Optional[Dict] = None,
) -> ColumnTransformer:
    cleaning_cfg = numeric_cleaning or {}
    q = cleaning_cfg.get("clip_quantiles")
    q = tuple(q) if isinstance(q, (list, tuple)) else None
    abs_max = cleaning_cfg.get("abs_max")

    num_steps: List[Tuple[str, TransformerMixin]] = [
        ("finite", FiniteCleaner(clip_quantiles=q, abs_max=abs_max, as_dataframe=False)),
        ("imp", SimpleImputer(strategy="median")),
    ]
    if scale_numeric:
        scaler = StandardScaler() if scaler_kind == "standard" else RobustScaler()
        num_steps.append(("scaler", scaler))

    cat_pipe = Pipeline(
        [
            (
                "rare",
                RareCategoryGrouper(min_count=min_cat_freq, rare_token="__RARE__", cols=cat_cols),
            ),
            ("imp", SimpleImputer(strategy="most_frequent")),
            ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )

    pre = ColumnTransformer(
        [
            ("num", Pipeline(num_steps), num_cols),
            ("cat", cat_pipe, cat_cols),
        ],
        remainder="drop",
        sparse_threshold=0.0,
    )
    return pre


# =============================================================================
# * Splitting: out-of-time test, then CV factory
# =============================================================================
@dataclass
class Splits:
    X_train: pd.DataFrame
    y_train: np.ndarray
    X_test: pd.DataFrame
    y_test: np.ndarray
    years_train: np.ndarray
    years_test: np.ndarray


def holdout_time_split(
    df: pd.DataFrame,
    target: str,
    year_level: int,
    test_kind: str = "last_years",
    n_years: Optional[int] = None,
    test_frac_years: Optional[float] = None,
    cutoff_year: Optional[int] = None,
) -> Splits:
    assert isinstance(df.index, pd.MultiIndex)
    years_all = np.array(sorted(df.index.get_level_values(year_level).unique()))
    if test_kind == "last_years":
        if n_years is None and test_frac_years is None:
            n_years = max(1, int(np.ceil(0.2 * len(years_all))))
        if n_years is None:
            n_years = max(1, int(np.ceil(test_frac_years * len(years_all))))
        years_test = years_all[-n_years:]
    elif test_kind == "cutoff":
        assert cutoff_year is not None, "Provide cutoff_year for test_kind='cutoff'"
        years_test = years_all[years_all > cutoff_year]
    else:
        raise ValueError("test_kind must be 'last_years' or 'cutoff'")

    def mask(years_subset):
        return df.index.get_level_values(year_level).isin(years_subset)

    X = df.drop(columns=[target])
    y = df[target].to_numpy()

    X_test, y_test = X[mask(years_test)], y[mask(years_test)]
    X_train, y_train = X[~mask(years_test)], y[~mask(years_test)]
    years_train = np.array(sorted(np.setdiff1d(years_all, years_test)))
    return Splits(X_train, y_train, X_test, y_test, years_train, years_test)


@dataclass
class CVSpec:
    kind: str
    n_splits: int
    n_repeats: int
    shuffle: bool
    purge_years: int


def cv_generator(
    kind: str,
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    groups: Optional[np.ndarray],
    n_splits: int = 5,
    n_repeats: int = 1,
    shuffle: bool = True,
    purge_years: int = 0,
) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
    kind = kind.lower()
    if kind == "year_blocked":
        yb = YearBlockedCV(n_splits=n_splits, purge_years=purge_years, year_level=1)
        for fold in yb.split(X_train):
            yield fold.train_idx, fold.val_idx
    elif kind == "stratified_group_kfold":
        assert groups is not None, "groups (firm ids) are required for StratifiedGroupKFold"
        s = StratifiedGroupKFold(n_splits=n_splits, shuffle=shuffle, random_state=SEED_DEFAULT)
        for tr, va in s.split(X_train, y_train, groups=groups):
            yield tr, va
        for r in range(1, n_repeats):
            s = StratifiedGroupKFold(
                n_splits=n_splits, shuffle=True, random_state=SEED_DEFAULT + r
            )
            for tr, va in s.split(X_train, y_train, groups=groups):
                yield tr, va
    elif kind == "repeated_stratified_kfold":
        rskf = RepeatedStratifiedKFold(
            n_splits=n_splits, n_repeats=n_repeats, random_state=SEED_DEFAULT
        )
        for tr, va in rskf.split(np.zeros(len(y_train)), y_train):
            yield tr, va
    else:
        raise ValueError(
            "cv.kind must be one of {'year_blocked','stratified_group_kfold','repeated_stratified_kfold'}"
        )


# =============================================================================
# * End-to-end runner (no model fit in smoke test)
# =============================================================================


def main(config_path: Path, raw_csv: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    cols = cfg.get("columns", {})
    target = cols.get("target", "misstatement firm-year")
    firm_col = cols.get("firm_col")
    year_col = cols.get("year_col")
    identifiers = cols.get("identifiers", [firm_col, year_col])
    stratify_on = cols.get("stratify_on", "__TARGET__")

    processing = cfg.get("processing", {})
    test_cfg = processing.get("test_split", {"kind": "last_years", "n_years": 3})
    cv_cfg = processing.get(
        "cv",
        {"kind": "year_blocked", "n_splits": 5, "n_repeats": 1, "shuffle": True, "purge_years": 0},
    )
    scale_numeric = bool(processing.get("scale_numeric", False))
    scaler_kind = processing.get("scaler_kind", "standard")
    min_cat_freq = int(processing.get("min_cat_freq", 25))
    autodrop_missing_threshold = float(processing.get("autodrop_missing_threshold", 0.98))
    drop_columns = processing.get("drop_columns", [])

    numeric_cleaning = processing.get(
        "numeric_cleaning", {"replace_inf": True, "clip_quantiles": None, "abs_max": None}
    )
    numeric_coercion = processing.get(
        "numeric_coercion", {"enable": True, "percent_as_fraction": False, "threshold": 0.9}
    )
    numeric_to_categorical_cfg = processing.get(
        "numeric_to_categorical", {"enable": False, "max_unique": 2}
    )

    # Load
    df = load_dataset(raw_csv, target=target, firm_col=firm_col, year_col=year_col)

    if numeric_cleaning.get("replace_inf", True):
        df = df.replace([np.inf, -np.inf], np.nan)

    df_feat = df.drop(
        columns=[c for c in identifiers if c in df.columns]
        + [c for c in drop_columns if c in df.columns]
    )

    if numeric_coercion.get("enable", True):
        df_feat = coerce_numeric_like_columns(
            df_feat,
            percent_as_fraction=bool(numeric_coercion.get("percent_as_fraction", False)),
            threshold=float(numeric_coercion.get("threshold", 0.9)),
        )

    miss_ratio = df_feat.isna().mean()
    too_missing = miss_ratio[miss_ratio > autodrop_missing_threshold].index.tolist()
    if len(too_missing):
        df_feat = df_feat.drop(columns=too_missing)

    splits = holdout_time_split(
        df_feat,
        target=target,
        year_level=1,
        test_kind=test_cfg.get("kind", "last_years"),
        n_years=test_cfg.get("n_years"),
        test_frac_years=test_cfg.get("test_frac_years"),
        cutoff_year=test_cfg.get("cutoff_year"),
    )

    # Schema on TRAIN only
    num_cols, cat_cols = auto_schema(
        pd.concat(
            [splits.X_train, pd.Series(splits.y_train, index=splits.X_train.index, name=target)],
            axis=1,
        ),
        target,
        numeric_to_categorical=bool(numeric_to_categorical_cfg.get("enable", False)),
        max_unique_for_cat=int(numeric_to_categorical_cfg.get("max_unique", 2)),
    )

    # Build preprocessor (available for downstream training scripts)
    build_preprocessor(
        num_cols=num_cols,
        cat_cols=cat_cols,
        scale_numeric=scale_numeric,
        scaler_kind=scaler_kind,
        min_cat_freq=min_cat_freq,
        numeric_cleaning=numeric_cleaning,
    )

    # === CV metrics using PRIOR baseline (no model fit) ===
    cv_kind = cv_cfg.get("kind", "year_blocked")
    n_splits = int(cv_cfg.get("n_splits", 5))
    n_repeats = int(cv_cfg.get("n_repeats", 1))
    shuffle = bool(cv_cfg.get("shuffle", True))
    purge_years = int(cv_cfg.get("purge_years", 0))

    groups_train = splits.X_train.index.get_level_values(0).to_numpy()
    strat_labels = splits.y_train if stratify_on == "__TARGET__" else splits.y_train

    cv_results: List[Dict] = []
    for fold_i, (tr_idx, va_idx) in enumerate(
        cv_generator(
            kind=cv_kind,
            X_train=splits.X_train,
            y_train=strat_labels,
            groups=groups_train,
            n_splits=n_splits,
            n_repeats=n_repeats,
            shuffle=shuffle,
            purge_years=purge_years,
        ),
        start=1,
    ):
        y_tr = splits.y_train[tr_idx]
        y_va = splits.y_train[va_idx]
        prior = float(np.mean(y_tr)) if len(y_tr) else float(np.mean(splits.y_train))
        p_va = np.full_like(y_va, fill_value=prior, dtype=float)
        cv_results.append(
            {
                "fold": fold_i,
                "roc_auc": float(0.5),
                "pr_auc": float(average_precision_score(y_va, p_va)),
                "brier": float(brier_score_loss(y_va, p_va)),
                "n_val": int(len(y_va)),
                "prior": prior,
            }
        )

    # === Test metrics using training PRIOR ===
    prior_full = float(np.mean(splits.y_train))
    p_test = np.full_like(splits.y_test, fill_value=prior_full, dtype=float)
    test_metrics = {
        "roc_auc": float(0.5),
        "pr_auc": float(average_precision_score(splits.y_test, p_test)),
        "brier": float(brier_score_loss(splits.y_test, p_test)),
        "pos_rate_test": float(np.mean(splits.y_test)),
        "train_prior": prior_full,
        "years_test": splits.years_test.tolist(),
    }

    # Persist artifacts
    (out_dir / "schema.json").write_text(
        json.dumps(
            {
                "numeric": num_cols,
                "categorical": cat_cols,
                "dropped_ultra_missing": too_missing,
            },
            indent=2,
        )
    )

    (out_dir / "cv_results.json").write_text(json.dumps(cv_results, indent=2))
    (out_dir / "test_metrics.json").write_text(json.dumps(test_metrics, indent=2))

    # Indices
    def dump_index(df_idx: pd.MultiIndex, path: Path):
        tmp = pd.DataFrame(
            {"firm": df_idx.get_level_values(0), "year": df_idx.get_level_values(1)}
        )
        tmp.to_csv(path, index=False)

    dump_index(splits.X_train.index, out_dir / "train_index.csv")
    dump_index(splits.X_test.index, out_dir / "test_index.csv")

    # Save effective config
    (out_dir / "effective_config.json").write_text(json.dumps(cfg, indent=2))

    # Console summary
    print("=== DATA SUMMARY ===")
    print(f"Train rows: {len(splits.X_train):,} | Test rows: {len(splits.X_test):,}")
    print(
        f"Train years: {splits.years_train[0]}..{splits.years_train[-1]} | Test years: {splits.years_test[0]}..{splits.years_test[-1]}"
    )
    print("=== SCHEMA ===")
    print(
        f"Numeric: {len(num_cols)} | Categorical: {len(cat_cols)} | Dropped ultra-missing: {len(too_missing)}"
    )
    print("=== CV (PRIOR baseline, no model) ===")
    if cv_results:
        mean_pr = np.mean([r["pr_auc"] for r in cv_results])
        mean_brier = np.mean([r["brier"] for r in cv_results])
        mean_prior = np.mean([r["prior"] for r in cv_results])
        print(
            f"Mean PR-AUC: {mean_pr:.3f} | Mean Brier: {mean_brier:.3f} | Mean train prior: {mean_prior:.4f}"
        )
    print("=== TEST (PRIOR baseline) ===")
    print(json.dumps(test_metrics, indent=2))


# =============================================================================
# * CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Misstatement data prep & CV runner")
    p.add_argument("--config", type=str, required=True, help="Path to YAML config")
    p.add_argument("--raw_data", type=str, required=False, help="Path to raw table file")
    p.add_argument("--raw_csv", type=str, required=False, help="Deprecated alias for --raw_data")
    p.add_argument("--out_dir", type=str, required=True, help="Directory to write artifacts")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raw_data = args.raw_data or args.raw_csv
    if raw_data is None:
        raise SystemExit("--raw_data is required")
    main(config_path=Path(args.config), raw_csv=Path(raw_data), out_dir=Path(args.out_dir))
