from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import scripts.build_reviewer_package as reviewer_module
from scripts.build_reviewer_package import (
    _derive_identity_redactions,
    _redact_entries,
    _sanitize,
    _source_allowed,
    _validate_entries,
    build_reviewer_package,
)
from scripts.verify_canonical_run import collect_canonical_evidence
from src.provenance import (
    config_provenance,
    input_provenance,
    path_record,
    public_lake_provenance,
    sha256_path,
    uv_lock_provenance,
)
from tests.canonical_fixture import canonical_fixture


REPO_ROOT = Path(__file__).resolve().parents[1]
SLASH = chr(47)
BACKSLASH = chr(92)
COLON = chr(58)
POSIX_HOME_PATH = SLASH + "home" + SLASH + "example" + SLASH + "private.csv"
WINDOWS_USER_PATH = (
    "C" + COLON + BACKSLASH + "Users" + BACKSLASH + "example" + BACKSLASH + "private.csv"
)
WINDOWS_USER_PATH_LOWER = WINDOWS_USER_PATH.lower()
WINDOWS_DRIVE_USER_PATH = "D" + COLON + SLASH + "Users" + SLASH + "alice" + SLASH + "private.csv"
WINDOWS_DRIVE_USER_PATH_BACKSLASH = (
    "D" + COLON + BACKSLASH + "Users" + BACKSLASH + "alice" + BACKSLASH + "private.csv"
)
WINDOWS_DRIVE_ROOT_PATH = "Z" + COLON + SLASH + "private" + SLASH + "data.csv"
BACKSLASH_UNC_PATH = BACKSLASH * 2 + "server" + BACKSLASH + "share" + BACKSLASH + "private.csv"
FORWARD_UNC_PATH = SLASH * 2 + "server" + SLASH + "share" + SLASH + "private.csv"


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


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _rebind_bounded_evidence_to_derivative(
    fixture: dict[str, Any],
    derivative_repo: Path,
    derivative_commit: str,
) -> None:
    run_metadata = json.loads(fixture["run_metadata"].read_text(encoding="utf-8"))
    run_metadata["provenance"] = {
        "commit_sha": derivative_commit,
        "dirty": False,
        "dirty_status": "",
        **config_provenance([derivative_repo / "config" / "public_lake.yaml"]),
        **input_provenance([fixture["sidecar"]]),
        **uv_lock_provenance(derivative_repo),
    }
    _write_json(fixture["run_metadata"], run_metadata)

    final_report = json.loads(fixture["final_report"].read_text(encoding="utf-8"))
    final_report["public_lake_run_metadata_sha256"] = sha256_path(fixture["run_metadata"])
    _write_json(fixture["final_report"], final_report)

    study_manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    input_paths = [Path(record["path"]) for record in study_manifest["provenance"]["input_files"]]
    study_manifest["repo_commit"] = derivative_commit
    study_manifest["git_dirty"] = False
    study_manifest["provenance"] = {
        "commit_sha": derivative_commit,
        "dirty": False,
        "dirty_status": "",
        **config_provenance(
            [
                derivative_repo / "config" / "study.yaml",
                derivative_repo / "config" / "benchmark.yaml",
                derivative_repo / "config" / "public_cascade.yaml",
            ]
        ),
        **input_provenance(input_paths),
        **uv_lock_provenance(derivative_repo),
    }
    study_manifest["public_lake_inputs"] = {
        key: path_record(Path(record["path"]))
        for key, record in study_manifest["public_lake_inputs"].items()
    }
    study_manifest["public_lake_provenance"] = public_lake_provenance(
        fixture["run_metadata"],
        fixture["form_ap"],
        bronze_root=fixture["bronze"],
    )
    _write_json(fixture["manifest"], study_manifest)

    package_manifest = json.loads(fixture["package_manifest"].read_text(encoding="utf-8"))
    package_manifest["study_commit"] = derivative_commit
    package_manifest["study_manifest_sha256"] = sha256_path(fixture["manifest"])
    _write_json(fixture["package_manifest"], package_manifest)


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
        "SEC_USER_AGENT",
        "UV_PROJECT_ENVIRONMENT",
        "MANUSCRIPT_DIR",
        "SEED_DEFAULT",
    }
    assert "/path/to/reporting-risk-cascade-data" in env_example
    assert 'SEC_USER_AGENT="Your Name your.email@institution.edu"' in env_example
    assert "must replace" in env_example.casefold()


