from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import scripts.verify_canonical_run as canonical_module
from scripts.build_manuscript_package import _validate_package_tree
from scripts.verify_canonical_run import (
    RAW_RECONSTRUCTION_OWNERS,
    _write_attestation,
    verify_canonical_run,
)
from src.provenance import input_provenance, path_record, path_set_provenance, sha256_path
from tests.canonical_fixture import canonical_fixture, git, write_json


def _verify(fixture: dict[str, Any], *, bronze_root: Path | None = None) -> list[str]:
    return verify_canonical_run(
        fixture["study_dir"],
        fixture["package_dir"],
        repo_root=fixture["repo"],
        expected_as_of_date="2026-07-06",
        bronze_root=bronze_root,
    )


def _run_cli(
    fixture: dict[str, Any], *, output: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/verify_canonical_run.py",
            "--repo-root",
            str(fixture["repo"]),
            "--study-dir",
            str(fixture["study_dir"]),
            "--manuscript-package",
            str(fixture["package_dir"]),
            "--expected-as-of-date",
            "2026-07-06",
            "--attestation-output",
            str(output or fixture["attestation"]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _write_json(path: Path, payload: object) -> None:
    write_json(path, payload)


def _refresh_package_artifact(fixture: dict[str, Any], table_key: str) -> None:
    manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    manifest["tables"][table_key]["csv"]["sha256"] = sha256_path(fixture[table_key])
    _write_json(fixture["package_manifest"], manifest)


def _refresh_package_study_digest(fixture: dict[str, Any]) -> None:
    manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    manifest["study_manifest_sha256"] = sha256_path(fixture["manifest"])
    _write_json(fixture["package_manifest"], manifest)


def test_r4_exact_precommit_surface_is_a_valid_r3_fixture(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)

    package = _validate_package_tree(fixture["package_dir"], fixture["manifest"])
    assert len(package["tables"]) == 16
    assert len(package["figures"]) == 5
    assert len(fixture["report_paths"]) == 6
    assert _verify(fixture) == []


def test_r5_accepts_all_skipped_dml_with_deferred_maturity(tmp_path: Path) -> None:
    fixture = canonical_fixture(
        tmp_path,
        dml_statuses=(
            "skipped_one_class_or_too_small",
            "skipped_missing_label_or_censor",
            "skipped_constant_treatment",
        ),
    )

    assert _verify(fixture) == []
    package_manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    contract = package_manifest["reporting_contract"]
    assert contract["opacity_dml_evidence"]["fit_outcomes"] == []
    assert contract["claim_maturity"]["opacity_dml"] == "deferred"


def test_canonical_suite_is_in_core_gate_exactly_once() -> None:
    justfile = (Path(__file__).resolve().parents[1] / "justfile").read_text(encoding="utf-8")
    core = justfile.split("\n_test-core:\n", 1)[1].split("\n_test-public-lake:", 1)[0]
    assert core.count("tests/test_canonical_run.py") == 1


def test_verify_recipe_writes_the_canonical_attestation_path() -> None:
    justfile = (Path(__file__).resolve().parents[1] / "justfile").read_text(encoding="utf-8")
    recipe = justfile.split("\nverify-canonical ", 1)[1].split("\nreviewer-package ", 1)[0]
    assert (
        '--attestation-output "${ARTIFACTS_DIR}/canonical_validation/canonical_attestation.json"'
    ) in recipe


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("parallel_jobs", 999),
        ("parallel_jobs", True),
        ("parallel_jobs", 4.0),
        ("model_threads", True),
        ("model_threads", 2.0),
        ("seed_policy", "shared"),
        ("peer_comparison_mode", "none"),
        ("peer_target", "benchmark"),
        ("peer_parallel_jobs", 999),
        ("peer_parallel_jobs", True),
        ("peer_parallel_jobs", 4.0),
        ("peer_model_threads", True),
        ("peer_model_threads", 2.0),
    ],
)
def test_r4_rejects_noncanonical_runtime_values_and_integer_impostors(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    fixture = canonical_fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["runtime"][field] = replacement
    _write_json(fixture["manifest"], manifest)

    assert f"runtime {field}" in _verify(fixture)


@pytest.mark.parametrize("target", ["config", "input", "lock"])
def test_r4_rejects_changed_study_provenance_bytes(
    tmp_path: Path,
    target: str,
) -> None:
    fixture = canonical_fixture(tmp_path)
    path = fixture[target]
    path.write_bytes(path.read_bytes() + b"\nforged")
    assert "recomputed study provenance" in _verify(fixture)


@pytest.mark.parametrize("target", ["lake_config", "sidecar", "payload"])
def test_r4_rejects_changed_public_lake_provenance_bytes(
    tmp_path: Path,
    target: str,
) -> None:
    fixture = canonical_fixture(tmp_path)
    path = fixture[target]
    path.write_bytes(path.read_bytes() + b"\nforged")
    assert any("public-lake" in error or "payload" in error for error in _verify(fixture))


@pytest.mark.parametrize("target", ["run_metadata", "form_ap", "panel", "final_report"])
def test_r4_rejects_changed_frozen_public_lake_input(
    tmp_path: Path,
    target: str,
) -> None:
    fixture = canonical_fixture(tmp_path)
    path = fixture[target]
    path.write_bytes(path.read_bytes() + b"\nforged")
    assert _verify(fixture)


def test_r4_rejects_changed_form_ap_member_after_outer_hashes_are_refreshed(
    tmp_path: Path,
) -> None:
    fixture = canonical_fixture(tmp_path)
    with zipfile.ZipFile(fixture["payload"], "w") as archive:
        archive.writestr("FirmFilings.csv", b"firm_id,filing_date\n9,2026-07-01\n")

    sidecar = json.loads(fixture["sidecar"].read_text(encoding="utf-8"))
    sidecar["sha256"] = sha256_path(fixture["payload"])
    sidecar["size_bytes"] = fixture["payload"].stat().st_size
    _write_json(fixture["sidecar"], sidecar)

    run_metadata = json.loads(fixture["run_metadata"].read_text(encoding="utf-8"))
    run_inputs = input_provenance([fixture["sidecar"]])
    run_metadata["provenance"].update(run_inputs)
    _write_json(fixture["run_metadata"], run_metadata)

    form_ap = json.loads(fixture["form_ap"].read_text(encoding="utf-8"))
    form_ap["archive_sha256"] = sha256_path(fixture["payload"])
    _write_json(fixture["form_ap"], form_ap)

    final_report = json.loads(fixture["final_report"].read_text(encoding="utf-8"))
    final_report["public_lake_run_metadata_sha256"] = sha256_path(fixture["run_metadata"])
    _write_json(fixture["final_report"], final_report)

    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    for key, target in (
        ("public_lake_final_report", "final_report"),
        ("public_lake_run_metadata", "run_metadata"),
        ("form_ap_source_metadata", "form_ap"),
    ):
        manifest["public_lake_inputs"][key] = path_record(fixture[target])
    input_paths = [Path(record["path"]) for record in manifest["provenance"]["input_files"]]
    manifest["provenance"].update(input_provenance(input_paths))
    inventory = manifest["public_lake_provenance"]["source_metadata_inventory"][0]
    inventory["metadata_sha256"] = sha256_path(fixture["sidecar"])
    inventory["payload_sha256"] = sha256_path(fixture["payload"])
    inventory["payload_size_bytes"] = fixture["payload"].stat().st_size
    manifest["public_lake_provenance"]["input_hash"] = run_inputs["input_hash"]
    manifest["public_lake_provenance"]["form_ap"]["archive_sha256"] = sha256_path(
        fixture["payload"]
    )
    _write_json(fixture["manifest"], manifest)
    _refresh_package_study_digest(fixture)

    assert "member_sha256" in _verify(fixture)[0]


def test_r4_accepts_equivalent_resolved_uv_lock_path_spelling(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    lock_path = str(fixture["lock"])
    if not lock_path.startswith("/private/var/"):
        pytest.skip("macOS /var alias is unavailable")
    alias = "/var/" + lock_path.removeprefix("/private/var/")
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["provenance"]["uv_lock"]["path"] = alias
    _write_json(fixture["manifest"], manifest)
    _refresh_package_study_digest(fixture)
    assert _verify(fixture) == []


def test_r4_derives_arbitrary_bronze_root_and_rejects_wrong_override(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    assert _verify(fixture) == []
    assert "Bronze root override" in _verify(fixture, bronze_root=tmp_path / "wrong")[0]


def test_r4_rejects_unresolvable_recorded_commit(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    for owner in (manifest, manifest["provenance"], manifest["public_lake_provenance"]):
        owner["repo_commit" if owner is manifest else "commit_sha"] = "0" * 40
    _write_json(fixture["manifest"], manifest)
    assert _verify(fixture)


def test_r4_rejects_wrong_live_head(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    (fixture["repo"] / "src" / "example.py").write_text("CHANGED = True\n", encoding="utf-8")
    git(fixture["repo"], "add", "src/example.py")
    git(fixture["repo"], "commit", "-m", "wrong head")
    assert "source HEAD" in _verify(fixture)[0]


@pytest.mark.parametrize(
    "mode",
    ["unstaged-source", "staged-test", "dirty-verifier", "rename", "untracked"],
)
def test_r4_rejects_nonreport_working_tree_state(tmp_path: Path, mode: str) -> None:
    fixture = canonical_fixture(tmp_path)
    repo = fixture["repo"]
    if mode == "unstaged-source":
        (repo / "src" / "example.py").write_text("CHANGED = True\n", encoding="utf-8")
    elif mode == "staged-test":
        (repo / "tests" / "test_example.py").write_text("def test_no(): assert False\n")
        git(repo, "add", "tests/test_example.py")
    elif mode == "dirty-verifier":
        (repo / "scripts" / "verify_canonical_run.py").write_text("VERIFIER_VERSION = 'x'\n")
    elif mode == "rename":
        git(repo, "mv", "src/example.py", "src/renamed.py")
    else:
        (repo / "scripts" / "untracked.py").write_text("print('x')\n")
    assert "working tree report surface" in _verify(fixture)[0]


@pytest.mark.parametrize("status", ["DD", "AU", "UD", "UA", "DU", "AA", "UU"])
def test_r4_rejects_unmerged_report_surface_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    fixture = canonical_fixture(tmp_path)
    report_path = fixture["report_paths"][0].relative_to(fixture["repo"]).as_posix()
    monkeypatch.setattr(
        canonical_module,
        "_working_tree_records",
        lambda _repo: ([(status, report_path)], False),
    )
    assert "unmerged" in _verify(fixture)[0]


@pytest.mark.parametrize("mode", ["grandchild", "merge"])
def test_r4_rejects_explicit_nonstudy_precommit_head(tmp_path: Path, mode: str) -> None:
    fixture = canonical_fixture(tmp_path)
    repo = fixture["repo"]
    if mode == "grandchild":
        git(repo, "commit", "--allow-empty", "-m", "child")
        git(repo, "commit", "--allow-empty", "-m", "grandchild")
    else:
        main_branch = git(repo, "branch", "--show-current")
        git(repo, "checkout", "-b", "side")
        git(repo, "commit", "--allow-empty", "-m", "side")
        git(repo, "checkout", main_branch)
        git(repo, "commit", "--allow-empty", "-m", "main")
        git(repo, "merge", "--no-ff", "side", "-m", "merge")
    assert "source HEAD" in _verify(fixture)[0]


def test_r4_rejects_dirty_recorded_config(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    fixture["config"].write_text("study: dirty\n", encoding="utf-8")
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    config_paths = [Path(record["path"]) for record in manifest["provenance"]["config_files"]]
    refreshed = path_set_provenance(config_paths)
    manifest["provenance"]["config_files"] = refreshed["files"]
    manifest["provenance"]["config_hash"] = refreshed["hash"]
    _write_json(fixture["manifest"], manifest)
    _refresh_package_study_digest(fixture)
    assert "working tree report surface" in _verify(fixture)[0]


@pytest.mark.parametrize("mode", ["extra", "missing", "symlink", "snapshot-symlink"])
def test_r4_rejects_nonexact_report_surface(tmp_path: Path, mode: str) -> None:
    fixture = canonical_fixture(tmp_path)
    asset_root = fixture["repo"] / "docs" / "assets" / "results_snapshot"
    if mode == "extra":
        (asset_root / "stale.png").write_bytes(b"stale")
    elif mode == "missing":
        fixture["report_paths"][-1].unlink()
    elif mode == "symlink":
        target = fixture["report_paths"][-1]
        target.unlink()
        try:
            target.symlink_to(tmp_path / "outside.png")
        except OSError as exc:
            pytest.skip(f"symlink unavailable: {exc}")
    else:
        target = fixture["report_paths"][0]
        target.unlink()
        try:
            target.symlink_to(tmp_path / "outside.md")
        except OSError as exc:
            pytest.skip(f"symlink unavailable: {exc}")
    assert "report" in _verify(fixture)[0] or "asset" in _verify(fixture)[0]


def test_r4_rejects_report_png_that_no_longer_matches_package_png(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    fixture["report_paths"][-1].write_bytes(b"\x89PNG\r\nforged")
    assert "package PNG" in _verify(fixture)[0]


@pytest.mark.parametrize(
    ("files_field", "hash_field"),
    [("config_files", "config_hash"), ("input_files", "input_hash")],
)
def test_r4_rejects_recomputed_missing_path_record(
    tmp_path: Path,
    files_field: str,
    hash_field: str,
) -> None:
    fixture = canonical_fixture(tmp_path)
    provenance = path_set_provenance([tmp_path / "missing-input"])
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["provenance"][files_field] = provenance["files"]
    manifest["provenance"][hash_field] = provenance["hash"]
    _write_json(fixture["manifest"], manifest)
    _refresh_package_study_digest(fixture)
    assert "existing regular file" in _verify(fixture)[0]


def test_r4_malformed_components_returns_failure_instead_of_raising(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["components"] = []
    _write_json(fixture["manifest"], manifest)
    _refresh_package_study_digest(fixture)
    assert "components must be an object" in _verify(fixture)[0]


def test_r4_rejects_symlink_package_root(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    link = tmp_path / "package-link"
    try:
        link.symlink_to(fixture["package_dir"], target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    fixture["package_dir"] = link
    assert "package root must not be a symlink" in _verify(fixture)[0]


@pytest.mark.parametrize(
    ("table_key", "column", "replacement"),
    [
        ("table_03", "Mean_PR_AUC", 0.999),
        ("table_09", "PR_AUC", 0.999),
        ("table_12", "Coef", 0.999),
        ("table_12", "Coef", float("nan")),
        ("table_18", "Stage", "forged_stage"),
    ],
)
def test_r4_rejects_refreshed_hash_table_cell_substitution(
    tmp_path: Path,
    table_key: str,
    column: str,
    replacement: object,
) -> None:
    fixture = canonical_fixture(tmp_path)
    table = pd.read_csv(fixture[table_key])
    table.loc[0, column] = replacement
    table.to_csv(fixture[table_key], index=False)
    _refresh_package_artifact(fixture, table_key)
    _validate_package_tree(fixture["package_dir"], fixture["manifest"])
    assert f"{table_key} deterministic reconstruction" in _verify(fixture)


def test_r4_rejects_one_file_package_even_when_the_file_exists(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    manifest["tables"] = {"table_03": manifest["tables"]["table_03"]}
    manifest["figures"] = {}
    _write_json(fixture["package_manifest"], manifest)
    assert "package tables keys must be exactly" in _verify(fixture)[0]


@pytest.mark.parametrize("table_key", ["table_03", "table_09", "table_12", "table_18"])
def test_r4_rejects_every_refreshed_hash_displayed_cell(
    tmp_path: Path,
    table_key: str,
) -> None:
    fixture = canonical_fixture(tmp_path)
    table_path = fixture[table_key]
    original_table = table_path.read_bytes()
    original_manifest = fixture["package_manifest"].read_bytes()
    for column in pd.read_csv(table_path).columns:
        table = pd.read_csv(table_path)
        value = table.loc[0, column]
        if pd.isna(value):
            replacement: object = 0.123
        elif isinstance(value, bool):
            replacement = not value
        elif pd.api.types.is_number(value):
            replacement = float(value) + 0.123
        else:
            replacement = f"{value}__forged"
        table[column] = table[column].astype(object)
        table.loc[0, column] = replacement
        table.to_csv(table_path, index=False)
        _refresh_package_artifact(fixture, table_key)
        assert f"{table_key} deterministic reconstruction" in _verify(fixture), column
        table_path.write_bytes(original_table)
        fixture["package_manifest"].write_bytes(original_manifest)


@pytest.mark.parametrize("table_key", ["table_03", "table_09", "table_12", "table_18"])
@pytest.mark.parametrize("mode", ["rows", "columns"])
def test_r4_rejects_refreshed_hash_table_order_mutation(
    tmp_path: Path,
    table_key: str,
    mode: str,
) -> None:
    fixture = canonical_fixture(tmp_path)
    table = pd.read_csv(fixture[table_key])
    table = table.iloc[::-1].reset_index(drop=True) if mode == "rows" else table.iloc[:, ::-1]
    table.to_csv(fixture[table_key], index=False)
    _refresh_package_artifact(fixture, table_key)
    assert f"{table_key} deterministic reconstruction" in _verify(fixture)


@pytest.mark.parametrize(
    ("target", "path", "replacement", "message"),
    [
        ("manifest", ("components", "benchmark", "status"), "pending", "benchmark component"),
        (
            "manifest",
            ("claim_maturity", "public_prediction"),
            "diagnostic",
            "claim maturity",
        ),
        ("construct", ("interval_seed",), 7, "construct bootstrap seed"),
        (
            "construct",
            ("interval_method",),
            "row_percentile_bootstrap",
            "construct bootstrap method",
        ),
        (
            "construct",
            ("primary_alignment", "public_to_benchmark_count"),
            0,
            "public-to-benchmark primary count",
        ),
        ("public", ("primary_specification_status",), "mutable", "public primary status"),
        (
            "dml_meta",
            ("n_encoded_controls_by_fold", "comment_thread", 0, "fold_id"),
            2,
            "DML CSV/meta/Table 12 consistency",
        ),
    ],
)
def test_r4_shared_collector_preserves_research_semantic_gates(
    tmp_path: Path,
    target: str,
    path: tuple[object, ...],
    replacement: object,
    message: str,
) -> None:
    fixture = canonical_fixture(tmp_path)
    target_path = fixture["raw"][target] if target in fixture["raw"] else fixture[target]
    payload = json.loads(target_path.read_text(encoding="utf-8"))
    cursor: Any = payload
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    _write_json(target_path, payload)
    if target == "manifest":
        _refresh_package_study_digest(fixture)
    assert message in _verify(fixture)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("reporting_boundaries", "sample_proxy", "validates_us_gaap"), True),
        (("feature_family_summary", "oversight", "model_eligible_features"), []),
        (
            (
                "reporting_boundaries",
                "pcaob_inspection_predictors",
                "inspection_event_joined_to_gold",
            ),
            True,
        ),
        (
            (
                "reporting_boundaries",
                "partner_nonadministrative_amendment",
                "nonzero_rows",
            ),
            0,
        ),
        (("opacity_dml_evidence", "fit_outcomes"), []),
        (("claim_maturity", "opacity_dml"), "deferred"),
        (("artifact_ownership", "experiment_3", "tables"), ["table_12", "table_01"]),
    ],
    ids=[
        "proxy-flag",
        "oversight-features",
        "inspection-status",
        "partner-variation",
        "dml-evidence",
        "dml-maturity",
        "ownership",
    ],
)
def test_r5_rejects_package_reporting_contract_mutation(
    tmp_path: Path,
    path: tuple[str, ...],
    replacement: object,
) -> None:
    fixture = canonical_fixture(tmp_path)
    package_manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    cursor = package_manifest["reporting_contract"]
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    _write_json(fixture["package_manifest"], package_manifest)

    error = _verify(fixture)[0]
    expected = "claim maturity" if path[0] == "claim_maturity" else "reporting contract"
    assert expected in error


def test_r5_rejects_coordinated_dml_evidence_forgery(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    public_summary = json.loads(fixture["public"].read_text(encoding="utf-8"))
    forged_evidence = public_summary["opacity_dml_evidence"]
    forged_evidence["status_by_outcome"] = {
        outcome: "fit" for outcome in forged_evidence["required_outcomes"]
    }
    forged_evidence["fit_outcomes"] = list(forged_evidence["required_outcomes"])
    forged_evidence["maturity_by_outcome"] = {
        outcome: "diagnostic" for outcome in forged_evidence["required_outcomes"]
    }
    _write_json(fixture["public"], public_summary)

    study_manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    study_manifest["components"]["public_cascade"]["opacity_dml_evidence"] = forged_evidence
    _write_json(fixture["manifest"], study_manifest)

    package_manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    package_manifest["reporting_contract"]["opacity_dml_evidence"] = forged_evidence
    package_manifest["study_manifest_sha256"] = sha256_path(fixture["manifest"])
    _write_json(fixture["package_manifest"], package_manifest)

    assert "artifact-derived DML evidence" in _verify(fixture)


def test_r5_rejects_coordinated_dml_maturity_forgery(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    study_manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    study_manifest["claim_maturity"]["opacity_dml"] = "deferred"
    _write_json(fixture["manifest"], study_manifest)

    package_manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    package_manifest["reporting_contract"]["claim_maturity"]["opacity_dml"] = "deferred"
    package_manifest["study_manifest_sha256"] = sha256_path(fixture["manifest"])
    _write_json(fixture["package_manifest"], package_manifest)

    assert "artifact-derived DML maturity" in _verify(fixture)


def test_r4_rejects_unpaired_construct_tier(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    construct = json.loads(fixture["construct"].read_text(encoding="utf-8"))
    construct["validation_tier"] = "candidate_external"
    _write_json(fixture["construct"], construct)
    assert "paired bridge tier" in _verify(fixture)[0]


def test_r5_cli_writes_complete_sanitized_atomic_attestation(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    completed = _run_cli(fixture)
    assert completed.returncode == 0, completed.stdout + completed.stderr

    raw = fixture["attestation"].read_text(encoding="utf-8")
    attestation = json.loads(raw)
    assert set(attestation) == {
        "schema_version",
        "verifier_version",
        "verified_at_utc",
        "study_commit",
        "expected_as_of_date",
        "paired_bridge_tier",
        "runtime",
        "study_manifest_sha256",
        "study_config_hash",
        "study_input_hash",
        "study_uv_lock_hash",
        "public_lake_inputs",
        "public_lake_config_hash",
        "public_lake_input_hash",
        "public_lake_uv_lock_hash",
        "package_manifest_sha256",
        "package_study_manifest_sha256",
        "package_artifacts",
        "raw_reconstruction_owners",
        "report_surface",
    }
    assert attestation["schema_version"] == "canonical-attestation-v1"
    assert attestation["verifier_version"] == "5"
    assert "reporting_contract" not in attestation
    timestamp = datetime.fromisoformat(attestation["verified_at_utc"])
    assert timestamp.tzinfo is not None and timestamp.utcoffset() == timedelta(0)
    assert attestation["study_commit"] == fixture["commit"]
    assert attestation["expected_as_of_date"] == "2026-07-06"
    assert attestation["paired_bridge_tier"] == "wrds_validated"
    assert attestation["runtime"] == {
        "parallel_jobs": 4,
        "model_threads": 2,
        "seed_policy": "task-isolated",
        "peer_comparison_mode": "full",
        "peer_target": "both",
        "peer_parallel_jobs": 4,
        "peer_model_threads": 2,
    }
    study_manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    package_manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    assert attestation["study_manifest_sha256"] == sha256_path(fixture["manifest"])
    assert attestation["study_config_hash"] == study_manifest["provenance"]["config_hash"]
    assert attestation["study_input_hash"] == study_manifest["provenance"]["input_hash"]
    assert attestation["study_uv_lock_hash"] == study_manifest["provenance"]["uv_lock_hash"]
    assert attestation["public_lake_inputs"] == {
        key: record["sha256"]
        for key, record in sorted(study_manifest["public_lake_inputs"].items())
    }
    assert (
        attestation["public_lake_config_hash"]
        == study_manifest["public_lake_provenance"]["config_hash"]
    )
    assert (
        attestation["public_lake_input_hash"]
        == study_manifest["public_lake_provenance"]["input_hash"]
    )
    assert (
        attestation["public_lake_uv_lock_hash"]
        == study_manifest["public_lake_provenance"]["uv_lock_hash"]
    )
    assert attestation["package_manifest_sha256"] == sha256_path(fixture["package_manifest"])
    assert (
        attestation["package_study_manifest_sha256"] == package_manifest["study_manifest_sha256"]
    )
    assert len(attestation["package_artifacts"]) == 59
    assert len(attestation["raw_reconstruction_owners"]) == len(RAW_RECONSTRUCTION_OWNERS) == 8
    assert len(attestation["report_surface"]) == 6
    for field in ("package_artifacts", "raw_reconstruction_owners", "report_surface"):
        assert [record["path"] for record in attestation[field]] == sorted(
            record["path"] for record in attestation[field]
        )
        assert all(not Path(record["path"]).is_absolute() for record in attestation[field])
    for record in attestation["package_artifacts"]:
        assert record["sha256"] == sha256_path(fixture["package_dir"] / record["path"])
    for record in attestation["raw_reconstruction_owners"]:
        assert record["sha256"] == sha256_path(fixture["study_dir"] / record["path"])
    for record in attestation["report_surface"]:
        assert record["sha256"] == sha256_path(fixture["repo"] / record["path"])
    assert str(tmp_path) not in raw


@pytest.mark.parametrize("prior", [None, b"prior-attestation\n"])
def test_r4_invalid_verification_does_not_create_or_replace_attestation(
    tmp_path: Path,
    prior: bytes | None,
) -> None:
    fixture = canonical_fixture(tmp_path)
    if prior is not None:
        fixture["attestation"].write_bytes(prior)
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    manifest["runtime"]["parallel_jobs"] = 999
    _write_json(fixture["manifest"], manifest)

    completed = _run_cli(fixture)
    assert completed.returncode == 1
    if prior is None:
        assert not fixture["attestation"].exists()
    else:
        assert fixture["attestation"].read_bytes() == prior


def test_r4_atomic_attestation_replace_failure_preserves_prior_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "canonical_attestation.json"
    output.write_bytes(b"prior\n")
    real_replace = Path.replace

    def fail_output_replace(source: Path, target: Path) -> Path:
        if Path(target) == output:
            raise OSError("injected replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_output_replace)
    with pytest.raises(OSError, match="injected"):
        _write_attestation(output, {"study_commit": "0" * 40})
    assert output.read_bytes() == b"prior\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_r4_cli_help_names_attestation_and_repository_inputs() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify_canonical_run.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--repo-root" in completed.stdout
    assert "--bronze-root" in completed.stdout
    assert "--attestation-output" in completed.stdout


def test_r4_attestation_contains_no_raw_zip_member_bytes(tmp_path: Path) -> None:
    fixture = canonical_fixture(tmp_path)
    assert _run_cli(fixture).returncode == 0
    with zipfile.ZipFile(fixture["payload"]) as archive:
        member = archive.read("FirmFilings.csv")
    assert member not in fixture["attestation"].read_bytes()
