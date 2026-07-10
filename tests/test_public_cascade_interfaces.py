from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import fetch_public_data
from src.public_cascade import (
    VISIBILITY_HISTORY_FEATURES,
    _sample_attrition,
    build_public_missingness_density_score,
    fit_public_opacity_dml,
    _build_preprocessor,
    _evaluate_binary,
    _infer_feature_families,
    _prepare_xy,
    _public_dml_matrix,
    _resolve_primary_specification,
    _run_public_cascade_unit,
    _validate_primary_metric_rows,
    run_public_cascade,
)
from src.table_io import read_table, write_table


def test_public_cascade_feature_families_exclude_labels_availability_and_identifiers() -> None:
    panel = pd.DataFrame(
        {
            "issuer_cik": ["0000000001"],
            "fiscal_year": [2022],
            "sic": [1234],
            "form": ["10-K"],
            "items": ["1.01,4.02"],
            "source_available_notes": [1],
            "public_date_notes": ["2020-11-01"],
            "vintage_notes": ["2020-11+"],
            "label_comment_thread_365": [0],
            "censored_365": [0],
            "label_amendment_365": [0],
            "label_8k_402_365": [0],
            "k402_item_metadata_unknown_365": [1],
            "xbrl_fact_count": [10],
            "note_text_count": [1],
            "form_ap_event_count": [1],
            "auditor_partner_prior_other_issuer_8k_402_count": [1],
            "prior_comment_thread_count": [1],
        }
    )

    families = _infer_feature_families(panel)

    all_features = set(families["all"])
    assert "sic" in families["metadata"]
    assert "xbrl_fact_count" in families["xbrl"]
    assert "note_text_count" in families["text"]
    assert "form_ap_event_count" in families["auditor"]
    assert "auditor_partner_prior_other_issuer_8k_402_count" in families["auditor"]
    assert "prior_comment_thread_count" in families["oversight"]
    assert "items" not in all_features
    assert "source_available_notes" not in all_features
    assert "public_date_notes" not in all_features
    assert "vintage_notes" not in all_features
    assert "label_comment_thread_365" not in all_features
    assert "censored_365" not in all_features
    assert "k402_item_metadata_unknown_365" not in all_features


def test_visibility_history_is_exact_and_reports_unavailable_fields() -> None:
    panel = pd.DataFrame(
        {
            "size": [100],
            "form": ["10-K"],
            "entity_type": ["operating"],
            "isXBRL": [1],
            "days_since_previous_filing": [365],
            "prior_filing_count": [8],
            "filing_friction_is_nt": [0],
            "public_history_comment_thread_1y_count": [1],
            "public_history_8k_402_3y_count": [0],
            "label_comment_thread_365": [0],
            "source_available_notes": [1],
            "xbrl_ratio_leverage": [0.2],
        }
    )

    families = _infer_feature_families(panel)

    assert families["visibility_history"] == [
        "size",
        "form",
        "entity_type",
        "isXBRL",
        "days_since_previous_filing",
        "prior_filing_count",
        "filing_friction_is_nt",
        "public_history_comment_thread_1y_count",
        "public_history_8k_402_3y_count",
    ]
    assert "xbrl_ratio_leverage" not in families["visibility_history"]
    assert "source_available_notes" not in families["visibility_history"]


def test_visibility_history_contract_is_complete_and_ordered() -> None:
    assert VISIBILITY_HISTORY_FEATURES == (
        "size",
        "core_type",
        "form",
        "entity_type",
        "isXBRL",
        "isInlineXBRL",
        "isXBRLNumeric",
        "days_since_previous_filing",
        "prior_filing_count",
        "filing_friction_is_nt",
        "filing_friction_nt_pre_origin",
        "filing_friction_nt_delay_days",
        "public_history_comment_thread_1y_count",
        "public_history_comment_thread_3y_count",
        "public_history_amendment_1y_count",
        "public_history_amendment_3y_count",
        "public_history_8k_301_1y_count",
        "public_history_8k_301_3y_count",
        "public_history_8k_401_1y_count",
        "public_history_8k_401_3y_count",
        "public_history_8k_402_1y_count",
        "public_history_8k_402_3y_count",
        "public_history_8k_502_1y_count",
        "public_history_8k_502_3y_count",
    )


