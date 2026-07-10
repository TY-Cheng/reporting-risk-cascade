from __future__ import annotations

import pandas as pd

from scripts.build_manuscript_package import (
    MIN_VALID_FOLDS_FOR_CI,
    SPARSE_POSITIVE_THRESHOLD,
    _bridge_overlap_matrix,
    _bridge_sample_boundaries,
    _construct_alignment,
    _dispersion_text,
    _public_fold_support,
    _public_task_metrics,
    _task_feature_family_metrics,
)


def test_sparse_fold_display_uses_diagnostic_label_without_interval() -> None:
    row = pd.Series(
        {
            "ci_low": float("nan"),
            "ci_high": float("nan"),
            "fold_min": 0.1,
            "fold_max": 0.2,
            "valid_folds": MIN_VALID_FOLDS_FOR_CI - 1,
        }
    )

    assert _dispersion_text(row) == f"diagnostic only (<{MIN_VALID_FOLDS_FOR_CI} valid folds)"


def test_dispersion_display_uses_interval_when_available() -> None:
    row = pd.Series(
        {
            "ci_low": 0.12345,
            "ci_high": 0.23456,
            "valid_folds": MIN_VALID_FOLDS_FOR_CI,
        }
    )

    assert _dispersion_text(row) == "[0.1235, 0.2346]"


def test_public_task_metrics_include_calibration_diagnostics() -> None:
    metrics = pd.DataFrame(
        {
            "task": ["comment_thread"] * MIN_VALID_FOLDS_FOR_CI,
            "test_year": list(range(2020, 2020 + MIN_VALID_FOLDS_FOR_CI)),
            "positive_rate_test": [0.2] * MIN_VALID_FOLDS_FOR_CI,
            "n_test": [100] * MIN_VALID_FOLDS_FOR_CI,
            "roc_auc": [0.6] * MIN_VALID_FOLDS_FOR_CI,
            "pr_auc": [0.3] * MIN_VALID_FOLDS_FOR_CI,
            "brier": [0.18] * MIN_VALID_FOLDS_FOR_CI,
            "brier_skill_score": [0.05] * MIN_VALID_FOLDS_FOR_CI,
            "ece": [0.04] * MIN_VALID_FOLDS_FOR_CI,
        }
    )

    table = _public_task_metrics(metrics, {"task_positive_counts": {"comment_thread": 100}})

    assert table.loc[0, "Panel_Positives"] == "100"
    assert table.loc[0, "Mean_Brier_Skill"] == "0.0500"
    assert table.loc[0, "Mean_ECE"] == "0.0400"


def test_public_fold_support_marks_sparse_folds() -> None:
    task_status = pd.DataFrame(
        {
            "feature_set": ["all", "metadata"],
            "train_window": ["expanding", "expanding"],
            "test_year": [2024, 2024],
            "task": ["8k_402", "8k_402"],
            "status": ["fit", "fit"],
            "n_train": [1000, 1000],
            "n_test": [100, 100],
            "excluded_train": [0, 0],
            "excluded_test": [0, 0],
            "positive_train": [20, 20],
            "positive_test": [SPARSE_POSITIVE_THRESHOLD - 1, SPARSE_POSITIVE_THRESHOLD - 1],
        }
    )

    table = _public_fold_support(task_status)

    assert table.loc[0, "Task"] == "8k_402"
    assert table.loc[0, "Test_Year"] == "2024"
    assert table.loc[0, "Sparse_Excluded"] == "Yes"


def test_task_feature_family_metrics_preserve_task_dimension() -> None:
    metrics = pd.DataFrame(
        {
            "task": ["amendment"] * MIN_VALID_FOLDS_FOR_CI,
            "feature_set": ["metadata"] * MIN_VALID_FOLDS_FOR_CI,
            "test_year": list(range(2020, 2020 + MIN_VALID_FOLDS_FOR_CI)),
            "positive_rate_test": [0.15] * MIN_VALID_FOLDS_FOR_CI,
            "n_test": [100] * MIN_VALID_FOLDS_FOR_CI,
            "roc_auc": [0.65] * MIN_VALID_FOLDS_FOR_CI,
            "pr_auc": [0.25] * MIN_VALID_FOLDS_FOR_CI,
            "brier_skill_score": [0.02] * MIN_VALID_FOLDS_FOR_CI,
            "ece": [0.05] * MIN_VALID_FOLDS_FOR_CI,
        }
    )

    table = _task_feature_family_metrics(metrics)

    assert table.loc[0, "Task"] == "amendment"
    assert table.loc[0, "Feature_Set"] == "metadata"
    assert table.loc[0, "Mean_PR_AUC"] == "0.2500"


