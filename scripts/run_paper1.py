"""
Run the Paper 1 misstatement pipeline with repo defaults.
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

    from src import ARTIFACTS_DIR, PROJECT_ROOT, RAW_DATASET_PATH

    parser = argparse.ArgumentParser(description="Run the Paper 1 rolling misstatement pipeline")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "paper1.yaml",
        help="Path to the Paper 1 YAML config",
    )
    parser.add_argument(
        "--raw-csv",
        type=Path,
        default=RAW_DATASET_PATH,
        help="Path to the raw firm-year CSV",
    )
    parser.add_argument(
        "--timing-csv",
        type=Path,
        default=None,
        help="Optional external timing CSV with detection/filling dates",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ARTIFACTS_DIR / "paper1",
        help="Directory for Paper 1 outputs",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.paper1 import run_paper1

    args = parse_args()
    run_paper1(
        config_path=args.config,
        raw_csv=args.raw_csv,
        out_dir=args.out_dir,
        timing_csv=args.timing_csv,
    )


if __name__ == "__main__":
    main()
