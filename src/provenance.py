from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import zipfile
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


def _required(
    payload: dict[str, Any],
    field: str,
    expected_type: type,
    context: str,
) -> Any:
    if field not in payload:
        raise ValueError(f"{context}.{field} is required")
    value = payload[field]
    valid = type(value) is expected_type
    if expected_type is str:
        valid = valid and bool(value.strip())
    if not valid:
        type_label = "a nonempty string" if expected_type is str else expected_type.__name__
        raise ValueError(f"{context}.{field} must be {type_label}")
    return value


def _load_json_object(path: Path, context: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} is not valid JSON: {exc.msg}") from exc
    if type(payload) is not dict:
        raise ValueError(f"{context} must be a JSON object")
    return payload


def _contained_bronze_path(
    path: Path,
    *,
    bronze_root: Path,
    context: str,
) -> tuple[Path, str]:
    if ".." in path.parts:
        raise ValueError(f"{context} must not contain parent traversal ('..')")
    resolved_root = Path(bronze_root).resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{context} must be resolved-contained under Bronze root") from exc
    return resolved_path, relative_path.as_posix()


def _source_metadata_inventory(
    input_files: list[Any],
    *,
    bronze_root: Path,
) -> tuple[list[dict[str, Any]], list[Path]]:
    if not input_files:
        raise ValueError(
            "public lake run metadata.provenance.input_files must contain at least one record"
        )
    inventory: list[dict[str, Any]] = []
    payload_paths: list[Path] = []
    for index, raw_record in enumerate(input_files):
        context = f"public lake run metadata.provenance.input_files[{index}]"
        if type(raw_record) is not dict:
            raise ValueError(f"{context} must be a JSON object")
        raw_path = Path(_required(raw_record, "path", str, context))
        metadata_sha256 = _required(raw_record, "sha256", str, context)
        path, relative_name = _contained_bronze_path(
            raw_path,
            bronze_root=bronze_root,
            context=f"{context}.path",
        )
        item: dict[str, Any] = {
            "metadata_file": relative_name,
            "metadata_sha256": metadata_sha256,
        }
        if path.name.endswith(".meta.json"):
            if not path.is_file():
                raise ValueError(f"{context}.path references missing metadata sidecar: {path}")
            sidecar_context = f"source metadata sidecar {path}"
            payload = _load_json_object(path, sidecar_context)
            for output_field, source_field, expected_type in (
                ("source_name", "source_name", str),
                ("source_url", "source_url", str),
                ("downloaded_at_utc", "downloaded_at_utc", str),
                ("payload_sha256", "sha256", str),
                ("payload_size_bytes", "size_bytes", int),
                ("parser_version", "parser_version", str),
                ("schema_version", "schema_version", str),
            ):
                item[output_field] = _required(
                    payload,
                    source_field,
                    expected_type,
                    sidecar_context,
                )
            actual_metadata_sha256 = sha256_path(path)
            if metadata_sha256 != actual_metadata_sha256:
                raise ValueError(
                    f"{context}.sha256 recorded sha256 does not match metadata sidecar bytes"
                )
            if "size_bytes" in raw_record:
                recorded_size = _required(raw_record, "size_bytes", int, context)
                if recorded_size != path.stat().st_size:
                    raise ValueError(
                        f"{context}.size_bytes does not match metadata sidecar byte size"
                    )
            payload_path, _ = _contained_bronze_path(
                path.with_name(path.name.removesuffix(".meta.json")),
                bronze_root=bronze_root,
                context=f"{sidecar_context} payload path",
            )
            if not payload_path.is_file():
                raise ValueError(f"{sidecar_context} references missing payload: {payload_path}")
            if item["payload_sha256"] != sha256_path(payload_path):
                raise ValueError(f"{sidecar_context} payload sha256 does not match payload bytes")
            if item["payload_size_bytes"] != payload_path.stat().st_size:
                raise ValueError(
                    f"{sidecar_context} payload size does not match payload byte size"
                )
            payload_paths.append(payload_path)
        else:
            if not path.is_file():
                raise ValueError(f"{context}.path references missing metadata file: {path}")
            if metadata_sha256 != sha256_path(path):
                raise ValueError(f"{context}.sha256 recorded sha256 does not match file bytes")
            if "size_bytes" in raw_record:
                recorded_size = _required(raw_record, "size_bytes", int, context)
                if recorded_size != path.stat().st_size:
                    raise ValueError(f"{context}.size_bytes does not match metadata file byte size")
        inventory.append(item)
    return sorted(inventory, key=lambda item: str(item["metadata_file"])), payload_paths


