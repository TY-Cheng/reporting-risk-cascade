from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import scripts.build_manuscript_package as manuscript_module
from scripts.build_reviewer_package import _declared_package_files
from scripts.build_manuscript_package import (
    DML_INTERVAL_NOTE,
    MIN_VALID_FOLDS_FOR_CI,
    PUBLIC_TASK_NOTE,
    SPARSE_POSITIVE_THRESHOLD,
    _bridge_overlap_matrix,
    _bridge_sample_boundaries,
    _construct_alignment,
    _dispersion_text,
    _package_primary_identity,
    _public_fold_support,
    _public_opacity_dml_table,
    _public_sample_attrition_table,
    _public_task_metrics,
    _rel,
    _result_narrative,
    _select_primary_public_metrics,
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
            "feature_set": ["all"] * MIN_VALID_FOLDS_FOR_CI,
            "train_window": ["expanding"] * MIN_VALID_FOLDS_FOR_CI,
            "task": ["comment_thread"] * MIN_VALID_FOLDS_FOR_CI,
            "test_year": [2020, 2021, 2022, 2023, 2024],
            "positive_rate_test": [0.2] * MIN_VALID_FOLDS_FOR_CI,
            "n_test": [100] * MIN_VALID_FOLDS_FOR_CI,
            "roc_auc": [0.6] * MIN_VALID_FOLDS_FOR_CI,
            "pr_auc": [0.10, 0.30, 0.30, 0.30, 0.30],
            "brier": [0.18] * MIN_VALID_FOLDS_FOR_CI,
            "brier_skill_score": [0.05] * MIN_VALID_FOLDS_FOR_CI,
            "ece": [0.04] * MIN_VALID_FOLDS_FOR_CI,
        }
    )
    task_status = pd.DataFrame(
        {
            "feature_set": ["all"] * MIN_VALID_FOLDS_FOR_CI + ["metadata"],
            "train_window": ["expanding"] * (MIN_VALID_FOLDS_FOR_CI + 1),
            "task": ["comment_thread"] * (MIN_VALID_FOLDS_FOR_CI + 1),
            "test_year": [2020, 2021, 2022, 2023, 2024, 2024],
            "status": ["fit"] * (MIN_VALID_FOLDS_FOR_CI + 1),
            "positive_test": [1, 2, 3, 4, 5, 999],
        }
    )

    table = _public_task_metrics(
        metrics,
        task_status,
        {
            "primary_specification": {
                "feature_set": "all",
                "train_window": "expanding",
            },
            "task_positive_counts": {"comment_thread": 100},
        },
    )

    assert table.loc[0, "Panel_Positives"] == "15"
    assert table.loc[0, "Mean_PR_AUC"] == "0.2600"
    assert table.loc[0, "Excluding_2020_PR_AUC"] == "0.3000"
    assert table.loc[0, "Excluding_2020_Delta"] == "0.0400"
    assert table.loc[0, "Mean_Brier_Skill"] == "0.0500"
    assert table.loc[0, "Mean_ECE"] == "0.0400"


@pytest.mark.parametrize(
    "status_rows",
    [
        [
            {
                "feature_set": "all",
                "train_window": "expanding",
                "task": "comment_thread",
                "test_year": 2024,
                "status": "fit",
                "positive_test": 2,
            },
            {
                "feature_set": "all",
                "train_window": "expanding",
                "task": "comment_thread",
                "test_year": 2024,
                "status": "fit",
                "positive_test": 2,
            },
        ],
        [],
        [
            {
                "feature_set": "all",
                "train_window": "expanding",
                "task": "comment_thread",
                "test_year": 2024,
                "status": "fit",
                "positive_test": 2,
            },
            {
                "feature_set": "all",
                "train_window": "expanding",
                "task": "comment_thread",
                "test_year": 2023,
                "status": "fit",
                "positive_test": 1,
            },
        ],
    ],
    ids=["duplicate", "missing", "extra"],
)
def test_public_task_metrics_rejects_non_bijective_fit_ownership(
    status_rows: list[dict[str, object]],
) -> None:
    metrics = pd.DataFrame(
        {
            "feature_set": ["all"],
            "train_window": ["expanding"],
            "task": ["comment_thread"],
            "test_year": [2024],
            "positive_rate_test": [0.02],
            "n_test": [100],
            "roc_auc": [0.6],
            "pr_auc": [0.2],
            "brier": [0.02],
            "brier_skill_score": [0.05],
            "ece": [0.01],
        }
    )

    with pytest.raises(ValueError, match="one-to-one fit ownership"):
        _public_task_metrics(
            metrics,
            pd.DataFrame(status_rows),
            {
                "primary_specification": {
                    "feature_set": "all",
                    "train_window": "expanding",
                }
            },
        )


