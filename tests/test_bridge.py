from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.bridge import run_bridge_probe


def test_bridge_probe_blocks_current_raw_shape_without_identifiers(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    out_dir = tmp_path / "bridge"
    pd.DataFrame(
        {
            "gvkey": ["1", "2"],
            "data_year": [2020, 2020],
            "misstatement firm-year": [1, 0],
        }
    ).to_csv(raw_path, index=False)

    summary = run_bridge_probe(raw_csv=raw_path, out_dir=out_dir)
    summary_json = json.loads((out_dir / "bridge_probe_summary.json").read_text())
    coverage = pd.read_csv(out_dir / "coverage_report.csv")
    unmatched = pd.read_csv(out_dir / "unmatched_raw_characteristics.csv")

    assert summary["status"] == "raw_identifier_blocker"
    assert summary_json["status"] == "raw_identifier_blocker"
    assert int(coverage.loc[coverage["metric"].eq("matched_raw_rows"), "value"].iloc[0]) == 0
    assert int(unmatched["unmatched_rows"].sum()) == 2


def test_bridge_probe_reports_candidate_coverage_and_multiplicity(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    issuer_dim = tmp_path / "issuer_dim.csv.gz"
    out_dir = tmp_path / "bridge"
    pd.DataFrame(
        {
            "gvkey": ["1", "1", "2"],
            "data_year": [2020, 2021, 2020],
            "tic": ["ABC", "ABC", "XYZ"],
            "misstatement firm-year": [1, 0, 0],
        }
    ).to_csv(raw_path, index=False)
    pd.DataFrame(
        {
            "issuer_cik": ["0000000001", "0000000002", "0000000003"],
            "tickers_json": ['["ABC"]', '["ABC"]', '["QRS"]'],
            "entity_name": ["Alpha Beta Corp", "Alpha Beta Holdings", "Other Corp"],
            "sic": [1234, 1234, 9999],
        }
    ).to_csv(issuer_dim, index=False, compression="gzip")

    summary = run_bridge_probe(
        raw_csv=raw_path,
        issuer_dim_csv=issuer_dim,
        out_dir=out_dir,
    )
    candidates = pd.read_csv(out_dir / "candidate_crosswalk.csv")
    coverage = pd.read_csv(out_dir / "coverage_report.csv")
    multiplicity = pd.read_csv(out_dir / "multiplicity_report.csv")

    assert summary["status"] == "candidate_crosswalk_available"
    assert set(candidates["provenance"]) == {"public_probe"}
    assert int(coverage.loc[coverage["metric"].eq("matched_raw_rows"), "value"].iloc[0]) == 2
    raw_row_mult = multiplicity.loc[multiplicity["grain"].eq("raw_row")]
    assert raw_row_mult["candidate_count"].max() == 2
    assert summary["ambiguous_raw_rows"] == 2