def test_construct_alignment_reports_absolute_precision_and_fdr(tmp_path) -> None:
    overlap_dir = tmp_path / "construct_overlap"
    overlap_dir.mkdir()
    pd.DataFrame(
        {
            "model_id": ["public_cascade"],
            "task": ["8k_402"],
            "feature_set": ["all"],
            "train_window": ["rolling_7y"],
            "label_mode": ["benchmark_naive"],
            "score_aggregation": ["mean"],
            "bridge_tier": ["high_confidence"],
            "n_benchmark_positives_in_overlap": [10],
            "n_benchmark_negatives_in_overlap": [90],
            "roc_auc": [0.7],
            "pr_auc": [0.04],
            "top_1pct_precision": [0.1],
            "top_5pct_precision": [0.08],
            "top_10pct_precision": [0.06],
            "top_decile_lift": [2.0],
            "top_decile_lift_ci_low": [1.2],
            "top_decile_lift_ci_high": [2.8],
            "metric_status": ["fit"],
            "bridge_source": ["wrds"],
        }
    ).to_csv(overlap_dir / "public_score_benchmark_ranking.csv", index=False)
    pd.DataFrame(
        {
            "model_id": ["bao"],
            "target_public_label": ["label_8k_402_365"],
            "feature_set": ["peer"],
            "train_window": ["expanding"],
            "label_mode": ["naive"],
            "score_aggregation": ["benchmark_score"],
            "bridge_tier": ["high_confidence"],
            "n_public_positives_in_overlap": [20],
            "n_public_negatives_in_overlap": [180],
            "roc_auc": [0.6],
            "pr_auc": [0.03],
            "top_1pct_precision": [0.09],
            "top_5pct_precision": [0.07],
            "top_10pct_precision": [0.05],
            "top_decile_lift": [1.8],
            "top_decile_lift_ci_low": [1.1],
            "top_decile_lift_ci_high": [2.5],
            "metric_status": ["fit"],
            "bridge_source": ["wrds"],
        }
    ).to_csv(overlap_dir / "reciprocal_alignment.csv", index=False)

    table = _construct_alignment(tmp_path)

    assert set(table["Top_10pct_Precision"]) == {"0.0600", "0.0500"}
    assert set(table["Top_10pct_FDR"]) == {"0.9400", "0.9500"}
    assert table.loc[table["Direction"].eq("Public score to benchmark positives"), "N"].item() == "100"
    assert table.loc[table["Direction"].eq("Public score to benchmark positives"), "Top_10pct_K"].item() == "10"
    assert table.loc[table["Direction"].eq("Public score to benchmark positives"), "Top_10pct_Hits"].item() == "1"


def test_bridge_sample_boundaries_reports_shares_and_interpretations(tmp_path) -> None:
    overlap_dir = tmp_path / "construct_overlap"
    bridge_dir = tmp_path / "bridge_probe"
    overlap_dir.mkdir()
    bridge_dir.mkdir()
    pd.DataFrame(
        {
            "bridge_tier": ["full_raw", "ambiguous", "dropped", "high_confidence"],
            "rows": [100, 10, 40, 50],
            "benchmark_positives": [20, 2, 8, 10],
        }
    ).to_csv(overlap_dir / "overlap_sample_flow.csv", index=False)
    pd.DataFrame(
        {
            "data_year": [2020, 2021],
            "unmatched_rows": [3, 7],
            "unmatched_positive_rate": [0.1, 0.2],
        }
    ).to_csv(bridge_dir / "unmatched_raw_characteristics.csv", index=False)

    table = _bridge_sample_boundaries(tmp_path)

    high_conf = table.loc[table["Boundary"].eq("high_confidence")].iloc[0]
    assert high_conf["Row_Share"] == "0.5000"
    assert high_conf["Positive_Share"] == "0.5000"
    assert "headline bridge-gated" in high_conf["Interpretation"]
    assert "unmatched_raw" not in set(table["Boundary"])
    assert table.attrs["unmatched_raw_rows"] == 10


def test_bridge_overlap_matrix_keeps_all_public_labels(tmp_path) -> None:
    overlap_dir = tmp_path / "construct_overlap"
    overlap_dir.mkdir()
    pd.DataFrame(
        {
            "public_label": [
                "label_comment_thread_365",
                "label_amendment_365",
                "label_8k_402_365",
            ],
            "bridge_tier": ["high_confidence", "high_confidence", "high_confidence"],
            "n": [100, 100, 100],
            "benchmark_positive_rows": [10, 10, 10],
            "public_positive_rows": [30, 20, 5],
            "both_positive_rows": [4, 5, 2],
            "benchmark_prevalence": [0.1, 0.1, 0.1],
            "public_prevalence": [0.3, 0.2, 0.05],
            "public_rate_given_benchmark_pos": [0.4, 0.5, 0.2],
            "public_rate_given_benchmark_neg": [0.2889, 0.1667, 0.0333],
            "lift_public_given_benchmark": [1.3, 2.5, 4.0],
            "benchmark_rate_given_public_pos": [0.1333, 0.25, 0.4],
            "benchmark_rate_given_public_neg": [0.0857, 0.0625, 0.0842],
            "lift_benchmark_given_public": [1.3, 2.5, 4.0],
        }
    ).to_csv(overlap_dir / "label_contingency_lift.csv", index=False)

    table = _bridge_overlap_matrix(tmp_path)

    assert table["Public_Label"].tolist() == ["comment_thread", "amendment", "8k_402"]
    assert "Public_Rate_If_Benchmark_Pos" in table.columns
