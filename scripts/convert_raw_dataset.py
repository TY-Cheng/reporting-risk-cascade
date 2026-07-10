"""
Convert the benchmark raw dataset from CSV or ZIP to the repo-default Parquet path.
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

    from src import RAW_DATASET_PATH

    parser = argparse.ArgumentParser(description="Convert raw benchmark CSV/ZIP to Parquet")
    parser.add_argument(
        "--input-data",
        type=Path,
        default=None,
        help=(
            "Existing raw benchmark CSV or ZIP. Defaults to DATA_DIR/raw_dataset_misstatement.csv, "
            "then DATA_DIR/raw_dataset_misstatement.zip, then "
            "DATA_DIR/raw/raw_dataset_misstatement.csv, then "
            "DATA_DIR/raw/raw_dataset_misstatement.zip."
        ),
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=None,
        help="Deprecated alias for --input-data",
    )
    parser.add_argument(
        "--out-data",
        type=Path,
        default=RAW_DATASET_PATH,
        help="Output Parquet path",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing output")
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.raw_dataset import materialize_raw_dataset

    args = parse_args()
    source = args.input_data or args.input_csv
    result = materialize_raw_dataset(
        source_path=source,
        out_data=args.out_data,
        overwrite=args.overwrite,
    )
    if result.wrote_output:
        print(f"Wrote {result.rows_written} rows from {result.source_path} to {result.out_data}")
    elif result.source_path is None:
        print(f"Exists: {result.out_data}")
    else:
        print(f"Exists: {result.out_data} (source available: {result.source_path})")


if __name__ == "__main__":
    main()
