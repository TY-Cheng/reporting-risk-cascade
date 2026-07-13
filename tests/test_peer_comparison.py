from __future__ import annotations

import json
import warnings
from pathlib import Path

import pandas as pd
import pytest

import src.peer_comparison as pc
from src.peer_comparison import (
    IMPORTANCE_COLUMNS,
    MAPPING_COLUMNS,
    PREDICTION_COLUMNS,
    STATUS_COLUMNS,
    aggregate_mapping_quality,
    run_peer_comparison,
    validate_parallel_budget,
)
from src.table_io import read_table, write_table


def _peer_config(tmp_path: Path) -> Path:
    config = tmp_path / "benchmark.yaml"
    config.write_text(
        """
columns:
  target: "misstatement firm-year"
  firm_col: "gvkey"
  year_col: "data_year"
  leakage_cols: ["res_an0", "res_an1", "res_an2", "res_an3"]
analysis:
  raw_missing_threshold: 0.30
  unknown_positive_strategy: "drop"
  label_modes: ["naive"]
  candidate_train_windows: [null, 3]
  min_train_years: 2
  top_k: [1, 2, 50, 100, 200]
  seed: 42
""",
        encoding="utf-8",
    )
    return config


def _peer_raw(tmp_path: Path) -> Path:
    rows = []
    for year in range(2018, 2023):
        for firm_id in range(1, 7):
            rows.append(
                {
                    "gvkey": f"{firm_id:04d}",
                    "data_year": year,
                    "misstatement firm-year": int((firm_id + year) % 4 == 0),
                    "res_an0": 0,
                    "res_an1": 0,
                    "res_an2": 0,
                    "res_an3": 0,
                    "ch_rec": firm_id * 0.01,
                    "ch_inv": (year - 2017) * 0.02,
                    "soft_assets": 0.5 + firm_id * 0.01,
                    "ch_cs": (firm_id % 3) * 0.03,
                    "ch_roa": (year - 2020) * 0.01,
                    "issue": int(firm_id % 2 == 0),
                    "WC_acc": firm_id * 0.02,
                    "ret_t": 0.01 * firm_id,
                    "bm": 0.4 + 0.01 * firm_id,
                    "big4": int(firm_id % 2 == 1),
                }
            )
    raw = tmp_path / "raw.parquet"
    write_table(pd.DataFrame(rows), raw)
    return raw


def _peer_raw_full_mapping(tmp_path: Path) -> Path:
    rows = []
    for year in range(2018, 2022):
        for firm_id in range(1, 13):
            base = firm_id + (year - 2018)
            rows.append(
                {
                    "gvkey": f"{firm_id:04d}",
                    "data_year": year,
                    "misstatement firm-year": int(base % 5 == 0),
                    "res_an0": 0,
                    "res_an1": 0,
                    "res_an2": 0,
                    "res_an3": 0,
                    "rsst_ac": base * 0.01,
                    "ch_rec": firm_id * 0.01,
                    "ch_inv": (year - 2017) * 0.02,
                    "soft_assets": 0.5 + firm_id * 0.01,
                    "ch_cs": (firm_id % 3) * 0.03,
                    "ch_roa": (year - 2020) * 0.01,
                    "issue": int(firm_id % 2 == 0),
                    "WC_acc": firm_id * 0.02,
                    "da": 0.01 * base,
                    "dadif": 0.005 * base,
                    "resid": 0.001 * base,
                    "sresid": 0.002 * base,
                    "ch_cm": 0.01 * (firm_id % 4),
                    "ch_fcf": 0.03 * (firm_id % 5),
                    "tax": int(firm_id % 3 == 0),
                    "leasedum": 1,
                    "oplease": 0.02 * firm_id,
                    "pension": int(firm_id % 4 == 0),
                    "ch_pension": 0.01 * (firm_id % 2),
                    "ch_emp": 0.01 * base,
                    "ch_backlog": 0.02 * base,
                    "exfin": 0.01 * firm_id,
                    "cff": 0.02 * firm_id,
                    "leverage": 0.3 + 0.01 * firm_id,
                    "ret_t": 0.01 * firm_id,
                    "ret_{t-1}": 0.02 * firm_id,
                    "bm": 0.4 + 0.01 * firm_id,
                    "ep": 0.05 + 0.001 * base,
                    "big4": int(firm_id % 2 == 1),
                }
            )
    raw = tmp_path / "raw_full.parquet"
    write_table(pd.DataFrame(rows), raw)
    return raw


