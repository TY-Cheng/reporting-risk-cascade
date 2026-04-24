"""
Thin wrapper around ``src.data_prep`` with repo defaults.
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

    from src import DEFAULT_CONFIG_PATH

    parser = argparse.ArgumentParser(description="Run the data-prep baseline with repo defaults")
    parser.add_argument(
        "--dataset",
        choices=["sample", "raw"],
        default="sample",
        help="Named dataset shortcut when --raw-data is omitted",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the YAML config file",
    )
    parser.add_argument(
        "--raw-data",
        type=Path,
        default=None,
        help="Optional explicit raw table path; overrides --dataset",
    )
    parser.add_argument(
        "--raw-csv",
        type=Path,
        default=None,
        help="Deprecated alias for --raw-data",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for generated artifacts",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src import ARTIFACTS_DIR, DATA_DIR, RAW_DATASET_PATH, SAMPLE_DATASET_PATH
    from src.data_prep import main as run_data_prep
    from src.sample_dataset import materialize_sample_dataset
    from src.table_io import read_table, write_table

    args = parse_args()

    raw_override = args.raw_data or args.raw_csv
    if raw_override is not None:
        raw_csv = raw_override
    elif args.dataset == "sample":
        legacy_csv = DATA_DIR / "raw_dataset_misstatement.csv"
        if (
            not RAW_DATASET_PATH.exists()
            and RAW_DATASET_PATH.suffix.lower() == ".parquet"
            and legacy_csv.exists()
        ):
            write_table(read_table(legacy_csv, low_memory=False), RAW_DATASET_PATH)
        materialize_sample_dataset(raw_csv=RAW_DATASET_PATH, out_csv=SAMPLE_DATASET_PATH)
        raw_csv = SAMPLE_DATASET_PATH
    else:
        legacy_csv = DATA_DIR / "raw_dataset_misstatement.csv"
        if (
            not RAW_DATASET_PATH.exists()
            and RAW_DATASET_PATH.suffix.lower() == ".parquet"
            and legacy_csv.exists()
        ):
            write_table(read_table(legacy_csv, low_memory=False), RAW_DATASET_PATH)
        raw_csv = RAW_DATASET_PATH

    out_dir = args.out_dir or (ARTIFACTS_DIR / f"{args.dataset}_run")

    run_data_prep(
        config_path=args.config,
        raw_csv=raw_csv,
        out_dir=out_dir,
    )


if __name__ == "__main__":
    main()
