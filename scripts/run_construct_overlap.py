"""
Run construct-overlap validation from existing study artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_repo_root() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    _bootstrap_repo_root()

    from src import ARTIFACTS_DIR, DATA_DIR

    parser = argparse.ArgumentParser(description="Run construct-overlap validation")
    parser.add_argument(
        "--study-dir",
        type=Path,
        default=ARTIFACTS_DIR / "full_with_peer",
        help="Existing study artifact directory",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory; defaults to <study-dir>/construct_overlap",
    )
    parser.add_argument(
        "--opacity-out-dir",
        type=Path,
        default=None,
        help="Opacity refresh output directory; defaults to <study-dir>/opacity_validation_refresh",
    )
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=DATA_DIR / "external" / "gvkey_cik_year.csv",
        help="Candidate gvkey-CIK-year bridge",
    )
    parser.add_argument(
        "--issuer-origin-panel",
        type=Path,
        default=None,
        help="Public issuer-origin panel; defaults to study manifest input",
    )
    parser.add_argument(
        "--farr-aaer-firm-year",
        type=Path,
        default=DATA_DIR / "external" / "farr_aaer_firm_year.csv",
        help="farr AAER firm-year support file",
    )
    parser.add_argument(
        "--farr-aaer-dates",
        type=Path,
        default=DATA_DIR / "external" / "farr_aaer_dates.csv",
        help="farr AAER date support file",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.construct_overlap import run_construct_overlap

    args = parse_args()
    summary = run_construct_overlap(
        study_dir=args.study_dir,
        out_dir=args.out_dir,
        opacity_out_dir=args.opacity_out_dir,
        crosswalk_path=args.crosswalk,
        issuer_origin_panel_path=args.issuer_origin_panel,
        farr_aaer_firm_year_path=args.farr_aaer_firm_year,
        farr_aaer_dates_path=args.farr_aaer_dates,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
