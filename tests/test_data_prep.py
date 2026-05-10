from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data_prep import (
    FiniteCleaner,
    RareCategoryGrouper,
    YearBlockedCV,
    _autodetect,
    auto_schema,
    build_preprocessor,
    coerce_numeric_like_columns,
    cv_generator,
    drop_identifier_like_columns,
    holdout_time_split,
    load_dataset,
    main,
)
from src.table_io import write_table


def _indexed_training_frame() -> pd.DataFrame:
    rows = []
    for year in range(2018, 2022):
        for firm_id in range(6):
            rows.append(
                {
                    "gvkey": f"g{firm_id}",
                    "data_year": year,
                    "misstatement firm-year": int((year + firm_id) % 2 == 0),
                    "numeric_text": f"{1_000 + firm_id:,}",
                    "pct_text": f"{10 + firm_id}%",
                    "bool_text": "true" if firm_id % 2 == 0 else "false",
                    "category": "common" if firm_id < 4 else f"rare_{firm_id}",
                    "identifier": f"id-{year}-{firm_id}",
                    "mostly_missing": np.nan if firm_id != 0 else 1.0,
                    "inf_feature": np.inf if firm_id == 0 else float(firm_id),
                }
            )
    return pd.DataFrame(rows)


def test_data_prep_transformers_schema_cv_and_main_outputs(tmp_path: Path) -> None:
    raw = _indexed_training_frame()
    raw_path = tmp_path / "raw.parquet"
    write_table(raw, raw_path)
    config_path = tmp_path / "data_prep.yaml"
    out_dir = tmp_path / "out"
    config_path.write_text(
        """
columns:
  target: "misstatement firm-year"
  firm_col: "gvkey"
  year_col: "data_year"
  identifiers: ["identifier"]
processing:
  test_split:
    kind: "cutoff"
    cutoff_year: 2020
  cv:
    kind: "year_blocked"
    n_splits: 2
    purge_years: 0
  scale_numeric: true
  scaler_kind: "robust"
  min_cat_freq: 3
  autodrop_missing_threshold: 0.75
  numeric_cleaning:
    replace_inf: true
    clip_quantiles: [0.05, 0.95]
    abs_max: 10000
  numeric_coercion:
    enable: true
    percent_as_fraction: true
    threshold: 0.5
  numeric_to_categorical:
    enable: true
    max_unique: 2
""",
        encoding="utf-8",
    )

    main(config_path=config_path, raw_csv=raw_path, out_dir=out_dir)

    schema = json.loads((out_dir / "schema.json").read_text())
    metrics = json.loads((out_dir / "test_metrics.json").read_text())
    cv_results = json.loads((out_dir / "cv_results.json").read_text())
    assert "mostly_missing" in schema["dropped_ultra_missing"]
    assert metrics["years_test"] == [2021]
    assert len(cv_results) == 2
    assert (out_dir / "train_index.csv").exists()
    assert (out_dir / "effective_config.json").exists()

    coerced = coerce_numeric_like_columns(
        raw[["numeric_text", "pct_text"]].copy(),
        percent_as_fraction=True,
        threshold=0.5,
    )
    assert coerced["numeric_text"].iloc[0] == 1000
    assert coerced["pct_text"].iloc[0] == 0.10

    cleaner = FiniteCleaner(clip_quantiles=(0.1, 0.9), abs_max=3)
    cleaner.fit(pd.DataFrame({"x": [1.0, 2.0, np.inf, 100.0]}))
    cleaned = cleaner.transform(pd.DataFrame({"x": [1.0, -np.inf, 5.0, 100.0]}))
    assert cleaned.shape == (4, 1)
    assert np.nanmax(cleaned) <= 3

    grouper = RareCategoryGrouper(min_count=10, cols=["category"])
    grouped = grouper.fit(raw[["category"]]).transform(
        pd.DataFrame({"category": ["common", "rare_4", "new"]})
    )
    assert grouped["category"].tolist() == ["common", "__RARE__", "__RARE__"]

    schema_frame = raw[["misstatement firm-year", "bool_text", "inf_feature"]].replace(
        [np.inf, -np.inf], np.nan
    )
    num_cols, cat_cols = auto_schema(
        schema_frame,
        "misstatement firm-year",
        numeric_to_categorical=True,
        max_unique_for_cat=2,
    )
    assert "bool_text" in cat_cols
    assert "inf_feature" in num_cols

    pre = build_preprocessor(
        num_cols=["inf_feature"],
        cat_cols=["category"],
        scale_numeric=True,
        scaler_kind="standard",
        min_cat_freq=2,
    )
    transformed = pre.fit_transform(raw[["inf_feature", "category"]].replace(np.inf, np.nan))
    assert transformed.shape[0] == len(raw)


def test_data_prep_split_and_cv_error_branches() -> None:
    frame = _indexed_training_frame().set_index(["gvkey", "data_year"])
    assert _autodetect(frame.reset_index(), ["missing", "gvkey"]) == "gvkey"
    assert _autodetect(frame.reset_index(), ["missing"]) is None
    pd.testing.assert_frame_equal(
        drop_identifier_like_columns(frame.reset_index(), ["missing"]),
        frame.reset_index(),
    )
    with pytest.raises(ValueError, match="test_kind"):
        holdout_time_split(frame, "misstatement firm-year", year_level=1, test_kind="bad")

    default_split = holdout_time_split(frame, "misstatement firm-year", year_level=1)
    assert default_split.years_test.tolist() == [2021]
    splits = holdout_time_split(
        frame,
        "misstatement firm-year",
        year_level=1,
        test_kind="last_years",
        test_frac_years=0.25,
    )
    assert splits.years_test.tolist() == [2021]

    groups = splits.X_train.index.get_level_values(0).to_numpy()
    group_folds = list(
        cv_generator(
            "stratified_group_kfold",
            splits.X_train,
            splits.y_train,
            groups,
            n_splits=2,
            n_repeats=2,
        )
    )
    repeated_folds = list(
        cv_generator(
            "repeated_stratified_kfold",
            splits.X_train,
            splits.y_train,
            groups=None,
            n_splits=2,
            n_repeats=2,
        )
    )
    assert len(group_folds) == 4
    assert len(repeated_folds) == 4
    purged = list(YearBlockedCV(n_splits=2, purge_years=1).split(frame))
    assert purged
    with pytest.raises(ValueError, match="cv.kind"):
        list(cv_generator("bad", splits.X_train, splits.y_train, groups=None))


def test_load_dataset_autodetects_columns_and_reports_missing_target(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    pd.DataFrame(
        {
            "Firm": ["a", "b", None],
            "fyear": ["2020", "2021", "2021"],
            "label": ["1", None, "0"],
        }
    ).to_csv(raw_path, index=False)
    loaded = load_dataset(raw_path, target="label", firm_col=None, year_col=None)
    assert loaded.index.names == ["Firm", "fyear"]
    assert loaded["label"].tolist() == [1, 0]
    with pytest.raises(ValueError, match="Target column"):
        load_dataset(raw_path, target="missing", firm_col=None, year_col=None)
