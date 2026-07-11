from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scripts.build_reviewer_package import (
    _derive_identity_redactions,
    _redact_entries,
    _source_allowed,
    _validate_entries,
    build_reviewer_package,
)
from tests.canonical_fixture import canonical_fixture


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _write_canonical_attestation(fixture: dict[str, Any]) -> None:
    completed = subprocess.run(
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
            str(fixture["attestation"]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _attested_report_fixture(tmp_path: Path) -> dict[str, Any]:
    fixture = canonical_fixture(tmp_path)
    _write_canonical_attestation(fixture)
    repo = fixture["repo"]
    _git(repo, "add", *(path.relative_to(repo).as_posix() for path in fixture["report_paths"]))
    _git(repo, "commit", "-m", "attested report")
    return fixture


def _build(fixture: dict[str, Any], output: Path) -> Path:
    return build_reviewer_package(
        repo_root=fixture["repo"],
        study_dir=fixture["study_dir"],
        manuscript_package=fixture["package_dir"],
        attestation=fixture["attestation"],
        output=output,
    )


def test_reviewer_suite_is_part_of_core_gate_once() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    core = justfile.split("\n_test-core:\n", 1)[1].split("\n_test-public-lake:", 1)[0]
    assert core.count("tests/test_reviewer_package.py") == 1


def test_source_filter_rejects_forbidden_names_case_insensitively() -> None:
    assert _source_allowed(".env.example")
    assert _source_allowed(".gitignore")
    assert _source_allowed(".github/workflows/ci.yml")
    assert not _source_allowed(".github/workflows/other.yml")
    assert not _source_allowed("tests/private.PARQUET")
    assert not _source_allowed("docs/.VeNv/private.txt")
    assert not _source_allowed("docs/SITE/private.txt")


def test_env_example_uses_portable_placeholders_and_preserves_contract() -> None:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    variables = {
        line.split("=", 1)[0]
        for line in env_example.splitlines()
        if line and not line.startswith("#")
    }
    assert variables == {
        "PROJECT_ROOT",
        "WORK_DIR",
        "DATA_DIR",
        "DOCS_DIR",
        "PAPER_DIR",
        "ARTIFACTS_DIR",
        "DEFAULT_CONFIG_PATH",
        "RAW_DATASET_PATH",
        "PUBLIC_LAKE_DIR",
        "LAKE_BRONZE_DIR",
        "LAKE_SILVER_DIR",
        "LAKE_GOLD_DIR",
        "UV_PROJECT_ENVIRONMENT",
        "MANUSCRIPT_DIR",
        "SEED_DEFAULT",
    }
    assert "/path/to/reporting-risk-cascade-data" in env_example


@pytest.mark.parametrize(
    "marker",
    [
        "/home/example/private.csv",
        "C:\\Users\\example\\private.csv",
        "c:\\users\\example\\private.csv",
    ],
)
def test_validate_entries_rejects_local_path_markers(marker: str) -> None:
    with pytest.raises(ValueError, match="local identity/path marker"):
        _validate_entries({"generated/results.txt": marker.encode()})


def test_identity_redactions_cover_all_categories() -> None:
    entries = {
        "source/pyproject.toml": (
            b'[project]\nname = "fixture"\nversion = "0.1"\n'
            b'authors = [{name = "Avery Example", email = "avery@example.invalid"}]\n'
        ),
        "source/LICENSE": b"Copyright (c) 2026 Example Research Group\n",
        "source/README.md": b"https://github.com/example-owner/fixture\n",
    }
    redactions = _derive_identity_redactions(entries)
    assert {category for _, _, category in redactions} == {
        "project_author_name",
        "project_author_email",
        "repository_owner",
        "copyright_holder",
    }
    redacted = _redact_entries(entries, redactions)
    text = b"\n".join(redacted.values()).decode()
    assert "Avery Example" not in text
    assert "example-owner" not in text


def test_reviewer_accepts_exact_attested_direct_child_and_anonymizes(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "provenance/canonical_attestation.sanitized.json" in names
        package_manifest = json.loads(archive.read("provenance/package_manifest.json"))
        payload = b"\n".join(archive.read(name) for name in names).decode("utf-8", errors="ignore")
    assert package_manifest["study_commit"] == fixture["commit"]
    assert package_manifest["report_commit"] == _git(fixture["repo"], "rev-parse", "HEAD")
    assert package_manifest["upstream_study_commit"] == fixture["commit"]
    assert package_manifest["upstream_report_commit"] == package_manifest["report_commit"]
    for original in ("Avery Example", "avery@example.invalid", "example-owner"):
        assert original.casefold() not in payload.casefold()
    for replacement in ("Anonymous Researcher", "researcher@example.invalid", "anonymous-owner"):
        assert replacement in payload


def test_extracted_attested_source_just_check_passes_without_git(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(output) as archive:
        archive.extractall(extracted)
    source = extracted / "source"
    assert not (source / ".git").exists()
    listed = subprocess.run(
        ["just", "--list"],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, listed.stdout + listed.stderr
    checked = subprocess.run(
        ["just", "check"],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_reviewer_rejects_symlink_package_root(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    link = tmp_path / "package-link"
    try:
        link.symlink_to(fixture["package_dir"], target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    fixture["package_dir"] = link
    with pytest.raises(ValueError, match="symlink"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_forbidden_generated_data(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    (fixture["package_dir"] / "tables" / "forbidden.PARQUET").write_bytes(b"PAR1")
    with pytest.raises(ValueError, match="evidence|undeclared|forbidden"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_grandchild_report_commit(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    _git(fixture["repo"], "commit", "--allow-empty", "-m", "grandchild")
    with pytest.raises(ValueError, match="direct child"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_nonattested_source_delta(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    repo = fixture["repo"]
    _git(repo, "reset", "--soft", fixture["commit"])
    (repo / "src" / "example.py").write_text("FORGED = True\n", encoding="utf-8")
    _git(repo, "add", "src/example.py")
    _git(repo, "commit", "-m", "report plus source")
    with pytest.raises(ValueError, match="report-commit delta"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_source_rename_hidden_as_attested_report_addition(
    tmp_path: Path,
) -> None:
    fixture = canonical_fixture(tmp_path)
    _write_canonical_attestation(fixture)
    repo = fixture["repo"]
    fixture["report_paths"][0].unlink()
    _git(repo, "mv", "src/report_collision.md", "docs/results_snapshot.md")
    _git(
        repo,
        "add",
        *(path.relative_to(repo).as_posix() for path in fixture["report_paths"][1:]),
    )
    _git(repo, "commit", "-m", "rename source into report surface")

    with pytest.raises(ValueError, match="outside the attested report surface"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_changed_attested_report_blob(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    repo = fixture["repo"]
    _git(repo, "reset", "--soft", fixture["commit"])
    snapshot = repo / "docs" / "results_snapshot.md"
    snapshot.write_text("# Forged snapshot\n", encoding="utf-8")
    _git(repo, "add", "docs/results_snapshot.md")
    _git(repo, "commit", "-m", "changed report bytes")
    with pytest.raises(ValueError, match="attested report.*hash"):
        _build(fixture, tmp_path / "reviewer.zip")


@pytest.mark.parametrize("target", ["study", "package", "raw-owner"])
def test_reviewer_rejects_post_attestation_evidence_mutation(
    tmp_path: Path,
    target: str,
) -> None:
    fixture = _attested_report_fixture(tmp_path)
    if target == "study":
        fixture["manifest"].write_bytes(fixture["manifest"].read_bytes() + b"\n")
    elif target == "package":
        fixture["table_03"].write_bytes(fixture["table_03"].read_bytes() + b"\n")
    else:
        fixture["raw"]["metrics"].write_bytes(fixture["raw"]["metrics"].read_bytes() + b"\n")
    output = tmp_path / "reviewer.zip"
    with pytest.raises(ValueError, match="attestation|evidence|provenance|sha256"):
        _build(fixture, output)
    assert not output.exists()


def test_reviewer_rejects_empty_direct_child(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    repo = fixture["repo"]
    _git(repo, "checkout", "-B", "empty-report", fixture["commit"])
    _git(repo, "commit", "--allow-empty", "-m", "empty report")
    with pytest.raises(ValueError, match="delta must be nonempty"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_merge_report_commit(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    repo = fixture["repo"]
    report_branch = _git(repo, "branch", "--show-current")
    _git(repo, "checkout", "-b", "side", fixture["commit"])
    _git(repo, "commit", "--allow-empty", "-m", "side")
    _git(repo, "checkout", report_branch)
    _git(repo, "merge", "--no-ff", "side", "-m", "merge report")
    with pytest.raises(ValueError, match="direct child"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_undeclared_report_delta(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    repo = fixture["repo"]
    _git(repo, "reset", "--soft", fixture["commit"])
    extra = repo / "docs" / "assets" / "results_snapshot" / "undeclared.png"
    extra.write_bytes(b"undeclared")
    _git(repo, "add", extra.relative_to(repo).as_posix())
    _git(repo, "commit", "-m", "report plus undeclared asset")
    with pytest.raises(ValueError, match="outside the attested report surface"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_missing_attested_report_blob(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    repo = fixture["repo"]
    missing = fixture["report_paths"][-1].relative_to(repo).as_posix()
    _git(repo, "reset", "--soft", fixture["commit"])
    _git(repo, "rm", "--cached", "--", missing)
    _git(repo, "commit", "-m", "incomplete report")
    with pytest.raises(ValueError, match="attested report blob is missing"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_refreshed_package_hash_substitution(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    table = pd.read_csv(fixture["table_03"])
    table.loc[0, "Mean_PR_AUC"] = 0.999
    table.to_csv(fixture["table_03"], index=False)
    manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    manifest["tables"]["table_03"]["csv"]["sha256"] = hashlib.sha256(
        fixture["table_03"].read_bytes()
    ).hexdigest()
    _write(fixture["package_manifest"], json.dumps(manifest))
    with pytest.raises(ValueError, match="current evidence does not match attestation"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_forged_attestation_field(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    attestation = json.loads(fixture["attestation"].read_text(encoding="utf-8"))
    attestation["package_manifest_sha256"] = "0" * 64
    _write(fixture["attestation"], json.dumps(attestation))
    with pytest.raises(ValueError, match="exactly match canonical attestation"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_rejects_non_utc_attestation_timestamp(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    attestation = json.loads(fixture["attestation"].read_text(encoding="utf-8"))
    attestation["verified_at_utc"] = "2026-07-06T08:00:00+08:00"
    _write(fixture["attestation"], json.dumps(attestation))
    with pytest.raises(ValueError, match="UTC timestamp"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_failure_preserves_existing_zip(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = tmp_path / "reviewer.zip"
    output.write_bytes(b"prior reviewer archive")
    _git(fixture["repo"], "commit", "--allow-empty", "-m", "grandchild")
    with pytest.raises(ValueError, match="direct child"):
        _build(fixture, output)
    assert output.read_bytes() == b"prior reviewer archive"


def test_reviewer_archives_only_attested_report_paths_and_hashes_attestation(
    tmp_path: Path,
) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    with zipfile.ZipFile(output) as archive:
        report_names = sorted(name for name in archive.namelist() if name.startswith("report/"))
        expected = sorted(
            f"report/{path.relative_to(fixture['repo']).as_posix()}"
            for path in fixture["report_paths"]
        )
        assert report_names == expected
        manifest = json.loads(archive.read("provenance/package_manifest.json"))
        record = manifest["canonical_attestation"]
        archived = archive.read(record["path"])
    assert hashlib.sha256(archived).hexdigest() == record["sha256"]


def test_reviewer_recipe_consumes_canonical_attestation() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    recipe = justfile.split("\nreviewer-package ", 1)[1].split("\n_docs-build:", 1)[0]
    assert (
        '--attestation "${ARTIFACTS_DIR}/canonical_validation/canonical_attestation.json"'
    ) in recipe


def test_reviewer_cli_help_requires_attestation() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/build_reviewer_package.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--attestation" in completed.stdout


def test_validate_entries_rejects_original_identity() -> None:
    with pytest.raises(ValueError, match="original identity marker"):
        _validate_entries(
            {"source/README.md": b"Avery Example"},
            identity_needles=["Avery Example"],
        )


def test_binary_path_marker_is_rejected() -> None:
    marker = b"\x89PNG\r\nC:\\Users\\example\\private.png"
    with pytest.raises(ValueError, match="local identity/path marker"):
        _validate_entries({"generated/figure.png": marker})


def test_reviewer_attestation_hash_uses_archived_sanitized_bytes(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("provenance/package_manifest.json"))
        record = manifest["canonical_attestation"]
        payload = archive.read(record["path"])
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()


def test_reviewer_archive_contains_no_local_fixture_path(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    with zipfile.ZipFile(output) as archive:
        payload = b"\n".join(archive.read(name) for name in archive.namelist())
    assert str(tmp_path).encode() not in payload


def test_reviewer_output_is_created_only_after_validation(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = tmp_path / "missing" / "reviewer.zip"
    _git(fixture["repo"], "commit", "--allow-empty", "-m", "grandchild")
    with pytest.raises(ValueError, match="direct child"):
        _build(fixture, output)
    assert not output.parent.exists()


def test_reviewer_package_root_has_no_symlink_entries(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    external = tmp_path / "external.csv"
    external.write_text("private\n", encoding="utf-8")
    link = fixture["package_dir"] / "tables" / "escape.csv"
    try:
        link.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    with pytest.raises(ValueError, match="symlink"):
        _build(fixture, tmp_path / "reviewer.zip")


def test_reviewer_preserves_replication_readme(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    with zipfile.ZipFile(output) as archive:
        readme = archive.read("REPLICATION_README.md").decode()
    assert "cd source" in readme
    assert "just verify-canonical" in readme


def test_reviewer_provenance_manifest_names_upstream_identities(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("provenance/package_manifest.json"))
    assert manifest["study_commit"] == manifest["upstream_study_commit"]
    assert manifest["report_commit"] == manifest["upstream_report_commit"]


def test_reviewer_report_overlay_manifest_lists_exact_six_paths(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("provenance/package_manifest.json"))
    expected = sorted(
        path.relative_to(fixture["repo"]).as_posix() for path in fixture["report_paths"]
    )
    assert manifest["report_overlay"] == {
        "policy": "report_commit_overlays_source",
        "paths": expected,
    }


def test_reviewer_generated_inventory_matches_attested_package(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    attestation = json.loads(fixture["attestation"].read_text(encoding="utf-8"))
    output = _build(fixture, tmp_path / "reviewer.zip")
    with zipfile.ZipFile(output) as archive:
        generated = {
            name.removeprefix("generated/manuscript_package/")
            for name in archive.namelist()
            if name.startswith("generated/manuscript_package/")
            and not name.endswith("manifest.json")
        }
    assert generated == {record["path"] for record in attestation["package_artifacts"]}
