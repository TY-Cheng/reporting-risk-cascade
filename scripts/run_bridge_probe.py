"""
Run the public-only bridge feasibility probe.
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

    from src import ARTIFACTS_DIR, LAKE_GOLD_DIR, LAKE_SILVER_DIR

    parser = argparse.ArgumentParser(description="Run public-only gvkey-CIK bridge probe")
    parser.add_argument(
        "--raw-data",
        type=Path,
        default=None,
        help="Old gvkey firm-year table",
    )
    parser.add_argument(
        "--raw-csv",
        type=Path,
        default=None,
        help="Deprecated alias for --raw-data",
    )
    parser.add_argument(
        "--issuer-dim",
        type=Path,
        default=LAKE_SILVER_DIR / "issuer_dim.parquet",
        help="Public-lake silver issuer dimension",
    )
    parser.add_argument(
        "--issuer-origin-panel",
        type=Path,
        default=LAKE_GOLD_DIR / "issuer_origin_panel.parquet",
        help="Fallback public-lake gold issuer panel",
    )
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=REPO_ROOT / "data" / "external" / "gvkey_cik_year.csv",
        help="Optional authoritative gvkey-CIK-year crosswalk",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ARTIFACTS_DIR / "bridge_probe",
        help="Directory for bridge-probe outputs",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.bridge import run_bridge_probe
    from src import RAW_DATASET_PATH

    args = parse_args()
    raw_data = args.raw_data or args.raw_csv or RAW_DATASET_PATH
    summary = run_bridge_probe(
        raw_data_path=raw_data,
        issuer_dim_path=args.issuer_dim,
        issuer_origin_panel_path=args.issuer_origin_panel,
        crosswalk_path=args.crosswalk,
        out_dir=args.out_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
