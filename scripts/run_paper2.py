"""
Build Paper 2 lightweight multimodal features from downloaded public data.
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

    from src import ARTIFACTS_DIR, PCAOB_DATA_DIR, SEC_DATA_DIR

    parser = argparse.ArgumentParser(description="Build Paper 2 text and monitoring features")
    parser.add_argument(
        "--master-panel",
        type=Path,
        required=True,
        help="Paper 1 master panel CSV produced by scripts/run_paper1.py",
    )
    parser.add_argument(
        "--download-manifest",
        type=Path,
        default=SEC_DATA_DIR / "filings" / "download_manifest.csv",
        help="Manifest created by scripts/fetch_public_data.py --mode sec-download",
    )
    parser.add_argument(
        "--pcaob-form-ap-csv",
        type=Path,
        default=PCAOB_DATA_DIR / "FirmFilings.csv",
        help="Extracted PCAOB Form AP CSV",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ARTIFACTS_DIR / "paper2",
        help="Directory for Paper 2 outputs",
    )
    return parser.parse_args()


def main() -> None:
    _bootstrap_repo_root()

    from src.paper2 import (
        build_paper2_dataset,
        build_paper2_readiness_report,
        build_section_feature_table,
    )

    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    section_features = build_section_feature_table(
        download_manifest_csv=args.download_manifest,
        out_dir=args.out_dir / "sections",
    )
    section_features_path = args.out_dir / "sections" / "section_features_with_embeddings.csv"

    dataset = build_paper2_dataset(
        master_panel_csv=args.master_panel,
        section_features_csv=section_features_path,
        pcaob_form_ap_csv=args.pcaob_form_ap_csv if args.pcaob_form_ap_csv.exists() else None,
        out_csv=args.out_dir / "paper2_dataset.csv.gz",
    )
    report = build_paper2_readiness_report(dataset)
    (args.out_dir / "paper2_readiness.json").write_text(json.dumps(report, indent=2))
    print(section_features.head().to_string())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
