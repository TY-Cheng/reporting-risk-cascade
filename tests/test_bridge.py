from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.bridge import (
    _external_crosswalk_candidates,
    _external_crosswalk_frame,
    _first_existing,
    _normalize_cik,
    _normalize_gvkey,
    _normalize_name,
    _normalize_ticker,
    _normalize_year,
    _parse_tickers,
    _public_identifier_frame,
    _read_table_if_exists,
    _unmatched_raw_characteristics,
    prepare_gvkey_cik_crosswalk,
    run_bridge_probe,
)
from src.table_io import write_table


def test_bridge_identifier_normalizers_cover_messy_public_values() -> None:
    assert _first_existing(["CiK"], ["cik"]) == "CiK"
    assert _first_existing(["other"], ["cik"]) is None
    assert _normalize_cik(None) is None
    assert _normalize_cik("nan") is None
    assert _normalize_cik("CIK 123") == "0000000123"
    assert _normalize_cik("not available") is None
    assert _normalize_cik("0") is None

    assert _normalize_gvkey("001004") == "1004"
    assert _normalize_gvkey("1004.0") == "1004"
    assert _normalize_gvkey(None) is None
    assert _normalize_gvkey("nan") is None
    assert _normalize_gvkey("missing") is None
    assert _normalize_gvkey("-1") is None
    assert _normalize_year("2020.0") == 2020
    assert _normalize_year("2020-12-31") == 2020
    assert _normalize_year(None) is None
    assert _normalize_year("nan") is None
    assert _normalize_year("20") is None
    assert _normalize_year("99999") is None

    assert _normalize_ticker(None) is None
    assert _normalize_ticker(" none ") is None
    assert _normalize_ticker("brk.b") == "BRK-B"

    assert _normalize_name(None) is None
    assert _normalize_name(" nan ") is None
    assert _normalize_name("  Acme   Incorporated ") == "ACME"

    assert _parse_tickers(None) == []
    assert _parse_tickers(["abc", None, "brk.b"]) == ["ABC", "BRK-B"]
    assert _parse_tickers(float("nan")) == []
    assert _parse_tickers("[]") == []
    assert _parse_tickers("abc; brk.b") == ["ABC", "BRK-B"]


def test_bridge_public_identifier_blockers_and_missing_file_reader(tmp_path: Path) -> None:
    assert _read_table_if_exists(None).empty
    assert _read_table_if_exists(tmp_path / "missing.csv").empty
    assert _public_identifier_frame(pd.DataFrame()).empty
    assert _public_identifier_frame(pd.DataFrame({"ticker": ["ABC"]})).empty
    assert _public_identifier_frame(pd.DataFrame({"issuer_cik": ["nan"]})).empty

    public_ids = _public_identifier_frame(
        pd.DataFrame(
            {
                "CIK": ["1", "2"],
                "tickers": ["ABC, DEF", "[]"],
                "name": ["Alpha Corp", "Beta Limited"],
                "sic": [1234, 5678],
            }
        )
    )
    assert set(public_ids["match_type"]) == {"cik", "ticker", "name"}
    assert "ALPHA" in set(public_ids["match_value"])


def test_bridge_unmatched_characteristics_empty_and_missing_year_branches() -> None:
    empty = _unmatched_raw_characteristics(
        pd.DataFrame(),
        pd.DataFrame(),
        year_col="data_year",
        target_col="target",
    )
    assert list(empty.columns) == ["data_year", "unmatched_rows", "unmatched_positive_rate"]

    all_matched = _unmatched_raw_characteristics(
        pd.DataFrame({"data_year": [2020], "target": [1]}),
        pd.DataFrame({"raw_row_id": [0]}),
        year_col="data_year",
        target_col="target",
    )
    assert all_matched.empty

    no_year = _unmatched_raw_characteristics(
        pd.DataFrame({"target": [1, 0]}),
        pd.DataFrame({"raw_row_id": [0]}),
        year_col="data_year",
        target_col="target",
    )
    assert no_year.to_dict("records") == [
        {"data_year": "", "unmatched_rows": 1, "unmatched_positive_rate": 0.0}
    ]


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

    summary = run_bridge_probe(raw_data_path=raw_path, out_dir=out_dir)
    summary_json = json.loads((out_dir / "bridge_probe_summary.json").read_text())
    coverage = pd.read_csv(out_dir / "coverage_report.csv")
    unmatched = pd.read_csv(out_dir / "unmatched_raw_characteristics.csv")

    assert summary["status"] == "raw_identifier_blocker"
    assert summary_json["status"] == "raw_identifier_blocker"
    assert int(coverage.loc[coverage["metric"].eq("matched_raw_rows"), "value"].iloc[0]) == 0
    assert int(unmatched["unmatched_rows"].sum()) == 2