def test_primary_specification_requires_configured_family_and_window() -> None:
    resolved = _resolve_primary_specification(
        {"primary_specification": {"feature_set": "all", "train_window": "expanding"}},
        requested_families=["metadata", "all"],
        train_windows=[None, 5, 7, 10],
    )
    assert resolved == {"feature_set": "all", "train_window": "expanding"}

    with pytest.raises(ValueError, match="primary feature_set"):
        _resolve_primary_specification(
            {"primary_specification": {"feature_set": "missing", "train_window": "expanding"}},
            requested_families=["all"],
            train_windows=[None],
        )

    with pytest.raises(ValueError, match="primary train_window"):
        _resolve_primary_specification(
            {"primary_specification": {"feature_set": "all", "train_window": "rolling_99y"}},
            requested_families=["all"],
            train_windows=[None, 5, 7, 10],
        )


def test_primary_metric_rows_fail_closed_but_allow_all_empty_diagnostics() -> None:
    primary = {"feature_set": "all", "train_window": "expanding"}
    missing_identity = pd.DataFrame(
        {
            "feature_set": ["all"],
            "task": ["comment_thread"],
            "test_year": [2021],
        }
    )
    with pytest.raises(ValueError, match="lacks primary identity columns"):
        _validate_primary_metric_rows(missing_identity, primary)

    missing = pd.DataFrame(
        {
            "feature_set": ["metadata"],
            "train_window": ["expanding"],
            "task": ["comment_thread"],
            "test_year": [2021],
        }
    )
    with pytest.raises(ValueError, match="produced no metric rows"):
        _validate_primary_metric_rows(missing, primary)

    duplicated = pd.DataFrame(
        {
            "feature_set": ["all", "all"],
            "train_window": ["expanding", "expanding"],
            "task": ["comment_thread", "comment_thread"],
            "test_year": [2021, 2021],
        }
    )
    with pytest.raises(ValueError, match="duplicated task-year"):
        _validate_primary_metric_rows(duplicated, primary)

    empty = pd.DataFrame(columns=["feature_set", "train_window", "task", "test_year"])
    assert _validate_primary_metric_rows(empty, primary).empty


def test_sic_is_treated_as_categorical_feature() -> None:
    panel = pd.DataFrame({"sic": [1234, 5678], "xbrl_fact_count": [1.0, 2.0]})
    preprocessor = _build_preprocessor(panel, ["sic", "xbrl_fact_count"])
    categorical_cols = preprocessor.transformers[1][2]
    assert "sic" in categorical_cols


def test_public_cascade_tree_preprocessor_preserves_numeric_missing_values() -> None:
    panel = pd.DataFrame(
        {
            "sic": [1234, None, 5678],
            "xbrl_ratio_leverage": [0.2, np.nan, 0.5],
            "form_ap_filing_count": pd.Series([1, pd.NA, 3], dtype="Int64"),
        }
    )
    feature_cols = ["xbrl_ratio_leverage", "form_ap_filing_count", "sic"]
    preprocessor = _build_preprocessor(panel, feature_cols)
    transformed = preprocessor.fit_transform(panel[feature_cols])
    dense = transformed.toarray() if hasattr(transformed, "toarray") else transformed

    numeric_block = np.asarray(dense)[:, :2].astype(float)
    assert np.isnan(numeric_block[1, 0])
    assert np.isnan(numeric_block[1, 1])


