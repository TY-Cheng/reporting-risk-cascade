from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.benchmark import (
    _build_detection_year_proxy,
    _merge_external_timing,
    load_master_panel,
    _prepare_xy,
    build_recommendation,
    build_timing_coverage_report,
    compute_structural_breaks,
    compute_metrics,
    compute_window_summary,
    expected_calibration_error,
    fit_missing_profile_model,
    get_feature_columns,
    infer_feature_family,
    render_summary_markdown,
    run_benchmark,
    run_rolling_backtest,
    stable_task_seed,
)
from src.data_prep import load_dataset
from src.sample_dataset import materialize_sample_dataset
from src.table_io import read_table, write_table


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


def test_rolling_backtest_parallel_matches_serial_task_keys() -> None:
    rows = []
    for year in range(2010, 2017):
        for firm_id in range(6):
            rows.append(
                {
                    "gvkey": f"g{firm_id}",
                    "data_year": year,
                    "misstatement firm-year": int((year + firm_id) % 2 == 0),
                    "detection_year_proxy": year,
                    "feature_signal": float(firm_id),
                    "feature_year": float(year - 2000),
                }
            )
    panel = pd.DataFrame(rows)
    kwargs = {
        "panel": panel,
        "firm_col": "gvkey",
        "year_col": "data_year",
        "target_col": "misstatement firm-year",
        "feature_cols": ["feature_signal", "feature_year"],
        "label_modes": ["naive"],
        "candidate_windows": [None, 3],
        "min_train_years": 2,
        "top_k": [2],
        "unknown_positive_strategy": "drop",
        "model_cfg": {"n_estimators": 2, "max_depth": 2, "n_jobs": 1},
        "seed": 42,
        "seed_policy": "task_isolated",
    }

    serial = run_rolling_backtest(**kwargs, parallel_jobs=1)
    parallel = run_rolling_backtest(**kwargs, parallel_jobs=2)
    key_cols = ["window", "label_mode", "test_year"]

    pd.testing.assert_frame_equal(serial.metrics[key_cols], parallel.metrics[key_cols])
    assert len(serial.predictions) == len(parallel.predictions)
    assert set(serial.feature_importance["family"]) == set(parallel.feature_importance["family"])


def test_raw_dataset_csv_and_parquet_paths_are_equivalent(tmp_path: Path) -> None:
    raw = pd.DataFrame(
        [
            {
                "gvkey": "a",
                "data_year": 2020,
                "misstatement firm-year": 0,
                "feature_signal": 1.0,
            },
            {
                "gvkey": "b",
                "data_year": 2020,
                "misstatement firm-year": 1,
                "feature_signal": 2.0,
            },
            {
                "gvkey": "a",
                "data_year": 2021,
                "misstatement firm-year": 1,
                "feature_signal": 3.0,
            },
        ]
    )
    csv_path = tmp_path / "raw_dataset_misstatement.csv"
    parquet_path = tmp_path / "raw_dataset_misstatement.parquet"
    raw.to_csv(csv_path, index=False)
    write_table(raw, parquet_path)

    csv_loaded = load_dataset(
        csv_path,
        target="misstatement firm-year",
        firm_col="gvkey",
        year_col="data_year",
    )
    parquet_loaded = load_dataset(
        parquet_path,
        target="misstatement firm-year",
        firm_col="gvkey",
        year_col="data_year",
    )
    pd.testing.assert_frame_equal(csv_loaded, parquet_loaded)

    csv_panel = load_master_panel(
        csv_path,
        firm_col="gvkey",
        year_col="data_year",
        target_col="misstatement firm-year",
        leakage_cols=[],
        raw_missing_threshold=0.99,
        unknown_positive_strategy="drop",
        timing_csv=None,
        detection_year_col="",
        filing_date_col=None,
    )
    parquet_panel = load_master_panel(
        parquet_path,
        firm_col="gvkey",
        year_col="data_year",
        target_col="misstatement firm-year",
        leakage_cols=[],
        raw_missing_threshold=0.99,
        unknown_positive_strategy="drop",
        timing_csv=None,
        detection_year_col="",
        filing_date_col=None,
    )
    pd.testing.assert_frame_equal(csv_panel, parquet_panel)

    csv_sample = tmp_path / "sample.csv"
    parquet_sample = tmp_path / "sample.parquet"
    materialize_sample_dataset(csv_path, csv_sample, n_firms=1, seed=42)
    materialize_sample_dataset(parquet_path, parquet_sample, n_firms=1, seed=42)
    pd.testing.assert_frame_equal(
        pd.read_csv(csv_sample).reset_index(drop=True),
        read_table(parquet_sample).reset_index(drop=True),
    )


