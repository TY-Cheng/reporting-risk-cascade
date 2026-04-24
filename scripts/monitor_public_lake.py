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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _row_count_report(silver_dir: Path, gold_dir: Path) -> Dict[str, int]:
    targets = {
        "issuer_dim": silver_dir / "issuer_dim.csv.gz",
        "filing_dim": silver_dir / "filing_dim.csv.gz",
        "comment_thread": silver_dir / "comment_thread.csv.gz",
        "correction_event": silver_dir / "correction_event.csv.gz",
        "aaer_event": silver_dir / "aaer_event.csv.gz",
        "issuer_origin_panel": gold_dir / "issuer_origin_panel.csv.gz",
        "filing_origin_panel": gold_dir / "filing_origin_panel.csv.gz",
    }
    return {name: _count_csv_rows(path) for name, path in targets.items() if path.exists()}


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
        row["row_counts_json"] = json.dumps(
            _row_count_report(args.silver_dir, args.gold_dir), sort_keys=True
        )
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
        row = _snapshot(args, include_row_counts=True)
        _append_csv(monitor_csv, [row])
        if args.report_json:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(
                json.dumps(
                    {
                        "snapshot": row,
                        "row_counts": _row_count_report(args.silver_dir, args.gold_dir),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        print(json.dumps(row, indent=2, sort_keys=True))
        return

    while True:
        _append_csv(monitor_csv, [_snapshot(args)])
        time.sleep(float(args.interval))


if __name__ == "__main__":
    main()