@pytest.mark.parametrize(
    "marker",
    [
        POSIX_HOME_PATH,
        WINDOWS_USER_PATH,
        WINDOWS_USER_PATH_LOWER,
    ],
)
def test_validate_entries_rejects_local_path_markers(marker: str) -> None:
    with pytest.raises(ValueError, match="local identity/path marker"):
        _validate_entries({"generated/results.txt": marker.encode()})


@pytest.mark.parametrize(
    ("path", "basename"),
    [
        (POSIX_HOME_PATH.replace("example", "alice"), "private.csv"),
        (WINDOWS_DRIVE_USER_PATH, "private.csv"),
        (WINDOWS_DRIVE_USER_PATH_BACKSLASH, "private.csv"),
        (WINDOWS_DRIVE_ROOT_PATH, "data.csv"),
        (BACKSLASH_UNC_PATH, "private.csv"),
        (FORWARD_UNC_PATH, "private.csv"),
    ],
)
def test_sanitize_redacts_posix_windows_and_unc_absolute_paths(
    path: str,
    basename: str,
) -> None:
    assert _sanitize(path) == f"<external>/{basename}"


@pytest.mark.parametrize(
    "marker",
    [
        WINDOWS_DRIVE_USER_PATH,
        WINDOWS_DRIVE_USER_PATH_BACKSLASH.lower(),
        WINDOWS_DRIVE_ROOT_PATH,
        BACKSLASH_UNC_PATH,
        FORWARD_UNC_PATH,
    ],
)
@pytest.mark.parametrize("binary", [False, True], ids=["text", "binary"])
def test_validate_entries_rejects_embedded_windows_and_unc_paths(
    marker: str,
    binary: bool,
) -> None:
    payload = marker.encode()
    if binary:
        payload = b"\x89PNG\r\n" + payload
    with pytest.raises(ValueError, match="local identity/path marker"):
        _validate_entries({"generated/results.bin": payload})


def test_validate_entries_does_not_treat_https_url_as_unc_path() -> None:
    _validate_entries({"generated/results.txt": b"https://www.sec.gov/files/data.zip"})


def test_real_allowed_worktree_source_survives_archive_validation() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    entries = {
        f"source/{relative}": (REPO_ROOT / relative).read_bytes()
        for raw in tracked
        if raw
        for relative in [raw.decode("utf-8")]
        if _source_allowed(relative) and (REPO_ROOT / relative).is_file()
    }
    redactions = _derive_identity_redactions(entries)
    redacted = _redact_entries(entries, redactions)

    _validate_entries(
        redacted,
        identity_needles=[needle for needle, _, _ in redactions],
    )


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