def test_public_cascade_helper_branches_cover_degenerate_cases() -> None:
    degenerate = _evaluate_binary(pd.Series([0, 0]).to_numpy(), pd.Series([0.1, 0.2]).to_numpy())
    assert pd.isna(degenerate["roc_auc"])
    assert pd.isna(degenerate["pr_auc"])
    assert degenerate["brier_null"] == 0.0
    assert pd.isna(degenerate["brier_skill_score"])
    assert degenerate["bao_top_1pct_k"] == 0
    assert degenerate["bao_top_1pct_ndcg"] == 0.0

    informative = _evaluate_binary(
        pd.Series([0, 1]).to_numpy(),
        pd.Series([0.1, 0.9]).to_numpy(),
    )
    assert informative["brier_null"] == pytest.approx(0.25)
    assert informative["brier_skill_score"] > 0
    assert "ece" in informative
    assert "ece_quantile" in informative
    assert "top_50_precision" in informative

    x, y = _prepare_xy(
        pd.DataFrame({"feature": ["1", "bad"], "label": ["1", None]}),
        feature_cols=["feature"],
        label_col="label",
    )
    assert x["feature"].tolist() == ["1", "bad"]
    assert y.tolist() == [1, 0]

    base_panel = pd.DataFrame(
        {
            "fiscal_year": [2020, 2021],
            "sic": [1234, 1234],
            "label_comment_thread_365": [0, 0],
            "label_amendment_365": [0, 0],
            "label_8k_402_365": [0, 0],
            "censored_365": [0, 0],
        }
    )
    assert (
        _run_public_cascade_unit(
            panel=base_panel,
            task_order=0,
            family="metadata",
            feature_cols=["sic"],
            window=None,
            test_year=2030,
            train_years=[2020],
            seed=1,
            model_cfg={"xgb": {"n_estimators": 1, "n_jobs": 1}},
            seed_policy="shared",
        )
        is None
    )
    all_missing_feature = base_panel.assign(empty_feature=pd.NA)
    assert (
        _run_public_cascade_unit(
            panel=all_missing_feature,
            task_order=0,
            family="metadata",
            feature_cols=["empty_feature"],
            window=None,
            test_year=2021,
            train_years=[2020],
            seed=1,
            model_cfg={"xgb": {"n_estimators": 1, "n_jobs": 1}},
            seed_policy="shared",
        )
        is None
    )


def test_sample_attrition_is_sequential_and_task_specific() -> None:
    panel = pd.DataFrame(
        {
            "fiscal_year": [2010, 2011, 2011, 2011, 2011],
            "is_domestic_us_gaap_proxy": [1, 0, 1, 1, 1],
            "censored_365": [0, 0, 1, 0, 0],
            "label_comment_thread_365": [0, 0, 0, 1, 0],
            "label_amendment_365": [0, 0, 0, 0, 1],
            "label_8k_402_365": [0, 0, 0, 1, 0],
            "k402_item_metadata_unknown_365": [0, 0, 0, 1, 0],
        }
    )

    attrition = _sample_attrition(
        panel,
        start_year=2011,
        end_year=2024,
        domestic_only=True,
    ).set_index("stage")

    assert attrition.loc["source_issuer_origin", "n_rows"] == 5
    assert attrition.loc["fiscal_year_2011_2024", "n_rows"] == 4
    assert attrition.loc["domestic_us_gaap_proxy", "n_rows"] == 3
    assert attrition.loc["observable_365_day_horizon", "n_rows"] == 2
    assert attrition.loc["eligible_comment_thread", "n_rows"] == 2
    assert attrition.loc["eligible_8k_402", "n_rows"] == 1


