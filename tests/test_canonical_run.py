import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scripts.verify_canonical_run import verify_canonical_run


def _write_json(path: Path, payload: object) -> None:
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
                "config_hash": "6" * 64,
                "input_hash": "7" * 64,
                "uv_lock_hash": "8" * 64,
                "source_metadata_inventory": [
                    {
                        "metadata_file": "form-ap/FirmFilings.zip.meta.json",
                        "metadata_sha256": "1" * 64,
                        "source_name": "FINRA Firm Filings",
                        "source_url": "https://example.invalid/FirmFilings.zip",
                        "downloaded_at_utc": "2026-07-06T00:00:00Z",
                        "payload_sha256": "2" * 64,
                        "payload_size_bytes": 123,
                        "parser_version": "1",
                        "schema_version": "1",
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
            "n_effective_nuisance_folds": [3, float("nan")],
            "n_controls_definition": [
                "maximum_fold_local_encoded_nuisance_columns",
                "maximum_fold_local_encoded_nuisance_columns",
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
            "n_encoded_controls_by_fold": {
                "comment_thread": [
                    {"fold_id": 1, "n_encoded_controls": 64},
                    {"fold_id": 2, "n_encoded_controls": 64},
                    {"fold_id": 3, "n_encoded_controls": 64},
                ]
            },
            "n_effective_nuisance_folds_by_outcome": {"comment_thread": 3},
            "n_opacity_components": 17,
            "n_controls_definition": "maximum_fold_local_encoded_nuisance_columns",
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
                "Detected-misstatement score to public labels",
            ],
            "Model": ["public_cascade", "benchmark_xgb"],
            "Target": ["Item 4.02", "Item 4.02"],
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
            "n_controls_definition": ["maximum_fold_local_encoded_nuisance_columns"],
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


def test_verify_canonical_run_accepts_fold_local_dml_width_contract(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    dml_path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml.csv"
    dml = pd.read_csv(dml_path)
    dml["n_controls_definition"] = "maximum_fold_local_encoded_nuisance_columns"
    dml.to_csv(dml_path, index=False)
    meta_path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["n_controls_definition"] = "maximum_fold_local_encoded_nuisance_columns"
    meta["n_encoded_controls_by_fold"] = {
        "comment_thread": [
            {"fold_id": 1, "n_encoded_controls": 63},
            {"fold_id": 2, "n_encoded_controls": 64},
            {"fold_id": 3, "n_encoded_controls": 64},
        ]
    }
    _write_json(meta_path, meta)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert errors == []


@pytest.mark.parametrize(
    "fold_widths",
    [
        [
            {"fold_id": 1, "n_encoded_controls": 64},
            {"fold_id": 1, "n_encoded_controls": 64},
            {"fold_id": 3, "n_encoded_controls": 64},
        ],
        [
            {"fold_id": 1, "n_encoded_controls": 63},
            {"fold_id": 2, "n_encoded_controls": 65},
            {"fold_id": 3, "n_encoded_controls": 63},
        ],
    ],
    ids=["nonsequential-fold-ids", "wrong-maximum"],
)
def test_verify_canonical_run_rejects_invalid_fold_local_dml_widths(
    tmp_path: Path,
    fold_widths: list[dict[str, int]],
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    dml_path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml.csv"
    dml = pd.read_csv(dml_path)
    dml["n_controls_definition"] = "maximum_fold_local_encoded_nuisance_columns"
    dml.to_csv(dml_path, index=False)
    meta_path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["n_controls_definition"] = "maximum_fold_local_encoded_nuisance_columns"
    meta["n_encoded_controls_by_fold"] = {"comment_thread": fold_widths}
    _write_json(meta_path, meta)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("DML CSV/meta/Table 12 consistency" in error for error in errors)


def test_verify_canonical_run_rejects_truncated_fold_width_tail(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    meta_path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["n_encoded_controls_by_fold"]["comment_thread"] = meta["n_encoded_controls_by_fold"][
        "comment_thread"
    ][:-1]
    _write_json(meta_path, meta)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("DML CSV/meta/Table 12 consistency" in error for error in errors)


@pytest.mark.parametrize("with_effective_count", [True, False], ids=["complete", "missing"])
def test_verify_canonical_run_enforces_effective_fold_count_for_post_encoding_skip(
    tmp_path: Path,
    with_effective_count: bool,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    dml_path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml.csv"
    dml = pd.read_csv(dml_path)
    dml.loc[1, ["status", "n_encoded_controls", "n_controls"]] = [
        "skipped_constant_residual_treatment",
        63,
        63,
    ]
    if with_effective_count:
        dml.loc[1, "n_effective_nuisance_folds"] = 2
    dml.to_csv(dml_path, index=False)
    meta_path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["n_encoded_controls_by_outcome"]["amendment"] = 63
    meta["n_encoded_controls_by_fold"]["amendment"] = [
        {"fold_id": 1, "n_encoded_controls": 63},
        {"fold_id": 2, "n_encoded_controls": 63},
    ]
    if with_effective_count:
        meta["n_effective_nuisance_folds_by_outcome"]["amendment"] = 2
    _write_json(meta_path, meta)
    table_path = fixture["package_dir"] / "tables" / "table_12_public_opacity_dml.csv"
    table = pd.read_csv(table_path)
    table.loc[1, "Encoded_Controls"] = 63
    table.to_csv(table_path, index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    if with_effective_count:
        assert errors == []
    else:
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


@pytest.mark.parametrize(
    ("key_path", "replacement", "message"),
    [
        (("public_lake_provenance",), None, "public-lake provenance object"),
        (("components", "benchmark"), [], "benchmark component object"),
        (
            ("claim_maturity",),
            [
                ["public_prediction", "reportable"],
                ["feature_and_window_sensitivity", "supporting"],
                ["construct_alignment", "supporting"],
                ["opacity_dml", "diagnostic"],
            ],
            "claim maturity object",
        ),
    ],
)
def test_verify_canonical_run_rejects_malformed_nested_json_without_raising(
    tmp_path: Path,
    key_path: tuple[str, ...],
    replacement: object,
    message: str,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    cursor = payload
    for key in key_path[:-1]:
        cursor = cursor[key]
    cursor[key_path[-1]] = replacement
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any(message in error for error in errors)


def test_verify_canonical_run_aggregates_nested_and_semantic_failures(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["public_lake_provenance"] = None
    _write_json(fixture["manifest"], manifest)
    construct = json.loads(fixture["construct"].read_text(encoding="utf-8"))
    construct["interval_seed"] = 7
    _write_json(fixture["construct"], construct)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("public-lake provenance object" in error for error in errors)
    assert any("construct bootstrap seed" in error for error in errors)


@pytest.mark.parametrize(
    "replacement",
    [["crosswalk_available"], {"value": "crosswalk_available"}],
)
def test_verify_canonical_run_rejects_non_string_bridge_status_without_raising(
    tmp_path: Path,
    replacement: object,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["components"]["bridge_probe"]["status"] = replacement
    _write_json(fixture["manifest"], manifest)
    construct = json.loads(fixture["construct"].read_text(encoding="utf-8"))
    construct["interval_seed"] = 7
    _write_json(fixture["construct"], construct)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert "bridge component" in errors
    assert "construct bootstrap seed" in errors


@pytest.mark.parametrize(
    ("count_key", "replacement", "message"),
    [
        ("public_to_benchmark_count", True, "public-to-benchmark primary count"),
        ("benchmark_to_public_count", True, "benchmark-to-public primary count"),
        ("public_to_benchmark_count", 1.0, "public-to-benchmark primary count"),
    ],
)
def test_verify_canonical_run_rejects_non_integer_primary_count(
    tmp_path: Path,
    count_key: str,
    replacement: object,
    message: str,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    construct = json.loads(fixture["construct"].read_text(encoding="utf-8"))
    construct["primary_alignment"][count_key] = replacement
    _write_json(fixture["construct"], construct)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert message in errors


@pytest.mark.parametrize(
    ("column", "values"),
    [
        (
            "Direction",
            [
                "Detected-misstatement score to public labels",
                "Public score to benchmark positives",
            ],
        ),
        ("Target", ["Item 4.02", "label_8k_402_365"]),
    ],
)
def test_verify_canonical_run_rejects_wrong_table_09_display_identity(
    tmp_path: Path,
    column: str,
    values: list[str],
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    table = pd.read_csv(fixture["table_09"])
    table[column] = values
    table.to_csv(fixture["table_09"], index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("Table 9 primary rows" in error for error in errors)


def test_verify_canonical_run_rejects_fit_dml_row_with_nan_encoded_controls(
    tmp_path: Path,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml.csv"
    dml = pd.read_csv(path)
    dml.loc[1, "status"] = "fit"
    dml.to_csv(path, index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("DML CSV/meta/Table 12 consistency" in error for error in errors)


def test_verify_canonical_run_accepts_insufficient_folds_without_dimensions(
    tmp_path: Path,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    dml_path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml.csv"
    dml = pd.read_csv(dml_path)
    dml.loc[1, "status"] = "skipped_insufficient_folds"
    dml.to_csv(dml_path, index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert errors == []


@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("Mean_PR_AUC", float("inf")),
        ("Panel_Positives", 100.5),
        ("Panel_Positives", -1),
    ],
)
def test_verify_canonical_run_rejects_invalid_table_03_numbers(
    tmp_path: Path,
    column: str,
    replacement: float,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    path = fixture["package_dir"] / "tables" / "table_03_public_task_metrics.csv"
    table = pd.read_csv(path)
    table[column] = table[column].astype(float)
    table.loc[0, column] = replacement
    table.to_csv(path, index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("Table 3 primary metrics" in error for error in errors)


def test_verify_canonical_run_rejects_fractional_summary_attrition_count(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["public"].read_text(encoding="utf-8"))
    payload["sample_attrition"][0]["n_rows"] = 205652.5
    _write_json(fixture["public"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("sample attrition/table 18 consistency" in error for error in errors)


@pytest.mark.parametrize(
    ("column", "row", "replacement"),
    [
        ("Rows", 0, 205652.5),
        ("Dropped_From_Parent", 1, 108625.5),
        ("Rows", 0, float("inf")),
        ("Dropped_From_Parent", 1, float("inf")),
    ],
)
def test_verify_canonical_run_rejects_invalid_table_18_counts_without_raising(
    tmp_path: Path,
    column: str,
    row: int,
    replacement: float,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    path = fixture["package_dir"] / "tables" / "table_18_public_sample_attrition.csv"
    table = pd.read_csv(path)
    table[column] = table[column].astype(float)
    table.loc[row, column] = replacement
    table.to_csv(path, index=False)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("sample attrition/table 18 consistency" in error for error in errors)


def test_verify_canonical_run_rejects_dirty_provenance(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    payload["provenance"]["dirty"] = True
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("provenance dirty" in error for error in errors)


@pytest.mark.parametrize(
    ("key_path", "replacement", "message"),
    [
        (("provenance", "config_hash"), "b" * 63, "config hash"),
        (("provenance", "input_hash"), "not-hex" * 10, "input hash"),
        (("provenance", "uv_lock_hash"), 123, "uv.lock hash"),
        (
            ("public_lake_provenance", "config_hash"),
            "6" * 63,
            "public-lake config hash",
        ),
        (
            ("public_lake_provenance", "input_hash"),
            "not-hex",
            "public-lake input hash",
        ),
        (
            ("public_lake_provenance", "uv_lock_hash"),
            None,
            "public-lake uv.lock hash",
        ),
        (
            ("public_lake_provenance", "form_ap", "archive_sha256"),
            "e" * 63,
            "Form AP archive hash",
        ),
        (
            ("public_lake_provenance", "form_ap", "member_sha256"),
            "z" * 64,
            "Form AP member hash",
        ),
        (
            ("public_lake_provenance", "source_metadata_inventory", 0, "metadata_sha256"),
            "1" * 63,
            "public source inventory",
        ),
        (
            ("public_lake_provenance", "source_metadata_inventory", 0, "payload_sha256"),
            "x" * 64,
            "public source inventory",
        ),
    ],
)
def test_verify_canonical_run_rejects_malformed_sha256_values(
    tmp_path: Path,
    key_path: tuple[object, ...],
    replacement: object,
    message: str,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    cursor: Any = payload
    for key in key_path[:-1]:
        cursor = cursor[key]
    cursor[key_path[-1]] = replacement
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any(message in error for error in errors)


@pytest.mark.parametrize(
    ("key_path", "message"),
    [
        (("repo_commit",), "study commit"),
        (("provenance", "commit_sha"), "provenance commit"),
        (("public_lake_provenance", "commit_sha"), "public-lake commit"),
    ],
)
def test_verify_canonical_run_rejects_malformed_commit_shape(
    tmp_path: Path,
    key_path: tuple[str, ...],
    message: str,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    cursor = payload
    for key in key_path[:-1]:
        cursor = cursor[key]
    cursor[key_path[-1]] = "g" * 40
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any(message in error for error in errors)


def test_verify_canonical_run_rejects_malformed_source_inventory(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    payload["public_lake_provenance"]["source_metadata_inventory"] = [None]
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert any("public source inventory" in error for error in errors)


@pytest.mark.parametrize(
    "field",
    [
        "source_name",
        "source_url",
        "downloaded_at_utc",
        "payload_sha256",
        "payload_size_bytes",
        "parser_version",
        "schema_version",
    ],
)
def test_verify_canonical_run_rejects_sidecar_missing_required_field(
    tmp_path: Path,
    field: str,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    payload["public_lake_provenance"]["source_metadata_inventory"][0].pop(field)
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert "public source inventory" in errors


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_name", ""),
        ("source_url", 1),
        ("downloaded_at_utc", []),
        ("payload_sha256", 1),
        ("payload_size_bytes", True),
        ("payload_size_bytes", 1.0),
        ("payload_size_bytes", "1"),
        ("payload_size_bytes", -1),
        ("parser_version", None),
        ("schema_version", " "),
    ],
)
def test_verify_canonical_run_rejects_sidecar_wrong_field_type_or_value(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    payload["public_lake_provenance"]["source_metadata_inventory"][0][field] = replacement
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert "public source inventory" in errors


def test_verify_canonical_run_rejects_sidecar_extra_field(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    payload["public_lake_provenance"]["source_metadata_inventory"][0]["unexpected"] = "extra"
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert "public source inventory" in errors


def test_verify_canonical_run_accepts_minimal_non_sidecar_inventory_record(
    tmp_path: Path,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    payload["public_lake_provenance"]["source_metadata_inventory"] = [
        {
            "metadata_file": "issuer-origin/issuer_origin.csv",
            "metadata_sha256": "3" * 64,
        }
    ]
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert errors == []


@pytest.mark.parametrize(
    "extra_fields",
    [
        {"payload_sha256": "2" * 64},
        {"payload_sha256": "not-a-sha256"},
        {"source_name": "unexpected acquisition metadata"},
    ],
)
def test_verify_canonical_run_rejects_non_sidecar_acquisition_fields(
    tmp_path: Path,
    extra_fields: dict[str, object],
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    payload["public_lake_provenance"]["source_metadata_inventory"] = [
        {
            "metadata_file": "issuer-origin/issuer_origin.csv",
            "metadata_sha256": "3" * 64,
            **extra_fields,
        }
    ]
    _write_json(fixture["manifest"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert "public source inventory" in errors


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("interval_seed", 42.0, "construct bootstrap seed"),
        ("interval_seed", True, "construct bootstrap seed"),
        ("interval_seed", "42", "construct bootstrap seed"),
        ("interval_reps", 1000.0, "construct bootstrap reps"),
        ("interval_reps", True, "construct bootstrap reps"),
        ("interval_reps", "1000", "construct bootstrap reps"),
    ],
)
def test_verify_canonical_run_rejects_non_integer_bootstrap_contract(
    tmp_path: Path,
    field: str,
    replacement: object,
    message: str,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["construct"].read_text(encoding="utf-8"))
    payload[field] = replacement
    _write_json(fixture["construct"], payload)

    errors = verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )

    assert message in errors


@pytest.mark.parametrize(
    "invalid_case",
    [
        "nested",
        "table_09",
        "dml",
        "table_03",
        "attrition",
        "dirty",
        "hash",
        "sidecar_missing_payload_hash",
        "sidecar_extra_field",
        "interval_seed_float",
        "interval_reps_float",
    ],
)
def test_cli_never_verifies_invalid_canonical_fixture(
    tmp_path: Path,
    invalid_case: str,
) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    if invalid_case in {
        "nested",
        "dirty",
        "hash",
        "sidecar_missing_payload_hash",
        "sidecar_extra_field",
    }:
        payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
        if invalid_case == "nested":
            payload["public_lake_provenance"] = None
        elif invalid_case == "dirty":
            payload["provenance"]["dirty"] = True
        elif invalid_case == "sidecar_missing_payload_hash":
            payload["public_lake_provenance"]["source_metadata_inventory"][0].pop("payload_sha256")
        elif invalid_case == "sidecar_extra_field":
            payload["public_lake_provenance"]["source_metadata_inventory"][0]["unexpected"] = (
                "extra"
            )
        else:
            payload["provenance"]["config_hash"] = "not-a-sha256"
        _write_json(fixture["manifest"], payload)
    elif invalid_case in {"interval_seed_float", "interval_reps_float"}:
        payload = json.loads(fixture["construct"].read_text(encoding="utf-8"))
        if invalid_case == "interval_seed_float":
            payload["interval_seed"] = 42.0
        else:
            payload["interval_reps"] = 1000.0
        _write_json(fixture["construct"], payload)
    elif invalid_case == "table_09":
        table = pd.read_csv(fixture["table_09"])
        table.loc[0, "Direction"] = "wrong direction"
        table.to_csv(fixture["table_09"], index=False)
    elif invalid_case == "dml":
        path = fixture["study_dir"] / "public_cascade" / "public_opacity_dml.csv"
        dml = pd.read_csv(path)
        dml.loc[1, "status"] = "fit"
        dml.to_csv(path, index=False)
    elif invalid_case == "table_03":
        path = fixture["package_dir"] / "tables" / "table_03_public_task_metrics.csv"
        table = pd.read_csv(path)
        table.loc[0, "Mean_PR_AUC"] = float("inf")
        table.to_csv(path, index=False)
    else:
        payload = json.loads(fixture["public"].read_text(encoding="utf-8"))
        payload["sample_attrition"][0]["n_rows"] = 205652.5
        _write_json(fixture["public"], payload)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_canonical_run.py",
            "--study-dir",
            str(fixture["study_dir"]),
            "--manuscript-package",
            str(fixture["package_dir"]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "CANONICAL RUN VERIFIED" not in completed.stdout
    assert "FAILED:" in completed.stdout
    assert "Traceback" not in completed.stderr


def test_cli_rejects_non_string_bridge_status_without_traceback(tmp_path: Path) -> None:
    fixture = _write_canonical_fixture(tmp_path)
    payload = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    payload["components"]["bridge_probe"]["status"] = []
    _write_json(fixture["manifest"], payload)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_canonical_run.py",
            "--study-dir",
            str(fixture["study_dir"]),
            "--manuscript-package",
            str(fixture["package_dir"]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "FAILED: bridge component" in completed.stdout
    assert "CANONICAL RUN VERIFIED" not in completed.stdout
    assert "Traceback" not in completed.stderr
