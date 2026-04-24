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
            "aaer",
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
    parser.add_argument("--end-year", type=int, default=2023)
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
    return parser.parse_args()


def _resolve_as_of_date(config_path: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        lake_cfg = config.get("lake", {})
        if lake_cfg.get("as_of_date"):
            return str(lake_cfg["as_of_date"])
    return date.today().isoformat()


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
        "aaer",
        "insider",
        "13f",
        "edgar-logs",
        "market-structure",
        "form-ap",
        "pcaob-inspections",
    }:
        manifest = fetch_source_assets(
            mode=args.mode,
            bronze_dir=args.bronze_dir,
            start_year=args.start_year,
            end_year=args.end_year,
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
        outputs = build_public_lake(
            bronze_dir=args.bronze_dir,
            silver_dir=args.silver_dir,
            gold_dir=args.gold_dir,
            as_of_date=as_of_date,
            submissions_max_ciks=args.submissions_max_ciks
            if args.submissions_max_ciks > 0
            else None,
        )
        print(json.dumps({k: str(v) for k, v in outputs.items()}, indent=2))
        return


if __name__ == "__main__":
    main()