def test_public_opacity_dml_uses_public_labels_not_benchmark_misstatement() -> None:
    rows = []
    for year in range(2011, 2017):
        for issuer_id in range(12):
            opaque = int(issuer_id % 3 == 0)
            rows.append(
                {
                    "issuer_cik": f"{issuer_id:010d}",
                    "accession": f"{issuer_id:010d}-{year}-000001",
                    "origin_date": f"{year + 1}-03-01",
                    "fiscal_year": year,
                    "form": "10-K",
                    "sic": 1200 + issuer_id,
                    "is_domestic_us_gaap_proxy": 1,
                    "xbrl_coverage_assets": 1 - opaque,
                    "note_text_count": 0 if opaque else 3,
                    "xbrl_ratio_leverage": 0.1 + issuer_id / 100,
                    "prior_filing_count": year - 2010,
                    "label_comment_thread_365": int(opaque or (year + issuer_id) % 7 == 0),
                    "label_amendment_365": int(opaque and year % 2 == 0),
                    "label_8k_402_365": int(opaque and issuer_id % 2 == 0),
                    "censored_365": 0,
                }
            )
    rows.append(
        {
            **rows[0],
            "issuer_cik": "9999999999",
            "accession": "9999999999-2011-000001",
            "censored_365": pd.NA,
        }
    )
    panel = pd.DataFrame(rows)
    panel.loc[0, "form"] = "20-F"
    scored, components = build_public_missingness_density_score(panel)
    dml, meta = fit_public_opacity_dml(
        scored,
        outcomes=["comment_thread", "amendment", "8k_402"],
        seed=42,
        n_splits=3,
        max_iter=5,
    )

    assert components
    assert set(dml["status"]) == {"fit"}
    assert (dml["n_obs"] == len(rows) - 1).all()
    assert (dml["n_raw_controls"] == len(meta["control_columns"])).all()
    assert (dml["n_encoded_controls"] == dml["n_controls"]).all()
    assert set(dml["n_controls_definition"]) == {"maximum_fold_local_encoded_nuisance_columns"}
    assert meta["n_raw_controls"] == len(meta["control_columns"])
    assert meta["n_controls_definition"] == "maximum_fold_local_encoded_nuisance_columns"
    for row in dml.itertuples(index=False):
        assert meta["n_encoded_controls_by_outcome"][row.outcome] == row.n_encoded_controls
        fold_widths = meta["n_encoded_controls_by_fold"][row.outcome]
        assert [record["fold_id"] for record in fold_widths] == [1, 2, 3]
        assert row.n_encoded_controls == max(
            record["n_encoded_controls"] for record in fold_widths
        )
    assert (
        len(
            {
                record["n_encoded_controls"]
                for record in meta["n_encoded_controls_by_fold"]["comment_thread"]
            }
        )
        == 2
    )

    degenerate = scored.assign(label_amendment_365=0)
    skipped, skipped_meta = fit_public_opacity_dml(
        degenerate,
        outcomes=["amendment"],
        seed=42,
        n_splits=3,
        max_iter=5,
    )
    skipped_row = skipped.iloc[0]
    assert skipped_row["status"] == "skipped_one_class_or_too_small"
    assert skipped_row["n_raw_controls"] == len(skipped_meta["control_columns"])
    assert pd.isna(skipped_row["n_encoded_controls"])
    assert pd.isna(skipped_row["n_controls"])
    assert skipped_row["n_controls_definition"] == "maximum_fold_local_encoded_nuisance_columns"


def test_public_dml_matrix_fits_imputation_and_categories_on_training_fold_only() -> None:
    work = pd.DataFrame(
        {
            "numeric_control": [0.0, float("nan"), 100.0],
            "form": ["10-K", "10-K", "20-F"],
        }
    )

    train, held_out, used_controls = _public_dml_matrix(
        work.iloc[:2], work.iloc[2:], ["numeric_control", "form"]
    )

    np.testing.assert_allclose(train, [[0.0, 1.0], [0.0, 1.0]])
    np.testing.assert_allclose(held_out, [[100.0, 0.0]])
    assert len(used_controls) == 2


