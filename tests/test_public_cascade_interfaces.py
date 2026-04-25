from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import fetch_public_data
from src.public_cascade import (
    _build_preprocessor,
    _evaluate_binary,
    _infer_feature_families,
    _prepare_xy,
    _run_public_cascade_unit,
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
            "label_aaer_proxy_730": [0],
            "censored_730": [0],
            "xbrl_fact_count": [10],
            "note_text_count": [1],
            "form_ap_event_count": [1],
            "prior_comment_thread_count": [1],
        }
    )

    families = _infer_feature_families(panel)

    all_features = set(families["all"])
    assert "sic" in families["metadata"]
    assert "xbrl_fact_count" in families["xbrl"]
    assert "note_text_count" in families["text"]
    assert "form_ap_event_count" in families["auditor"]
    assert "prior_comment_thread_count" in families["oversight"]
    assert "items" not in all_features
    assert "source_available_notes" not in all_features
    assert "public_date_notes" not in all_features
    assert "vintage_notes" not in all_features
    assert "label_comment_thread_365" not in all_features
    assert "censored_365" not in all_features


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
        }
    )
    preprocessor = _build_preprocessor(panel, ["xbrl_ratio_leverage", "sic"])
    transformed = preprocessor.fit_transform(panel[["xbrl_ratio_leverage", "sic"]])
    dense = transformed.toarray() if hasattr(transformed, "toarray") else transformed

    assert np.isnan(np.asarray(dense)[:, 0].astype(float)).any()


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
            "label_aaer_proxy_730": [0, 0],
            "censored_365": [0, 0],
            "censored_730": [0, 0],
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
            seed_policy="legacy",
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
            seed_policy="legacy",
        )
        is None
    )


def test_public_cascade_skips_zero_positive_tasks_without_metrics(
    tmp_path: Path,
) -> None:
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
                "form": "10-K",
                "sic": 1234,
                "is_domestic_us_gaap_proxy": 1,
                "label_comment_thread_365": 0,
                "label_amendment_365": 0,
                "label_8k_402_365": 0,
                "label_aaer_proxy_730": 0,
                "censored_365": 0,
                "censored_730": 0,
                "xbrl_fact_count": 10 + year,
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
  feature_sets: ["metadata"]
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

    assert "aaer_proxy" in summary["zero_positive_tasks"]
    assert metrics.empty
    assert set(task_status["status"]) == {"skipped_one_class_train"}
    assert "aaer_proxy" in set(task_status["task"])
    assert summary["cascade_readiness_level"] == "metadata_baseline"


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
                "form": "10-K",
                "sic": 1234,
                "is_domestic_us_gaap_proxy": 1,
                "label_comment_thread_365": 0,
                "label_amendment_365": 0,
                "label_8k_402_365": 0,
                "label_aaer_proxy_730": 0,
                "censored_365": 0,
                "censored_730": 0,
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
  feature_sets: ["xbrl"]
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

    assert summary["cascade_readiness_level"] == "xbrl_ratio_baseline"
    assert summary["feature_family_summary"]["xbrl"]["n_xbrl_ratio_features"] == 1
    assert summary["feature_family_summary"]["xbrl"]["n_xbrl_coverage_features"] == 1


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
                "label_aaer_proxy_730": 0,
                "censored_365": 0,
                "censored_730": 0,
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
                    "label_aaer_proxy_730": int((year + issuer_id) % 7 == 0),
                    "censored_365": 0,
                    "censored_730": 0,
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
    predictions = read_table(result["predictions_table"])
    status = pd.read_csv(result["task_status_csv"])
    assert not metrics.empty
    assert "brier_skill_score" in metrics.columns
    assert "bao_top_1pct_ndcg" in metrics.columns
    assert "bao_top_5pct_precision" in metrics.columns
    assert not predictions.empty
    assert "fit" in set(status["status"])


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
            "data_prep.py",
            "public_cascade.py",
            "public_lake.py",
            "ranking_metrics.py",
            "sample_dataset.py",
            "table_io.py",
        }
    assert script_files == {
        "convert_raw_dataset.py",
        "fetch_public_data.py",
        "generate_sample_dataset.py",
        "monitor_public_lake.py",
        "prepare_gvkey_cik_crosswalk.py",
        "run_bridge_probe.py",
        "run_benchmark.py",
        "run_data_prep.py",
        "run_public_cascade.py",
        "run_public_lake_full.sh",
        "run_study.py",
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
