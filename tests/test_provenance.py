from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import run_study as run_study_script
from scripts.run_study import _claim_maturity
from src import public_cascade as public_cascade_module
from src.provenance import (
    input_provenance,
    public_lake_provenance,
    sha256_path,
    wrds_export_metadata,
)


def _valid_public_lake_run_metadata(
    *,
    input_files: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "as_of_date": "2026-07-06",
        "fresh_build": True,
        "provenance": {
            "commit_sha": "lake-commit",
            "dirty": False,
            "config_hash": "lake-config-hash",
            "input_hash": "lake-input-hash",
            "uv_lock_hash": "lake-lock-hash",
            "input_files": input_files or [],
        },
    }


def _valid_form_ap_metadata() -> dict[str, Any]:
    return {
        "source_kind": "verified_zip_member",
        "archive_sha256": "archive-hash",
        "member": "FirmFilings.csv",
        "member_sha256": "member-hash",
    }


def _valid_source_sidecar() -> dict[str, Any]:
    return {
        "source_name": "form-ap",
        "source_url": "https://example.invalid/FirmFilings.zip",
        "downloaded_at_utc": "2026-07-06T00:00:00+00:00",
        "sha256": "payload-hash",
        "size_bytes": 0,
        "parser_version": "public-lake-v1",
        "schema_version": "public-lake-v1",
    }


def _write_public_lake_metadata(
    tmp_path: Path,
    run_payload: Any,
    form_ap_payload: Any,
) -> tuple[Path, Path]:
    run_metadata = tmp_path / "public_lake_run_metadata.json"
    form_ap_metadata = tmp_path / "form_ap_source_metadata.json"
    run_metadata.write_text(json.dumps(run_payload), encoding="utf-8")
    form_ap_metadata.write_text(json.dumps(form_ap_payload), encoding="utf-8")
    return run_metadata, form_ap_metadata


def _write_study_fixture(
    tmp_path: Path,
    *,
    skip_public_cascade: bool,
) -> tuple[Namespace, dict[str, Path]]:
    paths = {
        "config": tmp_path / "study.yaml",
        "benchmark_config": tmp_path / "benchmark.yaml",
        "public_cascade_config": tmp_path / "public_cascade.yaml",
        "raw_data": tmp_path / "raw.parquet",
        "issuer_dim": tmp_path / "issuer_dim.parquet",
        "issuer_origin_panel": tmp_path / "issuer_origin_panel.parquet",
        "crosswalk": tmp_path / "crosswalk.csv",
        "public_lake_run_metadata": tmp_path / "public_lake_run_metadata.json",
        "form_ap_source_metadata": tmp_path / "form_ap_source_metadata.json",
        "out_dir": tmp_path / "study",
    }
    paths["issuer_origin_panel"].write_bytes(b"issuer-panel")
    paths["public_lake_run_metadata"].write_text(
        json.dumps(_valid_public_lake_run_metadata()),
        encoding="utf-8",
    )
    paths["form_ap_source_metadata"].write_text(
        json.dumps(_valid_form_ap_metadata()),
        encoding="utf-8",
    )
    paths["config"].write_text(
        json.dumps(
            {
                "inputs": {
                    "raw_data": str(paths["raw_data"]),
                    "issuer_dim": str(paths["issuer_dim"]),
                    "issuer_origin_panel": str(paths["issuer_origin_panel"]),
                    "gvkey_cik_crosswalk": str(paths["crosswalk"]),
                    "public_lake_run_metadata": str(paths["public_lake_run_metadata"]),
                    "form_ap_source_metadata": str(paths["form_ap_source_metadata"]),
                },
                "peer_comparison": {"mode": "none", "target": "both"},
            }
        ),
        encoding="utf-8",
    )
    args = Namespace(
        config=paths["config"],
        benchmark_config=paths["benchmark_config"],
        public_cascade_config=paths["public_cascade_config"],
        raw_data=None,
        raw_csv=None,
        timing_csv=None,
        issuer_origin_panel=None,
        issuer_dim=None,
        crosswalk=None,
        out_dir=paths["out_dir"],
        skip_benchmark=True,
        skip_public_cascade=skip_public_cascade,
        skip_bridge_probe=True,
        skip_construct_overlap=True,
        parallel_jobs=None,
        model_threads=None,
        seed_policy=None,
        peer_comparison_mode=None,
        peer_target=None,
    )
    return args, paths