def test_documented_bootstrap_uses_scrubbed_env_and_creates_clean_derivative_commit(
    tmp_path: Path,
) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    extracted = tmp_path / "portable-extraction"
    with zipfile.ZipFile(output) as archive:
        archive.extractall(extracted)

    readme = (extracted / "REPLICATION_README.md").read_text(encoding="utf-8")
    bootstrap_section = readme.split("## Bootstrap", 1)[1].split("## Production", 1)[0]
    bootstrap = bootstrap_section.split("```bash", 1)[1].split("```", 1)[0].strip()
    syntax = subprocess.run(
        ["/bin/bash", "-n"],
        input=bootstrap,
        text=True,
        check=False,
        capture_output=True,
    )
    assert syntax.returncode == 0, syntax.stdout + syntax.stderr

    poison = extracted / ".env"
    poison.write_text(
        'PROJECT_ROOT="/poison/project"\nDATA_DIR="/poison/data"\n'
        'ARTIFACTS_DIR="/poison/artifacts"\n'
        'UV_PROJECT_ENVIRONMENT="/poison/uv-venv"\n'
        'UV_CACHE_DIR="/poison/uv-cache"\n'
        'MANUSCRIPT_DIR="/poison/manuscript"\n'
        'SEC_USER_AGENT="Poison Contact poison@institution.edu"\n',
        encoding="utf-8",
    )
    replication_root = tmp_path / "reviewer runtime"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    common_log = (
        'printf "%s\\n" "$*" >> "$REPLICATION_ROOT/COMMAND-calls.txt"\n'
        'printf "%s\\n" "$WORK_DIR|$DATA_DIR|$RAW_DATASET_PATH|$PUBLIC_LAKE_DIR|'
        "$LAKE_BRONZE_DIR|$LAKE_SILVER_DIR|$LAKE_GOLD_DIR|"
        "$UV_PROJECT_ENVIRONMENT|$UV_CACHE_DIR|$ARTIFACTS_DIR|$MANUSCRIPT_DIR|"
        '$COVERAGE_FILE|$PYTHONPYCACHEPREFIX|$RUFF_CACHE_DIR|$MKDOCS_SITE_DIR|${TMPDIR:-}" '
        '>> "$REPLICATION_ROOT/COMMAND-env.txt"\n'
        'printf "%s\\n" "$PYTEST_ADDOPTS" >> "$REPLICATION_ROOT/COMMAND-pytest-addopts.txt"\n'
    )
    uv_script = (
        "#!/bin/sh\nset -eu\n"
        + common_log.replace("COMMAND", "uv")
        + 'if [ "${1:-}" = "sync" ]; then mkdir -p "$UV_PROJECT_ENVIRONMENT" "$UV_CACHE_DIR"; fi\n'
        + 'if [ "${1:-}" = "run" ] && printf "%s\\n" "$*" | grep -q "mkdocs build"; then\n'
        '    site_dir="site"\n'
        '    while [ "$#" -gt 0 ]; do\n'
        '        if [ "$1" = "--site-dir" ]; then shift; site_dir="$1"; fi\n'
        "        shift\n"
        "    done\n"
        '    mkdir -p "$site_dir" "${PYTHONPYCACHEPREFIX:-scripts/__pycache__}"\n'
        "fi\n"
    )
    just_script = (
        "#!/bin/sh\nset -eu\n" + common_log.replace("COMMAND", "just") + 'case "${1:-}" in\n'
        "    check)\n"
        "        : > .coverage\n"
        "        mkdir -p .pytest_cache .ruff_cache site src/__pycache__\n"
        "        ;;\n"
        "    _test)\n"
        '        coverage_file="${COVERAGE_FILE:-.coverage}"\n'
        '        pytest_cache=".pytest_cache"\n'
        '        pytest_tmp="${TMPDIR:-.}/pytest-tmp"\n'
        '        case "${PYTEST_ADDOPTS:-}" in\n'
        '            *cache_dir=*) pytest_cache="$REPLICATION_ROOT/pytest-cache" ;;\n'
        "        esac\n"
        '        mkdir -p "$(dirname "$coverage_file")" "$pytest_cache" "$pytest_tmp" "${PYTHONPYCACHEPREFIX:-src/__pycache__}"\n'
        '        : > "$coverage_file"\n'
        "        ;;\n"
        '    _ruff) mkdir -p "${RUFF_CACHE_DIR:-.ruff_cache}" ;;\n'
        "esac\n"
    )
    for command, script in (("uv", uv_script), ("just", just_script)):
        executable = fake_bin / command
        executable.write_text(script, encoding="utf-8")
        executable.chmod(0o755)

    scrubbed = dict(os.environ)
    for name in {
        "PROJECT_ROOT",
        "WORK_DIR",
        "DIR_WORK",
        "DATA_DIR",
        "DOCS_DIR",
        "PAPER_DIR",
        "DOC_DIR",
        "ARTIFACTS_DIR",
        "DEFAULT_CONFIG_PATH",
        "RAW_DATASET_PATH",
        "SAMPLE_DATASET_PATH",
        "PUBLIC_LAKE_DIR",
        "PUBLIC_LAKE_SMOKE_DIR",
        "LAKE_BRONZE_DIR",
        "LAKE_SILVER_DIR",
        "LAKE_GOLD_DIR",
        "UV_PROJECT_ENVIRONMENT",
        "UV_CACHE_DIR",
        "COVERAGE_FILE",
        "PYTHONPYCACHEPREFIX",
        "RUFF_CACHE_DIR",
        "PYTEST_ADDOPTS",
        "MKDOCS_SITE_DIR",
        "TMPDIR",
        "MANUSCRIPT_DIR",
        "DIR_MANUSCRIPT",
        "SEC_USER_AGENT",
    }:
        scrubbed.pop(name, None)
    scrubbed.update(
        {
            "PATH": f"{fake_bin}:{scrubbed['PATH']}",
            "REPLICATION_ROOT": str(replication_root),
        }
    )
    completed = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", bootstrap],
        cwd=extracted,
        env=scrubbed,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    source = extracted / "source"
    forbidden_names = {
        ".venv",
        ".pytest_cache",
        ".ruff_cache",
        "pytest-tmp",
        "site",
        "__pycache__",
    }
    assert not [path for path in source.rglob("*") if path.name in forbidden_names]
    assert not [path for path in source.rglob("*") if path.name.startswith(".coverage")]
    local_env = (source / ".env").read_text(encoding="utf-8")
    assert "/poison/" not in local_env
    env_values = {
        key: value.strip().strip('"')
        for line in local_env.splitlines()
        if line and not line.startswith("#")
        for key, value in [line.split("=", 1)]
    }
    path_variables = (
        "WORK_DIR",
        "DATA_DIR",
        "RAW_DATASET_PATH",
        "PUBLIC_LAKE_DIR",
        "LAKE_BRONZE_DIR",
        "LAKE_SILVER_DIR",
        "LAKE_GOLD_DIR",
        "UV_PROJECT_ENVIRONMENT",
        "UV_CACHE_DIR",
        "ARTIFACTS_DIR",
        "MANUSCRIPT_DIR",
        "COVERAGE_FILE",
        "PYTHONPYCACHEPREFIX",
        "RUFF_CACHE_DIR",
        "MKDOCS_SITE_DIR",
        "TMPDIR",
    )
    for name in path_variables:
        value = env_values[name]
        Path(value).resolve().relative_to(replication_root.resolve())
        with pytest.raises(ValueError):
            Path(value).resolve().relative_to(source.resolve())
    pytest_addopts = env_values["PYTEST_ADDOPTS"]
    assert "--basetemp" not in pytest_addopts
    pytest_paths = (replication_root / "pytest-cache",)
    for value in pytest_paths:
        assert str(value) in pytest_addopts
        assert f"cache_dir={value}" in shlex.split(pytest_addopts)
        value.resolve().relative_to(replication_root.resolve())
        with pytest.raises(ValueError):
            value.resolve().relative_to(source.resolve())
    assert 'SEC_USER_AGENT="Your Name your.email@institution.edu"' in local_env

    derivative = _git(source, "rev-parse", "HEAD")
    archived = json.loads((extracted / "provenance" / "package_manifest.json").read_text())
    assert derivative not in {
        archived["upstream_study_commit"],
        archived["upstream_report_commit"],
    }
    assert _git(source, "show", "-s", "--format=%an") == "Anonymous Reviewer"
    assert _git(source, "show", "-s", "--format=%ae") == "reviewer@example.invalid"
    assert _git(source, "status", "--porcelain", "--untracked-files=all") == ""
    assert "sync --locked" in (replication_root / "uv-calls.txt").read_text()
    just_calls = (replication_root / "just-calls.txt").read_text().splitlines()
    assert just_calls == ["_test", "_ruff"]
    assert "mkdocs build --strict --clean" in (replication_root / "uv-calls.txt").read_text()
    assert env_values["COVERAGE_FILE"] and Path(env_values["COVERAGE_FILE"]).is_file()
    for value in (
        env_values["UV_PROJECT_ENVIRONMENT"],
        env_values["UV_CACHE_DIR"],
        env_values["PYTHONPYCACHEPREFIX"],
        env_values["RUFF_CACHE_DIR"],
        env_values["MKDOCS_SITE_DIR"],
        env_values["TMPDIR"],
        *pytest_paths,
    ):
        assert Path(value).is_dir()
    for command in ("uv", "just"):
        command_env = (replication_root / f"{command}-env.txt").read_text().strip()
        assert "/poison/" not in command_env
        for value in command_env.split("|"):
            Path(value).resolve().relative_to(replication_root.resolve())
            with pytest.raises(ValueError):
                Path(value).resolve().relative_to(source.resolve())
        command_addopts = (replication_root / f"{command}-pytest-addopts.txt").read_text()
        assert "/poison/" not in command_addopts
        for value in pytest_paths:
            assert str(value) in command_addopts

    identity = json.loads((replication_root / "replication_identity.json").read_text())
    assert identity["derivative_commit"] == derivative
    assert identity["upstream_study_commit"] == archived["upstream_study_commit"]
    assert identity["upstream_report_commit"] == archived["upstream_report_commit"]

    _rebind_bounded_evidence_to_derivative(fixture, source, derivative)
    evidence = collect_canonical_evidence(
        repo_root=source,
        study_dir=fixture["study_dir"],
        manuscript_package=fixture["package_dir"],
        expected_as_of_date="2026-07-06",
    )
    rebound_study = json.loads(fixture["manifest"].read_text())
    assert evidence["study_commit"] == derivative
    assert rebound_study["provenance"]["commit_sha"] == derivative
    assert rebound_study["provenance"]["dirty"] is False
    assert rebound_study["public_lake_provenance"]["commit_sha"] == derivative
    assert rebound_study["public_lake_provenance"]["git_dirty"] is False


