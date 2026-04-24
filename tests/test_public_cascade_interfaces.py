from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from scripts import fetch_public_data
from src.public_cascade import _build_preprocessor, _infer_feature_families, run_public_cascade


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
        }
    )

    families = _infer_feature_families(panel)

    all_features = set(families["all"])
    assert "sic" in families["metadata"]
    assert "xbrl_fact_count" in families["xbrl"]
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


def test_public_cascade_skips_zero_positive_tasks_without_metrics(
    tmp_path: Path,
) -> None:
    panel_path = tmp_path / "issuer_origin_panel.csv.gz"
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
    pd.DataFrame(rows).to_csv(panel_path, index=False, compression="gzip")
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
        issuer_origin_panel_csv=panel_path,
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
    panel_path = tmp_path / "issuer_origin_panel.csv.gz"
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
    pd.DataFrame(rows).to_csv(panel_path, index=False, compression="gzip")
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
        issuer_origin_panel_csv=panel_path,
        out_dir=out_dir,
    )
    summary = json.loads(Path(result["summary_json"]).read_text(encoding="utf-8"))

    assert summary["cascade_readiness_level"] == "xbrl_ratio_baseline"
    assert summary["feature_family_summary"]["xbrl"]["n_xbrl_ratio_features"] == 1
    assert summary["feature_family_summary"]["xbrl"]["n_xbrl_coverage_features"] == 1


@pytest.mark.parametrize("mode", ["sec-index", "sec-download", "filings-index", "filings-download"])
def test_fetch_cli_rejects_removed_non_current_modes(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["fetch_public_data.py", "--mode", mode])
    with pytest.raises(SystemExit):
        fetch_public_data.parse_args()


def test_runtime_surface_contains_only_current_analysis_modules() -> None:
    src_files = {path.name for path in (fetch_public_data.REPO_ROOT / "src").glob("*.py")}
    script_files = {
        path.name for path in (fetch_public_data.REPO_ROOT / "scripts").iterdir()
        if path.is_file()
    }
    config_files = {
        path.name for path in (fetch_public_data.REPO_ROOT / "config").iterdir()
        if path.is_file()
    }
    assert src_files == {
        "__init__.py",
        "bridge.py",
        "benchmark.py",
        "data_prep.py",
        "public_cascade.py",
        "public_lake.py",
        "sample_dataset.py",
    }
    assert script_files == {
        "fetch_public_data.py",
        "generate_sample_dataset.py",
        "monitor_public_lake.py",
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