def test_wrds_export_metadata_summarizes_crosswalk_source(tmp_path: Path) -> None:
    crosswalk = tmp_path / "gvkey_cik_year.csv"
    crosswalk.write_text(
        "\n".join(
            [
                "gvkey,data_year,issuer_cik,source,source_version,extracted_at,match_method",
                "001000,2020,0000000001,wrds_sec_analytics_cik_gvkey:compustat_company,"
                "WRDS SEC Analytics Suite / CIK-GVKEY Link Table.csv,"
                "2026-05-25T00:00:00Z,wrds_sec_analytics_cik_gvkey_intersection",
            ]
        ),
        encoding="utf-8",
    )

    metadata = wrds_export_metadata(crosswalk)
    inputs = input_provenance([crosswalk])

    assert metadata["row_count"] == 1
    assert metadata["wrds_detected"] is True
    assert metadata["source_version_values"] == [
        "WRDS SEC Analytics Suite / CIK-GVKEY Link Table.csv"
    ]
    assert metadata["sha256"] == inputs["input_files"][0]["sha256"]
    assert inputs["input_hash"]


def test_public_lake_provenance_is_pathless_and_keeps_form_ap_hashes(tmp_path: Path) -> None:
    run_metadata = tmp_path / "public_lake_run_metadata.json"
    form_ap_metadata = tmp_path / "form_ap_source_metadata.json"
    source_sidecar = tmp_path / "bronze" / "form-ap" / "FirmFilings.zip.meta.json"
    source_sidecar.parent.mkdir(parents=True)
    source_sidecar.write_text(
        json.dumps(_valid_source_sidecar()),
        encoding="utf-8",
    )
    run_metadata.write_text(
        json.dumps(
            {
                "as_of_date": "2026-07-06",
                "fresh_build": True,
                "provenance": {
                    "commit_sha": "abc123",
                    "dirty": False,
                    "config_hash": "config-hash",
                    "input_hash": "input-hash",
                    "uv_lock_hash": "lock-hash",
                    "input_files": [
                        {
                            "path": str(source_sidecar),
                            "sha256": "sidecar-hash",
                            "size_bytes": source_sidecar.stat().st_size,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    form_ap_metadata.write_text(
        json.dumps(
            {
                "source_kind": "verified_zip_member",
                "archive_sha256": "archive-hash",
                "member": "FirmFilings.csv",
                "member_sha256": "member-hash",
            }
        ),
        encoding="utf-8",
    )

    reduced = public_lake_provenance(run_metadata, form_ap_metadata)

    assert reduced["as_of_date"] == "2026-07-06"
    assert reduced["git_dirty"] is False
    assert reduced["form_ap"]["archive_sha256"] == "archive-hash"
    assert reduced["source_metadata_inventory"] == [
        {
            "metadata_file": "form-ap/FirmFilings.zip.meta.json",
            "metadata_sha256": "sidecar-hash",
            "source_name": "form-ap",
            "source_url": "https://example.invalid/FirmFilings.zip",
            "downloaded_at_utc": "2026-07-06T00:00:00+00:00",
            "payload_sha256": "payload-hash",
            "payload_size_bytes": 0,
            "parser_version": "public-lake-v1",
            "schema_version": "public-lake-v1",
        }
    ]
    assert str(tmp_path) not in json.dumps(reduced)


@pytest.mark.parametrize(
    ("malformed_part", "match"),
    [
        ("run_metadata", "public lake run metadata"),
        ("form_ap_metadata", "Form AP source metadata"),
        ("provenance", "provenance"),
        ("input_files", "input_files"),
        ("input_file", r"input_files\[0\]"),
        ("source_sidecar", "source metadata sidecar"),
    ],
)
def test_public_lake_provenance_rejects_malformed_object_and_list_shapes(
    tmp_path: Path,
    malformed_part: str,
    match: str,
) -> None:
    run_payload: Any = _valid_public_lake_run_metadata()
    form_ap_payload: Any = _valid_form_ap_metadata()
    if malformed_part == "run_metadata":
        run_payload = []
    elif malformed_part == "form_ap_metadata":
        form_ap_payload = []
    elif malformed_part == "provenance":
        run_payload["provenance"] = []
    elif malformed_part == "input_files":
        run_payload["provenance"]["input_files"] = {}
    elif malformed_part == "input_file":
        run_payload["provenance"]["input_files"] = [[]]
    else:
        sidecar = tmp_path / "bronze" / "form-ap" / "source.meta.json"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("[]", encoding="utf-8")
        run_payload["provenance"]["input_files"] = [
            {"path": str(sidecar), "sha256": "sidecar-hash"}
        ]
    run_metadata, form_ap_metadata = _write_public_lake_metadata(
        tmp_path,
        run_payload,
        form_ap_payload,
    )

    with pytest.raises(ValueError, match=match):
        public_lake_provenance(run_metadata, form_ap_metadata)


@pytest.mark.parametrize(
    ("section", "missing_field"),
    [
        ("run", "as_of_date"),
        ("run", "fresh_build"),
        ("provenance", "commit_sha"),
        ("provenance", "dirty"),
        ("provenance", "input_files"),
        ("input_file", "path"),
        ("input_file", "sha256"),
    ],
)
def test_public_lake_provenance_rejects_missing_run_provenance_fields(
    tmp_path: Path,
    section: str,
    missing_field: str,
) -> None:
    run_payload = _valid_public_lake_run_metadata(
        input_files=[{"path": "manifest.csv", "sha256": "manifest-hash"}]
    )
    if section == "run":
        del run_payload[missing_field]
    elif section == "provenance":
        del run_payload["provenance"][missing_field]
    else:
        del run_payload["provenance"]["input_files"][0][missing_field]
    run_metadata, form_ap_metadata = _write_public_lake_metadata(
        tmp_path,
        run_payload,
        _valid_form_ap_metadata(),
    )

    with pytest.raises(ValueError, match=missing_field):
        public_lake_provenance(run_metadata, form_ap_metadata)


@pytest.mark.parametrize(
    ("section", "field", "invalid_value"),
    [
        ("run", "as_of_date", ""),
        ("run", "fresh_build", "true"),
        ("provenance", "commit_sha", ""),
        ("provenance", "config_hash", None),
        ("provenance", "dirty", 0),
        ("input_file", "path", ""),
        ("input_file", "sha256", ""),
    ],
)
def test_public_lake_provenance_rejects_invalid_run_provenance_values(
    tmp_path: Path,
    section: str,
    field: str,
    invalid_value: Any,
) -> None:
    run_payload = _valid_public_lake_run_metadata(
        input_files=[{"path": "manifest.csv", "sha256": "manifest-hash"}]
    )
    if section == "run":
        run_payload[field] = invalid_value
    elif section == "provenance":
        run_payload["provenance"][field] = invalid_value
    else:
        run_payload["provenance"]["input_files"][0][field] = invalid_value
    run_metadata, form_ap_metadata = _write_public_lake_metadata(
        tmp_path,
        run_payload,
        _valid_form_ap_metadata(),
    )

    with pytest.raises(ValueError, match=field):
        public_lake_provenance(run_metadata, form_ap_metadata)


def test_public_lake_provenance_rejects_missing_referenced_sidecar(tmp_path: Path) -> None:
    missing_sidecar = tmp_path / "bronze" / "form-ap" / "missing.meta.json"
    run_payload = _valid_public_lake_run_metadata(
        input_files=[{"path": str(missing_sidecar), "sha256": "sidecar-hash"}]
    )
    run_metadata, form_ap_metadata = _write_public_lake_metadata(
        tmp_path,
        run_payload,
        _valid_form_ap_metadata(),
    )

    with pytest.raises(ValueError, match="missing metadata sidecar"):
        public_lake_provenance(run_metadata, form_ap_metadata)


@pytest.mark.parametrize("missing_field", ["source_name", "size_bytes"])
def test_public_lake_provenance_rejects_missing_sidecar_fields(
    tmp_path: Path,
    missing_field: str,
) -> None:
    sidecar = tmp_path / "bronze" / "form-ap" / "source.meta.json"
    sidecar.parent.mkdir(parents=True)
    sidecar_payload = _valid_source_sidecar()
    del sidecar_payload[missing_field]
    sidecar.write_text(json.dumps(sidecar_payload), encoding="utf-8")
    run_payload = _valid_public_lake_run_metadata(
        input_files=[{"path": str(sidecar), "sha256": "sidecar-hash"}]
    )
    run_metadata, form_ap_metadata = _write_public_lake_metadata(
        tmp_path,
        run_payload,
        _valid_form_ap_metadata(),
    )

    with pytest.raises(ValueError, match=missing_field):
        public_lake_provenance(run_metadata, form_ap_metadata)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("source_url", ""), ("size_bytes", False)],
)
def test_public_lake_provenance_rejects_invalid_sidecar_values(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
) -> None:
    sidecar = tmp_path / "bronze" / "form-ap" / "source.meta.json"
    sidecar.parent.mkdir(parents=True)
    sidecar_payload = _valid_source_sidecar()
    sidecar_payload[field] = invalid_value
    sidecar.write_text(json.dumps(sidecar_payload), encoding="utf-8")
    run_payload = _valid_public_lake_run_metadata(
        input_files=[{"path": str(sidecar), "sha256": "sidecar-hash"}]
    )
    run_metadata, form_ap_metadata = _write_public_lake_metadata(
        tmp_path,
        run_payload,
        _valid_form_ap_metadata(),
    )

    with pytest.raises(ValueError, match=field):
        public_lake_provenance(run_metadata, form_ap_metadata)


@pytest.mark.parametrize(
    "missing_field",
    ["source_kind", "archive_sha256", "member", "member_sha256"],
)
def test_public_lake_provenance_rejects_missing_form_ap_fields(
    tmp_path: Path,
    missing_field: str,
) -> None:
    form_ap_payload = _valid_form_ap_metadata()
    del form_ap_payload[missing_field]
    run_metadata, form_ap_metadata = _write_public_lake_metadata(
        tmp_path,
        _valid_public_lake_run_metadata(),
        form_ap_payload,
    )

    with pytest.raises(ValueError, match=missing_field):
        public_lake_provenance(run_metadata, form_ap_metadata)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("source_kind", "unverified_source"),
        ("archive_sha256", None),
        ("member", ""),
        ("member_sha256", ""),
    ],
)
def test_public_lake_provenance_rejects_invalid_form_ap_values(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
) -> None:
    form_ap_payload = _valid_form_ap_metadata()
    form_ap_payload[field] = invalid_value
    run_metadata, form_ap_metadata = _write_public_lake_metadata(
        tmp_path,
        _valid_public_lake_run_metadata(),
        form_ap_payload,
    )

    with pytest.raises(ValueError, match=field):
        public_lake_provenance(run_metadata, form_ap_metadata)


def test_public_lake_provenance_accepts_standalone_form_ap_without_archive_hash(
    tmp_path: Path,
) -> None:
    form_ap_payload = _valid_form_ap_metadata()
    form_ap_payload.update(
        {
            "source_kind": "standalone_csv_fallback",
            "archive_sha256": None,
        }
    )
    run_metadata, form_ap_metadata = _write_public_lake_metadata(
        tmp_path,
        _valid_public_lake_run_metadata(),
        form_ap_payload,
    )

    reduced = public_lake_provenance(run_metadata, form_ap_metadata)

    assert reduced["form_ap"]["archive_sha256"] is None


def test_claim_maturity_is_controlled_by_component_status() -> None:
    maturity = _claim_maturity(
        {
            "public_cascade": {"status": "complete"},
            "construct_overlap": {
                "run_status": "complete",
                "validation_tier": "wrds_validated",
            },
        }
    )

    assert maturity == {
        "public_prediction": "reportable",
        "feature_and_window_sensitivity": "supporting",
        "construct_alignment": "supporting",
        "opacity_dml": "diagnostic",
    }


@pytest.mark.parametrize("validation_tier", ["candidate_external", "none", None])
def test_claim_maturity_defers_complete_construct_without_wrds_validation(
    validation_tier: str | None,
) -> None:
    maturity = _claim_maturity(
        {
            "public_cascade": {"status": "complete"},
            "construct_overlap": {
                "run_status": "complete",
                "validation_tier": validation_tier,
            },
        }
    )

    assert maturity["construct_alignment"] == "deferred"


def test_run_study_captures_public_cascade_evidence_once_and_hashes_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args, paths = _write_study_fixture(tmp_path, skip_public_cascade=False)
    calls: list[dict[str, Any]] = []
    primary_specification = {
        "feature_set": "actual-summary-feature-set",
        "train_window": "actual-summary-window",
    }

    def fake_run_public_cascade(**kwargs: Any) -> dict[str, Path]:
        calls.append(kwargs)
        out_dir = Path(kwargs["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        summary_json = out_dir / "returned-summary.nonstandard.json"
        sample_attrition_csv = out_dir / "returned-attrition.nonstandard.csv"
        summary_json.write_text(
            json.dumps({"primary_specification": primary_specification}),
            encoding="utf-8",
        )
        sample_attrition_csv.write_text("stage,n_rows\nfinal,7\n", encoding="utf-8")
        return {
            "summary_json": summary_json,
            "sample_attrition_csv": sample_attrition_csv,
        }

    monkeypatch.setattr(run_study_script, "parse_args", lambda: args)
    monkeypatch.setattr(
        public_cascade_module,
        "run_public_cascade",
        fake_run_public_cascade,
    )

    run_study_script.main()

    assert len(calls) == 1
    manifest = json.loads(
        (paths["out_dir"] / "study_run_manifest.json").read_text(encoding="utf-8")
    )
    component = manifest["components"]["public_cascade"]
    assert component == {
        "status": "complete",
        "out_dir": str(paths["out_dir"] / "public_cascade"),
        "summary_json": str(
            paths["out_dir"] / "public_cascade/returned-summary.nonstandard.json"
        ),
        "sample_attrition_csv": str(
            paths["out_dir"] / "public_cascade/returned-attrition.nonstandard.csv"
        ),
        "primary_specification": primary_specification,
    }
    assert manifest["public_lake_provenance"]["form_ap"]["member_sha256"] == "member-hash"
    assert manifest["claim_maturity"]["public_prediction"] == "reportable"
    input_records = {record["path"]: record for record in manifest["provenance"]["input_files"]}
    for metadata_key in ["public_lake_run_metadata", "form_ap_source_metadata"]:
        metadata_path = paths[metadata_key]
        assert input_records[str(metadata_path)]["sha256"] == sha256_path(metadata_path)


@pytest.mark.parametrize(
    "missing_metadata_key",
    ["public_lake_run_metadata", "form_ap_source_metadata"],
)
def test_run_study_fails_before_public_cascade_when_metadata_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_metadata_key: str,
) -> None:
    args, paths = _write_study_fixture(tmp_path, skip_public_cascade=False)
    paths[missing_metadata_key].unlink()
    calls = 0

    def fake_run_public_cascade(**kwargs: Any) -> dict[str, Path]:
        nonlocal calls
        calls += 1
        raise AssertionError(f"unexpected public cascade call: {kwargs}")

    monkeypatch.setattr(run_study_script, "parse_args", lambda: args)
    monkeypatch.setattr(
        public_cascade_module,
        "run_public_cascade",
        fake_run_public_cascade,
    )

    with pytest.raises(FileNotFoundError, match=paths[missing_metadata_key].name):
        run_study_script.main()

    assert calls == 0


@pytest.mark.parametrize(
    "missing_metadata_key",
    ["public_lake_run_metadata", "form_ap_source_metadata"],
)
def test_run_study_skipped_public_cascade_omits_singly_missing_lake_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_metadata_key: str,
) -> None:
    args, paths = _write_study_fixture(tmp_path, skip_public_cascade=True)
    paths[missing_metadata_key].unlink()

    def fail_if_called(**kwargs: Any) -> dict[str, Path]:
        raise AssertionError(f"unexpected public cascade call: {kwargs}")

    monkeypatch.setattr(run_study_script, "parse_args", lambda: args)
    monkeypatch.setattr(public_cascade_module, "run_public_cascade", fail_if_called)

    run_study_script.main()

    manifest = json.loads(
        (paths["out_dir"] / "study_run_manifest.json").read_text(encoding="utf-8")
    )
    assert "public_lake_provenance" not in manifest
    assert manifest["claim_maturity"] == {
        "public_prediction": "deferred",
        "feature_and_window_sensitivity": "deferred",
        "construct_alignment": "deferred",
        "opacity_dml": "deferred",
    }
