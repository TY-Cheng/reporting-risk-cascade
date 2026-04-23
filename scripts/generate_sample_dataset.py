"""
Materialize a deterministic firm-level sample panel from the raw dataset.
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

    from src import RAW_DATASET_PATH, SAMPLE_DATASET_PATH, SEED_DEFAULT

    parser = argparse.ArgumentParser(description="Generate the runtime sample dataset")
    parser.add_argument("--raw-csv", type=Path, default=RAW_DATASET_PATH)
    parser.add_argument("--out-csv", type=Path, default=SAMPLE_DATASET_PATH)
    parser.add_argument("--firm-col", default="gvkey")
    parser.add_argument("--n-firms", type=int, default=500)
    parser.add_argument("--seed", type=int, default=SEED_DEFAULT)
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.sample_dataset import materialize_sample_dataset

    args = parse_args()
    summary = materialize_sample_dataset(
        raw_csv=args.raw_csv,
        out_csv=args.out_csv,
        firm_col=args.firm_col,
        n_firms=args.n_firms,
        seed=args.seed,
    )
    print(f"Wrote {summary.rows_written} rows across {summary.n_firms} firms to {summary.out_csv}")


if __name__ == "__main__":
    main()