def test_public_task_note_defines_excluding_2020_test_fold_sensitivity() -> None:
    assert "all + expanding" in PUBLIC_TASK_NOTE
    assert "2020 test fold" in PUBLIC_TASK_NOTE
    assert "training specifications are unchanged" in PUBLIC_TASK_NOTE
    assert "one-to-one fit-owner rows" in PUBLIC_TASK_NOTE


def test_select_primary_public_metrics_excludes_grid_distractors() -> None:
    metrics = pd.DataFrame(
        {
            "feature_set": ["all", "all", "metadata"],
            "train_window": ["expanding", "rolling_7y", "expanding"],
            "task": ["comment_thread"] * 3,
            "test_year": [2021, 2021, 2021],
            "pr_auc": [0.30, 0.90, 0.80],
        }
    )
    summary = {
        "primary_specification": {"feature_set": "all", "train_window": "expanding"}
    }

    selected = _select_primary_public_metrics(metrics, summary)

    assert selected[["feature_set", "train_window", "pr_auc"]].to_dict("records") == [
        {"feature_set": "all", "train_window": "expanding", "pr_auc": 0.30}
    ]


def test_primary_public_package_identity_records_summary_contract() -> None:
    identity = _package_primary_identity(
        {"primary_specification": {"feature_set": "all", "train_window": "expanding"}}
    )

    assert identity == {
        "primary_public_specification": {
            "feature_set": "all",
            "train_window": "expanding",
        }
    }


def test_results_narrative_renders_external_component_path_privately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    external_root = tmp_path / "private-fixture-root"
    external_output = external_root / "public_cascade"
    monkeypatch.setattr(manuscript_module, "PROJECT_ROOT", repo_root)
    public_task = pd.DataFrame(
        {
            "Task": ["comment_thread", "amendment", "8k_402"],
            "Mean_PR_AUC": ["0.3000", "0.2000", "0.1000"],
        }
    )

    narrative = _result_narrative(
        manifest={
            "generated_at_utc": "2026-07-10T00:00:00Z",
            "components": {"public_cascade": {"out_dir": str(external_output)}},
        },
        public_summary={
            "primary_specification": {"feature_set": "all", "train_window": "expanding"}
        },
        public_task=public_task,
        benchmark_peer=pd.DataFrame(),
        public_peer=pd.DataFrame(),
        construct_alignment=pd.DataFrame(),
        construct_manifest={"validation_tier": "fixture"},
    )

    assert str(external_output) not in narrative
    assert str(external_root) not in narrative
    assert str(tmp_path) not in narrative
    assert "`<external>/public_cascade`" in narrative


def test_external_manifest_paths_are_private_and_basename_resolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    external_root = tmp_path / "private-fixture-root"
    monkeypatch.setattr(manuscript_module, "PROJECT_ROOT", repo_root)
    package_manifest = {
        "study_dir": _rel(external_root / "study"),
        "out_dir": _rel(external_root / "manuscript_package"),
        "tables": {"table_03": {"csv": _rel(external_root / "tables" / "table_03.csv")}},
        "figures": {"figure_01": {"png": _rel(external_root / "figures" / "figure_01.png")}},
    }

    assert package_manifest["study_dir"] == "<external>/study"
    assert package_manifest["out_dir"] == "<external>/manuscript_package"
    assert package_manifest["tables"]["table_03"]["csv"] == "<external>/table_03.csv"
    assert package_manifest["figures"]["figure_01"]["png"] == "<external>/figure_01.png"
    assert str(tmp_path) not in str(package_manifest)
    assert _declared_package_files(package_manifest) == {
        "results_narrative.md",
        "tables/table_03.csv",
        "figures/figure_01.png",
    }
    assert _rel(repo_root / "artifacts" / "table.csv") == "artifacts/table.csv"


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
            "is_primary": [True],
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
            "is_primary": [True],
        }
    ).to_csv(overlap_dir / "reciprocal_alignment.csv", index=False)

    table = _construct_alignment(tmp_path)

    assert set(table["Top_10pct_Precision"]) == {"0.0600", "0.0500"}
    assert set(table["Top_10pct_FDR"]) == {"0.9400", "0.9500"}
    assert table.loc[table["Direction"].eq("Public score to benchmark positives"), "N"].item() == "100"
    assert table.loc[table["Direction"].eq("Public score to benchmark positives"), "Top_10pct_K"].item() == "10"
    assert table.loc[table["Direction"].eq("Public score to benchmark positives"), "Top_10pct_Hits"].item() == "1"


