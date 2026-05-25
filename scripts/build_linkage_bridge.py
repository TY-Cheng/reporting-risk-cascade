"""Build the raw-only gvkey-CIK-year linkage folder."""

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

    from src import DATA_DIR, RAW_DATASET_PATH
    from src.linkage import (
        DEFAULT_LINKAGE_OUT_DIR,
        DEFAULT_RAW_CIK_GVKEY_LINK_PATH,
    )

    parser = argparse.ArgumentParser(
        description=(
            "Build DATA_DIR/linkage/raw_only with raw CIK-GVKEY links as the sole "
            "gvkey-CIK-year bridge evidence."
        )
    )
    parser.add_argument(
        "--raw-link",
        type=Path,
        default=DEFAULT_RAW_CIK_GVKEY_LINK_PATH,
        help="Raw CIK-GVKEY Link Table.csv input",
    )
    parser.add_argument(
        "--raw-data",
        type=Path,
        default=RAW_DATASET_PATH,
        help="Raw benchmark panel used to restrict expanded years and compute coverage",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_LINKAGE_OUT_DIR,
        help="Output folder for combined linkage data",
    )
    parser.add_argument(
        "--public-lake-panel",
        type=Path,
        default=DATA_DIR / "public_lake" / "gold" / "issuer_origin_panel.parquet",
        help="Full public-lake issuer_origin_panel path for overlap output",
    )
    parser.add_argument(
        "--public-lake-smoke-panel",
        type=Path,
        default=DATA_DIR / "public_lake_smoke" / "gold" / "issuer_origin_panel.parquet",
        help="Smoke public-lake issuer_origin_panel path for overlap output",
    )
    parser.add_argument(
        "--include-name-mismatch",
        action="store_true",
        help="Include raw CIK-GVKEY rows marked Link with Name Mismatch",
    )
    parser.add_argument(
        "--date-rule",
        choices=["intersection", "sec_window"],
        default="intersection",
        help="Annual expansion rule for raw link date windows",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.linkage import build_raw_primary_linkage

    args = parse_args()
    result = build_raw_primary_linkage(
        raw_link_path=args.raw_link,
        raw_data_path=args.raw_data,
        out_dir=args.out_dir,
        public_lake_panel_path=args.public_lake_panel,
        public_lake_smoke_panel_path=args.public_lake_smoke_panel,
        include_name_mismatch=args.include_name_mismatch,
        date_rule=args.date_rule,
    )
    print(json.dumps(result.summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