def test_mapping_quality_enum_and_budget_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    assert aggregate_mapping_quality(pd.DataFrame()) == "skipped"
    assert (
        aggregate_mapping_quality(
            pd.DataFrame({"mapping_status": ["exact"], "coverage_rate": [0.9]})
        )
        == "full"
    )
    assert (
        aggregate_mapping_quality(
            pd.DataFrame({"mapping_status": ["missing"], "coverage_rate": [None]})
        )
        == "skipped"
    )
    mapping = pd.DataFrame(
        {
            "mapping_status": ["exact", "proxy", "proxy", "missing"],
            "coverage_rate": [0.9, 0.8, 0.75, None],
        }
    )
    assert aggregate_mapping_quality(mapping) == "partial"

    low = pd.DataFrame({"mapping_status": ["exact", "missing"], "coverage_rate": [0.4, None]})
    assert aggregate_mapping_quality(low) == "insufficient"

    with pytest.raises(ValueError, match="mapping_status"):
        aggregate_mapping_quality(
            pd.DataFrame({"mapping_status": ["bad"], "coverage_rate": [1.0]})
        )
    with pytest.raises(ValueError, match="parallel budget exceeds available cores"):
        validate_parallel_budget(parallel_jobs=10_000, model_threads=10_000)
    with pytest.raises(ValueError, match="positive integers"):
        validate_parallel_budget(parallel_jobs=0, model_threads=1)
    with pytest.raises(ValueError, match="positive integers"):
        validate_parallel_budget(parallel_jobs=1, model_threads=0)
    monkeypatch.setenv("PEER_MAX_WORKERS", "1")
    validate_parallel_budget(parallel_jobs=1, model_threads=1)
    with pytest.raises(ValueError, match="parallel budget exceeds available cores"):
        validate_parallel_budget(parallel_jobs=2, model_threads=1)


def test_median_imputer_keeps_empty_features_without_warning() -> None:
    frame = pd.DataFrame({"all_missing": [None, None], "observed": [1.0, 2.0]})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        transformed = pc._median_imputer().fit_transform(frame)
    assert transformed.shape == (2, 2)
    assert not any("Skipping features without any observed values" in str(w.message) for w in caught)


def test_svm_pipeline_uses_convergence_budget() -> None:
    estimator = pc._svm_pipeline(seed=42).named_steps["model"].estimator
    assert estimator.max_iter == 20_000
    assert estimator.tol == 1e-3


