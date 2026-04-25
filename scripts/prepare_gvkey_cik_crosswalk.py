"""
Normalize an external gvkey-CIK-year crosswalk for the bridge probe.

This script expects an authoritative source export, typically WRDS/Compustat's
CIK-GVKEY link output or an equivalent institution-provided file. It does not
infer gvkey-CIK links from public SEC data.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_repo_root() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    _bootstrap_repo_root()

    from src import RAW_DATASET_PATH

    parser = argparse.ArgumentParser(
        description="Prepare data/external/gvkey_cik_year.csv from an external source export"
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="External crosswalk export with gvkey, cik/issuer_cik, and year or year range",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "data" / "external" / "gvkey_cik_year.csv",
        help="Normalized bridge crosswalk output",
    )
    parser.add_argument(
        "--raw-data",
        type=Path,
        default=RAW_DATASET_PATH,
        help="Optional raw benchmark table used to restrict expanded years",
    )
    parser.add_argument(
        "--no-raw-filter",
        action="store_true",
        help="Do not restrict expanded ranges to years present in the raw benchmark table",
    )
    parser.add_argument("--source", default="wrds_compustat_cik_gvkey_link")
    parser.add_argument("--source-version", default="")
    parser.add_argument(
        "--extracted-at",
        default=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        help="Source extraction timestamp to write into provenance columns",
    )
    parser.add_argument("--match-method", default="wrds_cik_gvkey_link")
    parser.add_argument("--match-score", type=float, default=None)
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=REPO_ROOT / "artifacts" / "bridge_crosswalk" / "crosswalk_summary.json",
        help="Summary JSON output",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.bridge import prepare_gvkey_cik_crosswalk

    args = parse_args()
    raw_data = None if args.no_raw_filter else args.raw_data
    summary = prepare_gvkey_cik_crosswalk(
        input_path=args.input,
        output_path=args.out,
        raw_data_path=raw_data,
        source=args.source,
        source_version=args.source_version,
        extracted_at=args.extracted_at,
        match_method=args.match_method,
        match_score=args.match_score,
    )
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
