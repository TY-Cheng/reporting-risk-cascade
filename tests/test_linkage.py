from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.linkage import (
    LINKAGE_OUTPUT_COLUMNS,
    _aggregate_normalized,
    _conflict_stats,
    _date_intersection,
    _first_existing,
    _linkage_stats,
    _normalize_cik,
    _normalize_gvkey,
    _normalize_year,
    _parse_date,
    _raw_coverage,
    _raw_external_conflicts,
    _raw_key_frame,
    _raw_year_set,
    _years_from_dates,
    build_raw_primary_linkage,
    normalize_external_crosswalk,
    normalize_raw_cik_gvkey_links,
    public_overlap_outputs,
    raw_primary_external_supplement,
)
from src.table_io import write_table


def _raw_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gvkey": [100, 100, 200],
            "data_year": [2011, 2012, 2013],
            "misstatement firm-year": [1, 0, 0],
        }
    )


def _raw_links() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "link_desc": ["Valid CIK-GVKEY Link", "Link with Name Mismatch"],
            "source": ["CRSP/Compustat Merged", "Capital IQ"],
            "cik": ["0000001111", "0000003333"],
            "gvkey": ["000100", "000300"],
            "sec_start_date": ["2010-01-01", "2010-01-01"],
            "sec_end_date": ["2020-12-31", "2020-12-31"],
            "link_start_date": ["2011-01-01", "2011-01-01"],
            "link_end_date": ["2012-12-31", "2012-12-31"],
        }
    )


def _external_crosswalk() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gvkey": ["100", "200"],
            "data_year": [2011, 2013],
            "issuer_cik": ["0000009999", "0000002222"],
            "source": ["farr_gvkey_ciks", "farr_gvkey_ciks"],
            "source_version": ["farr 1.0.1", "farr 1.0.1"],
            "extracted_at": ["2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z"],
            "match_method": ["farr_gvkey_ciks_date_range", "farr_gvkey_ciks_date_range"],
            "match_score": ["", ""],
        }
    )


def test_normalize_raw_cik_gvkey_links_filters_valid_rows_and_intersects_dates() -> None:
    out = normalize_raw_cik_gvkey_links(
        _raw_links(),
        raw_data=_raw_data(),
        extracted_at="2026-05-25T00:00:00Z",
    )

    assert out[["gvkey", "data_year", "issuer_cik"]].to_dict("records") == [
        {"gvkey": "100", "data_year": 2011, "issuer_cik": "0000001111"},
        {"gvkey": "100", "data_year": 2012, "issuer_cik": "0000001111"},
    ]
    assert out["bridge_origin"].unique().tolist() == ["raw"]
    assert out["raw_link_sources"].unique().tolist() == ["CRSP/Compustat Merged"]


def test_raw_primary_external_supplement_uses_external_only_for_missing_gvkey_years() -> None:
    raw = normalize_raw_cik_gvkey_links(
        _raw_links(),
        raw_data=_raw_data(),
        extracted_at="2026-05-25T00:00:00Z",
    )
    external = normalize_external_crosswalk(_external_crosswalk(), raw_data=_raw_data())

    combined, supplement, conflicts = raw_primary_external_supplement(raw, external)

    assert combined[["gvkey", "data_year", "issuer_cik", "bridge_origin"]].to_dict(
        "records"
    ) == [
        {"gvkey": "100", "data_year": 2011, "issuer_cik": "0000001111", "bridge_origin": "raw"},
        {"gvkey": "100", "data_year": 2012, "issuer_cik": "0000001111", "bridge_origin": "raw"},
        {
            "gvkey": "200",
            "data_year": 2013,
            "issuer_cik": "0000002222",
            "bridge_origin": "external",
        },
    ]
    assert supplement[["gvkey", "data_year", "issuer_cik"]].to_dict("records") == [
        {"gvkey": "200", "data_year": 2013, "issuer_cik": "0000002222"},
    ]
    assert conflicts[["gvkey", "data_year", "raw_issuer_ciks", "external_issuer_ciks"]].to_dict(
        "records"
    ) == [
        {
            "gvkey": "100",
            "data_year": 2011,
            "raw_issuer_ciks": "0000001111",
            "external_issuer_ciks": "0000009999",
        },
    ]


