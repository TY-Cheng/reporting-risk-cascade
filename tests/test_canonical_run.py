import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scripts.verify_canonical_run import verify_canonical_run


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_canonical_fixture(tmp_path: Path) -> dict[str, Path]:
    study_dir = tmp_path / "study"
    package_dir = tmp_path / "package"
    manifest_path = study_dir / "study_run_manifest.json"
    public_path = study_dir / "public_cascade" / "public_cascade_summary.json"
    construct_path = study_dir / "construct_overlap" / "construct_overlap_manifest.json"
    dml_path = study_dir / "public_cascade" / "public_opacity_dml.csv"

    _write_json(
        manifest_path,
        {
            "repo_commit": "a" * 40,
            "git_dirty": False,
            "provenance": {
                "commit_sha": "a" * 40,
                "dirty": False,
                "config_hash": "b" * 64,
                "input_hash": "c" * 64,
                "uv_lock_hash": "d" * 64,
            },
            "public_lake_provenance": {
                "as_of_date": "2026-07-06",
                "fresh_build": True,
                "git_dirty": False,
                "commit_sha": "a" * 40,
                "source_metadata_inventory": [
                    {
                        "metadata_file": "form-ap/FirmFilings.zip.meta.json",
                        "metadata_sha256": "1" * 64,
                        "source_url": "https://example.invalid/FirmFilings.zip",
                        "payload_sha256": "2" * 64,
                    }
                ],
                "form_ap": {
                    "source_kind": "verified_zip_member",
                    "archive_sha256": "e" * 64,
                    "member_sha256": "f" * 64,
                },
            },
            "components": {
                "benchmark": {"status": "complete"},
                "public_cascade": {"status": "complete"},
                "bridge_probe": {"status": "crosswalk_available"},
                "peer_comparison": {"status": "complete"},
                "public_peer_comparison": {"status": "complete"},
                "construct_overlap": {"run_status": "complete"},
            },
            "claim_maturity": {
                "public_prediction": "reportable",
                "feature_and_window_sensitivity": "supporting",
                "construct_alignment": "supporting",
                "opacity_dml": "diagnostic",
            },
        },
    )
    _write_json(
        public_path,
        {
            "primary_specification": {
                "feature_set": "all",
                "train_window": "expanding",
            },
            "primary_specification_status": "revision_frozen",
            "feature_family_summary": {"visibility_history": {"n_features": 24}},
            "sample_attrition": [
                {"stage": "source_issuer_origin", "n_rows": 205652, "task": "all"},
                {"stage": "fiscal_year_2011_2024", "n_rows": 97027, "task": "all"},
                {"stage": "domestic_us_gaap_proxy", "n_rows": 96827, "task": "all"},
                {"stage": "observable_365_day_horizon", "n_rows": 96733, "task": "all"},
                {"stage": "eligible_comment_thread", "n_rows": 96733, "task": "comment_thread"},
                {"stage": "eligible_amendment", "n_rows": 96733, "task": "amendment"},
                {"stage": "eligible_8k_402", "n_rows": 96733, "task": "8k_402"},
            ],
        },
    )
    _write_json(
        construct_path,
        {
            "interval_scope": "primary_plus_top_5_per_direction",
            "interval_seed": 42,
            "interval_reps": 1000,
            "primary_alignment": {
                "public_to_benchmark": {
                    "model_id": "public_cascade",
                    "task": "8k_402",
                    "feature_set": "all",
                    "train_window": "expanding",
                    "label_mode": "benchmark_naive",
                    "score_aggregation": "mean",
                    "bridge_tier": "high_confidence",
                },
                "benchmark_to_public": {
                    "model_id": "benchmark_xgb",
                    "target_public_label": "label_8k_402_365",
                    "feature_set": "benchmark_all",
                    "train_window": "expanding",
                    "label_mode": "naive",
                    "score_aggregation": "benchmark_score",
                    "bridge_tier": "high_confidence",
                },
                "public_to_benchmark_count": 1,
                "benchmark_to_public_count": 1,
            },
            "primary_alignment_evidence": {
                "public_to_benchmark": {
                    "metric_status": "fit",
                    "top_decile_lift": 2.0,
                    "ci_low": 1.2,
                    "ci_high": 2.8,
                },
                "benchmark_to_public": {
                    "metric_status": "fit",
                    "top_decile_lift": 1.8,
                    "ci_low": 1.1,
                    "ci_high": 2.5,
                },
            },
            "exploratory_maxima": {
                "public_to_benchmark": {
                    "keys": {"train_window": "rolling_7y"},
                    "top_decile_lift": 2.4,
                    "primary_lift": 2.0,
                    "lift_minus_primary": 0.4,
                },
                "benchmark_to_public": {
                    "keys": {"train_window": "rolling_7y"},
                    "top_decile_lift": 2.1,
                    "primary_lift": 1.8,
                    "lift_minus_primary": 0.3,
                },
            },
        },
    )
    dml_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "outcome": ["comment_thread", "amendment"],
            "n_raw_controls": [60, 60],
            "n_encoded_controls": [64, float("nan")],
            "n_controls": [64, float("nan")],
            "n_controls_definition": [
                "encoded_nuisance_columns",
                "encoded_nuisance_columns",
            ],
            "n_opacity_components": [17, 17],
            "status": ["fit", "skipped_one_class_or_too_small"],
        }
    ).to_csv(dml_path, index=False)
    _write_json(
        study_dir / "public_cascade" / "public_opacity_dml_meta.json",
        {
            "n_raw_controls": 60,
            "n_encoded_controls_by_outcome": {"comment_thread": 64},
            "n_opacity_components": 17,
            "n_controls_definition": "encoded_nuisance_columns",
        },
    )
    tables = package_dir / "tables"
    tables.mkdir(parents=True)
    pd.DataFrame(
        {
            "Task": ["comment_thread", "amendment", "8k_402"],
            "Panel_Positives": [100, 80, 20],
            "Mean_Prevalence": [0.02, 0.015, 0.004],
            "Mean_PR_AUC": [0.2, 0.15, 0.05],
            "PR_AUC_Dispersion": [
                "[0.1800, 0.2200]",
                "[0.1300, 0.1700]",
                "[0.0400, 0.0600]",
            ],
            "Mean_ROC_AUC": [0.7, 0.68, 0.65],
            "Mean_Brier": [0.018, 0.014, 0.004],
            "Mean_Brier_Skill": [0.08, 0.06, 0.03],
            "Mean_ECE": [0.01, 0.009, 0.003],
            "Excluding_2020_PR_AUC": [0.21, 0.16, 0.055],
            "Excluding_2020_Delta": [0.01, 0.01, 0.005],
        }
    ).to_csv(tables / "table_03_public_task_metrics.csv", index=False)
    pd.DataFrame(
        {
            "Outcome": ["comment_thread", "amendment"],
            "Raw_Controls": [60, 60],
            "Encoded_Controls": [64, float("nan")],
            "Opacity_Components": [17, 17],
        }
    ).to_csv(tables / "table_12_public_opacity_dml.csv", index=False)
    pd.DataFrame(
        {
            "Direction": [
                "Public score to benchmark positives",
                "Benchmark score to public positives",
            ],
            "Model": ["public_cascade", "benchmark_xgb"],
            "Target": ["8k_402", "label_8k_402_365"],
            "Feature_Set": ["all", "benchmark_all"],
            "Window": ["expanding", "expanding"],
            "Bridge_Tier": ["high_confidence", "high_confidence"],
            "PR_AUC": [0.04, 0.03],
            "ROC_AUC": [0.70, 0.60],
            "Top_10pct_Precision": [0.06, 0.05],
            "Top_10pct_FDR": [0.94, 0.95],
            "Top_Decile_Lift": [2.0, 1.8],
            "Lift_Bootstrap_Interval": ["[1.2000, 2.8000]", "[1.1000, 2.5000]"],
        }
    ).to_csv(tables / "table_09_construct_alignment.csv", index=False)
    pd.DataFrame(
        {
            "Scope": ["sequential"] * 4 + ["task"] * 3,
            "Stage": [
                "source_issuer_origin",
                "fiscal_year_2011_2024",
                "domestic_us_gaap_proxy",
                "observable_365_day_horizon",
                "eligible_comment_thread",
                "eligible_amendment",
                "eligible_8k_402",
            ],
            "Task": ["all", "all", "all", "all", "comment_thread", "amendment", "8k_402"],
            "Rows": [205652, 97027, 96827, 96733, 96733, 96733, 96733],
            "Dropped_From_Parent": [0, 108625, 200, 94, 0, 0, 0],
        }
    ).to_csv(tables / "table_18_public_sample_attrition.csv", index=False)
    _write_json(
        package_dir / "manifest.json",
        {
            "primary_public_specification": {
                "feature_set": "all",
                "train_window": "expanding",
            },
            "tables": {
                "table_03_public_task_metrics": {
                    "csv": str(tables / "table_03_public_task_metrics.csv")
                },
                "table_09_construct_alignment": {
                    "csv": str(tables / "table_09_construct_alignment.csv")
                },
                "table_12_public_opacity_dml": {
                    "csv": str(tables / "table_12_public_opacity_dml.csv")
                },
                "table_18_public_sample_attrition": {
                    "csv": str(tables / "table_18_public_sample_attrition.csv")
                },
            },
            "figures": {},
        },
    )
    return {
        "study_dir": study_dir,
        "package_dir": package_dir,
        "manifest": manifest_path,
        "public": public_path,
        "construct": construct_path,
        "table_09": tables / "table_09_construct_alignment.csv",
    }