def test_prepare_gvkey_cik_crosswalk_expands_ranges_and_filters_to_raw_years(
    tmp_path: Path,
) -> None:
    source = tmp_path / "wrds_link.csv"
    raw_path = tmp_path / "raw.parquet"
    out_path = tmp_path / "gvkey_cik_year.csv"
    pd.DataFrame(
        {
            "GVKEY": ["001004", "002000", "bad"],
            "CIK": ["320193.0", "789019", "not available"],
            "start_year": [2019, 2018, 2019],
            "end_year": [2021, 2019, 2020],
        }
    ).to_csv(source, index=False)
    write_table(
        pd.DataFrame(
            {
                "gvkey": [1004, 1004, 2000],
                "data_year": [2020, 2021, 2020],
                "misstatement firm-year": [0, 1, 0],
            }
        ),
        raw_path,
    )

    summary = prepare_gvkey_cik_crosswalk(
        input_path=source,
        output_path=out_path,
        raw_data_path=raw_path,
        source="wrds",
        source_version="test",
        extracted_at="2026-04-25T00:00:00+00:00",
        match_method="wrds_link",
    )
    output = pd.read_csv(out_path, dtype={"issuer_cik": str, "gvkey": str})

    assert summary["output_rows"] == 2
    assert output[["gvkey", "data_year", "issuer_cik"]].to_dict("records") == [
        {"gvkey": "1004", "data_year": 2020, "issuer_cik": "0000320193"},
        {"gvkey": "1004", "data_year": 2021, "issuer_cik": "0000320193"},
    ]
    assert set(output["source"]) == {"wrds"}