def test_documented_production_orders_external_canonical_workflow(tmp_path: Path) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = _build(fixture, tmp_path / "reviewer.zip")
    with zipfile.ZipFile(output) as archive:
        readme = archive.read("REPLICATION_README.md").decode()
    production = readme.split("## Production", 1)[1]
    production_block = production.split("```bash", 1)[1].split("```", 1)[0].strip()
    syntax = subprocess.run(
        ["/bin/bash", "-n"],
        input=production_block,
        text=True,
        check=False,
        capture_output=True,
    )
    assert syntax.returncode == 0, syntax.stdout + syntax.stderr

    ordered = [
        'test -z "$(git status --porcelain --untracked-files=all)"',
        "just data full fresh",
        'just task study raw "$STUDY_DIR"',
        "scripts/build_manuscript_package.py",
        "scripts/refresh_results_snapshot.py",
        "just _test",
        "just _ruff",
        'uv run --group docs mkdocs build --strict --clean --site-dir "$MKDOCS_SITE_DIR"',
        "scripts/verify_canonical_run.py",
        "git add docs/results_snapshot.md docs/assets/results_snapshot",
        'git commit -m "Refresh canonical results snapshot"',
        "scripts/build_reviewer_package.py",
    ]
    offsets = [production.index(fragment) for fragment in ordered]
    assert offsets == sorted(offsets)
    assert 'MANUSCRIPT_PACKAGE="$MANUSCRIPT_DIR/manuscript_package"' in production
    assert 'ATTESTATION="$MANUSCRIPT_DIR/canonical_attestation.json"' in production
    assert 'REVIEWER_ZIP="$MANUSCRIPT_DIR/reporting-risk-cascade-reviewer.zip"' in production
    assert '--attestation-output "$ATTESTATION"' in production
    assert '--attestation "$ATTESTATION"' in production
    assert 'SEC_USER_AGENT" = "Your Name your.email@institution.edu"' in production
    assert "just snapshot" not in production
    assert "just reviewer-package" not in production
    assert "private benchmark" in readme.casefold()
    assert "crosswalk" in readme.casefold()
    assert "not distributed" in readme.casefold()


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
    marker = b"\x89PNG\r\n" + WINDOWS_USER_PATH.replace(".csv", ".png").encode()
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