def test_public_cascade_omitted_sample_end_year_includes_2024(
    tmp_path: Path,
) -> None:
    panel_path = tmp_path / "issuer_origin_panel.parquet"
    config_path = tmp_path / "public_cascade.yaml"
    out_dir = tmp_path / "out"
    rows = []
    for year in [2011, 2012, 2013, 2014, 2024]:
        rows.append(
            {
                "issuer_cik": "0000000001",
                "accession": f"0000000001-{year}-000001",
                "origin_date": f"{year + 1}-03-01",
                "filing_date": f"{year + 1}-03-01",
                "report_date": f"{year}-12-31",
                "as_of_date": "2026-04-23",
                "fiscal_year": year,
                "form": "10-K",
                "sic": 1234,
                "is_domestic_us_gaap_proxy": 1,
                "label_comment_thread_365": 0,
                "label_amendment_365": 0,
                "label_8k_402_365": 0,
                "censored_365": 0,
                "xbrl_fact_count": 10 + year,
            }
        )
    rows.append(
        {
            **rows[0],
            "accession": "0000000001-2011-000002",
            "censored_365": pd.NA,
        }
    )
    write_table(pd.DataFrame(rows), panel_path)
    config_path.write_text(
        """
sample:
  start_year: 2011
  domestic_only: true
analysis:
  candidate_train_windows: [null]
  min_train_years: 2
  feature_sets: ["metadata"]
  primary_specification:
    feature_set: "metadata"
    train_window: "expanding"
  opacity_dml:
    enabled: false
model:
  seed: 42
  xgb:
    n_estimators: 2
""",
        encoding="utf-8",
    )

    result = run_public_cascade(
        config_path=config_path,
        issuer_origin_panel_path=panel_path,
        out_dir=out_dir,
    )
    summary = json.loads(Path(result["summary_json"]).read_text(encoding="utf-8"))
    metrics = pd.read_csv(result["metrics_csv"])
    task_status = pd.read_csv(result["task_status_csv"])
    attrition = pd.read_csv(result["sample_attrition_csv"])
    opacity_meta = json.loads(
        Path(result["public_opacity_dml_meta_json"]).read_text(encoding="utf-8")
    )

    assert set(summary["zero_positive_tasks"]) == {"comment_thread", "amendment", "8k_402"}
    assert summary["n_rows"] == 5
    assert summary["sample_years"] == [2011, 2024]
    assert summary["sample_attrition"] == attrition.to_dict(orient="records")
    indexed_attrition = attrition.set_index("stage")
    assert indexed_attrition.loc["source_issuer_origin", "n_rows"] == 6
    assert indexed_attrition.loc["fiscal_year_2011_2024", "n_rows"] == 6
    assert indexed_attrition.loc["observable_365_day_horizon", "n_rows"] == 5
    assert opacity_meta["n_raw_controls"] == 0
    assert opacity_meta["n_encoded_controls_by_outcome"] == {}
    assert opacity_meta["n_encoded_controls_by_fold"] == {}
    assert opacity_meta["n_controls"] == 0
    assert opacity_meta["n_controls_definition"] == "maximum_fold_local_encoded_nuisance_columns"
    assert opacity_meta["control_columns_definition"] == "raw_controls_before_encoding"
    assert metrics.empty
    assert set(task_status["status"]) == {"skipped_one_class_train"}
    assert set(task_status["task"]) == {"comment_thread", "amendment", "8k_402"}
    assert summary["cascade_readiness_level"] == "metadata_baseline"
    assert summary["visibility_history_metric_rows"] == int(
        metrics["feature_set"].eq("visibility_history").sum()
    )
    assert summary["primary_metric_rows"] == int(
        (
            metrics["feature_set"].eq(summary["primary_specification"]["feature_set"])
            & metrics["train_window"].eq(summary["primary_specification"]["train_window"])
        ).sum()
    )


def test_public_cascade_excludes_8k402_item_metadata_unknown_rows(tmp_path: Path) -> None:
    panel_path = tmp_path / "issuer_origin_panel.parquet"
    config_path = tmp_path / "public_cascade.yaml"
    out_dir = tmp_path / "out"
    rows = []
    unknown_count = 0
    for year in range(2011, 2017):
        for issuer_id in range(6):
            unknown = int(issuer_id == 5 and year in {2014, 2016})
            unknown_count += unknown
            rows.append(
                {
                    "issuer_cik": f"{issuer_id:010d}",
                    "accession": f"{issuer_id:010d}-{year}-000001",
                    "origin_date": f"{year + 1}-03-01",
                    "filing_date": f"{year + 1}-03-01",
                    "report_date": f"{year}-12-31",
                    "as_of_date": "2026-04-23",
                    "fiscal_year": year,
                    "form": "10-K",
                    "sic": 1200 + issuer_id,
                    "is_domestic_us_gaap_proxy": 1,
                    "label_comment_thread_365": int((year + issuer_id) % 3 == 0),
                    "label_amendment_365": int((year + issuer_id) % 4 == 0),
                    "label_8k_402_365": pd.NA if unknown else int((year + issuer_id) % 2 == 0),
                    "k402_item_metadata_unknown_365": unknown,
                    "censored_365": 0,
                    "xbrl_ratio_leverage": 0.2 + issuer_id / 100 + year / 10000,
                }
            )
    write_table(pd.DataFrame(rows), panel_path)
    config_path.write_text(
        """
sample:
  start_year: 2011
  end_year: 2016
  domestic_only: true
analysis:
  candidate_train_windows: [3]
  min_train_years: 3
  feature_sets: ["xbrl"]
  primary_specification:
    feature_set: "xbrl"
    train_window: "rolling_3y"
model:
  seed: 42
  xgb:
    n_estimators: 2
    n_jobs: 1
""",
        encoding="utf-8",
    )

    result = run_public_cascade(
        config_path=config_path,
        issuer_origin_panel_path=panel_path,
        out_dir=out_dir,
        parallel_jobs=1,
        model_threads=1,
    )
    summary = json.loads(Path(result["summary_json"]).read_text(encoding="utf-8"))
    metrics = pd.read_csv(result["metrics_csv"])
    status = pd.read_csv(result["task_status_csv"])
    k402_status = status.loc[status["task"].eq("8k_402")]

    assert summary["task_exclusion_counts"]["8k_402"] == unknown_count
    assert int(k402_status["excluded_train"].sum() + k402_status["excluded_test"].sum()) > 0
    assert summary["visibility_history_metric_rows"] == int(
        metrics["feature_set"].eq("visibility_history").sum()
    )
    assert summary["primary_metric_rows"] == int(
        (
            metrics["feature_set"].eq(summary["primary_specification"]["feature_set"])
            & metrics["train_window"].eq(summary["primary_specification"]["train_window"])
        ).sum()
    )