def test_benchmark_end_to_end_toy_run_writes_expected_artifacts(tmp_path: Path) -> None:
    rows = []
    for year in range(2010, 2018):
        for firm_id in range(8):
            rows.append(
                {
                    "gvkey": f"g{firm_id}",
                    "data_year": year,
                    "misstatement firm-year": int((year + firm_id) % 5 == 0),
                    "res_an0": int((year + firm_id) % 5 == 0),
                    "res_an1": 0,
                    "res_an2": 0,
                    "res_an3": 0,
                    "big4": int(firm_id % 2 == 0),
                    "ret_t": float(year - 2000) / 10,
                    "feature_signal": float(firm_id),
                    "mostly_missing": None if firm_id else 1.0,
                }
            )
    raw = pd.DataFrame(rows)
    raw_path = tmp_path / "raw.parquet"
    write_table(raw, raw_path)
    config_path = tmp_path / "benchmark.yaml"
    out_dir = tmp_path / "benchmark"
    config_path.write_text(
        """
columns:
  target: "misstatement firm-year"
  firm_col: "gvkey"
  year_col: "data_year"
  leakage_cols: ["res_an0", "res_an1", "res_an2", "res_an3"]
analysis:
  raw_missing_threshold: 0.95
  unknown_positive_strategy: "drop"
  label_modes: ["naive"]
  candidate_train_windows: [3]
  min_train_years: 2
  top_k: [2]
  break_years: [2013, 2016]
  mixture_k_values: [2]
  dml_treatment_col: "missingness_density_score"
  dml_folds: 2
  recommendation_label_mode: "naive"
  seed: 7
  parallel_jobs: 1
  seed_policy: "task_isolated"
  xgb:
    n_estimators: 2
    max_depth: 2
    learning_rate: 0.2
    n_jobs: 1
    tree_method: "hist"
""",
        encoding="utf-8",
    )

    result = run_benchmark(
        config_path=config_path,
        raw_csv=raw_path,
        out_dir=out_dir,
        parallel_jobs=1,
        model_threads=1,
        seed_policy="task_isolated",
    )

    assert result["recommendation"]["recommended_window"] == "rolling_3y"
    assert (out_dir / "rolling_metrics.csv").exists()
    assert (out_dir / "benchmark_summary.md").read_text(encoding="utf-8").startswith(
        "# Benchmark Summary"
    )
    assert not pd.read_csv(out_dir / "missing_profile_clusters.csv").empty
    assert not pd.read_csv(out_dir / "structural_breaks.csv").empty


def test_benchmark_metric_helpers_cover_degenerate_inputs() -> None:
    assert stable_task_seed(42, "a", 1) == stable_task_seed(42, "a", 1)
    assert expected_calibration_error(
        pd.Series([0, 1, 1]),
        pd.Series([0.1, 0.6, 0.9]),
        n_bins=2,
    ) >= 0
    metrics = compute_metrics(
        pd.Series([0, 0, 0]),
        pd.Series([0.2, 0.2, 0.2]),
        top_k=[1, 5],
    )
    assert pd.isna(metrics["roc_auc"])
    assert metrics["pr_auc"] == pytest.approx(0.0)
    assert metrics["top_1_precision"] == 0.0
    assert metrics["top_5_precision"] == 0.0


