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


def _source_metadata_inventory(input_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for record in input_files:
        path = Path(str(record.get("path", "")))
        parts = path.parts
        relative_name = path.name
        if "bronze" in parts:
            relative_name = "/".join(parts[parts.index("bronze") + 1 :])
        item: dict[str, Any] = {
            "metadata_file": relative_name,
            "metadata_sha256": record.get("sha256"),
        }
        if path.name.endswith(".meta.json") and path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            item.update(
                {
                    "source_name": payload.get("source_name"),
                    "source_url": payload.get("source_url"),
                    "downloaded_at_utc": payload.get("downloaded_at_utc"),
                    "payload_sha256": payload.get("sha256"),
                    "payload_size_bytes": payload.get("size_bytes"),
                    "parser_version": payload.get("parser_version"),
                    "schema_version": payload.get("schema_version"),
                }
            )
        inventory.append(item)
    return sorted(inventory, key=lambda item: str(item["metadata_file"]))


def public_lake_provenance(
    run_metadata_path: Path,
    form_ap_metadata_path: Path,
) -> dict[str, Any]:
    run_metadata = json.loads(Path(run_metadata_path).read_text(encoding="utf-8"))
    form_ap = json.loads(Path(form_ap_metadata_path).read_text(encoding="utf-8"))
    provenance = dict(run_metadata.get("provenance", {}))
    return {
        "as_of_date": run_metadata.get("as_of_date"),
        "fresh_build": bool(run_metadata.get("fresh_build")),
        "commit_sha": provenance.get("commit_sha"),
        "git_dirty": provenance.get("dirty"),
        "config_hash": provenance.get("config_hash"),
        "input_hash": provenance.get("input_hash"),
        "uv_lock_hash": provenance.get("uv_lock_hash"),
        "source_metadata_inventory": _source_metadata_inventory(
            list(provenance.get("input_files", []))
        ),
        "form_ap": {
            "source_kind": form_ap.get("source_kind"),
            "archive_sha256": form_ap.get("archive_sha256"),
            "member": form_ap.get("member"),
            "member_sha256": form_ap.get("member_sha256"),
        },
    }


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