@pytest.mark.parametrize("target", ["study-manifest", "package-manifest", "package-artifact"])
@pytest.mark.parametrize("prior", [None, b"prior reviewer archive\n"])
def test_reviewer_rejects_post_validation_copy_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    prior: bytes | None,
) -> None:
    fixture = _attested_report_fixture(tmp_path)
    output = tmp_path / "reviewer.zip"
    if prior is not None:
        output.write_bytes(prior)
    validated_current_evidence = reviewer_module._validated_current_evidence

    def validate_then_mutate(**kwargs: Any) -> dict[str, Any]:
        evidence = validated_current_evidence(**kwargs)
        path = {
            "study-manifest": fixture["manifest"],
            "package-manifest": fixture["package_manifest"],
            "package-artifact": fixture["table_03"],
        }[target]
        path.write_bytes(path.read_bytes() + b"\n")
        return evidence

    monkeypatch.setattr(
        reviewer_module,
        "_validated_current_evidence",
        validate_then_mutate,
    )
    with pytest.raises(ValueError, match="changed after evidence validation"):
        _build(fixture, output)
    if prior is None:
        assert not output.exists()
    else:
        assert output.read_bytes() == prior


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
    assert "scripts/verify_canonical_run.py" in readme
    assert "just verify-canonical" not in readme
    assert "not distributed" in readme


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
