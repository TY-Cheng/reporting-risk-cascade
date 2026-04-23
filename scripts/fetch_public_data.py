"""
Fetch public SEC and PCAOB data used by the Paper 2 spine.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_repo_root() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    _bootstrap_repo_root()

    from src import ARTIFACTS_DIR, SEC_DATA_DIR, PCAOB_DATA_DIR

    parser = argparse.ArgumentParser(description="Fetch public SEC and PCAOB inputs")
    parser.add_argument(
        "--mode",
        choices=["references", "sec-index", "sec-download"],
        default="references",
        help="Which public-data task to run",
    )
    parser.add_argument(
        "--master-panel",
        type=Path,
        default=ARTIFACTS_DIR / "paper1" / "master_panel.csv.gz",
        help="Master panel CSV for SEC filing index construction",
    )
    parser.add_argument(
        "--gvkey-cik-csv",
        type=Path,
        default=None,
        help="Optional gvkey-CIK link file for SEC filing index construction",
    )
    parser.add_argument(
        "--sec-dir",
        type=Path,
        default=SEC_DATA_DIR,
        help="Directory for SEC reference data and downloads",
    )
    parser.add_argument(
        "--pcaob-dir",
        type=Path,
        default=PCAOB_DATA_DIR,
        help="Directory for PCAOB reference data",
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=None,
        help="Optional explicit output CSV path for sec-index mode",
    )
    parser.add_argument(
        "--forms",
        nargs="+",
        default=["10-K", "10-K/A", "8-K"],
        help="SEC forms to keep in sec-index mode",
    )
    parser.add_argument("--start-year", type=int, default=2001)
    parser.add_argument("--end-year", type=int, default=2019)
    parser.add_argument(
        "--limit", type=int, default=0, help="Optional download cap in sec-download mode"
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.public_data import (
        build_sec_filing_index,
        download_public_reference_data,
        download_sec_filings,
    )

    args = parse_args()
    if args.mode == "references":
        files = download_public_reference_data(sec_dir=args.sec_dir, pcaob_dir=args.pcaob_dir)
        print(files)
        return

    if args.mode == "sec-index":
        if args.gvkey_cik_csv is None:
            raise SystemExit("--gvkey-cik-csv is required for --mode sec-index")
        out_csv = args.out_csv or (args.sec_dir / "sec_filing_index.csv")
        index_df = build_sec_filing_index(
            master_panel_csv=args.master_panel,
            gvkey_cik_csv=args.gvkey_cik_csv,
            out_csv=out_csv,
            forms=args.forms,
            start_year=args.start_year,
            end_year=args.end_year,
        )
        print(index_df.head().to_string())
        return

    if args.mode == "sec-download":
        if args.out_csv is None:
            raise SystemExit(
                "--out-csv must point to an SEC filing index CSV in sec-download mode"
            )
        manifest = download_sec_filings(
            index_csv=args.out_csv,
            out_dir=args.sec_dir / "filings",
            limit=args.limit if args.limit > 0 else None,
        )
        print(manifest.head().to_string())


if __name__ == "__main__":
    main()
