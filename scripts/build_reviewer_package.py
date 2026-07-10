from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ALLOWED_ROOT_FILES = {
    ".python-version",
    "LICENSE",
    "README.md",
    "justfile",
    "mkdocs.yml",
    "pyproject.toml",
    "uv.lock",
}
ALLOWED_PREFIXES = ("config/", "docs/", "scripts/", "src/", "tests/")
EXCLUDED_PREFIXES = (
    "docs/superpowers/plans/",
    "docs/assets/results_snapshot/",
)
EXCLUDED_FILES = {"docs/results_snapshot.md"}
REPORT_FILES = {"docs/results_snapshot.md"}
REPORT_PREFIXES = ("docs/assets/results_snapshot/",)
FORBIDDEN_SUFFIXES = (".parquet", ".pkl")
FORBIDDEN_PARTS = {".env", ".serena", ".venv", "site", "__pycache__"}
BINARY_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
CODE_FENCE = "`" * 3
REPLICATION_README = f"""# Replication

{CODE_FENCE}bash
cd source
uv sync --locked
just check
just task benchmark sample artifacts/reviewer_smoke
just data full fresh
just task study raw artifacts/full_with_peer extra="--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated"
just manuscript study_dir=artifacts/full_with_peer out_dir=artifacts/manuscript_package
just snapshot study_dir=artifacts/full_with_peer
just verify-canonical study_dir=artifacts/full_with_peer package_dir=artifacts/manuscript_package
{CODE_FENCE}

The raw detected-misstatement benchmark and WRDS crosswalk are not distributed.
Authorized users must supply them at the configured paths before the full run.
"""


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout


def _tracked_paths(repo_root: Path, commit: str) -> list[str]:
    raw = _git_bytes(repo_root, "ls-tree", "-rz", "--name-only", commit)
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def _source_allowed(path: str) -> bool:
    parts = set(PurePosixPath(path).parts)
    if path in EXCLUDED_FILES or any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if parts & FORBIDDEN_PARTS or path.endswith(FORBIDDEN_SUFFIXES):
        return False
    return path in ALLOWED_ROOT_FILES or any(
        path.startswith(prefix) for prefix in ALLOWED_PREFIXES
    )


def _report_allowed(path: str) -> bool:
    return path in REPORT_FILES or any(path.startswith(prefix) for prefix in REPORT_PREFIXES)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and Path(value).is_absolute():
        return f"<external>/{Path(value).name}"
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _declared_package_files(package_manifest: dict[str, Any]) -> set[str]:
    declared = {"results_narrative.md"}
    for group in ("tables", "figures"):
        records = package_manifest.get(group, {})
        if not isinstance(records, dict):
            raise ValueError(f"invalid package manifest group: {group}")
        for formats in records.values():
            if not isinstance(formats, dict):
                raise ValueError(f"invalid package manifest format map: {group}")
            for recorded_path in formats.values():
                declared.add(f"{group}/{Path(str(recorded_path)).name}")
    return declared


def _validate_entries(entries: dict[str, bytes]) -> None:
    home = str(Path.home())
    user_prefix = "/" + "Users" + "/"
    volume_prefix = "/" + "Volumes" + "/"
    linux_home_prefix = "/" + "home" + "/"
    windows_user_prefix = "C:" + "\\" + "Users" + "\\"
    cloud_marker = "One" + "Drive"
    markers = (
        home,
        user_prefix,
        volume_prefix,
        linux_home_prefix,
        windows_user_prefix,
        cloud_marker,
    )
    for name, payload in entries.items():
        path = PurePosixPath(name)
        if set(path.parts) & FORBIDDEN_PARTS or name.endswith(FORBIDDEN_SUFFIXES):
            raise ValueError(f"forbidden archive entry: {name}")
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        text = payload.decode("utf-8", errors="ignore")
        for marker in markers:
            if marker and marker in text:
                raise ValueError(f"local identity/path marker in archive entry: {name}")


def build_reviewer_package(
    *,
    repo_root: Path,
    study_dir: Path,
    manuscript_package: Path,
    output: Path,
) -> Path:
    study_manifest = json.loads(
        (study_dir / "study_run_manifest.json").read_text(encoding="utf-8")
    )
    if not isinstance(study_manifest, dict):
        raise ValueError("study manifest must be a JSON object")
    public_lake = study_manifest.get("public_lake_provenance", {})
    if not isinstance(public_lake, dict):
        raise ValueError("public-lake provenance must be a JSON object")
    if study_manifest.get("git_dirty") is not False or public_lake.get("git_dirty") is not False:
        raise ValueError("dirty study or public-lake manifest")
    source_inventory = public_lake.get("source_metadata_inventory", [])
    if not isinstance(source_inventory, list) or any(
        not isinstance(item, dict) for item in source_inventory
    ):
        raise ValueError("source metadata inventory must be a JSON array of objects")
    if not source_inventory:
        raise ValueError("public source metadata inventory is missing")
    study_commit = str(study_manifest.get("repo_commit", ""))
    try:
        _git_bytes(repo_root, "cat-file", "-e", f"{study_commit}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"cannot resolve study commit: {study_commit}") from exc
    report_commit = _git_bytes(repo_root, "rev-parse", "HEAD").decode("utf-8").strip()

    entries: dict[str, bytes] = {}
    for path in _tracked_paths(repo_root, study_commit):
        if _source_allowed(path):
            entries[f"source/{path}"] = _git_bytes(repo_root, "show", f"{study_commit}:{path}")
    for path in _tracked_paths(repo_root, report_commit):
        if _report_allowed(path):
            entries[f"report/{path}"] = _git_bytes(repo_root, "show", f"{report_commit}:{path}")

    package_manifest = json.loads(
        (manuscript_package / "manifest.json").read_text(encoding="utf-8")
    )
    if not isinstance(package_manifest, dict):
        raise ValueError("package manifest must be a JSON object")
    declared_package_files = _declared_package_files(package_manifest)
    for relative in declared_package_files:
        if not (manuscript_package / relative).is_file():
            raise ValueError(f"declared package artifact is missing: {relative}")
    for candidate in sorted(path for path in manuscript_package.rglob("*") if path.is_file()):
        relative = candidate.relative_to(manuscript_package).as_posix()
        parts = set(PurePosixPath(relative).parts)
        if parts & FORBIDDEN_PARTS or relative.endswith(FORBIDDEN_SUFFIXES):
            raise ValueError(f"forbidden generated package entry: {relative}")
        if relative not in declared_package_files:
            continue
        entries[f"generated/manuscript_package/{relative}"] = candidate.read_bytes()

    entries["generated/manuscript_package/manifest.json"] = _json_bytes(
        _sanitize(package_manifest)
    )
    entries["provenance/study_run_manifest.sanitized.json"] = _json_bytes(
        _sanitize(study_manifest)
    )
    entries["provenance/public_lake_provenance.json"] = _json_bytes(_sanitize(public_lake))
    entries["provenance/public_source_inventory.json"] = _json_bytes(_sanitize(source_inventory))
    entries["REPLICATION_README.md"] = REPLICATION_README.encode("utf-8")
    entries["provenance/package_manifest.json"] = _json_bytes(
        {
            "study_commit": study_commit,
            "report_commit": report_commit,
            "source_namespace": "source/",
            "report_namespace": "report/",
            "generated_namespace": "generated/manuscript_package/",
        }
    )
    _validate_entries(entries)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--study-dir", type=Path, required=True)
    parser.add_argument("--manuscript-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = build_reviewer_package(
        repo_root=args.repo_root,
        study_dir=args.study_dir,
        manuscript_package=args.manuscript_package,
        output=args.output,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