def test_peer_comparison_light_mode_writes_pr1_artifacts(tmp_path: Path) -> None:
    out_dir = tmp_path / "peer"
    result = run_peer_comparison(
        config_path=_peer_config(tmp_path),
        raw_data_path=_peer_raw(tmp_path),
        out_dir=out_dir,
        mode="light",
        peer_config={"parallel_jobs": 1, "model_threads": 1},
    )

    assert result["summary_md"].exists()
    manifest = json.loads((out_dir / "peer_comparison_manifest.json").read_text())
    assert manifest["crosswalk_version"] == "not_applicable"
    assert manifest["paper" + "_anchors"] == [
        "dechow2011",
        "perols2011",
        "bao2020",
        "bertomeu2021",
    ]

    status = pd.read_csv(out_dir / "peer_task_status.csv")
    assert list(status.columns) == STATUS_COLUMNS
    assert {"perols_linear_svm", "perols_stacking", "perols_mlp"}.issubset(
        set(status.loc[status["reason_code"].eq("light_mode_disabled"), "peer_model_id"])
    )
    fixed = status.loc[status["peer_model_id"].eq("dechow_fixed_fscore_model1")]
    assert not fixed.empty
    assert set(fixed["status"]) == {"skipped"}

    mapping = pd.read_csv(out_dir / "feature_mapping_attrition.csv")
    assert list(mapping.columns) == MAPPING_COLUMNS
    assert {"sign_convention_match", "construction_match", "scale_match"}.issubset(
        mapping.columns
    )

    metrics = pd.read_csv(out_dir / "detected_misstatement_model_family_metrics.csv")
    required_metric_cols = {
        "peer_model_id",
        "ece",
        "ece_quantile",
        "ece_method",
        "calibration_warning",
        "mapping_attrition_rate",
    }
    assert required_metric_cols.issubset(metrics.columns)
    assert "dechow_variable_logit" in set(metrics["peer_model_id"])
    assert "bao_inspired_tree_ensemble" in set(metrics["peer_model_id"])
    assert "bao_style_ensemble" not in set(metrics["peer_model_id"])

    predictions = read_table(out_dir / "detected_misstatement_model_family_predictions.parquet")
    assert list(predictions.columns) == PREDICTION_COLUMNS
    assert not predictions.duplicated(
        subset=["gvkey", "data_year", "label_mode", "test_year", "train_window", "peer_model_id"]
    ).any()

    importance = pd.read_csv(out_dir / "detected_misstatement_feature_importance.csv")
    assert list(importance.columns) == IMPORTANCE_COLUMNS

    summary = (out_dir / "peer_comparison_summary.md").read_text(encoding="utf-8")
    assert "bao_style_ensemble" in summary
    assert "bao_inspired_tree_ensemble" in summary


