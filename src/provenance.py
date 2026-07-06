from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_path(path: Path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    if path.is_dir():
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            digest.update(str(child.relative_to(path)).encode("utf-8"))
            digest.update(b"\0")
            _hash_file_into(child, digest)
        return digest.hexdigest()
    _hash_file_into(path, digest)
    return digest.hexdigest()


def _hash_file_into(path: Path, digest: "hashlib._Hash") -> None:
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)


def path_record(path: Path) -> dict[str, Any]:
    path = Path(path)
    record: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "sha256": sha256_path(path),
    }
    if path.exists():
        if path.is_file():
            record["kind"] = "file"
            record["size_bytes"] = path.stat().st_size
        elif path.is_dir():
            record["kind"] = "directory"
            record["file_count"] = sum(1 for child in path.rglob("*") if child.is_file())
    return record


def path_set_provenance(paths: Iterable[Path]) -> dict[str, Any]:
    records = [path_record(Path(path)) for path in paths]
    payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"hash": hashlib.sha256(payload).hexdigest(), "files": records}


def config_provenance(paths: Iterable[Path]) -> dict[str, Any]:
    payload = path_set_provenance(paths)
    return {"config_hash": payload["hash"], "config_files": payload["files"]}


def input_provenance(paths: Iterable[Path]) -> dict[str, Any]:
    payload = path_set_provenance(paths)
    return {"input_hash": payload["hash"], "input_files": payload["files"]}


def uv_lock_provenance(repo_root: Path | None = None) -> dict[str, Any]:
    record = path_record((repo_root or _repo_root()) / "uv.lock")
    return {"uv_lock_hash": record["sha256"], "uv_lock": record}


def git_provenance(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    commit = _git_text(["rev-parse", "HEAD"], root) or "unknown"
    status = _git_text(["status", "--short"], root)
    return {
        "commit_sha": commit,
        "dirty": True if status is None else bool(status),
        "dirty_status": status if status is not None else "git_status_unavailable",
    }


def _git_text(args: list[str], repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
    except Exception:
        return None
    return completed.stdout.strip()


def wrds_export_metadata(crosswalk_path: Path) -> dict[str, Any]:
    path = Path(crosswalk_path)
    metadata: dict[str, Any] = path_record(path)
    metadata.update(
        {
            "row_count": 0,
            "columns": [],
            "source_values": [],
            "source_version_values": [],
            "extracted_at_values": [],
            "match_method_values": [],
            "wrds_detected": False,
        }
    )
    if not path.exists() or path.is_dir():
        return metadata

    values = {
        "source": set(),
        "source_version": set(),
        "extracted_at": set(),
        "match_method": set(),
    }
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        metadata["columns"] = list(reader.fieldnames or [])
        for row in reader:
            metadata["row_count"] += 1
            for key, bucket in values.items():
                value = str(row.get(key, "") or "").strip()
                if value:
                    bucket.add(value)

    metadata["source_values"] = _sample_values(values["source"])
    metadata["source_version_values"] = _sample_values(values["source_version"])
    metadata["extracted_at_values"] = _sample_values(values["extracted_at"])
    metadata["match_method_values"] = _sample_values(values["match_method"])
    evidence = " ".join(
        value.lower()
        for bucket in values.values()
        for value in bucket
    )
    metadata["wrds_detected"] = "wrds" in evidence
    return metadata


def _sample_values(values: set[str], *, limit: int = 50) -> list[str]:
    ordered = sorted(values)
    if len(ordered) <= limit:
        return ordered
    return [*ordered[:limit], f"...(+{len(ordered) - limit})"]
