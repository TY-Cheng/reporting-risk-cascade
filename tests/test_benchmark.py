from __future__ import annotations

import pandas as pd

from src.benchmark import (
    _build_detection_year_proxy,
    _prepare_xy,
    build_timing_coverage_report,
    get_feature_columns,
)


def _toy_timing_panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gvkey": ["a", "b", "c", "d", "e", "f"],
            "data_year": [2018, 2018, 2018, 2018, 2018, 2018],
            "misstatement firm-year": [1, 1, 1, 1, 1, 0],
            "res_an0": [1, 0, 0, 0, 0, 0],
            "res_an1": [0, 1, 0, 0, 0, 0],
            "res_an2": [0, 0, 1, 0, 0, 0],
            "res_an3": [0, 0, 0, 1, 0, 0],
            "feature_signal": [1, 2, 3, 4, 5, 6],
        }
    )


def test_detection_year_proxy_uses_res_an_offsets_and_preserves_unknowns() -> None:
    panel = _build_detection_year_proxy(
        _toy_timing_panel(),
        year_col="data_year",
        target_col="misstatement firm-year",
        leakage_cols=["res_an0", "res_an1", "res_an2", "res_an3"],
        unknown_positive_strategy="drop",
    )

    assert panel["detection_year_proxy"].iloc[:4].astype(int).tolist() == [
        2018,
        2019,
        2020,
        2021,
    ]
    assert pd.isna(panel.loc[4, "detection_year_proxy"])
    assert pd.isna(panel.loc[5, "detection_year_proxy"])
    assert int(panel["positive_without_proxy"].sum()) == 1
    assert panel.loc[4, "detection_source"] == "unknown_positive"


def test_proxy_sensitivity_labels_use_only_detection_visible_by_train_origin() -> None:
    panel = _build_detection_year_proxy(
        _toy_timing_panel(),
        year_col="data_year",
        target_col="misstatement firm-year",
        leakage_cols=["res_an0", "res_an1", "res_an2", "res_an3"],
        unknown_positive_strategy="drop",
    )

    x_train, y_train, _x_test, _y_test = _prepare_xy(
        panel,
        panel,
        feature_cols=["feature_signal"],
        target_col="misstatement firm-year",
        train_origin_year=2019,
        label_mode="proxy_sensitivity",
        unknown_positive_strategy="drop",
    )

    assert len(x_train) == 5
    assert y_train.tolist() == [1, 1, 0, 0, 0]


def test_res_an_timing_proxies_do_not_enter_benchmark_features() -> None:
    panel = _build_detection_year_proxy(
        _toy_timing_panel(),
        year_col="data_year",
        target_col="misstatement firm-year",
        leakage_cols=["res_an0", "res_an1", "res_an2", "res_an3"],
        unknown_positive_strategy="drop",
    )

    feature_cols = get_feature_columns(
        panel,
        firm_col="gvkey",
        year_col="data_year",
        target_col="misstatement firm-year",
        leakage_cols=["res_an0", "res_an1", "res_an2", "res_an3"],
    )

    assert "feature_signal" in feature_cols
    assert not any(col.startswith("res_an") for col in feature_cols)


def test_timing_coverage_report_labels_proxy_maturation_as_sensitivity() -> None:
    panel = _build_detection_year_proxy(
        _toy_timing_panel(),
        year_col="data_year",
        target_col="misstatement firm-year",
        leakage_cols=["res_an0", "res_an1", "res_an2", "res_an3"],
        unknown_positive_strategy="drop",
    )

    coverage, status = build_timing_coverage_report(
        panel,
        target_col="misstatement firm-year",
        leakage_cols=["res_an0", "res_an1", "res_an2", "res_an3"],
    )
    summary = coverage.loc[coverage["section"].eq("summary")].set_index("metric")["value"]

    assert status == "proxy_sensitivity"
    assert int(summary["positive_rows"]) == 5
    assert int(summary["same_row_positive_with_any_res_an"]) == 4
    assert int(summary["same_row_positive_without_any_res_an"]) == 1
    assert int(summary["positive_without_detection_proxy"]) == 1