def test_peer_comparison_full_mapping_enables_fixed_dechow_and_bao_style(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "peer_full"
    run_peer_comparison(
        config_path=_peer_config(tmp_path),
        raw_data_path=_peer_raw_full_mapping(tmp_path),
        out_dir=out_dir,
        mode="light",
        peer_config={"parallel_jobs": 2, "model_threads": 1, "benchmark_input_kind": "raw_numbers"},
    )

    status = pd.read_csv(out_dir / "peer_task_status.csv")
    metrics = pd.read_csv(out_dir / "detected_misstatement_model_family_metrics.csv")
    assert status.loc[
        status["peer_model_id"].eq("dechow_fixed_fscore_model1"), "status"
    ].eq("fit").any()
    assert "bao_style_ensemble" in set(metrics["peer_model_id"])
    assert "bao_inspired_tree_ensemble" not in set(metrics["peer_model_id"])
    fixed_metrics = metrics.loc[metrics["peer_model_id"].eq("dechow_fixed_fscore_model1")]
    assert set(fixed_metrics["calibration_method"]) == {"fixed_logit_probability"}


def test_peer_comparison_none_mode_and_invalid_mode_write_contract(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "peer_none"
    result = run_peer_comparison(
        config_path=_peer_config(tmp_path),
        raw_data_path=_peer_raw(tmp_path),
        out_dir=out_dir,
        mode="none",
    )
    assert result["manifest_json"].exists()
    assert pd.read_csv(out_dir / "peer_task_status.csv").empty
    assert read_table(out_dir / "detected_misstatement_model_family_predictions.parquet").empty
    assert "peer_comparison_mode_none" in (out_dir / "peer_comparison_summary.md").read_text(
        encoding="utf-8"
    )

    with pytest.raises(ValueError, match="peer comparison mode"):
        run_peer_comparison(
            config_path=_peer_config(tmp_path),
            raw_data_path=_peer_raw(tmp_path),
            out_dir=tmp_path / "bad",
            mode="invalid",
        )


def test_peer_helper_branches_cover_model_gates_and_status_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert pc._git_text(["definitely-not-a-git-command"]) == "unknown"
    assert pc._sigmoid(pd.Series([-100.0, 0.0, 100.0]).to_numpy()).tolist() == pytest.approx(
        [0.0, 0.5, 1.0], abs=1e-12
    )
    assert pc._mapping_attrition_rate(pd.DataFrame()) == 1.0

    X = pd.DataFrame({"x": range(6)})
    y = pd.Series([1, 1, 0, 0, 0, 0]).to_numpy()
    _, sampled_y = pc._apply_undersample_equal(X, y, seed=7)
    assert sampled_y.sum() == 2
    assert len(sampled_y) == 4
    same_X, same_y = pc._apply_undersample_equal(X.iloc[:2], pd.Series([0, 0]).to_numpy(), seed=7)
    assert len(same_X) == len(same_y) == 2

    class DecisionModel:
        def decision_function(self, X_test: pd.DataFrame) -> pd.Series:
            return pd.Series([-1.0, 1.0], index=X_test.index)

    class LabelModel:
        def predict(self, X_test: pd.DataFrame) -> pd.Series:
            return pd.Series([-5.0, 2.0], index=X_test.index)

    assert pc._predict_model(DecisionModel(), pd.DataFrame({"x": [1, 2]}))[1] > 0.5
    assert pc._predict_model(LabelModel(), pd.DataFrame({"x": [1, 2]})).tolist() == [0.0, 1.0]

    coef_model = pc.Pipeline(
        steps=[
            ("model", pc.LogisticRegression().fit(pd.DataFrame({"x": [0, 1, 2, 3]}), [0, 0, 1, 1]))
        ]
    )
    importance = pc._extract_importance(
        coef_model,
        feature_cols=["x"],
        peer_model_id="logit",
        label_mode="naive",
        test_year=2020,
        train_window="expanding",
    )
    assert importance[0]["importance_type"] == "absolute_coefficient"

    no_importance = pc._extract_importance(
        object(),
        feature_cols=["x"],
        peer_model_id="none",
        label_mode="naive",
        test_year=2020,
        train_window="expanding",
    )
    assert no_importance == []

    all_vars = [repo_col for repo_col, _ in pc.DECHOW_MODEL1_COEFFICIENTS.values()]
    train = pd.DataFrame({col: [0.1, 0.2, 0.3, 0.4] for col in all_vars})
    test = pd.DataFrame({col: [0.1, 0.2] for col in all_vars})
    assert pc._dechow_fixed_predict(X_train=train, X_test=test).shape == (2,)

    assert pc._mlp_pipeline(seed=1) is not None
    assert pc._stacking_pipeline(seed=1) is not None

    class FitEcho:
        def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> "FitEcho":
            return self

    monkeypatch.setattr(pc, "_mlp_pipeline", lambda seed: FitEcho())
    monkeypatch.setattr(pc, "_stacking_pipeline", lambda seed: FitEcho())
    assert pc._fit_peer_model({"kind": "mlp"}, X_train=train, y_train=[0, 1, 0, 1], seed=1)
    assert pc._fit_peer_model({"kind": "stacking"}, X_train=train, y_train=[0, 1, 0, 1], seed=1)
    svm_train = pd.DataFrame({col: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6] for col in all_vars})
    assert pc._fit_peer_model({"kind": "svm"}, X_train=svm_train, y_train=[0, 0, 0, 1, 1, 1], seed=1)
    with pytest.raises(ValueError, match="Unknown peer model kind"):
        pc._fit_peer_model({"kind": "unknown"}, X_train=train, y_train=[0, 1, 0, 1], seed=1)


def test_fit_one_spec_status_paths_are_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    panel = read_table(_peer_raw_full_mapping(tmp_path))
    tasks = [(None, 2021, "naive")]
    mapping_full = pd.DataFrame(
        {"mapping_status": ["exact"], "coverage_rate": [1.0], "repo_column": ["ch_rec"]}
    )
    mappings = {"dechow": mapping_full, "dechow_fixed": mapping_full, "bao": mapping_full}

    monkeypatch.setattr(
        pc,
        "_feature_columns_for_spec",
        lambda *args, **kwargs: (["ch_rec"], "bad_quality", 0.0),
    )
    with pytest.raises(ValueError, match="mapping_quality"):
        pc._fit_one_spec(
            spec={"peer_model_id": "perols_logit", "kind": "logit"},
            panel=panel,
            tasks=tasks,
            firm_col="gvkey",
            year_col="data_year",
            target_col="misstatement firm-year",
            feature_cols=["ch_rec"],
            min_train_years=1,
            top_k=[1],
            unknown_positive_strategy="drop",
            seed=42,
            mode="light",
            mapping_by_peer=mappings,
        )

    monkeypatch.undo()
    empty_mapping = pd.DataFrame(
        {"mapping_status": ["missing"], "coverage_rate": [None], "repo_column": [""]}
    )
    rows, metrics, preds, _, _ = pc._fit_one_spec(
        spec={"peer_model_id": "dechow_variable_logit", "kind": "logit"},
        panel=panel,
        tasks=tasks,
        firm_col="gvkey",
        year_col="data_year",
        target_col="misstatement firm-year",
        feature_cols=["ch_rec"],
        min_train_years=1,
        top_k=[1],
        unknown_positive_strategy="drop",
        seed=42,
        mode="light",
        mapping_by_peer={"dechow": empty_mapping, "dechow_fixed": mapping_full, "bao": mapping_full},
    )
    assert rows[0]["reason_code"] == "no_active_features"
    assert metrics == preds == []

    rows, *_ = pc._fit_one_spec(
        spec={"peer_model_id": "perols_logit", "kind": "logit"},
        panel=panel,
        tasks=[(None, 2030, "naive")],
        firm_col="gvkey",
        year_col="data_year",
        target_col="misstatement firm-year",
        feature_cols=["ch_rec"],
        min_train_years=10,
        top_k=[1],
        unknown_positive_strategy="drop",
        seed=42,
        mode="light",
        mapping_by_peer=mappings,
    )
    assert rows[0]["reason_code"] == "insufficient_train_or_test_years"

    one_class = panel.copy()
    one_class["misstatement firm-year"] = 0
    rows, *_ = pc._fit_one_spec(
        spec={"peer_model_id": "perols_logit", "kind": "logit"},
        panel=one_class,
        tasks=tasks,
        firm_col="gvkey",
        year_col="data_year",
        target_col="misstatement firm-year",
        feature_cols=["ch_rec"],
        min_train_years=1,
        top_k=[1],
        unknown_positive_strategy="drop",
        seed=42,
        mode="light",
        mapping_by_peer=mappings,
    )
    assert rows[0]["reason_code"] == "one_class_train_or_empty_features"

    rows, metrics, preds, _, imbalances = pc._fit_one_spec(
        spec={
            "peer_model_id": "perols_logit",
            "kind": "logit",
            "imbalance_strategy": "undersample_equal",
            "class_weight": None,
            "max_iter": 100,
        },
        panel=panel,
        tasks=tasks,
        firm_col="gvkey",
        year_col="data_year",
        target_col="misstatement firm-year",
        feature_cols=["ch_rec"],
        min_train_years=1,
        top_k=[1],
        unknown_positive_strategy="drop",
        seed=42,
        mode="full",
        mapping_by_peer=mappings,
    )
    assert rows[0]["status"] == "fit"
    assert metrics[0]["calibration_warning"] is True
    assert imbalances[0]["pos_train_after"] * 2 == imbalances[0]["n_train_after"]
    assert preds[0]["peer_model_id"].eq("perols_logit").all()

    rows, *_ = pc._fit_one_spec(
        spec={"peer_model_id": "broken", "kind": "unknown"},
        panel=panel,
        tasks=tasks,
        firm_col="gvkey",
        year_col="data_year",
        target_col="misstatement firm-year",
        feature_cols=["ch_rec"],
        min_train_years=1,
        top_k=[1],
        unknown_positive_strategy="drop",
        seed=42,
        mode="light",
        mapping_by_peer=mappings,
    )
    assert rows[0]["reason_code"] == "fit_error:ValueError"