def test_bridge_probe_uses_external_crosswalk_without_raw_identifiers(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    crosswalk_path = tmp_path / "gvkey_cik_year.csv"
    origin_panel_path = tmp_path / "issuer_origin_panel.parquet"
    out_dir = tmp_path / "bridge"
    pd.DataFrame(
        {
            "gvkey": [1004, 1004, 2000],
            "data_year": [2020, 2021, 2020],
            "misstatement firm-year": [1, 0, 0],
        }
    ).to_csv(raw_path, index=False)
    pd.DataFrame(
        {
            "gvkey": ["001004", "002000"],
            "issuer_cik": ["320193", "789019"],
            "start_year": [2020, 2020],
            "end_year": [2021, 2020],
            "source": ["wrds", "wrds"],
            "match_method": ["wrds_link", "wrds_link"],
        }
    ).to_csv(crosswalk_path, index=False)
    write_table(
        pd.DataFrame(
            {
                "issuer_cik": ["0000320193", "0000789019"],
                "fiscal_year": [2020, 2020],
            }
        ),
        origin_panel_path,
    )

    summary = run_bridge_probe(
        raw_data_path=raw_path,
        crosswalk_path=crosswalk_path,
        issuer_origin_panel_path=origin_panel_path,
        out_dir=out_dir,
    )
    candidates = pd.read_csv(out_dir / "candidate_crosswalk.csv", dtype={"issuer_cik": str})
    coverage = pd.read_csv(out_dir / "coverage_report.csv")

    assert summary["status"] == "external_crosswalk_available"
    assert summary["candidate_source"] == "external_crosswalk"
    assert summary["candidate_crosswalk_rows"] == 3
    assert summary["public_rows"] == 2
    assert summary["public_overlap_raw_rows"] == 2
    assert set(candidates["provenance"]) == {"wrds"}
    assert int(coverage.loc[coverage["metric"].eq("matched_raw_rows"), "value"].iloc[0]) == 3


def test_bridge_probe_reports_external_crosswalk_no_matches(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    crosswalk_path = tmp_path / "gvkey_cik_year.csv"
    out_dir = tmp_path / "bridge"
    pd.DataFrame(
        {
            "gvkey": [1004],
            "data_year": [2020],
            "misstatement firm-year": [1],
        }
    ).to_csv(raw_path, index=False)
    pd.DataFrame(
        {
            "gvkey": ["999999"],
            "issuer_cik": ["320193"],
            "data_year": [2020],
        }
    ).to_csv(crosswalk_path, index=False)

    summary = run_bridge_probe(
        raw_data_path=raw_path,
        crosswalk_path=crosswalk_path,
        out_dir=out_dir,
    )
    candidates = pd.read_csv(out_dir / "candidate_crosswalk.csv")

    assert summary["status"] == "external_crosswalk_no_matches"
    assert summary["candidate_crosswalk_rows"] == 0
    assert candidates.empty


def test_external_crosswalk_validation_and_empty_candidate_edges(tmp_path: Path) -> None:
    raw = pd.DataFrame({"gvkey": [1004], "data_year": [2020]})
    valid = pd.DataFrame({"gvkey": ["001004"], "issuer_cik": ["320193"], "data_year": [2020]})

    candidates = _external_crosswalk_candidates(
        raw,
        valid,
        firm_col="gvkey",
        year_col="data_year",
        target_col="missing_target",
    )
    assert candidates["missing_target"].isna().all()

    assert _external_crosswalk_candidates(
        pd.DataFrame({"gvkey": ["bad"], "data_year": ["bad"]}),
        valid,
        firm_col="gvkey",
        year_col="data_year",
        target_col="target",
    ).empty
    assert _external_crosswalk_candidates(
        raw,
        pd.DataFrame({"gvkey": ["bad"], "issuer_cik": ["bad"], "data_year": [2020]}),
        firm_col="gvkey",
        year_col="data_year",
        target_col="target",
    ).empty
    assert _external_crosswalk_frame(
        pd.DataFrame({"gvkey": ["001004"], "issuer_cik": ["320193"], "data_year": ["bad"]}),
        raw=raw,
    ).empty
    assert _external_crosswalk_frame(
        pd.DataFrame({"gvkey": ["001004"], "issuer_cik": ["320193"], "start_year": [2021], "end_year": [2020]}),
        raw=raw,
    ).empty
    assert _external_crosswalk_frame(
        pd.DataFrame({"gvkey": ["001004"], "issuer_cik": ["320193"], "start_year": ["bad"], "end_year": [2020]}),
        raw=raw,
    ).empty

    with pytest.raises(ValueError, match="missing a gvkey"):
        _external_crosswalk_frame(pd.DataFrame({"issuer_cik": ["320193"], "data_year": [2020]}))
    with pytest.raises(ValueError, match="missing an issuer_cik"):
        _external_crosswalk_frame(pd.DataFrame({"gvkey": ["001004"], "data_year": [2020]}))
    with pytest.raises(ValueError, match="start_year/end_year"):
        _external_crosswalk_frame(pd.DataFrame({"gvkey": ["001004"], "issuer_cik": ["320193"]}))

    out_dir = tmp_path / "bridge"
    with pytest.raises(ValueError, match="raw_data_path is required"):
        run_bridge_probe(out_dir=out_dir)


def test_bridge_probe_blocks_when_public_identifiers_are_unavailable(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    out_dir = tmp_path / "bridge"
    pd.DataFrame(
        {
            "gvkey": ["1"],
            "data_year": [2020],
            "cik": ["0000000001"],
            "misstatement firm-year": [1],
        }
    ).to_csv(raw_path, index=False)

    summary = run_bridge_probe(raw_data_path=raw_path, out_dir=out_dir)

    assert summary["status"] == "public_identifier_blocker"
    assert summary["public_rows"] == 0
    assert summary["raw_identifier_columns"]["cik"] == "cik"


def test_bridge_probe_blocks_when_identifier_columns_have_no_usable_values(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    issuer_dim = tmp_path / "issuer_dim.parquet"
    out_dir = tmp_path / "bridge"
    pd.DataFrame(
        {
            "gvkey": ["1"],
            "data_year": [2020],
            "cik": ["not available"],
            "tic": ["none"],
            "conm": ["nan"],
            "misstatement firm-year": [1],
        }
    ).to_csv(raw_path, index=False)
    write_table(pd.DataFrame({"issuer_cik": ["0000000001"], "ticker": ["ABC"]}), issuer_dim)

    summary = run_bridge_probe(raw_data_path=raw_path, issuer_dim_path=issuer_dim, out_dir=out_dir)

    assert summary["status"] == "raw_identifier_blocker"
    assert "contain no usable values" in summary["blocker"]


def test_bridge_probe_uses_origin_panel_fallback_and_reports_no_matches(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    origin_panel = tmp_path / "issuer_origin_panel.parquet"
    out_dir = tmp_path / "bridge"
    pd.DataFrame(
        {
            "gvkey": ["1"],
            "data_year": [2020],
            "CIK": ["0000000099"],
            "company_name": ["Unmatched Incorporated"],
            "misstatement firm-year": [1],
        }
    ).to_csv(raw_path, index=False)
    write_table(
        pd.DataFrame(
            {
                "issuer_cik": ["0000000001"],
                "ticker": ["ABC"],
                "entity_name": ["Alpha Corp"],
            }
        ),
        origin_panel,
    )

    summary = run_bridge_probe(
        raw_data_path=raw_path,
        issuer_origin_panel_path=origin_panel,
        out_dir=out_dir,
    )
    candidates = pd.read_csv(out_dir / "candidate_crosswalk.csv")

    assert summary["status"] == "no_candidate_matches"
    assert candidates.empty


def test_bridge_probe_reports_candidate_coverage_and_multiplicity(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    issuer_dim = tmp_path / "issuer_dim.parquet"
    out_dir = tmp_path / "bridge"
    pd.DataFrame(
        {
            "gvkey": ["1", "1", "2"],
            "data_year": [2020, 2021, 2020],
            "tic": ["ABC", "ABC", "XYZ"],
            "misstatement firm-year": [1, 0, 0],
        }
    ).to_csv(raw_path, index=False)
    write_table(
        pd.DataFrame(
            {
                "issuer_cik": ["0000000001", "0000000002", "0000000003"],
                "tickers_json": ['["ABC"]', '["ABC"]', '["QRS"]'],
                "entity_name": ["Alpha Beta Corp", "Alpha Beta Holdings", "Other Corp"],
                "sic": [1234, 1234, 9999],
            }
        ),
        issuer_dim,
    )

    summary = run_bridge_probe(
        raw_data_path=raw_path,
        issuer_dim_path=issuer_dim,
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