def test_verify_canonical_run_accepts_clean_fixture(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )
    assert errors == []


@pytest.mark.parametrize(
    ("target", "key_path", "replacement", "message"),
    [
        ("manifest", ("git_dirty",), True, "study git_dirty"),
        (
            "manifest",
            ("public_lake_provenance", "as_of_date"),
            "2026-07-05",
            "public-data as-of date",
        ),
        (
            "manifest",
            ("public_lake_provenance", "fresh_build"),
            False,
            "public-lake fresh build",
        ),
        (
            "construct",
            ("primary_alignment", "public_to_benchmark_count"),
            0,
            "public-to-benchmark primary count",
        ),
        (
            "manifest",
            ("provenance", "commit_sha"),
            "9" * 40,
            "study/provenance commit identity",
        ),
        ("public", ("sample_attrition",), [], "sample attrition"),
        ("construct", ("interval_seed",), 7, "construct bootstrap seed"),
        (
            "construct",
            ("primary_alignment", "public_to_benchmark", "train_window"),
            "rolling_7y",
            "public-to-benchmark primary keys",
        ),
    ],
)
def test_verify_canonical_run_rejects_broken_json_contracts(
    tmp_path: Path,
    target: str,
    key_path: tuple[str, ...],
    replacement: object,
    message: str,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    path = fixture[target]
    payload = json.loads(path.read_text(encoding="utf-8"))
    cursor = payload
    for key in key_path[:-1]:
        cursor = cursor[key]
    cursor[key_path[-1]] = replacement
    _write_json(path, payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any(message in error for error in errors)


def test_verify_canonical_run_rejects_one_row_table_09(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    pd.DataFrame({"Direction": ["public"]}).to_csv(fixture["table_09"], index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("Table 9" in error for error in errors)


def test_verify_canonical_run_rejects_table_09_without_interval(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    table = pd.read_csv(fixture["table_09"])
    table = table.drop(columns=["Lift_Bootstrap_Interval"])
    table.to_csv(fixture["table_09"], index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("Table 9 primary metrics and intervals" in error for error in errors)


def test_verify_canonical_run_rejects_incomplete_table_03(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    path = fixture["package_dir"] / "tables" / "table_03_public_task_metrics.csv"
    table = pd.read_csv(path).drop(columns=["Mean_ECE"])
    table.to_csv(path, index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("Table 3 primary metrics" in error for error in errors)


def test_verify_canonical_run_rejects_wrong_dml_dimensions(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    pd.DataFrame(
        {
            "n_raw_controls": [60],
            "n_encoded_controls": [65],
            "n_controls": [65],
            "n_controls_definition": ["encoded_nuisance_columns"],
        }
    ).to_csv(
        fixture["study_dir"] / "public_cascade" / "public_opacity_dml.csv",
        index=False,
    )

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("DML CSV/meta/Table 12 consistency" in error for error in errors)


def test_verify_canonical_run_rejects_wrong_attrition_drop(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    path = fixture["package_dir"] / "tables" / "table_18_public_sample_attrition.csv"
    table = pd.read_csv(path)
    table.loc[1, "Dropped_From_Parent"] = 999
    table.to_csv(path, index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("sample attrition/table 18 consistency" in error for error in errors)
