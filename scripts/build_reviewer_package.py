from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ALLOWED_ROOT_FILES = {
    ".env.example",
    ".gitignore",
    ".github/workflows/ci.yml",
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
IDENTITY_PLACEHOLDERS = {
    "project_author_name": "Anonymous Researcher",
    "project_author_email": "researcher@example.invalid",
    "repository_owner": "anonymous-owner",
    "copyright_holder": "Anonymous Copyright Holder",
}
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

The source tree is an identity-redacted derivative of the recorded study commit.
Refreshed report snapshot files from the report commit overlay their normal source paths.
Before network acquisition, an authorized user must set a compliant SEC contact user-agent.
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


def _path_forbidden(path: str | PurePosixPath) -> bool:
    value = str(path)
    parts = {part.casefold() for part in PurePosixPath(value).parts}
    return bool(
        parts & {part.casefold() for part in FORBIDDEN_PARTS}
    ) or value.casefold().endswith(tuple(suffix.casefold() for suffix in FORBIDDEN_SUFFIXES))


def _source_allowed(path: str) -> bool:
    if path in EXCLUDED_FILES or any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if _path_forbidden(path):
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


def _text_payload(name: str, payload: bytes) -> str | None:
    if PurePosixPath(name).suffix.casefold() in {suffix.casefold() for suffix in BINARY_SUFFIXES}:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _derive_identity_redactions(
    source_entries: dict[str, bytes],
) -> list[tuple[str, str, str]]:
    pyproject_text = _text_payload(
        "source/pyproject.toml", source_entries.get("source/pyproject.toml", b"")
    )
    if pyproject_text is None:
        raise ValueError("cannot derive identity redactions from pyproject.toml")
    project = tomllib.loads(pyproject_text).get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str):
        raise ValueError("cannot derive project identity metadata")
    project_name = project["name"]
    authors = project.get("authors", [])
    if not isinstance(authors, list):
        raise ValueError("project authors must be an array")

    candidates: list[tuple[str, str]] = []
    for author in authors:
        if not isinstance(author, dict):
            raise ValueError("project author records must be objects")
        for field, category in (
            ("name", "project_author_name"),
            ("email", "project_author_email"),
        ):
            value = author.get(field)
            if isinstance(value, str) and value.strip():
                candidates.append((value.strip(), category))

    license_text = _text_payload("source/LICENSE", source_entries.get("source/LICENSE", b""))
    if license_text is not None:
        for line in license_text.splitlines():
            match = re.match(
                r"^\s*copyright\s*(?:\(c\)|©)?\s*\d{4}(?:-\d{4})?\s+(.+?)\s*$",
                line,
                flags=re.IGNORECASE,
            )
            if match:
                candidates.append((match.group(1), "copyright_holder"))

    slug = re.escape(project_name)
    repository_url = re.compile(
        rf"https?://github[.]com/([^/\s\"'<>]+)/{slug}(?:[/#?\s\"'<>]|$)",
        flags=re.IGNORECASE,
    )
    pages_url = re.compile(
        rf"https?://([a-z0-9._-]+)[.]github[.]io/{slug}(?:[/#?\s\"'<>]|$)",
        flags=re.IGNORECASE,
    )
    for name, payload in source_entries.items():
        text = _text_payload(name, payload)
        if text is None:
            continue
        candidates.extend((match, "repository_owner") for match in repository_url.findall(text))
        candidates.extend((match, "repository_owner") for match in pages_url.findall(text))

    priority = {
        "repository_owner": 0,
        "project_author_email": 1,
        "project_author_name": 2,
        "copyright_holder": 3,
    }
    grouped: dict[str, tuple[str, set[str]]] = {}
    for needle, category in candidates:
        key = needle.casefold()
        if key not in grouped:
            grouped[key] = (needle, set())
        grouped[key][1].add(category)
    categories = {
        category for _, item_categories in grouped.values() for category in item_categories
    }
    missing = set(IDENTITY_PLACEHOLDERS) - categories
    if missing:
        raise ValueError(f"cannot derive identity redaction categories: {sorted(missing)}")
    redactions: list[tuple[str, str, str]] = []
    for needle, item_categories in grouped.values():
        replacement_category = min(item_categories, key=priority.__getitem__)
        replacement = IDENTITY_PLACEHOLDERS[replacement_category]
        redactions.extend((needle, replacement, category) for category in sorted(item_categories))
    return sorted(redactions, key=lambda item: (-len(item[0]), item[0].casefold(), item[2]))