def _verify_form_ap_member(
    *,
    source_kind: str,
    archive_sha256: str | None,
    member: str,
    member_sha256: str,
    payload_paths: list[Path],
    context: str,
) -> None:
    expected_name = (
        "FirmFilings.zip" if source_kind == "verified_zip_member" else "FirmFilings.csv"
    )
    matches = [path for path in payload_paths if path.name == expected_name]
    if len(matches) != 1:
        raise ValueError(f"{context} must bind exactly one {expected_name} metadata sidecar")
    payload_path = matches[0]
    if source_kind == "verified_zip_member":
        if member != "FirmFilings.csv":
            raise ValueError(f"{context}.member must be exact FirmFilings.csv; got {member}")
        if archive_sha256 != sha256_path(payload_path):
            raise ValueError(f"{context}.archive_sha256 does not match FirmFilings.zip")
        try:
            with zipfile.ZipFile(payload_path) as archive:
                with archive.open(member) as handle:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ValueError(f"{context} cannot read exact FirmFilings.csv member") from exc
        actual_member_sha256 = digest.hexdigest()
    else:
        if member != "FirmFilings.csv":
            raise ValueError(f"{context}.member must be exact FirmFilings.csv; got {member}")
        actual_member_sha256 = sha256_path(payload_path)
    if member_sha256 != actual_member_sha256:
        raise ValueError(f"{context}.member_sha256 does not match FirmFilings.csv bytes")


def public_lake_provenance(
    run_metadata_path: Path,
    form_ap_metadata_path: Path,
    *,
    bronze_root: Path,
) -> dict[str, Any]:
    run_context = f"public lake run metadata ({run_metadata_path})"
    form_ap_context = f"Form AP source metadata ({form_ap_metadata_path})"
    run_metadata = _load_json_object(Path(run_metadata_path), run_context)
    form_ap = _load_json_object(Path(form_ap_metadata_path), form_ap_context)
    _required(run_metadata, "as_of_date", str, run_context)
    _required(run_metadata, "fresh_build", bool, run_context)
    provenance = _required(run_metadata, "provenance", dict, run_context)
    provenance_context = f"{run_context}.provenance"
    for field, expected_type in (
        ("commit_sha", str),
        ("dirty", bool),
        ("config_hash", str),
        ("input_hash", str),
        ("uv_lock_hash", str),
    ):
        _required(provenance, field, expected_type, provenance_context)
    input_files = _required(provenance, "input_files", list, provenance_context)

    source_kind = _required(form_ap, "source_kind", str, form_ap_context)
    if source_kind not in {"verified_zip_member", "standalone_csv_fallback"}:
        raise ValueError(
            f"{form_ap_context}.source_kind must be verified_zip_member or "
            "standalone_csv_fallback"
        )
    if "archive_sha256" not in form_ap:
        raise ValueError(f"{form_ap_context}.archive_sha256 is required")
    archive_sha256 = form_ap["archive_sha256"]
    if archive_sha256 is None:
        if source_kind != "standalone_csv_fallback":
            raise ValueError(
                f"{form_ap_context}.archive_sha256 may be null only for "
                "standalone_csv_fallback"
            )
    elif not isinstance(archive_sha256, str) or not archive_sha256.strip():
        raise ValueError(f"{form_ap_context}.archive_sha256 must be a nonempty string or null")
    for field in ("member", "member_sha256"):
        _required(form_ap, field, str, form_ap_context)

    source_metadata_inventory, payload_paths = _source_metadata_inventory(
        input_files,
        bronze_root=bronze_root,
    )
    _verify_form_ap_member(
        source_kind=source_kind,
        archive_sha256=archive_sha256,
        member=form_ap["member"],
        member_sha256=form_ap["member_sha256"],
        payload_paths=payload_paths,
        context=form_ap_context,
    )

    return {
        "as_of_date": run_metadata["as_of_date"],
        "fresh_build": run_metadata["fresh_build"],
        "commit_sha": provenance["commit_sha"],
        "git_dirty": provenance["dirty"],
        "config_hash": provenance["config_hash"],
        "input_hash": provenance["input_hash"],
        "uv_lock_hash": provenance["uv_lock_hash"],
        "source_metadata_inventory": source_metadata_inventory,
        "form_ap": {
            "source_kind": source_kind,
            "archive_sha256": archive_sha256,
            "member": form_ap["member"],
            "member_sha256": form_ap["member_sha256"],
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
