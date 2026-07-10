import json
import os
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

import scripts.build_reviewer_package as reviewer_module
from scripts.build_reviewer_package import (
    ALLOWED_PREFIXES,
    ALLOWED_ROOT_FILES,
    _source_allowed,
    _validate_entries,
    build_reviewer_package,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTED_AUTHOR_NAME = "Avery Example"
INVENTED_AUTHOR_EMAIL = "avery.example@example.invalid"
INVENTED_REPOSITORY_OWNER = "example-owner"
INVENTED_COPYRIGHT_HOLDER = "Example Research Group"
ANONYMOUS_AUTHOR_NAME = "Anonymous Researcher"
ANONYMOUS_AUTHOR_EMAIL = "researcher@example.invalid"
ANONYMOUS_REPOSITORY_OWNER = "anonymous-owner"
ANONYMOUS_COPYRIGHT_HOLDER = "Anonymous Copyright Holder"
STALE_REPORT_MARKER = "STALE STUDY SNAPSHOT"
REFRESHED_REPORT_MARKER = "REFRESHED REPORT SNAPSHOT"
REPORT_OVERLAY_POLICY = {
    "policy": "report_commit_overlays_source",
    "paths": [
        "docs/results_snapshot.md",
        "docs/assets/results_snapshot/",
    ],
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _allowed_source_paths(repo_root: Path) -> list[str]:
    paths = {
        name
        for name in ALLOWED_ROOT_FILES
        if (repo_root / name).is_file() and _source_allowed(name)
    }
    for prefix in ALLOWED_PREFIXES:
        root = repo_root / prefix.rstrip("/")
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relative = candidate.relative_to(repo_root).as_posix()
            if _source_allowed(relative):
                paths.add(relative)
    return sorted(paths)


def _reviewer_fixture(
    tmp_path: Path, *, copyright_holder: str = INVENTED_COPYRIGHT_HOLDER
) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "reviewer-test@example.invalid")
    _git(repo, "config", "user.name", "Reviewer Test")
    contact = f"{INVENTED_AUTHOR_NAME} {INVENTED_AUTHOR_EMAIL}"
    files = {
        "src/__init__.py": "",
        "src/example.py": f'CONTACT = "{contact}"\n',
        "config/example.yaml": f'sec_user_agent: "{contact}"\n',
        "tests/test_example.py": (
            "from src.example import CONTACT\n\n\n"
            "def test_contact():\n"
            f'    assert CONTACT == "{contact}"\n'
        ),
        "docs/example.md": f"Maintained by {INVENTED_AUTHOR_NAME}.\n",
        "docs/results_snapshot.md": f"# {STALE_REPORT_MARKER}\n",
        "docs/assets/results_snapshot/figure_fixture.svg": (
            f"<svg><text>{STALE_REPORT_MARKER}</text></svg>\n"
        ),
        "README.md": (
            "# Fixture\n\n"
            f"https://github.com/{INVENTED_REPOSITORY_OWNER}/fixture\n"
            f"https://{INVENTED_REPOSITORY_OWNER}.github.io/fixture/\n"
        ),
        "LICENSE": (f"MIT License\n\nCopyright (c) 2026 {copyright_holder}\n"),
        ".python-version": "3.13\n",
        "pyproject.toml": (
            "[project]\n"
            'name = "fixture"\n'
            'version = "0.1.0"\n'
            f'authors = [{{ name = "{INVENTED_AUTHOR_NAME}", '
            f'email = "{INVENTED_AUTHOR_EMAIL}" }}]\n'
        ),
        "mkdocs.yml": (
            "site_name: Fixture\n"
            f"site_url: https://{INVENTED_REPOSITORY_OWNER}.github.io/fixture/\n"
            f"repo_url: https://github.com/{INVENTED_REPOSITORY_OWNER.upper()}/fixture\n"
        ),
        "justfile": "check:\n    python -m pytest\n",
        "uv.lock": "version = 1\n",
        ".env.example": 'PROJECT_ROOT="/path/to/fixture"\n',
        ".gitignore": ".env\n",
        ".github/workflows/ci.yml": "name: fixture-ci\n",
    }
    for relative, content in files.items():
        _write(repo / relative, content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    commit = _git(repo, "rev-parse", "HEAD")
    _write(
        repo / "docs" / "results_snapshot.md",
        f"# {REFRESHED_REPORT_MARKER}\nPrepared by {INVENTED_AUTHOR_EMAIL}.\n",
    )
    _write(
        repo / "docs" / "assets" / "results_snapshot" / "figure_fixture.svg",
        f"<svg><text>{REFRESHED_REPORT_MARKER}</text></svg>\n",
    )
    _git(repo, "add", "docs/results_snapshot.md", "docs/assets/results_snapshot")
    _git(repo, "commit", "-m", "refresh report")

    study_dir = tmp_path / "study"
    package_dir = tmp_path / "package"
    user_path = "/" + "Users" + "/example/private/input.csv"
    _write(
        study_dir / "study_run_manifest.json",
        json.dumps(
            {
                "repo_commit": commit,
                "git_dirty": False,
                "public_lake_provenance": {
                    "as_of_date": "2026-07-06",
                    "git_dirty": False,
                    "source_metadata_inventory": [
                        {
                            "metadata_file": "form-ap/FirmFilings.zip.meta.json",
                            "metadata_sha256": "a" * 64,
                            "source_url": "https://example.invalid/FirmFilings.zip",
                            "payload_sha256": "b" * 64,
                        }
                    ],
                },
                "developer_path": user_path,
                "prepared_by": INVENTED_AUTHOR_NAME,
            }
        ),
    )
    _write(package_dir / "tables" / "table_03.csv", "Task,PR_AUC\na,0.2\n")
    _write(package_dir / "figures" / "figure_01.svg", "<svg></svg>\n")
    _write(
        package_dir / "results_narrative.md",
        f"Canonical aggregate results prepared by {INVENTED_AUTHOR_EMAIL}.\n",
    )
    _write(
        package_dir / "manifest.json",
        json.dumps(
            {
                "tables": {"table_03": {"csv": "tables/table_03.csv"}},
                "figures": {"figure_01": {"svg": "figures/figure_01.svg"}},
                "prepared_by": INVENTED_AUTHOR_NAME,
            }
        ),
    )
    return repo, study_dir, package_dir, commit


def test_allowed_working_source_surface_does_not_self_trigger_validation() -> None:
    entries = {
        f"source/{path}": (REPO_ROOT / path).read_bytes()
        for path in _allowed_source_paths(REPO_ROOT)
    }
    redactions = reviewer_module._derive_identity_redactions(entries)
    redacted = reviewer_module._redact_entries(entries, redactions)
    original_needles = [
        needle
        for needle, replacement, _ in redactions
        if needle.casefold() != replacement.casefold()
    ]

    _validate_entries(redacted, identity_needles=original_needles)

    assert {item[2] for item in redactions} >= {
        "project_author_name",
        "project_author_email",
        "repository_owner",
        "copyright_holder",
    }
    payload = b"\n".join(redacted.values()).decode("utf-8", errors="ignore").casefold()
    assert all(needle.casefold() not in payload for needle in original_needles)
    implementation_text = "\n".join(
        (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "scripts/build_reviewer_package.py",
            "tests/test_reviewer_package.py",
        )
    ).casefold()
    assert all(needle.casefold() not in implementation_text for needle in original_needles)


def test_allowed_source_paths_include_untracked_allowed_files_only(tmp_path: Path) -> None:
    included = {
        "README.md": "# Fixture\n",
        ".env.example": "PROJECT_ROOT=/path/to/fixture\n",
        ".gitignore": ".env\n",
        ".github/workflows/ci.yml": "name: fixture-ci\n",
        "tests/test_untracked.py": "def test_fixture():\n    assert True\n",
        "scripts/untracked_helper.py": "VALUE = 1\n",
    }
    excluded = {
        ".github/workflows/other.yml": "name: unrelated\n",
        ".github/private.py": "VALUE = 1\n",
        ".git/config": "fixture\n",
        ".venv/private.py": "VALUE = 1\n",
        "artifacts/private.py": "VALUE = 1\n",
        "site/private.py": "VALUE = 1\n",
        "docs/results_snapshot.md": "stale\n",
        "docs/assets/results_snapshot/figure.svg": "<svg></svg>\n",
        "docs/superpowers/plans/private.md": "private\n",
        "tests/__pycache__/private.py": "VALUE = 1\n",
        "tests/private.PARQUET": "PAR1\n",
    }
    for relative, content in {**included, **excluded}.items():
        _write(tmp_path / relative, content)

    paths = _allowed_source_paths(tmp_path)

    assert set(included) <= set(paths)
    assert set(excluded).isdisjoint(paths)


def test_extracted_current_source_just_check_passes_without_git(tmp_path: Path) -> None:
    if not (REPO_ROOT / ".git").exists():
        paths = _allowed_source_paths(REPO_ROOT)
        assert "tests/test_reviewer_package.py" in paths
        assert all(_source_allowed(path) for path in paths)
        return

    repo = tmp_path / "current-source-repo"
    repo.mkdir()
    for relative in _allowed_source_paths(REPO_ROOT):
        source = REPO_ROOT / relative
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    _git(repo, "init")
    _git(repo, "config", "user.email", "reviewer-closure@example.invalid")
    _git(repo, "config", "user.name", "Reviewer Closure")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "current allowed source")
    study_commit = _git(repo, "rev-parse", "HEAD")
    snapshot = (REPO_ROOT / "docs" / "results_snapshot.md").read_text(encoding="utf-8")
    snapshot = re.sub(
        r"/(?:Users|Volumes|home)/[^`|\s]+",
        lambda match: f"<external>/{Path(match.group()).name}",
        snapshot,
    )
    _write(repo / "docs" / "results_snapshot.md", snapshot)
    report_assets = REPO_ROOT / "docs" / "assets" / "results_snapshot"
    for source in report_assets.rglob("*"):
        if source.is_file():
            relative = source.relative_to(REPO_ROOT)
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    _git(repo, "add", "docs/results_snapshot.md", "docs/assets/results_snapshot")
    _git(repo, "commit", "-m", "sanitized current report")

    study_dir = tmp_path / "study"
    package_dir = tmp_path / "package"
    _write(
        study_dir / "study_run_manifest.json",
        json.dumps(
            {
                "repo_commit": study_commit,
                "git_dirty": False,
                "public_lake_provenance": {
                    "git_dirty": False,
                    "source_metadata_inventory": [{"metadata_file": "fixture.meta.json"}],
                },
            }
        ),
    )
    _write(package_dir / "tables" / "table_03.csv", "Task,PR_AUC\na,0.2\n")
    _write(package_dir / "figures" / "figure_01.svg", "<svg></svg>\n")
    _write(package_dir / "results_narrative.md", "Canonical aggregate fixture results.\n")
    _write(
        package_dir / "manifest.json",
        json.dumps(
            {
                "tables": {"table_03": {"csv": "tables/table_03.csv"}},
                "figures": {"figure_01": {"svg": "figures/figure_01.svg"}},
            }
        ),
    )
    output = tmp_path / "reviewer.zip"
    build_reviewer_package(
        repo_root=repo,
        study_dir=study_dir,
        manuscript_package=package_dir,
        output=output,
    )
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(output) as archive:
        archive.extractall(extracted)
    source_dir = extracted / "source"
    assert not (source_dir / ".git").exists()

    listed = subprocess.run(
        ["just", "--list"],
        cwd=source_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, listed.stderr
    locked = subprocess.run(
        ["uv", "lock", "--check"],
        cwd=source_dir,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert locked.returncode == 0, locked.stdout + locked.stderr
    checked = subprocess.run(
        ["just", "check"],
        cwd=source_dir,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_reviewer_package_is_exact_commit_anonymized_and_data_free(tmp_path: Path) -> None:
    repo, study_dir, package_dir, commit = _reviewer_fixture(tmp_path)
    output = tmp_path / "reviewer.zip"
    user_path = "/" + "Users" + "/example/private/input.csv"
    _write(package_dir / "tables" / "stale_not_declared.csv", "old,value\n1,2\n")

    build_reviewer_package(
        repo_root=repo,
        study_dir=study_dir,
        manuscript_package=package_dir,
        output=output,
    )

    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
        assert "source/src/example.py" in names
        assert "source/.python-version" in names
        assert "source/uv.lock" in names
        assert "source/.env.example" in names
        assert "source/.gitignore" in names
        assert "source/.github/workflows/ci.yml" in names
        assert "source/docs/results_snapshot.md" in names
        assert "source/docs/assets/results_snapshot/figure_fixture.svg" in names
        assert "report/docs/results_snapshot.md" in names
        assert "report/docs/assets/results_snapshot/figure_fixture.svg" in names
        assert "generated/manuscript_package/manifest.json" in names
        assert "provenance/study_run_manifest.sanitized.json" in names
        assert "provenance/public_lake_provenance.json" in names
        assert "provenance/public_source_inventory.json" in names
        assert "provenance/package_manifest.json" in names
        assert "REPLICATION_README.md" in names
        assert "generated/manuscript_package/tables/stale_not_declared.csv" not in names
        assert not any(name.endswith((".parquet", ".env")) for name in names)
        package_manifest = json.loads(zf.read("provenance/package_manifest.json").decode("utf-8"))
        assert package_manifest["study_commit"] == commit
        assert package_manifest["report_commit"] == _git(repo, "rev-parse", "HEAD")
        assert package_manifest["report_overlay"] == REPORT_OVERLAY_POLICY
        assert package_manifest["identity_redaction"] == {
            "policy": "derived_from_study_source",
            "categories": [
                "copyright_holder",
                "project_author_email",
                "project_author_name",
                "repository_owner",
            ],
        }
        payload = "\n".join(zf.read(name).decode("utf-8", errors="ignore") for name in names)
        assert str(tmp_path) not in payload
        assert user_path not in payload
        for original in (
            INVENTED_AUTHOR_NAME,
            INVENTED_AUTHOR_EMAIL,
            INVENTED_REPOSITORY_OWNER,
            INVENTED_COPYRIGHT_HOLDER,
        ):
            assert original.casefold() not in payload.casefold()
        for replacement in (
            ANONYMOUS_AUTHOR_NAME,
            ANONYMOUS_AUTHOR_EMAIL,
            ANONYMOUS_REPOSITORY_OWNER,
            ANONYMOUS_COPYRIGHT_HOLDER,
        ):
            assert replacement in payload
        assert ANONYMOUS_AUTHOR_NAME in zf.read("source/pyproject.toml").decode("utf-8")
        assert ANONYMOUS_AUTHOR_EMAIL in zf.read("source/src/example.py").decode("utf-8")
        assert ANONYMOUS_AUTHOR_EMAIL in zf.read("source/tests/test_example.py").decode("utf-8")
        assert ANONYMOUS_REPOSITORY_OWNER in zf.read("source/README.md").decode("utf-8")
        assert ANONYMOUS_COPYRIGHT_HOLDER in zf.read("source/LICENSE").decode("utf-8")
        assert ANONYMOUS_AUTHOR_EMAIL in zf.read("report/docs/results_snapshot.md").decode("utf-8")
        source_snapshot = zf.read("source/docs/results_snapshot.md")
        report_snapshot = zf.read("report/docs/results_snapshot.md")
        source_asset = zf.read("source/docs/assets/results_snapshot/figure_fixture.svg")
        report_asset = zf.read("report/docs/assets/results_snapshot/figure_fixture.svg")
        assert source_snapshot == report_snapshot
        assert source_asset == report_asset
        assert REFRESHED_REPORT_MARKER.encode() in source_snapshot
        assert STALE_REPORT_MARKER.encode() not in source_snapshot
        readme = zf.read("REPLICATION_README.md").decode("utf-8")
        assert "cd source\nuv sync --locked" in readme
        assert "identity-redacted derivative" in readme
        assert "SEC contact user-agent" in readme
        extracted = tmp_path / "extracted"
        zf.extractall(extracted)

    listed = subprocess.run(
        ["just", "--list"],
        cwd=extracted / "source",
        check=False,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, listed.stderr
    assert "check" in listed.stdout
    parsed_project = tomllib.loads(
        (extracted / "source" / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert parsed_project["project"]["authors"] == [
        {"name": ANONYMOUS_AUTHOR_NAME, "email": ANONYMOUS_AUTHOR_EMAIL}
    ]
    tested = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=extracted / "source",
        check=False,
        capture_output=True,
        text=True,
    )
    assert tested.returncode == 0, tested.stdout + tested.stderr


def test_reviewer_suite_is_part_of_core_gate_once() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    core_recipe = justfile.split("\n_test-core:\n", maxsplit=1)[1].split(
        "\n_test-public-lake:", maxsplit=1
    )[0]

    assert core_recipe.count("tests/test_reviewer_package.py") == 1


def test_overlapping_repository_owner_and_copyright_preserves_both_categories(
    tmp_path: Path,
) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(
        tmp_path,
        copyright_holder=INVENTED_REPOSITORY_OWNER.upper(),
    )
    output = tmp_path / "reviewer.zip"

    build_reviewer_package(
        repo_root=repo,
        study_dir=study_dir,
        manuscript_package=package_dir,
        output=output,
    )

    with zipfile.ZipFile(output) as zf:
        manifest = json.loads(zf.read("provenance/package_manifest.json"))
        license_text = zf.read("source/LICENSE").decode("utf-8")
    assert {"repository_owner", "copyright_holder"} <= set(
        manifest["identity_redaction"]["categories"]
    )
    assert INVENTED_REPOSITORY_OWNER.casefold() not in license_text.casefold()
    assert ANONYMOUS_REPOSITORY_OWNER in license_text


def _rewrite_study_manifest(study_dir: Path, **updates: object) -> None:
    path = study_dir / "study_run_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    _write(path, json.dumps(payload))


def _rewrite_package_manifest(package_dir: Path, **updates: object) -> None:
    path = package_dir / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    _write(path, json.dumps(payload))


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def test_reviewer_package_accepts_clean_full_study_sha(tmp_path: Path) -> None:
    repo, study_dir, package_dir, commit = _reviewer_fixture(tmp_path)
    output = tmp_path / "reviewer.zip"

    build_reviewer_package(
        repo_root=repo,
        study_dir=study_dir,
        manuscript_package=package_dir,
        output=output,
    )

    with zipfile.ZipFile(output) as zf:
        package_manifest = json.loads(zf.read("provenance/package_manifest.json").decode("utf-8"))
    assert package_manifest["study_commit"] == commit


def test_reviewer_package_rejects_head_as_study_commit(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    _rewrite_study_manifest(study_dir, repo_commit="HEAD")

    with pytest.raises(ValueError, match="full 40-hex"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_abbreviated_study_commit(tmp_path: Path) -> None:
    repo, study_dir, package_dir, commit = _reviewer_fixture(tmp_path)
    _rewrite_study_manifest(study_dir, repo_commit=commit[:12])

    with pytest.raises(ValueError, match="full 40-hex"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


@pytest.mark.parametrize("invalid_commit", [123, None, "g" * 40])
def test_reviewer_package_rejects_noncanonical_study_commit(
    tmp_path: Path, invalid_commit: object
) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    _rewrite_study_manifest(study_dir, repo_commit=invalid_commit)

    with pytest.raises(ValueError, match="full 40-hex"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_dirty_study(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    _rewrite_study_manifest(study_dir, git_dirty=True)

    with pytest.raises(ValueError, match="dirty"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_forbidden_generated_data(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    (package_dir / "tables" / "forbidden.parquet").write_bytes(b"PAR1")

    with pytest.raises(ValueError, match="forbidden"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_uppercase_forbidden_generated_data(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    (package_dir / "tables" / "forbidden.PARQUET").write_bytes(b"PAR1")

    with pytest.raises(ValueError, match="forbidden"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


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
        line.split("=", maxsplit=1)[0]
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
    assert "cloud workspace" in env_example.casefold()
    assert "/path/to/reporting-risk-cascade-data" in env_example
    assert "reporting-risk-cascade-manuscript" in env_example
    forbidden_markers = (
        "/" + "Users" + "/",
        "/" + "Volumes" + "/",
        "/" + "home" + "/",
        "One" + "Drive",
    )
    assert all(marker.casefold() not in env_example.casefold() for marker in forbidden_markers)


def test_reviewer_package_rejects_declared_external_file_symlink(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    external = tmp_path / "external-table.csv"
    _write(external, "private,value\n1,2\n")
    declared = package_dir / "tables" / "table_03.csv"
    declared.unlink()
    _symlink_or_skip(declared, external)

    with pytest.raises(ValueError, match="symlink"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


@pytest.mark.parametrize("symlinked_parent", [False, True])
def test_reviewer_package_rejects_symlinked_package_path(
    tmp_path: Path, symlinked_parent: bool
) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    if symlinked_parent:
        link = tmp_path / "parent-link"
        _symlink_or_skip(link, tmp_path, target_is_directory=True)
        package_path = link / package_dir.name
    else:
        link = tmp_path / "package-link"
        _symlink_or_skip(link, package_dir, target_is_directory=True)
        package_path = link

    with pytest.raises(ValueError, match="symlink"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_path,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_unresolvable_study_commit(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    _rewrite_study_manifest(study_dir, repo_commit="0" * 40)

    with pytest.raises(ValueError, match="cannot resolve"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_non_object_study_manifest(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    _write(study_dir / "study_run_manifest.json", json.dumps([]))

    with pytest.raises(ValueError, match="study manifest must be a JSON object"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_non_object_public_lake_provenance(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    _rewrite_study_manifest(
        study_dir,
        public_lake_provenance=[
            ["git_dirty", False],
            ["source_metadata_inventory", [{"metadata_file": "fixture.meta.json"}]],
        ],
    )

    with pytest.raises(ValueError, match="public-lake provenance must be a JSON object"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_non_array_source_inventory(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    path = study_dir / "study_run_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["public_lake_provenance"]["source_metadata_inventory"] = {
        "metadata_file": "fixture.meta.json"
    }
    _write(path, json.dumps(payload))

    with pytest.raises(ValueError, match="source metadata inventory must be a JSON array"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_non_object_package_manifest(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    _write(
        package_dir / "manifest.json",
        json.dumps([["tables", {}], ["figures", {}]]),
    )

    with pytest.raises(ValueError, match="package manifest must be a JSON object"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_linux_home_path_marker(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    linux_home_prefix = "/" + "home" + "/"
    _write(
        package_dir / "results_narrative.md",
        linux_home_prefix + "example/private/input.csv\n",
    )

    with pytest.raises(ValueError, match="local identity/path marker"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_windows_user_path_marker(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    windows_user_prefix = "C:" + "\\" + "Users" + "\\"
    _write(
        package_dir / "results_narrative.md",
        windows_user_prefix + "example" + "\\" + "private" + "\\" + "input.csv\n",
    )

    with pytest.raises(ValueError, match="local identity/path marker"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_lowercase_windows_user_path_marker(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    windows_user_prefix = "c:" + "\\" + "users" + "\\"
    _write(
        package_dir / "results_narrative.md",
        windows_user_prefix + "example" + "\\" + "private" + "\\" + "input.csv\n",
    )

    with pytest.raises(ValueError, match="local identity/path marker"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_path_marker_in_declared_binary(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    windows_user_prefix = "c:" + "\\" + "users" + "\\"
    (package_dir / "figures" / "figure_01.png").write_bytes(
        b"\x89PNG\r\n" + windows_user_prefix.encode("utf-8") + b"example\\private.png"
    )
    _rewrite_package_manifest(
        package_dir,
        figures={"figure_01": {"png": "figures/figure_01.png"}},
    )

    with pytest.raises(ValueError, match="local identity/path marker"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )


def test_reviewer_package_rejects_identity_in_declared_binary(tmp_path: Path) -> None:
    repo, study_dir, package_dir, _ = _reviewer_fixture(tmp_path)
    (package_dir / "figures" / "figure_01.png").write_bytes(
        b"\x89PNG\r\n" + INVENTED_AUTHOR_EMAIL.upper().encode("utf-8")
    )
    _rewrite_package_manifest(
        package_dir,
        figures={"figure_01": {"png": "figures/figure_01.png"}},
    )

    with pytest.raises(ValueError, match="identity"):
        build_reviewer_package(
            repo_root=repo,
            study_dir=study_dir,
            manuscript_package=package_dir,
            output=tmp_path / "reviewer.zip",
        )
