"""
Fetch public SEC and PCAOB data for the filing-native public program.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_repo_root() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    _bootstrap_repo_root()

    from src import (
        LAKE_BRONZE_DIR,
        LAKE_GOLD_DIR,
        LAKE_SILVER_DIR,
        PROJECT_ROOT,
    )

    parser = argparse.ArgumentParser(description="Fetch public SEC and PCAOB inputs")
    parser.add_argument(
        "--mode",
        choices=[
            "sec-bulk",
            "fsds",
            "notes",
            "comment-letters",
            "insider",
            "13f",
            "edgar-logs",
            "market-structure",
            "form-ap",
            "pcaob-inspections",
            "build-lake",
        ],
        default="sec-bulk",
        help="Which public-data task to run",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "public_data.yaml",
        help="Public-data config used for defaults such as as-of date",
    )
    parser.add_argument(
        "--bronze-dir",
        type=Path,
        default=LAKE_BRONZE_DIR,
        help="Bronze-layer directory for the filing-native public lake",
    )
    parser.add_argument(
        "--silver-dir",
        type=Path,
        default=LAKE_SILVER_DIR,
        help="Silver-layer directory for the filing-native public lake",
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=LAKE_GOLD_DIR,
        help="Gold-layer directory for the filing-native public lake",
    )
    parser.add_argument("--start-year", type=int, default=2011)
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Source archive end year; defaults to the configured as-of year.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Optional start date for date-ranged sources such as comment letters",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Optional end date for date-ranged sources such as comment letters",
    )
    parser.add_argument(
        "--match",
        type=str,
        default=None,
        help="Optional substring filter for discovered asset links",
    )
    parser.add_argument(
        "--limit-links",
        type=int,
        default=0,
        help="Optional cap on discovered source links for page-based modes",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Discover and manifest links without downloading payloads",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download source payloads even when cached files and metadata exist",
    )
    parser.add_argument(
        "--as-of-date",
        type=str,
        default=None,
        help="As-of date for censoring-aware gold panels; defaults to config, then today",
    )
    parser.add_argument(
        "--submissions-max-ciks",
        type=int,
        default=0,
        help="Optional cap when normalizing submissions.zip into silver/gold",
    )
    parser.add_argument(
        "--engine",
        choices=["pandas", "duckdb"],
        default=None,
        help="Public-lake build engine; defaults to config lake.engine",
    )
    parser.add_argument(
        "--duckdb-threads",
        type=int,
        default=0,
        help="DuckDB PRAGMA threads for build-lake; defaults to config lake.duckdb_threads",
    )
    parser.add_argument(
        "--duckdb-memory-limit",
        type=str,
        default=None,
        help="DuckDB memory_limit for build-lake; defaults to config lake.duckdb_memory_limit",
    )
    parser.add_argument(
        "--duckdb-temp-directory",
        type=Path,
        default=None,
        help="DuckDB temp_directory for build-lake; defaults to silver-local temp storage",
    )
    parser.add_argument(
        "--duckdb-max-temp-size",
        type=str,
        default=None,
        help="DuckDB max_temp_directory_size for build-lake; defaults to config",
    )
    parser.add_argument(
        "--storage-format",
        choices=["parquet", "csv-gz"],
        default=None,
        help=(
            "Heavy-table storage format; parquet is the production default. "
            "csv-gz is a compatibility fallback for small oracle tests."
        ),
    )
    parser.add_argument(
        "--notes-mode",
        choices=["summary", "raw", "skip"],
        default=None,
        help="Notes extraction mode for Parquet builds; defaults to config lake.notes_mode",
    )
    parser.add_argument(
        "--fresh-build",
        action="store_true",
        help="Rebuild silver/gold layers from bronze without re-downloading bronze",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse build-lake DAG done markers for completed tasks",
    )
    parser.add_argument(
        "--fsds-batch-size",
        type=int,
        default=0,
        help="FSDS archive batch size for Parquet builds; defaults to config lake.fsds_batch_size",
    )
    parser.add_argument(
        "--notes-batch-size",
        type=int,
        default=0,
        help="Notes archive batch size for Parquet builds; defaults to config lake.notes_batch_size",
    )
    return parser.parse_args()


def _load_lake_config(config_path: Path) -> dict:
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return config.get("lake", {}) or {}
    return {}


def _resolve_as_of_date(config_path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    lake_cfg = _load_lake_config(config_path)
    if lake_cfg.get("as_of_date"):
        return str(lake_cfg["as_of_date"])
    return date.today().isoformat()


def _resolve_source_end_year(config_path: Path, explicit: int | None) -> int:
    if explicit is not None:
        return int(explicit)
    as_of_date = _resolve_as_of_date(config_path, None)
    try:
        return int(str(as_of_date).split("-", maxsplit=1)[0])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cannot infer source end year from as-of date: {as_of_date}") from exc


def _resolve_engine(config_path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    lake_cfg = _load_lake_config(config_path)
    return str(lake_cfg.get("engine", "duckdb"))


def _resolve_duckdb_threads(config_path: Path, explicit: int) -> int:
    if explicit > 0:
        return int(explicit)
    lake_cfg = _load_lake_config(config_path)
    return int(lake_cfg.get("duckdb_threads", 4))


def _resolve_string_config(config_path: Path, explicit: str | None, key: str, default: str) -> str:
    if explicit is not None:
        return explicit
    lake_cfg = _load_lake_config(config_path)
    return str(lake_cfg.get(key, default))


def _resolve_path_config(config_path: Path, explicit: Path | None, key: str) -> Path | None:
    if explicit is not None:
        return explicit
    lake_cfg = _load_lake_config(config_path)
    value = lake_cfg.get(key)
    if value is None or str(value).strip() == "":
        return None
    return Path(str(value))


def _resolve_storage_format(config_path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    lake_cfg = _load_lake_config(config_path)
    return str(lake_cfg.get("storage_format", "parquet"))


def _resolve_notes_mode(config_path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    lake_cfg = _load_lake_config(config_path)
    return str(lake_cfg.get("notes_mode", "summary"))


def _resolve_batch_size(config_path: Path, explicit: int, key: str, default: int) -> int:
    if explicit > 0:
        return int(explicit)
    lake_cfg = _load_lake_config(config_path)
    return int(lake_cfg.get(key, default))


def main() -> None:
    _bootstrap_repo_root()

    from src.public_lake import (
        build_public_lake,
        fetch_source_assets,
    )

    args = parse_args()
    if args.mode in {
        "sec-bulk",
        "fsds",
        "notes",
        "comment-letters",
        "insider",
        "13f",
        "edgar-logs",
        "market-structure",
        "form-ap",
        "pcaob-inspections",
    }:
        end_year = _resolve_source_end_year(args.config, args.end_year)
        manifest = fetch_source_assets(
            mode=args.mode,
            bronze_dir=args.bronze_dir,
            start_year=args.start_year,
            end_year=end_year,
            start_date=args.start_date,
            end_date=args.end_date,
            match=args.match,
            limit_links=args.limit_links if args.limit_links > 0 else None,
            list_only=args.list_only,
            force=args.force,
        )
        print(manifest.head().to_string())
        return

    if args.mode == "build-lake":
        as_of_date = _resolve_as_of_date(args.config, args.as_of_date)
        engine = _resolve_engine(args.config, args.engine)
        duckdb_threads = _resolve_duckdb_threads(args.config, args.duckdb_threads)
        duckdb_memory_limit = _resolve_string_config(
            args.config, args.duckdb_memory_limit, "duckdb_memory_limit", "10GB"
        )
        duckdb_temp_directory = _resolve_path_config(
            args.config, args.duckdb_temp_directory, "duckdb_temp_directory"
        )
        duckdb_max_temp_size = _resolve_string_config(
            args.config, args.duckdb_max_temp_size, "duckdb_max_temp_directory_size", "400GB"
        )
        storage_format = _resolve_storage_format(args.config, args.storage_format)
        notes_mode = _resolve_notes_mode(args.config, args.notes_mode)
        fsds_batch_size = _resolve_batch_size(
            args.config, args.fsds_batch_size, "fsds_batch_size", 4
        )
        notes_batch_size = _resolve_batch_size(
            args.config, args.notes_batch_size, "notes_batch_size", 2
        )
        outputs = build_public_lake(
            bronze_dir=args.bronze_dir,
            silver_dir=args.silver_dir,
            gold_dir=args.gold_dir,
            as_of_date=as_of_date,
            submissions_max_ciks=args.submissions_max_ciks
            if args.submissions_max_ciks > 0
            else None,
            engine=engine,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_size,
            storage_format=storage_format,
            notes_mode=notes_mode,
            fsds_batch_size=fsds_batch_size,
            notes_batch_size=notes_batch_size,
            fresh_build=args.fresh_build,
            resume=args.resume,
        )
        print(json.dumps({k: str(v) for k, v in outputs.items()}, indent=2))
        return


if __name__ == "__main__":
    main()