def test_xbrl_ratio_features_unlock_xbrl_readiness_level(tmp_path: Path) -> None:
    panel_path = tmp_path / "issuer_origin_panel.parquet"
    config_path = tmp_path / "public_cascade.yaml"
    out_dir = tmp_path / "out"
    rows = []
    for year in [2011, 2012, 2013, 2014]:
        rows.append(
            {
                "issuer_cik": "0000000001",
                "accession": f"0000000001-{year}-000001",
                "origin_date": f"{year + 1}-03-01",
                "filing_date": f"{year + 1}-03-01",
                "report_date": f"{year}-12-31",
                "as_of_date": "2026-04-23",
                "fiscal_year": year,
                "size": 100,
                "form": "10-K",
                "sic": 1234,
                "is_domestic_us_gaap_proxy": 1,
                "label_comment_thread_365": 0,
                "label_amendment_365": 0,
                "label_8k_402_365": 0,
                "censored_365": 0,
                "xbrl_ratio_leverage": 0.2 + year / 10000,
                "xbrl_coverage_assets": 1,
            }
        )
    write_table(pd.DataFrame(rows), panel_path)
    config_path.write_text(
        """
sample:
  start_year: 2011
  end_year: 2014
  domestic_only: true
analysis:
  candidate_train_windows: [null]
  min_train_years: 2
  feature_sets: ["xbrl", "visibility_history"]
  primary_specification:
    feature_set: "xbrl"
    train_window: "expanding"
model:
  seed: 42
  xgb:
    n_estimators: 2
""",
        encoding="utf-8",
    )

    result = run_public_cascade(
        config_path=config_path,
        issuer_origin_panel_path=panel_path,
        out_dir=out_dir,
    )
    summary = json.loads(Path(result["summary_json"]).read_text(encoding="utf-8"))
    metrics = pd.read_csv(result["metrics_csv"])

    assert summary["cascade_readiness_level"] == "xbrl_ratio_baseline"
    assert summary["feature_family_summary"]["xbrl"]["n_xbrl_ratio_features"] == 1
    assert summary["feature_family_summary"]["xbrl"]["n_xbrl_coverage_features"] == 1
    visibility = summary["feature_family_summary"]["visibility_history"]
    assert visibility["configured_features"] == list(VISIBILITY_HISTORY_FEATURES)
    assert visibility["available_features"] == ["size", "form"]
    assert visibility["unavailable_features"] == [
        field for field in VISIBILITY_HISTORY_FEATURES if field not in {"size", "form"}
    ]
    assert summary["visibility_history_metric_rows"] == int(
        metrics["feature_set"].eq("visibility_history").sum()
    )
    assert summary["primary_metric_rows"] == int(
        (
            metrics["feature_set"].eq(summary["primary_specification"]["feature_set"])
            & metrics["train_window"].eq(summary["primary_specification"]["train_window"])
        ).sum()
    )


