"""
Convert the benchmark raw dataset from CSV to the repo-default Parquet path.
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

    from src import DATA_DIR

    parser = argparse.ArgumentParser(description="Convert raw benchmark CSV to Parquet")
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=DATA_DIR / "raw_dataset_misstatement.csv",
        help="Existing raw benchmark CSV",
    )
    parser.add_argument(
        "--out-data",
        type=Path,
        default=DATA_DIR / "raw_dataset_misstatement.parquet",
        help="Output Parquet path",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing output")
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.table_io import read_table, write_table

    args = parse_args()
    if args.out_data.exists() and not args.overwrite:
        print(f"Exists: {args.out_data}")
        return
    if not args.input_csv.exists():
        raise FileNotFoundError(f"Raw benchmark CSV not found: {args.input_csv}")

    frame = read_table(args.input_csv, low_memory=False)
    write_table(frame, args.out_data, overwrite=True)
    print(f"Wrote {len(frame)} rows to {args.out_data}")


if __name__ == "__main__":
    main()