def test_build_raw_primary_linkage_writes_combined_and_public_overlap(tmp_path: Path) -> None:
    raw_link_path = tmp_path / "CIK-GVKEY Link Table.csv"
    external_path = tmp_path / "gvkey_cik_year.csv"
    raw_data_path = tmp_path / "raw_dataset_misstatement.parquet"
    full_panel = tmp_path / "public_lake" / "gold" / "issuer_origin_panel.parquet"
    smoke_panel = tmp_path / "public_lake_smoke" / "gold" / "issuer_origin_panel.parquet"

    _raw_links().to_csv(raw_link_path, index=False)
    _external_crosswalk().to_csv(external_path, index=False)
    write_table(_raw_data(), raw_data_path)
    write_table(
        pd.DataFrame(
            {
                "issuer_cik": ["0000001111", "0000002222"],
                "fiscal_year": [2011, 2013],
            }
        ),
        full_panel,
    )
    write_table(
        pd.DataFrame({"issuer_cik": ["0000002222"], "fiscal_year": [2013]}),
        smoke_panel,
    )

    result = build_raw_primary_linkage(
        raw_link_path=raw_link_path,
        external_crosswalk_path=external_path,
        raw_data_path=raw_data_path,
        out_dir=tmp_path / "linkage" / "raw_primary_external_supplement",
        public_lake_panel_path=full_panel,
        public_lake_smoke_panel_path=smoke_panel,
        extracted_at="2026-05-25T00:00:00Z",
    )

    combined = pd.read_csv(result.combined_path)
    assert len(combined) == 3
    assert result.summary["raw_benchmark_coverage"]["combined_covered_rows"] == 3
    assert result.summary["raw_benchmark_coverage"]["raw_primary_covered_rows"] == 2
    assert result.summary["conflicts"]["raw_benchmark_conflict_rows"] == 1
    assert result.summary["conflicts"]["raw_benchmark_positive_conflict_rows"] == 1
    assert result.summary["public_lake"]["overlap_rows"] == 2
    assert result.summary["public_lake"]["raw_benchmark_overlap_rows"] == 2
    assert result.summary["public_lake"]["raw_benchmark_positive_overlap_rows"] == 1
    assert result.summary["public_lake_smoke"]["overlap_rows"] == 1
    assert result.summary["public_lake_smoke"]["raw_benchmark_overlap_rows"] == 1
    assert (result.out_dir / "public_lake" / "gvkey_cik_year_public_overlap.csv").exists()
    assert (result.out_dir / "public_lake_smoke" / "gvkey_cik_year_public_overlap.csv").exists()


def test_linkage_normalizers_cover_invalid_inputs_and_empty_frames(tmp_path: Path) -> None:
    assert _normalize_cik(None) is None
    assert _normalize_cik("nan") is None
    assert _normalize_cik("abc") is None
    assert _normalize_cik("0") is None
    assert _normalize_cik("CIK 42") == "0000000042"
    assert _normalize_gvkey(None) is None
    assert _normalize_gvkey("none") is None
    assert _normalize_gvkey("abc") is None
    assert _normalize_gvkey("-1") is None
    assert _normalize_gvkey("GVKEY 001234") == "1234"
    assert _normalize_year(None) is None
    assert _normalize_year("nan") is None
    assert _normalize_year("fy") is None
    assert _normalize_year("1999-10-01") == 1999
    assert _normalize_year("1700") is None
    assert _first_existing(["Issuer_CIK"], ("issuer_cik",)) == "Issuer_CIK"
    assert _parse_date(None) is None
    assert _parse_date("nat") is None
    assert _parse_date("not a date") is None

    span = _years_from_dates(
        pd.Timestamp("2010-01-01"),
        pd.Timestamp("2012-01-01"),
        raw_year_set=set(),
    )
    assert span == [2010, 2011, 2012]
    assert _raw_year_set(None) == set()
    assert _raw_key_frame(None).empty
    assert _raw_key_frame(pd.DataFrame({"gvkey": [1]})).empty
    assert _raw_key_frame(pd.DataFrame({"gvkey": [1], "data_year": [2020]}))[
        "legacy_label"
    ].tolist() == [0]
    assert _linkage_stats(pd.DataFrame()).get("rows") == 0
    assert _aggregate_normalized(pd.DataFrame()).columns.tolist() == list(LINKAGE_OUTPUT_COLUMNS)
    assert _raw_coverage(pd.DataFrame(), None)["raw_rows"] == 0
    assert _conflict_stats(pd.DataFrame(), _raw_data())["raw_benchmark_conflict_rows"] == 0
    assert _raw_external_conflicts(pd.DataFrame(), pd.DataFrame()).empty

    missing_summary = public_overlap_outputs(
        pd.DataFrame(columns=LINKAGE_OUTPUT_COLUMNS),
        issuer_origin_panel_path=tmp_path / "missing.parquet",
        out_dir=tmp_path / "missing_out",
    )
    assert missing_summary["status"] == "missing_issuer_origin_panel"


