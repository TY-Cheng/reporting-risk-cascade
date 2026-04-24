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

    from src import ARTIFACTS_DIR, LAKE_GOLD_DIR, LAKE_SILVER_DIR, RAW_DATASET_PATH

    parser = argparse.ArgumentParser(description="Run public-only gvkey-CIK bridge probe")
    parser.add_argument(
        "--raw-csv",
        type=Path,
        default=RAW_DATASET_PATH,
        help="Old gvkey firm-year CSV",
    )
    parser.add_argument(
        "--issuer-dim",
        type=Path,
        default=LAKE_SILVER_DIR / "issuer_dim.csv.gz",
        help="Public-lake silver issuer dimension",
    )
    parser.add_argument(
        "--issuer-origin-panel",
        type=Path,
        default=LAKE_GOLD_DIR / "issuer_origin_panel.csv.gz",
        help="Fallback public-lake gold issuer panel",
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

    args = parse_args()
    summary = run_bridge_probe(
        raw_csv=args.raw_csv,
        issuer_dim_csv=args.issuer_dim,
        issuer_origin_panel_csv=args.issuer_origin_panel,
        out_dir=args.out_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