def test_construct_alignment_uses_is_primary_not_maximum_lift(tmp_path: Path) -> None:
    overlap_dir = tmp_path / "construct_overlap"
    overlap_dir.mkdir()
    common = {
        "bridge_tier": "high_confidence",
        "metric_status": "fit",
        "bridge_source": "wrds",
        "roc_auc": 0.70,
        "pr_auc": 0.04,
        "top_1pct_precision": 0.10,
        "top_5pct_precision": 0.08,
        "top_10pct_precision": 0.06,
        "top_decile_lift_ci_low": 1.20,
        "top_decile_lift_ci_high": 2.80,
    }
    pd.DataFrame(
        [
            {
                **common,
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "expanding",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "n_benchmark_positives_in_overlap": 10,
                "n_benchmark_negatives_in_overlap": 90,
                "top_decile_lift": 2.0,
                "is_primary": True,
            },
            {
                **common,
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "rolling_7y",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "n_benchmark_positives_in_overlap": 10,
                "n_benchmark_negatives_in_overlap": 90,
                "top_decile_lift": 9.0,
                "is_primary": False,
            },
        ]
    ).to_csv(overlap_dir / "public_score_benchmark_ranking.csv", index=False)
    pd.DataFrame(
        [
            {
                **common,
                "model_id": "benchmark_xgb",
                "target_public_label": "label_8k_402_365",
                "feature_set": "benchmark_all",
                "train_window": "expanding",
                "label_mode": "naive",
                "score_aggregation": "benchmark_score",
                "n_public_positives_in_overlap": 20,
                "n_public_negatives_in_overlap": 180,
                "top_decile_lift": 1.8,
                "is_primary": True,
            },
            {
                **common,
                "model_id": "benchmark_xgb",
                "target_public_label": "label_8k_402_365",
                "feature_set": "benchmark_all",
                "train_window": "rolling_7y",
                "label_mode": "naive",
                "score_aggregation": "benchmark_score",
                "n_public_positives_in_overlap": 20,
                "n_public_negatives_in_overlap": 180,
                "top_decile_lift": 8.0,
                "is_primary": False,
            },
        ]
    ).to_csv(overlap_dir / "reciprocal_alignment.csv", index=False)

    table = _construct_alignment(tmp_path)

    assert set(table["Window"]) == {"expanding"}
    assert set(table["Top_Decile_Lift"]) == {"2.0000", "1.8000"}


def test_public_sample_attrition_preserves_sequence_and_task_branches() -> None:
    summary = {
        "sample_attrition": [
            {"stage": "source_issuer_origin", "n_rows": 100, "task": "all"},
            {"stage": "fiscal_year_2011_2024", "n_rows": 80, "task": "all"},
            {"stage": "domestic_us_gaap_proxy", "n_rows": 75, "task": "all"},
            {"stage": "observable_365_day_horizon", "n_rows": 70, "task": "all"},
            {"stage": "eligible_comment_thread", "n_rows": 68, "task": "comment_thread"},
            {"stage": "eligible_amendment", "n_rows": 69, "task": "amendment"},
            {"stage": "eligible_8k_402", "n_rows": 65, "task": "8k_402"},
        ]
    }

    table = _public_sample_attrition_table(summary).set_index("Stage")

    assert table.loc["source_issuer_origin", "Dropped_From_Parent"] == 0
    assert table.loc["fiscal_year_2011_2024", "Dropped_From_Parent"] == 20
    assert table.loc["observable_365_day_horizon", "Dropped_From_Parent"] == 5
    assert table.loc["eligible_comment_thread", "Dropped_From_Parent"] == 2
    assert table.loc["eligible_amendment", "Dropped_From_Parent"] == 1
    assert table.loc["eligible_8k_402", "Dropped_From_Parent"] == 5


def test_public_opacity_dml_displays_explicit_dimensions_and_nan(tmp_path: Path) -> None:
    cascade_dir = tmp_path / "public_cascade"
    cascade_dir.mkdir()
    pd.DataFrame(
        {
            "outcome": ["comment_thread", "amendment"],
            "status": ["fit", "skipped_one_class_or_too_small"],
            "n_obs": [100, 100],
            "prevalence": [0.10, 0.00],
            "coef": [0.02, float("nan")],
            "std_err": [0.01, float("nan")],
            "p_value": [0.05, float("nan")],
            "n_raw_controls": [60, 60],
            "n_encoded_controls": [64, float("nan")],
            "n_opacity_components": [17, 17],
        }
    ).to_csv(cascade_dir / "public_opacity_dml.csv", index=False)

    table = _public_opacity_dml_table(tmp_path)

    assert table[["Raw_Controls", "Encoded_Controls", "Opacity_Components"]].to_dict(
        "records"
    ) == [
        {"Raw_Controls": "60", "Encoded_Controls": "64", "Opacity_Components": "17"},
        {"Raw_Controls": "60", "Encoded_Controls": "", "Opacity_Components": "17"},
    ]
    assert DML_INTERVAL_NOTE == (
        "Raw controls are source variables before encoding; encoded controls are nuisance-model "
        "columns reported at the maximum fold-local width after training-fold categorical "
        "expansion and imputation; opacity components form the missingness-density treatment. "
        "Intervals use HC3 residual OLS after cross-fitting. The estimates are adjusted "
        "associations, not identified structural effects."
    )


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