def test_normalize_raw_cik_gvkey_links_handles_options_and_bad_rows() -> None:
    links = pd.concat(
        [
            _raw_links(),
            pd.DataFrame(
                {
                    "link_desc": ["Valid CIK-GVKEY Link", "Valid CIK-GVKEY Link"],
                    "source": ["Bad", "No Date"],
                    "cik": ["bad", "0000004444"],
                    "gvkey": ["000400", "000400"],
                    "sec_start_date": ["2010-01-01", ""],
                    "sec_end_date": ["2020-12-31", ""],
                    "link_start_date": ["2011-01-01", ""],
                    "link_end_date": ["2012-12-31", ""],
                }
            ),
        ],
        ignore_index=True,
    )

    out = normalize_raw_cik_gvkey_links(
        links,
        raw_data=_raw_data(),
        include_name_mismatch=True,
        date_rule="sec_window",
        extracted_at="2026-05-25T00:00:00Z",
    )

    assert {"100", "300"}.issubset(set(out["gvkey"]))
    assert set(out.loc[out["gvkey"].eq("300"), "data_year"]) == {2011, 2012, 2013}
    assert (
        _date_intersection(pd.Series({"sec_start_date": "2020-01-01"}), date_rule="sec_window")
        is None
    )
    with pytest.raises(ValueError, match="date_rule"):
        _date_intersection(pd.Series(), date_rule="not_a_rule")

    inverted = pd.Series(
        {
            "sec_start_date": "2020-01-01",
            "sec_end_date": "2019-01-01",
        }
    )
    assert _date_intersection(inverted, date_rule="sec_window") is None

    try:
        normalize_raw_cik_gvkey_links(pd.DataFrame({"gvkey": [1]}))
    except ValueError as exc:
        assert "missing columns" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected missing raw columns to raise")


def test_normalize_external_crosswalk_handles_ranges_empty_inputs_and_errors() -> None:
    ranged = pd.DataFrame(
        {
            "GVKEY": ["000500", "bad", "000600"],
            "CIK": ["0000005555", "0000006666", "bad"],
            "start_year": [2010, 2010, 2010],
            "end_year": [2013, 2011, 2011],
        }
    )
    out = normalize_external_crosswalk(ranged, raw_data=_raw_data())

    assert out[["gvkey", "data_year", "issuer_cik"]].to_dict("records") == [
        {"gvkey": "500", "data_year": 2011, "issuer_cik": "0000005555"},
        {"gvkey": "500", "data_year": 2012, "issuer_cik": "0000005555"},
        {"gvkey": "500", "data_year": 2013, "issuer_cik": "0000005555"},
    ]
    assert normalize_external_crosswalk(pd.DataFrame()).columns.tolist() == list(
        LINKAGE_OUTPUT_COLUMNS
    )
    year_invalid = normalize_external_crosswalk(
        pd.DataFrame({"gvkey": [700], "data_year": ["unknown"], "issuer_cik": ["0000007777"]})
    )
    assert year_invalid.empty

    for frame, message in [
        (pd.DataFrame({"issuer_cik": [1], "data_year": [2020]}), "gvkey"),
        (pd.DataFrame({"gvkey": [1], "data_year": [2020]}), "issuer_cik"),
        (pd.DataFrame({"gvkey": [1], "issuer_cik": [1]}), "data_year"),
    ]:
        try:
            normalize_external_crosswalk(frame)
        except ValueError as exc:
            assert message in str(exc)
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("expected malformed external crosswalk to raise")


def test_public_overlap_outputs_available_without_raw_data(tmp_path: Path) -> None:
    combined = normalize_external_crosswalk(
        pd.DataFrame({"gvkey": [10], "data_year": [2020], "issuer_cik": ["0000000010"]})
    )
    panel = tmp_path / "issuer_origin_panel.parquet"
    write_table(pd.DataFrame({"issuer_cik": ["0000000010"], "fiscal_year": [2020]}), panel)

    summary = public_overlap_outputs(
        combined,
        issuer_origin_panel_path=panel,
        out_dir=tmp_path / "overlap",
    )

    assert summary["overlap_rows"] == 1
    assert summary["raw_benchmark_rows"] == 0
    assert (tmp_path / "overlap" / "coverage_summary.json").exists()
