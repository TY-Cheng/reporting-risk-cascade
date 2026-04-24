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

    from src import SEED_DEFAULT

    parser = argparse.ArgumentParser(description="Generate the runtime sample dataset")
    parser.add_argument("--raw-data", type=Path, default=None)
    parser.add_argument("--raw-csv", type=Path, default=None, help="Deprecated alias for --raw-data")
    parser.add_argument("--out-data", type=Path, default=None)
    parser.add_argument("--out-csv", type=Path, default=None, help="Deprecated alias for --out-data")
    parser.add_argument("--firm-col", default="gvkey")
    parser.add_argument("--n-firms", type=int, default=500)
    parser.add_argument("--seed", type=int, default=SEED_DEFAULT)
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.sample_dataset import materialize_sample_dataset

    args = parse_args()
    raw_data = args.raw_data or args.raw_csv
    out_data = args.out_data or args.out_csv
    if raw_data is None:
        from src import DATA_DIR, RAW_DATASET_PATH
        from src.table_io import read_table, write_table

        raw_data = RAW_DATASET_PATH
        legacy_csv = DATA_DIR / "raw_dataset_misstatement.csv"
        if not raw_data.exists() and raw_data.suffix.lower() == ".parquet" and legacy_csv.exists():
            write_table(read_table(legacy_csv, low_memory=False), raw_data)
    if out_data is None:
        from src import SAMPLE_DATASET_PATH

        out_data = SAMPLE_DATASET_PATH
    summary = materialize_sample_dataset(
        raw_csv=raw_data,
        out_csv=out_data,
        firm_col=args.firm_col,
        n_firms=args.n_firms,
        seed=args.seed,
    )
    print(f"Wrote {summary.rows_written} rows across {summary.n_firms} firms to {summary.out_csv}")


if __name__ == "__main__":
    main()
