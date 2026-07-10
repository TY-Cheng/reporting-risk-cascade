import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.build_reviewer_package import (
    _source_allowed,
    _validate_entries,
    build_reviewer_package,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _reviewer_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "reviewer-test@example.invalid")
    _git(repo, "config", "user.name", "Reviewer Test")
    files = {
        "src/example.py": "VALUE = 1\n",
        "config/example.yaml": "seed: 42\n",
        "tests/test_example.py": "def test_value():\n    assert 1 == 1\n",
        "docs/example.md": "# Example\n",
        "README.md": "# Fixture\n",
        ".python-version": "3.13\n",
        "pyproject.toml": "[project]\nname='fixture'\nversion='0.1.0'\n",
        "justfile": "check:\n    python -m pytest\n",
        "uv.lock": "version = 1\n",
    }
    for relative, content in files.items():
        _write(repo / relative, content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    commit = _git(repo, "rev-parse", "HEAD")

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
            }
        ),
    )
    _write(package_dir / "tables" / "table_03.csv", "Task,PR_AUC\na,0.2\n")
    _write(package_dir / "figures" / "figure_01.svg", "<svg></svg>\n")
    _write(package_dir / "results_narrative.md", "Canonical aggregate results.\n")
    _write(
        package_dir / "manifest.json",
        json.dumps(
            {
                "tables": {"table_03": {"csv": "tables/table_03.csv"}},
                "figures": {"figure_01": {"svg": "figures/figure_01.svg"}},
            }
        ),
    )
    return repo, study_dir, package_dir, commit


def test_allowed_working_source_surface_does_not_self_trigger_validation() -> None:
    paths = {
        *_git(REPO_ROOT, "ls-files").splitlines(),
        *_git(REPO_ROOT, "ls-files", "--others", "--exclude-standard").splitlines(),
    }
    entries = {
        f"source/{path}": (REPO_ROOT / path).read_bytes()
        for path in paths
        if _source_allowed(path)
    }

    _validate_entries(entries)


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
        assert package_manifest["report_commit"] == commit
        payload = "\n".join(zf.read(name).decode("utf-8", errors="ignore") for name in names)
        assert str(tmp_path) not in payload
        assert user_path not in payload
        readme = zf.read("REPLICATION_README.md").decode("utf-8")
        assert "cd source\nuv sync --locked" in readme
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


def _rewrite_study_manifest(study_dir: Path, **updates: object) -> None:
    path = study_dir / "study_run_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    _write(path, json.dumps(payload))


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