def test_public_cascade_parallel_matches_serial_status_keys(tmp_path: Path) -> None:
    panel_path = tmp_path / "issuer_origin_panel.parquet"
    config_path = tmp_path / "public_cascade.yaml"
    rows = []
    for year in [2011, 2012, 2013, 2014]:
        rows.append(
            {
                "issuer_cik": "0000000001",
                "accession": f"0000000001-{year}-000001",
                "origin_date": f"{year + 1}-03-01",
                "filing_date": f"{year + 1}-03-01",
                "report_date": f"{year}-12-31",
                "as_of_date": "2026-04-23",
                "fiscal_year": year,
                "form": "10-K",
                "sic": 1234,
                "is_domestic_us_gaap_proxy": 1,
                "label_comment_thread_365": 0,
                "label_amendment_365": 0,
                "label_8k_402_365": 0,
                "censored_365": 0,
                "xbrl_ratio_leverage": 0.2 + year / 10000,
            }
        )
    write_table(pd.DataFrame(rows), panel_path)
    config_path.write_text(
        """
sample:
  start_year: 2011
  end_year: 2014
  domestic_only: true
analysis:
  candidate_train_windows: [null]
  min_train_years: 2
  feature_sets: ["xbrl"]
  primary_specification:
    feature_set: "xbrl"
    train_window: "expanding"
  seed_policy: "task_isolated"
model:
  seed: 42
  xgb:
    n_estimators: 2
    n_jobs: 1
""",
        encoding="utf-8",
    )

    serial = run_public_cascade(
        config_path=config_path,
        issuer_origin_panel_path=panel_path,
        out_dir=tmp_path / "serial",
        parallel_jobs=1,
    )
    parallel = run_public_cascade(
        config_path=config_path,
        issuer_origin_panel_path=panel_path,
        out_dir=tmp_path / "parallel",
        parallel_jobs=2,
    )
    serial_status = pd.read_csv(serial["task_status_csv"])
    parallel_status = pd.read_csv(parallel["task_status_csv"])
    key_cols = ["feature_set", "train_window", "test_year", "task", "status"]

    pd.testing.assert_frame_equal(serial_status[key_cols], parallel_status[key_cols])
    for result in [serial, parallel]:
        summary = json.loads(Path(result["summary_json"]).read_text(encoding="utf-8"))
        metrics = pd.read_csv(result["metrics_csv"])
        assert summary["visibility_history_metric_rows"] == int(
            metrics["feature_set"].eq("visibility_history").sum()
        )
        assert summary["primary_metric_rows"] == int(
            (
                metrics["feature_set"].eq(summary["primary_specification"]["feature_set"])
                & metrics["train_window"].eq(
                    summary["primary_specification"]["train_window"]
                )
            ).sum()
        )


def test_public_cascade_trains_nonzero_positive_tasks_and_writes_predictions(
    tmp_path: Path,
) -> None:
    panel_path = tmp_path / "issuer_origin_panel.parquet"
    config_path = tmp_path / "public_cascade.yaml"
    out_dir = tmp_path / "out"
    rows = []
    for year in range(2011, 2019):
        for issuer_id in range(8):
            rows.append(
                {
                    "issuer_cik": f"{issuer_id:010d}",
                    "accession": f"{issuer_id:010d}-{year}-000001",
                    "origin_date": f"{year + 1}-03-01",
                    "filing_date": f"{year + 1}-03-01",
                    "report_date": f"{year}-12-31",
                    "as_of_date": "2026-04-23",
                    "fiscal_year": year,
                    "form": "10-K",
                    "sic": 1200 + issuer_id,
                    "is_domestic_us_gaap_proxy": 1,
                    "label_comment_thread_365": int((year + issuer_id) % 4 == 0),
                    "label_amendment_365": int((year + issuer_id) % 5 == 0),
                    "label_8k_402_365": int((year + issuer_id) % 6 == 0),
                    "censored_365": 0,
                    "xbrl_ratio_leverage": 0.2 + issuer_id / 100 + year / 10000,
                    "xbrl_coverage_assets": 1,
                }
            )
    write_table(pd.DataFrame(rows), panel_path)
    config_path.write_text(
        """
sample:
  start_year: 2011
  end_year: 2018
  domestic_only: true
analysis:
  candidate_train_windows: [3]
  min_train_years: 3
  feature_sets: ["metadata", "xbrl"]
  primary_specification:
    feature_set: "metadata"
    train_window: "rolling_3y"
  parallel_jobs: 1
  seed_policy: "task_isolated"
model:
  seed: 42
  xgb:
    n_estimators: 2
    max_depth: 2
    n_jobs: 1
    tree_method: "hist"
""",
        encoding="utf-8",
    )

    result = run_public_cascade(
        config_path=config_path,
        issuer_origin_panel_path=panel_path,
        out_dir=out_dir,
        parallel_jobs=1,
        model_threads=1,
        seed_policy="task_isolated",
    )

    metrics = pd.read_csv(result["metrics_csv"])
    summary = json.loads(Path(result["summary_json"]).read_text(encoding="utf-8"))
    predictions = read_table(result["predictions_table"])
    status = pd.read_csv(result["task_status_csv"])
    opacity_dml = pd.read_csv(result["public_opacity_dml_csv"])
    assert not metrics.empty
    assert "brier_skill_score" in metrics.columns
    assert "ece" in metrics.columns
    assert "ece_quantile" in metrics.columns
    assert "ece_method" in metrics.columns
    assert "top_50_precision" in metrics.columns
    assert "top_100_precision" in metrics.columns
    assert "top_200_precision" in metrics.columns
    assert "bao_top_1pct_ndcg" in metrics.columns
    assert "bao_top_5pct_precision" in metrics.columns
    assert not predictions.empty
    assert "accession" in predictions.columns
    assert "origin_date" in predictions.columns
    assert predictions["accession"].notna().all()
    assert "fit" in set(status["status"])
    assert "outcome" in opacity_dml.columns
    assert summary["visibility_history_metric_rows"] == int(
        metrics["feature_set"].eq("visibility_history").sum()
    )
    assert summary["primary_metric_rows"] == int(
        (
            metrics["feature_set"].eq(summary["primary_specification"]["feature_set"])
            & metrics["train_window"].eq(summary["primary_specification"]["train_window"])
        ).sum()
    )