def _redact_entries(
    entries: dict[str, bytes], redactions: list[tuple[str, str, str]]
) -> dict[str, bytes]:
    redacted: dict[str, bytes] = {}
    for name, payload in entries.items():
        text = _text_payload(name, payload)
        if text is None:
            redacted[name] = payload
            continue
        for needle, replacement, _ in redactions:
            text = re.sub(re.escape(needle), replacement, text, flags=re.IGNORECASE)
        redacted[name] = text.encode("utf-8")
    return redacted


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


def _validated_package_root(manuscript_package: Path) -> Path:
    package_root = manuscript_package.expanduser().absolute()
    for candidate in (package_root, *package_root.parents):
        if candidate.is_symlink():
            raise ValueError(f"symlink in manuscript package path: {candidate}")
    if not package_root.is_dir():
        raise ValueError(f"manuscript package directory is missing: {package_root}")
    for candidate in package_root.rglob("*"):
        if candidate.is_symlink():
            raise ValueError(
                f"symlink in manuscript package tree: {candidate.relative_to(package_root)}"
            )
    return package_root


def _validate_entries(
    entries: dict[str, bytes], *, identity_needles: list[str] | tuple[str, ...] = ()
) -> None:
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
    folded_markers = tuple(marker.casefold() for marker in markers if marker)
    folded_identities = tuple(needle.casefold() for needle in identity_needles if needle)
    for name, payload in entries.items():
        if _path_forbidden(name):
            raise ValueError(f"forbidden archive entry: {name}")
        text = payload.decode("utf-8", errors="ignore").casefold()
        for marker in folded_markers:
            if marker in text:
                raise ValueError(f"local identity/path marker in archive entry: {name}")
        for needle in folded_identities:
            if needle in text:
                raise ValueError(f"original identity marker in archive entry: {name}")


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
    study_commit = study_manifest.get("repo_commit")
    if not isinstance(study_commit, str) or re.fullmatch(r"[0-9a-f]{40}", study_commit) is None:
        raise ValueError("study commit must be a full 40-hex lowercase SHA")
    try:
        _git_bytes(repo_root, "cat-file", "-e", f"{study_commit}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"cannot resolve study commit: {study_commit}") from exc
    resolved_commit = (
        _git_bytes(repo_root, "rev-parse", "--verify", f"{study_commit}^{{commit}}")
        .decode("utf-8")
        .strip()
    )
    if resolved_commit != study_commit:
        raise ValueError("study commit is not the canonical full commit SHA")
    report_commit = _git_bytes(repo_root, "rev-parse", "--verify", "HEAD").decode("utf-8").strip()

    entries: dict[str, bytes] = {}
    for path in _tracked_paths(repo_root, study_commit):
        if _source_allowed(path):
            entries[f"source/{path}"] = _git_bytes(repo_root, "show", f"{study_commit}:{path}")
    redactions = _derive_identity_redactions(entries)
    for path in _tracked_paths(repo_root, report_commit):
        if _report_allowed(path):
            payload = _git_bytes(repo_root, "show", f"{report_commit}:{path}")
            entries[f"report/{path}"] = payload
            entries[f"source/{path}"] = payload

    manuscript_package = _validated_package_root(manuscript_package)
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
        if _path_forbidden(relative):
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
            "report_overlay": {
                "policy": "report_commit_overlays_source",
                "paths": [
                    "docs/results_snapshot.md",
                    "docs/assets/results_snapshot/",
                ],
            },
            "identity_redaction": {
                "policy": "derived_from_study_source",
                "categories": sorted({category for _, _, category in redactions}),
            },
        }
    )
    entries = _redact_entries(entries, redactions)
    _validate_entries(entries, identity_needles=[needle for needle, _, _ in redactions])
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
