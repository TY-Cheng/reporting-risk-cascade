"""
Run the filing-native public cascade pipeline.
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

    parser = argparse.ArgumentParser(description="Run public cascade on the public filing-native panel")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "public_cascade.yaml",
        help="Path to the public cascade YAML config",
    )
    parser.add_argument(
        "--issuer-origin-panel",
        type=Path,
        default=PROJECT_ROOT / "data" / "public_lake" / "gold" / "issuer_origin_panel.csv.gz",
        help="Issuer-level gold panel built from the public lake",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ARTIFACTS_DIR / "public_cascade",
        help="Directory for public cascade outputs",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.public_cascade import run_public_cascade

    args = parse_args()
    run_public_cascade(
        config_path=args.config,
        issuer_origin_panel_csv=args.issuer_origin_panel,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