@pytest.mark.parametrize(
    "mode", ["sec-index", "sec-download", "filings-index", "filings-download"]
)
def test_fetch_cli_rejects_removed_non_current_modes(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["fetch_public_data.py", "--mode", mode])
    with pytest.raises(SystemExit):
        fetch_public_data.parse_args()


def test_runtime_surface_contains_only_current_analysis_modules() -> None:
    src_files = {path.name for path in (fetch_public_data.REPO_ROOT / "src").glob("*.py")}
    script_files = {
        path.name for path in (fetch_public_data.REPO_ROOT / "scripts").iterdir() if path.is_file()
    }
    config_files = {
        path.name for path in (fetch_public_data.REPO_ROOT / "config").iterdir() if path.is_file()
    }
    assert src_files == {
        "__init__.py",
        "bridge.py",
        "benchmark.py",
        "construct_overlap.py",
        "data_prep.py",
        "linkage.py",
        "peer_comparison.py",
        "provenance.py",
        "public_cascade.py",
        "public_peer_comparison.py",
        "public_lake.py",
        "raw_dataset.py",
        "ranking_metrics.py",
        "sample_dataset.py",
        "table_io.py",
    }
    assert script_files == {
        "convert_raw_dataset.py",
        "fetch_public_data.py",
        "generate_sample_dataset.py",
        "build_manuscript_package.py",
        "build_reviewer_package.py",
        "build_linkage_bridge.py",
        "monitor_public_lake.py",
        "prepare_gvkey_cik_crosswalk.py",
        "refresh_results_snapshot.py",
        "run_bridge_probe.py",
        "run_benchmark.py",
        "run_construct_overlap.py",
        "run_data_prep.py",
        "run_public_cascade.py",
        "run_public_lake_full.sh",
        "run_study.py",
        "verify_canonical_run.py",
    }
    assert config_files == {
        "benchmark.yaml",
        "data_prep.yaml",
        "public_cascade.yaml",
        "public_data.yaml",
        "study.yaml",
    }


def test_runtime_surface_avoids_old_paper_codenames() -> None:
    checked_paths = [
        fetch_public_data.REPO_ROOT / "README.md",
        fetch_public_data.REPO_ROOT / "justfile",
        fetch_public_data.REPO_ROOT / "config",
        fetch_public_data.REPO_ROOT / "scripts",
        fetch_public_data.REPO_ROOT / "src",
        fetch_public_data.REPO_ROOT / "tests",
    ]
    old_paper = "pa" + "per"
    forbidden = [
        old_paper + "1",
        old_paper + "_1",
        old_paper + "_a",
        old_paper + "a",
        "flag" + "ship",
        "run_" + old_paper,
        "run_" + "flag" + "ship",
    ]

    for root in checked_paths:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path == Path(__file__):
                continue
            if (
                path.suffix not in {".md", ".py", ".sh", ".yaml", ".yml"}
                and path.name != "justfile"
            ):
                continue
            text = path.read_text(encoding="utf-8")
            lower = text.lower()
            for token in forbidden:
                assert token not in lower, f"{token!r} found in {path}"