def test_benchmark_timing_and_summary_edge_branches(tmp_path: Path) -> None:
    base = pd.DataFrame(
        {
            "gvkey": ["a", "b"],
            "data_year": [2020, 2020],
            "misstatement firm-year": [1, 0],
            "res_an0": [0, 0],
        }
    )
    current = _build_detection_year_proxy(
        base,
        year_col="data_year",
        target_col="misstatement firm-year",
        leakage_cols=["missing_res_an1"],
        unknown_positive_strategy="current_year",
    )
    final = _build_detection_year_proxy(
        base,
        year_col="data_year",
        target_col="misstatement firm-year",
        leakage_cols=["missing_res_an1"],
        unknown_positive_strategy="final_label",
    )
    assert current.loc[0, "detection_source"] == "fallback_current_year"
    assert final.loc[0, "detection_source"] == "fallback_final_label"
    with pytest.raises(ValueError, match="unknown_positive_strategy"):
        _build_detection_year_proxy(
            base,
            year_col="data_year",
            target_col="misstatement firm-year",
            leakage_cols=[],
            unknown_positive_strategy="bad",
        )

    timing_path = tmp_path / "timing.csv"
    pd.DataFrame(
        {
            " gvkey ": ["a"],
            " data_year ": [2020],
            "res_filing_date": ["2022-04-01"],
        }
    ).to_csv(timing_path, index=False)
    merged = _merge_external_timing(
        current,
        timing_path,
        firm_col="gvkey",
        year_col="data_year",
        target_col="misstatement firm-year",
        detection_year_col="detection_year",
        filing_date_col="res_filing_date",
    )
    assert merged.loc[0, "detection_source"] == "external_timing"
    assert int(merged.loc[0, "detection_year_proxy"]) == 2022
    bad_timing = tmp_path / "bad_timing.csv"
    pd.DataFrame({"gvkey": ["a"]}).to_csv(bad_timing, index=False)
    with pytest.raises(ValueError, match="contain 'gvkey' and 'data_year'"):
        _merge_external_timing(
            current,
            bad_timing,
            firm_col="gvkey",
            year_col="data_year",
            target_col="misstatement firm-year",
            detection_year_col="detection_year",
            filing_date_col=None,
        )
    missing_detection = tmp_path / "missing_detection.csv"
    pd.DataFrame({"gvkey": ["a"], "data_year": [2020]}).to_csv(missing_detection, index=False)
    with pytest.raises(ValueError, match="External timing data"):
        _merge_external_timing(
            current,
            missing_detection,
            firm_col="gvkey",
            year_col="data_year",
            target_col="misstatement firm-year",
            detection_year_col="detection_year",
            filing_date_col=None,
        )

    coverage, status = build_timing_coverage_report(
        current,
        target_col="misstatement firm-year",
        leakage_cols=["missing_res_an1"],
    )
    assert status == "proxy_sensitivity"
    assert "missing_column" in set(coverage["value"].astype(str))
    blocked_panel = current.assign(detection_year_proxy=pd.NA, detection_source="none")
    _blocked_coverage, blocked_status = build_timing_coverage_report(
        blocked_panel,
        target_col="misstatement firm-year",
        leakage_cols=[],
    )
    assert blocked_status == "blocked"

    assert infer_feature_family("res_an0") == "timing_proxy"
    assert infer_feature_family("raw_missing_x") == "missingness"
    assert infer_feature_family("ind12") == "industry"
    assert infer_feature_family("big4") == "audit"
    assert infer_feature_family("Boardsize") == "governance"
    assert infer_feature_family("ret_t") == "market"
    assert infer_feature_family("gvkey") == "id"
    assert infer_feature_family("assets") == "accounting"

    with pytest.raises(ValueError, match="label_mode"):
        _prepare_xy(
            current,
            current,
            feature_cols=["res_an0"],
            target_col="misstatement firm-year",
            train_origin_year=2020,
            label_mode="bad",
            unknown_positive_strategy="drop",
        )
    assert compute_window_summary(pd.DataFrame()).empty
    assert compute_structural_breaks(pd.DataFrame(), break_years=[2020]).empty
    with pytest.raises(ValueError, match="No missing-profile"):
        fit_missing_profile_model(
            current,
            target_col="misstatement firm-year",
            k_values=[2],
            seed=1,
        )

    empty_md = render_summary_markdown(
        timing_summary={
            "rows": 2,
            "firms": 2,
            "years": [2020, 2020],
            "positive_rate": 0.5,
            "positive_without_proxy": 1,
            "timing_claim_status": "blocked",
            "detection_source_counts": {},
            "same_row_positive_with_any_res_an": 0,
            "same_row_positive_without_any_res_an": 1,
        },
        window_summary=pd.DataFrame(),
        cluster_summary=pd.DataFrame(),
        dml_result={},
        recommendation={},
    )
    assert "No rolling metrics" in empty_md
    assert build_recommendation(pd.DataFrame(), focus_label_mode="naive") == {}
    fallback_rec = build_recommendation(
        pd.DataFrame(
            {
                "window": ["expanding"],
                "label_mode": ["naive"],
                "pr_auc": [0.2],
                "top_100_precision": [0.1],
            }
        ),
        focus_label_mode="proxy_sensitivity",
    )
    assert fallback_rec["label_mode"] == "naive"
