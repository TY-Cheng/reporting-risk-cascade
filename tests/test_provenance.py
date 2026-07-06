from __future__ import annotations

from pathlib import Path

from src.provenance import input_provenance, wrds_export_metadata


def test_wrds_export_metadata_summarizes_crosswalk_source(tmp_path: Path) -> None:
    crosswalk = tmp_path / "gvkey_cik_year.csv"
    crosswalk.write_text(
        "\n".join(
            [
                "gvkey,data_year,issuer_cik,source,source_version,extracted_at,match_method",
                "001000,2020,0000000001,wrds_sec_analytics_cik_gvkey:compustat_company,"
                "WRDS SEC Analytics Suite / CIK-GVKEY Link Table.csv,"
                "2026-05-25T00:00:00Z,wrds_sec_analytics_cik_gvkey_intersection",
            ]
        ),
        encoding="utf-8",
    )

    metadata = wrds_export_metadata(crosswalk)
    inputs = input_provenance([crosswalk])

    assert metadata["row_count"] == 1
    assert metadata["wrds_detected"] is True
    assert metadata["source_version_values"] == [
        "WRDS SEC Analytics Suite / CIK-GVKEY Link Table.csv"
    ]
    assert metadata["sha256"] == inputs["input_files"][0]["sha256"]
    assert inputs["input_hash"]
