"""
Run the benchmark misstatement pipeline with repo defaults.
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

    from src import ARTIFACTS_DIR, PROJECT_ROOT

    parser = argparse.ArgumentParser(description="Run the benchmark rolling misstatement pipeline")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "benchmark.yaml",
        help="Path to the benchmark YAML config",
    )
    parser.add_argument(
        "--raw-data",
        type=Path,
        default=None,
        help="Path to the raw firm-year table",
    )
    parser.add_argument(
        "--raw-csv",
        type=Path,
        default=None,
        help="Deprecated alias for --raw-data",
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
        default=ARTIFACTS_DIR / "benchmark",
        help="Directory for benchmark outputs",
    )
    parser.add_argument(
        "--parallel-jobs",
        type=int,
        default=None,
        help="Outer rolling-task workers; defaults to config analysis.parallel_jobs",
    )
    parser.add_argument(
        "--model-threads",
        type=int,
        default=None,
        help="Threads per XGBoost fit; overrides config analysis.xgb.n_jobs",
    )
    parser.add_argument(
        "--seed-policy",
        choices=["task-isolated", "shared"],
        default=None,
        help="Random seed policy for rolling tasks; defaults to config analysis.seed_policy",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.benchmark import run_benchmark

    args = parse_args()
    from src import RAW_DATASET_PATH

    raw_data = args.raw_data or args.raw_csv or RAW_DATASET_PATH
    run_benchmark(
        config_path=args.config,
        raw_csv=raw_data,
        out_dir=args.out_dir,
        timing_csv=args.timing_csv,
        parallel_jobs=args.parallel_jobs,
        model_threads=args.model_threads,
        seed_policy=args.seed_policy.replace("-", "_") if args.seed_policy else None,
    )


if __name__ == "__main__":
    main()
