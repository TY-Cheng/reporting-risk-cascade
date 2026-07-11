"""
Monitor public-lake disk footprint, manifests, and optional process memory.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Tuple

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_LAKE_FINAL_REPORT_SCHEMA = "public-lake-final-report-v1"
PUBLIC_LAKE_ROW_COUNT_KEYS = frozenset(
    {
        "issuer_dim",
        "filing_dim",
        "filing_xbrl_dim",
        "xbrl_fact_summary",
        "xbrl_core_fact",
        "notes_filing_dim",
        "note_summary",
        "comment_thread",
        "correction_event",
        "issuer_origin_panel",
        "filing_origin_panel",
    }
)


def _bootstrap_repo_root() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    _bootstrap_repo_root()
    from src import LAKE_BRONZE_DIR, LAKE_GOLD_DIR, LAKE_SILVER_DIR, PROJECT_ROOT

    parser = argparse.ArgumentParser(description="Monitor public-lake full-run progress")
    parser.add_argument("--bronze-dir", type=Path, default=LAKE_BRONZE_DIR)
    parser.add_argument("--silver-dir", type=Path, default=LAKE_SILVER_DIR)
    parser.add_argument("--gold-dir", type=Path, default=LAKE_GOLD_DIR)
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "logs" / "public_lake_full",
    )
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--pid", type=int, default=0, help="Optional root PID to monitor")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--write-final-report", action="store_true")
    parser.add_argument("--as-of-date", default=None)
    return parser.parse_args()


def _du_kib(path: Path) -> int:
    if not path.exists():
        return 0
    result = subprocess.run(["du", "-sk", str(path)], check=True, capture_output=True, text=True)
    return int(result.stdout.split()[0])


def _file_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    for _, _, filenames in os.walk(path):
        count += len(filenames)
    return count


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for chunk in pd.read_csv(path, chunksize=250_000, low_memory=False):
        total += len(chunk)
    return int(total)


def _count_parquet_rows(path: Path) -> int:
    if not path.exists():
        return 0
    _bootstrap_repo_root()
    from src.table_io import parquet_scan_sql

    import duckdb

    con = duckdb.connect(database=":memory:")
    try:
        return int(con.execute(f"SELECT count(*) FROM {parquet_scan_sql(path)}").fetchone()[0])
    finally:
        con.close()


def _count_table_rows(path: Path) -> int:
    if path.suffix.lower() == ".parquet" or path.is_dir():
        return _count_parquet_rows(path)
    return _count_csv_rows(path)


def _manifest_rows(bronze_dir: Path) -> Dict[str, int]:
    rows: Dict[str, int] = {}
    if not bronze_dir.exists():
        return rows
    for manifest in sorted(bronze_dir.glob("*/manifest.csv")):
        source = manifest.parent.name
        try:
            rows[source] = _count_csv_rows(manifest)
        except pd.errors.EmptyDataError:
            rows[source] = 0
    return rows


def _ps_table() -> Dict[int, tuple[int, int, str]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,rss=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    table: Dict[int, tuple[int, int, str]] = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 3:
            continue
        pid, ppid, rss = (int(parts[0]), int(parts[1]), int(parts[2]))
        command = parts[3] if len(parts) > 3 else ""
        table[pid] = (ppid, rss, command)
    return table


def _descendants(root_pid: int, table: Dict[int, tuple[int, int, str]]) -> set[int]:
    children: Dict[int, list[int]] = {}
    for pid, (ppid, _, _) in table.items():
        children.setdefault(ppid, []).append(pid)
    seen = {root_pid}
    queue = [root_pid]
    while queue:
        parent = queue.pop()
        for child in children.get(parent, []):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen


def _rss_kib(pid: int) -> int:
    if pid <= 0:
        return 0
    table = _ps_table()
    pids = _descendants(pid, table)
    return int(sum(table[item][1] for item in pids if item in table))


def _row_count_report(silver_dir: Path, gold_dir: Path) -> Tuple[Dict[str, int], Dict[str, str]]:
    targets = {
        "issuer_dim": silver_dir / "issuer_dim.parquet",
        "filing_dim": silver_dir / "filing_dim.parquet",
        "filing_xbrl_dim": silver_dir / "filing_xbrl_dim.parquet",
        "xbrl_fact_summary": silver_dir / "xbrl_fact_summary.parquet",
        "xbrl_core_fact": silver_dir / "xbrl_core_fact",
        "notes_filing_dim": silver_dir / "notes_filing_dim.parquet",
        "note_summary": silver_dir / "note_summary.parquet",
        "comment_thread": silver_dir / "comment_thread.csv.gz",
        "correction_event": silver_dir / "correction_event.csv.gz",
        "issuer_origin_panel": gold_dir / "issuer_origin_panel.parquet",
        "filing_origin_panel": gold_dir / "filing_origin_panel.parquet",
    }
    counts: Dict[str, int] = {}
    errors: Dict[str, str] = {}
    for name, path in targets.items():
        if not path.exists():
            continue
        try:
            counts[name] = _count_table_rows(path)
        except (FileNotFoundError, OSError, ValueError) as exc:
            errors[name] = str(exc)
    return counts, errors


def _load_json_object(path: Path, context: str) -> Dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} is not valid JSON: {exc.msg}") from exc
    if type(payload) is not dict:
        raise ValueError(f"{context} must be a JSON object")
    return payload


def _validate_public_lake_final_report(
    report_path: Path,
    *,
    run_metadata_path: Path,
    issuer_origin_panel_path: Path,
) -> Dict[str, object]:
    _bootstrap_repo_root()
    from src.provenance import sha256_path

    report = _load_json_object(Path(report_path), "public lake final report")
    expected_fields = {
        "schema_version",
        "as_of_date",
        "public_lake_run_metadata_sha256",
        "issuer_origin_panel_sha256",
        "row_counts",
        "row_count_errors",
    }
    if set(report) != expected_fields:
        raise ValueError(
            f"public lake final report fields must be exactly {sorted(expected_fields)}"
        )
    if report["schema_version"] != PUBLIC_LAKE_FINAL_REPORT_SCHEMA:
        raise ValueError(
            f"public lake final report.schema_version must be {PUBLIC_LAKE_FINAL_REPORT_SCHEMA}"
        )
    run_metadata = _load_json_object(Path(run_metadata_path), "public lake run metadata")
    expected_as_of = run_metadata.get("as_of_date")
    if type(expected_as_of) is not str or not expected_as_of:
        raise ValueError("public lake run metadata.as_of_date must be a nonempty string")
    if report["as_of_date"] != expected_as_of:
        raise ValueError(
            "public lake final report.as_of_date does not match public lake run metadata"
        )
    expected_hashes = {
        "public_lake_run_metadata_sha256": sha256_path(Path(run_metadata_path)),
        "issuer_origin_panel_sha256": sha256_path(Path(issuer_origin_panel_path)),
    }
    for field, actual in expected_hashes.items():
        if actual is None:
            raise FileNotFoundError(
                Path(run_metadata_path)
                if field == "public_lake_run_metadata_sha256"
                else Path(issuer_origin_panel_path)
            )
        if report[field] != actual:
            raise ValueError(f"public lake final report.{field} does not match bound input")
    row_counts = report["row_counts"]
    if type(row_counts) is not dict or set(row_counts) != PUBLIC_LAKE_ROW_COUNT_KEYS:
        raise ValueError(
            "public lake final report.row_counts keys must be exactly "
            f"{sorted(PUBLIC_LAKE_ROW_COUNT_KEYS)}"
        )
    for key, value in row_counts.items():
        if type(value) is not int or value < 0:
            raise ValueError(
                f"public lake final report.row_counts.{key} must be a nonnegative integer"
            )
    if report["row_count_errors"] != {}:
        raise ValueError("public lake final report.row_count_errors must be an empty object")
    return report


def _write_public_lake_final_report(
    *,
    silver_dir: Path,
    as_of_date: str,
    run_metadata_path: Path,
    issuer_origin_panel_path: Path,
    row_counts: Dict[str, int],
    row_count_errors: Dict[str, str],
) -> Path:
    _bootstrap_repo_root()
    from src.provenance import sha256_path

    silver_dir = Path(silver_dir)
    silver_dir.mkdir(parents=True, exist_ok=True)
    report_path = silver_dir / "public_lake_final_report.json"
    payload = {
        "schema_version": PUBLIC_LAKE_FINAL_REPORT_SCHEMA,
        "as_of_date": as_of_date,
        "public_lake_run_metadata_sha256": sha256_path(Path(run_metadata_path)),
        "issuer_origin_panel_sha256": sha256_path(Path(issuer_origin_panel_path)),
        "row_counts": row_counts,
        "row_count_errors": row_count_errors,
    }
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=silver_dir,
            prefix=f"{report_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _validate_public_lake_final_report(
            temp_path,
            run_metadata_path=Path(run_metadata_path),
            issuer_origin_panel_path=Path(issuer_origin_panel_path),
        )
        temp_path.replace(report_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return report_path


def _snapshot(args: argparse.Namespace, *, include_row_counts: bool = False) -> Dict[str, object]:
    manifests = _manifest_rows(args.bronze_dir)
    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bronze_kib": _du_kib(args.bronze_dir),
        "silver_kib": _du_kib(args.silver_dir),
        "gold_kib": _du_kib(args.gold_dir),
        "bronze_files": _file_count(args.bronze_dir),
        "silver_files": _file_count(args.silver_dir),
        "gold_files": _file_count(args.gold_dir),
        "monitored_pid": int(args.pid),
        "process_tree_rss_kib": _rss_kib(int(args.pid)),
        "manifest_rows_json": json.dumps(manifests, sort_keys=True),
    }
    if include_row_counts:
        counts, errors = _row_count_report(args.silver_dir, args.gold_dir)
        row["row_counts_json"] = json.dumps(counts, sort_keys=True)
        row["row_count_errors_json"] = json.dumps(errors, sort_keys=True)
    return row


def _append_csv(path: Path, rows: Iterable[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows:
        return
    fieldnames = sorted({key for row in rows for key in row})
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    monitor_csv = args.log_dir / "monitor.csv"
    if args.once:
        counts, errors = _row_count_report(args.silver_dir, args.gold_dir)
        row = _snapshot(args)
        row["row_counts_json"] = json.dumps(counts, sort_keys=True)
        row["row_count_errors_json"] = json.dumps(errors, sort_keys=True)
        _append_csv(monitor_csv, [row])
        if args.report_json:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(
                json.dumps(
                    {
                        "snapshot": row,
                        "row_counts": counts,
                        "row_count_errors": errors,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        if args.write_final_report:
            if not args.as_of_date:
                raise ValueError("--as-of-date is required with --write-final-report")
            final_report = _write_public_lake_final_report(
                silver_dir=args.silver_dir,
                as_of_date=args.as_of_date,
                run_metadata_path=args.silver_dir / "public_lake_run_metadata.json",
                issuer_origin_panel_path=args.gold_dir / "issuer_origin_panel.parquet",
                row_counts=counts,
                row_count_errors=errors,
            )
            print(f"Wrote stable final report: {final_report}")
        print(json.dumps(row, indent=2, sort_keys=True))
        return

    while True:
        _append_csv(monitor_csv, [_snapshot(args)])
        time.sleep(float(args.interval))


if __name__ == "__main__":
    main()
