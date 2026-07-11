from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.verify_canonical_run import (  # noqa: E402
    ATTESTATION_SCHEMA,
    VERIFIER_VERSION,
    collect_canonical_evidence,
)


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


def _load_attestation(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("canonical attestation is not valid JSON") from exc
    if type(payload) is not dict:
        raise ValueError("canonical attestation must be a JSON object")
    if payload.get("schema_version") != ATTESTATION_SCHEMA:
        raise ValueError(f"canonical attestation schema must be {ATTESTATION_SCHEMA}")
    if payload.get("verifier_version") != VERIFIER_VERSION:
        raise ValueError("canonical attestation verifier version does not match")
    timestamp = payload.get("verified_at_utc")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp) if type(timestamp) is str else None
    except ValueError:
        parsed_timestamp = None
    if (
        parsed_timestamp is None
        or parsed_timestamp.tzinfo is None
        or parsed_timestamp.utcoffset() != timedelta(0)
    ):
        raise ValueError("canonical attestation verified_at_utc must be an ISO-8601 UTC timestamp")
    return payload


def _attested_report_records(attestation: dict[str, Any]) -> list[dict[str, str]]:
    records = attestation.get("report_surface")
    if type(records) is not list or len(records) != 6:
        raise ValueError("canonical attestation must declare exactly six report paths")
    validated: list[dict[str, str]] = []
    for record in records:
        if type(record) is not dict or set(record) != {"path", "sha256"}:
            raise ValueError("canonical attestation report records are malformed")
        path = record["path"]
        digest = record["sha256"]
        pure = PurePosixPath(path) if type(path) is str else PurePosixPath("/")
        if (
            type(path) is not str
            or pure.is_absolute()
            or ".." in pure.parts
            or type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("canonical attestation report records are malformed")
        validated.append({"path": path, "sha256": digest})
    if validated != sorted(validated, key=lambda record: record["path"]):
        raise ValueError("canonical attestation report records must be sorted")
    if len({record["path"] for record in validated}) != len(validated):
        raise ValueError("canonical attestation report paths must be unique")
    return validated


def _validate_report_commit(
    repo_root: Path,
    attestation: dict[str, Any],
) -> tuple[str, str, list[dict[str, str]]]:
    study_commit = attestation.get("study_commit")
    if type(study_commit) is not str or re.fullmatch(r"[0-9a-f]{40}", study_commit) is None:
        raise ValueError("attested study commit must be a full 40-hex lowercase SHA")
    report_commit = _git_bytes(repo_root, "rev-parse", "--verify", "HEAD").decode().strip()
    parents = (
        _git_bytes(repo_root, "rev-list", "--parents", "-n", "1", report_commit).decode().split()
    )
    if len(parents) != 2 or parents[0] != report_commit or parents[1] != study_commit:
        raise ValueError(
            "report commit must be the exact direct child of the attested study commit"
        )
    report_records = _attested_report_records(attestation)
    allowed = {record["path"] for record in report_records}
    raw_delta = _git_bytes(repo_root, "diff", "--name-only", "-z", study_commit, report_commit)
    delta = {item.decode("utf-8") for item in raw_delta.split(b"\0") if item}
    if not delta:
        raise ValueError("report-commit delta must be nonempty")
    if not delta <= allowed:
        raise ValueError("report-commit delta contains paths outside the attested report surface")
    for record in report_records:
        try:
            payload = _git_bytes(repo_root, "show", f"{report_commit}:{record['path']}")
        except subprocess.CalledProcessError as exc:
            raise ValueError(f"attested report blob is missing: {record['path']}") from exc
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError(f"attested report blob hash mismatch: {record['path']}")
    return study_commit, report_commit, report_records


def _validated_current_evidence(
    *,
    repo_root: Path,
    study_dir: Path,
    manuscript_package: Path,
    attestation: dict[str, Any],
) -> dict[str, Any]:
    as_of_date = attestation.get("expected_as_of_date")
    if type(as_of_date) is not str or not as_of_date:
        raise ValueError("canonical attestation expected_as_of_date is missing")
    try:
        evidence = collect_canonical_evidence(
            repo_root=repo_root,
            study_dir=study_dir,
            manuscript_package=manuscript_package,
            expected_as_of_date=as_of_date,
            check_precommit=False,
        )
    except Exception as exc:
        raise ValueError(f"current evidence does not match attestation: {exc}") from exc
    deterministic = {
        key: value
        for key, value in attestation.items()
        if key not in {"schema_version", "verifier_version", "verified_at_utc"}
    }
    if deterministic != evidence:
        raise ValueError("current evidence does not exactly match canonical attestation")
    return evidence


def _write_zip_atomic(output: Path, entries: dict[str, bytes]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(entries):
                archive.writestr(name, entries[name])
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def build_reviewer_package(
    *,
    repo_root: Path,
    study_dir: Path,
    manuscript_package: Path,
    attestation: Path,
    output: Path,
) -> Path:
    repo_root = repo_root.resolve()
    study_dir = study_dir.resolve()
    manuscript_package = _validated_package_root(manuscript_package)
    attestation_payload = _load_attestation(attestation)
    study_commit, report_commit, report_records = _validate_report_commit(
        repo_root,
        attestation_payload,
    )
    evidence = _validated_current_evidence(
        repo_root=repo_root,
        study_dir=study_dir,
        manuscript_package=manuscript_package,
        attestation=attestation_payload,
    )
    study_manifest = json.loads(
        (study_dir / "study_run_manifest.json").read_text(encoding="utf-8")
    )
    public_lake = study_manifest["public_lake_provenance"]
    source_inventory = public_lake["source_metadata_inventory"]

    entries: dict[str, bytes] = {}
    for path in _tracked_paths(repo_root, study_commit):
        if _source_allowed(path):
            entries[f"source/{path}"] = _git_bytes(repo_root, "show", f"{study_commit}:{path}")
    redactions = _derive_identity_redactions(entries)
    for record in report_records:
        path = record["path"]
        payload = _git_bytes(repo_root, "show", f"{report_commit}:{path}")
        entries[f"report/{path}"] = payload
        entries[f"source/{path}"] = payload

    package_manifest = json.loads(
        (manuscript_package / "manifest.json").read_text(encoding="utf-8")
    )
    for record in evidence["package_artifacts"]:
        relative = record["path"]
        if _path_forbidden(relative):
            raise ValueError(f"forbidden generated package entry: {relative}")
        entries[f"generated/manuscript_package/{relative}"] = (
            manuscript_package / relative
        ).read_bytes()

    entries["generated/manuscript_package/manifest.json"] = _json_bytes(
        _sanitize(package_manifest)
    )
    entries["provenance/study_run_manifest.sanitized.json"] = _json_bytes(
        _sanitize(study_manifest)
    )
    entries["provenance/public_lake_provenance.json"] = _json_bytes(_sanitize(public_lake))
    entries["provenance/public_source_inventory.json"] = _json_bytes(_sanitize(source_inventory))
    attestation_name = "provenance/canonical_attestation.sanitized.json"
    entries[attestation_name] = _json_bytes(_sanitize(attestation_payload))
    entries["REPLICATION_README.md"] = REPLICATION_README.encode("utf-8")
    entries = _redact_entries(entries, redactions)
    archived_attestation_sha256 = hashlib.sha256(entries[attestation_name]).hexdigest()
    entries["provenance/package_manifest.json"] = _json_bytes(
        {
            "study_commit": study_commit,
            "report_commit": report_commit,
            "upstream_study_commit": study_commit,
            "upstream_report_commit": report_commit,
            "source_namespace": "source/",
            "report_namespace": "report/",
            "generated_namespace": "generated/manuscript_package/",
            "report_overlay": {
                "policy": "report_commit_overlays_source",
                "paths": [record["path"] for record in report_records],
            },
            "canonical_attestation": {
                "path": attestation_name,
                "sha256": archived_attestation_sha256,
            },
            "identity_redaction": {
                "policy": "derived_from_study_source",
                "categories": sorted({category for _, _, category in redactions}),
            },
        }
    )
    _validate_entries(entries, identity_needles=[needle for needle, _, _ in redactions])
    _write_zip_atomic(output, entries)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--study-dir", type=Path, required=True)
    parser.add_argument("--manuscript-package", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = build_reviewer_package(
        repo_root=args.repo_root,
        study_dir=args.study_dir,
        manuscript_package=args.manuscript_package,
        attestation=args.attestation,
        output=args.output,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
