from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

import src.public_lake as public_lake
from src.public_lake import (
    DagTask,
    SimpleDagRunner,
    _duckdb_connect,
    _duckdb_sec_date_expr,
    _event_within_horizon,
    _normalize_fsds_manifest_parquet,
    _write_metadata,
    build_gold_panels,
    build_public_lake,
    build_xbrl_core_features,
    fetch_source_assets,
    normalize_aaer_events,
    normalize_fsds_archive,
    normalize_notes_archive,
)
from src.table_io import read_table, write_table


def _write_csv_gz(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, compression="gzip")


def _write_submissions_zip(path: Path) -> None:
    payload = {
        "cik": "1",
        "name": "Alpha Beta Corp",
        "sic": "1234",
        "sicDescription": "Test SIC",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000001-22-000001"],
                "filingDate": ["2022-03-01"],
                "reportDate": ["2021-12-31"],
                "acceptanceDateTime": ["2022-03-01T10:00:00.000Z"],
                "act": ["34"],
                "form": ["10-K"],
                "fileNumber": ["001-00001"],
                "filmNumber": ["221111"],
                "items": [""],
                "size": [100],
                "isXBRL": [1],
                "isInlineXBRL": [1],
                "primaryDocument": ["alpha-20211231.htm"],
                "primaryDocDescription": ["10-K"],
            }
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("CIK0000000001.json", json.dumps(payload))


def _write_fsds_zip(path: Path, adsh: str, tag: str, *, ddate: object = "20211231") -> None:
    sub = pd.DataFrame(
        [
            {
                "adsh": adsh,
                "cik": 1,
                "name": "Alpha Beta Corp",
                "sic": 1234,
                "countryba": "US",
                "stprba": "CA",
                "form": "10-K",
                "period": "20211231",
                "filed": "20220301",
                "accepted": "2022-03-01 10:00:00",
                "fy": 2021,
                "fp": "FY",
            }
        ]
    )
    num = pd.DataFrame(
        [
            {
                "adsh": adsh,
                "tag": tag,
                "version": "us-gaap/2021",
                "ddate": ddate,
                "qtrs": 4,
                "uom": "USD",
                "value": 1.0,
                "coreg": "",
                "footnote": "",
            }
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("sub.txt", sub.to_csv(sep="\t", index=False))
        zf.writestr("num.txt", num.to_csv(sep="\t", index=False))


def _write_notes_zip(path: Path, adsh: str, tag: str, *, ddate: object = "20211231") -> None:
    txt = pd.DataFrame(
        [
            {
                "adsh": adsh,
                "tag": tag,
                "version": "us-gaap/2021",
                "ddate": ddate,
                "qtrs": 4,
                "txt": f"Note text for {tag}",
            }
        ]
    )
    sub = pd.DataFrame([{"adsh": adsh, "cik": 1, "form": "10-K"}])
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("txt.txt", txt.to_csv(sep="\t", index=False))
        zf.writestr("sub.txt", sub.to_csv(sep="\t", index=False))


def test_event_within_horizon_strictly_after_origin_and_matches_reference() -> None:
    base = pd.DataFrame(
        {
            "issuer_cik": ["0000000001", "0000000001", "0000000001", "0000000002"],
            "origin_date": pd.to_datetime(
                ["2020-01-01", "2020-01-02", "2020-01-10", "2020-01-01"]
            ),
        },
        index=[10, 11, 12, 13],
    )
    events = pd.DataFrame(
        {
            "issuer_cik": ["0000000001", "0000000001", "0000000002"],
            "event_date": pd.to_datetime(["2020-01-01", "2020-01-03", "2020-02-15"]),
        }
    )

    result = _event_within_horizon(
        base,
        events,
        date_col="event_date",
        horizon_days=7,
    )

    expected = pd.Series([1, 1, 0, 0], index=base.index)
    pd.testing.assert_series_equal(result, expected)


def test_duckdb_connection_applies_resource_guards(tmp_path: Path) -> None:
    temp_dir = tmp_path / "duckdb_tmp"
    con = _duckdb_connect(
        threads=1,
        memory_limit="64MB",
        temp_directory=temp_dir,
        max_temp_directory_size="1GB",
    )
    try:
        assert con.execute("SELECT current_setting('threads')").fetchone()[0] == 1
        assert "MiB" in con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
        assert con.execute("SELECT current_setting('temp_directory')").fetchone()[0] == str(
            temp_dir
        )
        assert (
            "MiB" in con.execute("SELECT current_setting('max_temp_directory_size')").fetchone()[0]
        )
    finally:
        con.close()
    assert temp_dir.exists()


def test_duckdb_sec_date_expr_parses_decimal_suffix_dates() -> None:
    con = _duckdb_connect(threads=1)
    try:
        rows = con.execute(
            f"""
            SELECT 'compact' AS case_name, {_duckdb_sec_date_expr("'20111231'")} AS parsed
            UNION ALL
            SELECT 'decimal_string' AS case_name, {_duckdb_sec_date_expr("'20111231.0'")} AS parsed
            UNION ALL
            SELECT 'double_numeric' AS case_name,
                {_duckdb_sec_date_expr("CAST(20111231.0 AS DOUBLE)")} AS parsed
            UNION ALL
            SELECT 'decimal_numeric' AS case_name,
                {_duckdb_sec_date_expr("CAST(20111231.0 AS DECIMAL(9,1))")} AS parsed
            UNION ALL
            SELECT 'bad' AS case_name, {_duckdb_sec_date_expr("'bad'")} AS parsed
            """
        ).fetchdf()
    finally:
        con.close()

    parsed = rows.set_index("case_name")["parsed"]
    assert pd.Timestamp(parsed.loc["compact"]).date().isoformat() == "2011-12-31"
    assert pd.Timestamp(parsed.loc["decimal_string"]).date().isoformat() == "2011-12-31"
    assert pd.Timestamp(parsed.loc["double_numeric"]).date().isoformat() == "2011-12-31"
    assert pd.Timestamp(parsed.loc["decimal_numeric"]).date().isoformat() == "2011-12-31"
    assert pd.isna(parsed.loc["bad"])


def test_build_public_lake_writes_parquet_fsds_and_notes_summary(tmp_path: Path) -> None:
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    _write_submissions_zip(bronze / "sec-bulk" / "submissions.zip")

    fsds_paths = [
        bronze / "fsds" / "fsds_1.zip",
        bronze / "fsds" / "fsds_2.zip",
        bronze / "fsds" / "fsds_3.zip",
    ]
    _write_fsds_zip(fsds_paths[0], "0000000001-22-000001", "Assets", ddate="20211231.0")
    _write_fsds_zip(fsds_paths[1], "0000000001-22-000002", "Liabilities")
    _write_fsds_zip(fsds_paths[2], "0000000001-22-000003", "EntityRegistrantName")
    pd.DataFrame({"local_path": [str(path) for path in fsds_paths]}).to_csv(
        bronze / "fsds" / "manifest.csv", index=False
    )

    note_paths = [bronze / "notes" / "notes_1.zip", bronze / "notes" / "notes_2.zip"]
    _write_notes_zip(note_paths[0], "0000000001-22-000001", "DebtTextBlock")
    _write_notes_zip(note_paths[1], "0000000001-22-000002", "TaxTextBlock")
    pd.DataFrame({"local_path": [str(path) for path in note_paths]}).to_csv(
        bronze / "notes" / "manifest.csv", index=False
    )
    (bronze / "pcaob-inspections").mkdir(parents=True)
    pd.DataFrame(
        {
            "local_path": [str(bronze / "pcaob-inspections" / "listed-only.json")],
            "status": ["listed"],
        }
    ).to_csv(bronze / "pcaob-inspections" / "manifest.csv", index=False)

    build_public_lake(
        bronze_dir=bronze,
        silver_dir=silver,
        gold_dir=gold,
        as_of_date="2026-04-23",
        fsds_batch_size=2,
        notes_batch_size=1,
    )

    xbrl_summary = read_table(silver / "xbrl_fact_summary.parquet")
    xbrl_core = read_table(silver / "xbrl_core_fact")
    note_summary = read_table(silver / "note_summary.parquet")
    assert (silver / "issuer_dim.parquet").exists()
    assert (silver / "filing_dim.parquet").exists()
    assert (gold / "issuer_origin_panel.parquet").exists()
    assert (gold / "filing_origin_panel.parquet").exists()
    assert not (silver / "issuer_dim.csv.gz").exists()
    assert not (silver / "filing_dim.csv.gz").exists()
    assert not (gold / "issuer_origin_panel.csv.gz").exists()
    assert not (gold / "filing_origin_panel.csv.gz").exists()
    assert int(xbrl_summary["xbrl_fact_count"].sum()) == 3
    assert set(xbrl_core["tag"]) == {"Assets", "Liabilities"}
    assets_row = xbrl_core.loc[xbrl_core["tag"].eq("Assets")].iloc[0]
    assert pd.Timestamp(assets_row["fact_date"]).date().isoformat() == "2021-12-31"
    assert int(assets_row["source_year"]) == 2021
    assert int(note_summary["note_text_count"].sum()) == 2
    assert not (silver / "xbrl_fact.csv.gz").exists()
    assert not (silver / "note_text.csv.gz").exists()
    assert not (silver / "note_text").exists()
    assert not (silver / "._staging_fsds").exists()
    assert not (silver / "._staging_notes").exists()
    fsds_markers = sorted((silver / ".public_lake_dag" / "normalize_fsds_batches").glob("*.json"))
    notes_markers = sorted(
        (silver / ".public_lake_dag" / "normalize_notes_batches").glob("*.json")
    )
    assert len(fsds_markers) == 2
    assert len(notes_markers) == 2
    run_metadata = json.loads((silver / "public_lake_run_metadata.json").read_text())
    assert run_metadata["duckdb_temp_directory"] == str(silver / "._duckdb_tmp")
    assert all("source_year=" not in str(path) for path in (silver / "xbrl_core_fact").rglob("*"))


def test_fsds_parquet_batch_resume_skips_completed_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    fsds_paths = [bronze / "fsds_1.zip", bronze / "fsds_2.zip"]
    _write_fsds_zip(fsds_paths[0], "0000000001-22-000001", "Assets")
    _write_fsds_zip(fsds_paths[1], "0000000001-22-000002", "Liabilities")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame({"local_path": [str(path) for path in fsds_paths]}).to_csv(manifest, index=False)

    original_extract = public_lake._extract_archive_members_batch

    def fail_second_batch(*args: object, **kwargs: object) -> dict[str, list[Path]]:
        archive_paths = kwargs["archive_paths"]
        if Path(archive_paths[0]).name == "fsds_2.zip":
            raise RuntimeError("planned second batch failure")
        return original_extract(*args, **kwargs)

    monkeypatch.setattr(public_lake, "_extract_archive_members_batch", fail_second_batch)
    with pytest.raises(RuntimeError, match="planned second batch failure"):
        _normalize_fsds_manifest_parquet(
            manifest_csv=manifest,
            silver_dir=silver,
            duckdb_threads=1,
            batch_size=1,
            resume=False,
        )

    first_marker = silver / ".public_lake_dag" / "normalize_fsds_batches" / "batch_0000.done.json"
    assert first_marker.exists()

    resumed_archives: list[str] = []

    def count_resumed_batches(*args: object, **kwargs: object) -> dict[str, list[Path]]:
        archive_paths = kwargs["archive_paths"]
        resumed_archives.extend(Path(path).name for path in archive_paths)
        return original_extract(*args, **kwargs)

    monkeypatch.setattr(public_lake, "_extract_archive_members_batch", count_resumed_batches)
    outputs = _normalize_fsds_manifest_parquet(
        manifest_csv=manifest,
        silver_dir=silver,
        duckdb_threads=1,
        batch_size=1,
        resume=True,
    )

    assert resumed_archives == ["fsds_2.zip"]
    assert outputs["xbrl_fact_summary"].exists()
    xbrl_summary = read_table(outputs["xbrl_fact_summary"])
    assert int(xbrl_summary["xbrl_fact_count"].sum()) == 2


def test_notes_raw_mode_writes_note_text_parquet_dataset(tmp_path: Path) -> None:
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    _write_submissions_zip(bronze / "sec-bulk" / "submissions.zip")
    note_path = bronze / "notes" / "notes_1.zip"
    _write_notes_zip(note_path, "0000000001-22-000001", "DebtTextBlock", ddate="20211231.0")
    pd.DataFrame({"local_path": [str(note_path)]}).to_csv(
        bronze / "notes" / "manifest.csv", index=False
    )

    build_public_lake(
        bronze_dir=bronze,
        silver_dir=silver,
        gold_dir=gold,
        as_of_date="2026-04-23",
        notes_mode="raw",
        notes_batch_size=1,
    )

    note_text = read_table(silver / "note_text")
    assert set(note_text["tag"]) == {"DebtTextBlock"}
    assert "note_text" in note_text.columns
    note_row = note_text.iloc[0]
    assert pd.Timestamp(note_row["fact_date"]).date().isoformat() == "2021-12-31"
    assert int(note_row["source_year"]) == 2021
    assert all("source_year=" not in str(path) for path in (silver / "note_text").rglob("*"))


def test_legacy_archive_normalizers_parse_decimal_suffix_dates(tmp_path: Path) -> None:
    fsds_zip = tmp_path / "fsds.zip"
    notes_zip = tmp_path / "notes.zip"
    _write_fsds_zip(fsds_zip, "0000000001-22-000001", "Assets", ddate="20111231.0")
    _write_notes_zip(notes_zip, "0000000001-22-000001", "DebtTextBlock", ddate="20111231.0")

    fsds_pandas = normalize_fsds_archive(
        archive_path=fsds_zip,
        silver_dir=tmp_path / "fsds_pandas",
        engine="pandas",
    )
    fsds_duckdb = normalize_fsds_archive(
        archive_path=fsds_zip,
        silver_dir=tmp_path / "fsds_duckdb",
        engine="duckdb",
        duckdb_threads=1,
    )
    notes_pandas = normalize_notes_archive(
        archive_path=notes_zip,
        silver_dir=tmp_path / "notes_pandas",
        engine="pandas",
    )
    notes_duckdb = normalize_notes_archive(
        archive_path=notes_zip,
        silver_dir=tmp_path / "notes_duckdb",
        engine="duckdb",
        duckdb_threads=1,
    )

    for path, date_col in [
        (fsds_pandas["xbrl_fact"], "fact_date"),
        (fsds_duckdb["xbrl_fact"], "fact_date"),
        (notes_pandas["note_text"], "fact_date"),
        (notes_duckdb["note_text"], "fact_date"),
    ]:
        frame = read_table(path)
        parsed = pd.to_datetime(frame.loc[0, date_col], errors="coerce")
        assert parsed.date().isoformat() == "2011-12-31"


def test_xbrl_core_features_build_stable_ratios_and_safe_denominators() -> None:
    facts = pd.DataFrame(
        [
            {
                "adsh": "a-annual",
                "tag": "Assets",
                "unit": "USD",
                "value": 100.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
            {
                "adsh": "a-annual",
                "tag": "Liabilities",
                "unit": "USD",
                "value": 40.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
            {
                "adsh": "a-annual",
                "tag": "Revenues",
                "unit": "USD",
                "value": 200.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
            {
                "adsh": "a-annual",
                "tag": "NetIncomeLoss",
                "unit": "USD",
                "value": 10.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
            {
                "adsh": "a-annual",
                "tag": "AccountsReceivableNetCurrent",
                "unit": "USD",
                "value": 50.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
            {
                "adsh": "zero-denom",
                "tag": "Assets",
                "unit": "USD",
                "value": 0.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
            {
                "adsh": "zero-denom",
                "tag": "Liabilities",
                "unit": "USD",
                "value": 1.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
        ]
    )

    features = build_xbrl_core_features(facts).set_index("accession")

    assert features.loc["a-annual", "xbrl_coverage_assets"] == 1
    assert features.loc["a-annual", "xbrl_coverage_revenues"] == 1
    assert features.loc["a-annual", "xbrl_ratio_leverage"] == 0.4
    assert features.loc["a-annual", "xbrl_ratio_profitability"] == 0.1
    assert features.loc["a-annual", "xbrl_ratio_receivables_to_revenue"] == 0.25
    assert pd.isna(features.loc["zero-denom", "xbrl_ratio_leverage"])


def test_fetch_source_assets_uses_cached_files_without_force(
    tmp_path: Path, monkeypatch: object
) -> None:
    bronze = tmp_path / "bronze"
    source_dir = bronze / "sec-bulk"
    source_dir.mkdir(parents=True)
    cached_files = {
        "submissions.zip": "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip",
        "companyfacts.zip": "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
    }
    for basename, url in cached_files.items():
        path = source_dir / basename
        path.write_bytes(b"cached")
        _write_metadata(path=path, source_url=url, source_name="sec-bulk")

    def fail_download(*args: object, **kwargs: object) -> None:
        raise AssertionError("cached source should not be downloaded")

    monkeypatch.setattr("src.public_lake._download_file", fail_download)
    manifest = fetch_source_assets(mode="sec-bulk", bronze_dir=bronze)

    assert set(manifest["status"]) == {"cached"}


def test_aaer_matching_uses_strict_token_overlap(tmp_path: Path) -> None:
    bronze = tmp_path / "bronze" / "aaer"
    silver = tmp_path / "silver"
    bronze.mkdir(parents=True)
    (bronze / "aaer_listing.html").write_text(
        """
        <time datetime="2022-01-01">Jan 1</time>
        <a href="/enforcement/accounting-auditing-enforcement-releases/aaer-1">
        In the Matter of Apple Hospitality REIT Inc.</a>
        <time datetime="2022-01-02">Jan 2</time>
        <a href="/enforcement/accounting-auditing-enforcement-releases/aaer-2">
        In the Matter of Alpha Beta Corporation</a>
        """,
        encoding="utf-8",
    )
    issuer_dim = tmp_path / "issuer_dim.parquet"
    write_table(
        pd.DataFrame(
            [
                {"issuer_cik": "0000000001", "entity_name": "Apple Inc."},
                {"issuer_cik": "0000000002", "entity_name": "Alpha Beta Corp"},
            ]
        ),
        issuer_dim,
    )

    out = normalize_aaer_events(
        aaer_bronze_dir=bronze,
        silver_dir=silver,
        issuer_dim_path=issuer_dim,
    )
    aaer = pd.read_csv(out)

    apple_row = aaer.loc[aaer["release_title"].str.contains("Apple Hospitality", na=False)].iloc[0]
    alpha_row = aaer.loc[aaer["release_title"].str.contains("Alpha Beta", na=False)].iloc[0]
    assert pd.isna(apple_row["issuer_cik"]) or str(apple_row["issuer_cik"]) in {"", "nan"}
    assert str(int(pd.to_numeric(alpha_row["issuer_cik"]))).zfill(10) == "0000000002"
    assert alpha_row["aaer_match_method"] == "token_all"


def test_gold_panel_period_semantics_annual_priority_and_fpi_year_state(tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "0000000001",
                    "entity_name": "Alpha Beta Corp",
                    "sic": 1234,
                    "sic_description": "A",
                    "entity_type": "operating",
                },
                {
                    "issuer_cik": "0000000002",
                    "entity_name": "Gamma Delta Corp",
                    "sic": 5678,
                    "sic_description": "B",
                    "entity_type": "operating",
                },
            ]
        ),
        silver / "issuer_dim.parquet",
    )
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "0000000001",
                    "accession": "a-amend",
                    "accession_nodash": "aamend",
                    "filing_date": "2022-02-01",
                    "report_date": "2021-12-31",
                    "acceptance_datetime": "2022-02-01",
                    "form": "10-K/A",
                    "items": "",
                    "primary_document": "a.htm",
                },
                {
                    "issuer_cik": "0000000001",
                    "accession": "a-annual",
                    "accession_nodash": "aannual",
                    "filing_date": "2022-03-01",
                    "report_date": "2021-12-31",
                    "acceptance_datetime": "2022-03-01",
                    "form": "10-K",
                    "items": "",
                    "primary_document": "b.htm",
                },
                {
                    "issuer_cik": "0000000001",
                    "accession": "a-8k",
                    "accession_nodash": "a8k",
                    "filing_date": "2022-04-01",
                    "report_date": "2022-03-28",
                    "acceptance_datetime": "2022-04-01",
                    "form": "8-K",
                    "items": "4.02",
                    "primary_document": "c.htm",
                },
                {
                    "issuer_cik": "0000000001",
                    "accession": "a-upload",
                    "accession_nodash": "aupload",
                    "filing_date": "2022-05-01",
                    "report_date": "2022-04-28",
                    "acceptance_datetime": "2022-05-01",
                    "form": "UPLOAD",
                    "items": "",
                    "primary_document": "d.htm",
                },
                {
                    "issuer_cik": "0000000002",
                    "accession": "g-20f",
                    "accession_nodash": "g20f",
                    "filing_date": "2016-03-01",
                    "report_date": "2015-12-31",
                    "acceptance_datetime": "2016-03-01",
                    "form": "20-F",
                    "items": "",
                    "primary_document": "e.htm",
                },
                {
                    "issuer_cik": "0000000002",
                    "accession": "g-annual",
                    "accession_nodash": "gannual",
                    "filing_date": "2019-03-01",
                    "report_date": "2018-12-31",
                    "acceptance_datetime": "2019-03-01",
                    "form": "10-K",
                    "items": "",
                    "primary_document": "f.htm",
                },
            ]
        ),
        silver / "filing_dim.parquet",
    )

    build_gold_panels(silver_dir=silver, gold_dir=gold, as_of_date="2026-04-23")
    filing = read_table(gold / "filing_origin_panel.parquet", date_cols=["fiscal_period_end"])
    issuer = read_table(gold / "issuer_origin_panel.parquet")

    assert filing.loc[filing["form"].eq("10-K"), "fiscal_period_end"].notna().all()
    assert filing.loc[filing["form"].isin(["8-K", "UPLOAD"]), "fiscal_period_end"].isna().all()
    alpha_2021 = issuer.loc[
        issuer["issuer_cik"].astype(str).str.zfill(10).eq("0000000001")
        & issuer["fiscal_year"].eq(2021)
    ].iloc[0]
    gamma_2018 = issuer.loc[
        issuer["issuer_cik"].astype(str).str.zfill(10).eq("0000000002")
        & issuer["fiscal_year"].eq(2018)
    ].iloc[0]
    assert alpha_2021["form"] == "10-K"
    assert int(gamma_2018["issuer_has_fpi_form_year"]) == 0
    assert int(gamma_2018["is_domestic_us_gaap_proxy"]) == 1


def test_duckdb_gold_build_matches_pandas_on_toy_public_lake(tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    gold_pandas = tmp_path / "gold_pandas"
    gold_duckdb = tmp_path / "gold_duckdb"
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "0000000001",
                    "entity_name": "Alpha Beta Corp",
                    "sic": 1234,
                    "sic_description": "A",
                    "entity_type": "operating",
                }
            ]
        ),
        silver / "issuer_dim.parquet",
    )
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "0000000001",
                    "accession": "a-annual",
                    "accession_nodash": "aannual",
                    "filing_date": "2022-03-01",
                    "report_date": "2021-12-31",
                    "acceptance_datetime": "2022-03-01",
                    "form": "10-K",
                    "items": "",
                    "primary_document": "a.htm",
                    "primary_doc_description": "10-K",
                }
            ]
        ),
        silver / "filing_dim.parquet",
    )
    _write_csv_gz(
        silver / "comment_thread.csv.gz",
        [
            {
                "issuer_cik": "0000000001",
                "thread_id": "0000000001-1",
                "first_public_date": "2022-05-01",
                "last_public_date": "2022-05-02",
                "upload_count": 1,
                "corresp_count": 1,
                "filing_count": 2,
            }
        ],
    )
    _write_csv_gz(
        silver / "correction_event.csv.gz",
        [
            {
                "issuer_cik": "0000000001",
                "accession": "a-amend",
                "public_date": "2022-06-01",
                "report_date": "2021-12-31",
                "correction_type": "amendment_10x_a",
                "identified_from": "form",
            },
            {
                "issuer_cik": "0000000001",
                "accession": "a-8k",
                "public_date": "2022-07-01",
                "report_date": "2021-12-31",
                "correction_type": "nonreliance_8k_402",
                "identified_from": "items_or_description",
            },
        ],
    )
    _write_csv_gz(
        silver / "aaer_event.csv.gz",
        [
            {
                "release_url": "https://example.com/aaer",
                "release_title": "Alpha Beta",
                "event_date": "2022-08-01",
                "issuer_cik": "0000000001",
                "aaer_match_score": 1.0,
                "aaer_match_method": "token_all",
            }
        ],
    )
    _write_csv_gz(
        silver / "xbrl_fact.csv.gz",
        [
            {
                "adsh": "a-annual",
                "tag": "Assets",
                "unit": "USD",
                "value": 100.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
            {
                "adsh": "a-annual",
                "tag": "Liabilities",
                "unit": "USD",
                "value": 40.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
        ],
    )
    _write_csv_gz(
        silver / "note_text.csv.gz",
        [{"adsh": "a-annual", "tag": "DebtTextBlock", "note_text": "short note"}],
    )

    build_gold_panels(
        silver_dir=silver,
        gold_dir=gold_pandas,
        as_of_date="2026-04-23",
        engine="pandas",
    )
    build_gold_panels(
        silver_dir=silver,
        gold_dir=gold_duckdb,
        as_of_date="2026-04-23",
        engine="duckdb",
        duckdb_threads=1,
    )
    pandas_panel = read_table(gold_pandas / "issuer_origin_panel.parquet")
    duckdb_panel = read_table(gold_duckdb / "issuer_origin_panel.parquet")
    compare_cols = [
        "fiscal_year",
        "label_comment_thread_365",
        "label_amendment_365",
        "label_8k_402_365",
        "label_aaer_proxy_730",
        "censored_365",
        "censored_730",
        "xbrl_fact_count",
        "xbrl_unique_tags",
        "xbrl_ratio_leverage",
        "xbrl_ratio_assets_yoy_change",
        "xbrl_coverage_assets_yoy",
        "xbrl_coverage_assets",
        "note_text_count",
        "note_text_char_count",
    ]

    pd.testing.assert_frame_equal(
        pandas_panel[compare_cols].reset_index(drop=True),
        duckdb_panel[compare_cols].reset_index(drop=True),
        check_dtype=False,
    )


def test_parquet_gold_build_matches_legacy_gold_build(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    parquet = tmp_path / "parquet"
    gold_legacy = tmp_path / "gold_legacy"
    gold_parquet = tmp_path / "gold_parquet"
    for silver in [legacy, parquet]:
        write_table(
            pd.DataFrame(
                [
                    {
                        "issuer_cik": "0000000001",
                        "entity_name": "Alpha Beta Corp",
                        "sic": 1234,
                        "sic_description": "A",
                        "entity_type": "operating",
                    }
                ]
            ),
            silver / "issuer_dim.parquet",
        )
        write_table(
            pd.DataFrame(
                [
                    {
                        "issuer_cik": "0000000001",
                        "accession": "a-annual",
                        "accession_nodash": "aannual",
                        "filing_date": "2022-03-01",
                        "report_date": "2021-12-31",
                        "acceptance_datetime": "2022-03-01",
                        "form": "10-K",
                        "items": "",
                        "primary_document": "a.htm",
                        "primary_doc_description": "10-K",
                    }
                ]
            ),
            silver / "filing_dim.parquet",
        )
        pd.DataFrame(
            columns=[
                "issuer_cik",
                "thread_id",
                "first_public_date",
                "last_public_date",
                "upload_count",
                "corresp_count",
                "filing_count",
            ]
        ).to_csv(silver / "comment_thread.csv.gz", index=False, compression="gzip")
        pd.DataFrame(
            columns=[
                "issuer_cik",
                "accession",
                "public_date",
                "report_date",
                "correction_type",
                "identified_from",
            ]
        ).to_csv(silver / "correction_event.csv.gz", index=False, compression="gzip")
        pd.DataFrame(
            columns=[
                "release_url",
                "release_title",
                "event_date",
                "issuer_cik",
                "aaer_match_score",
                "aaer_match_method",
            ]
        ).to_csv(silver / "aaer_event.csv.gz", index=False, compression="gzip")
    _write_csv_gz(
        legacy / "xbrl_fact.csv.gz",
        [
            {
                "adsh": "a-annual",
                "tag": "Assets",
                "unit": "USD",
                "value": 100.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
            {
                "adsh": "a-annual",
                "tag": "Liabilities",
                "unit": "USD",
                "value": 40.0,
                "quarters": 4,
                "fact_date": "2021-12-31",
            },
        ],
    )
    _write_csv_gz(
        legacy / "note_text.csv.gz",
        [{"adsh": "a-annual", "tag": "DebtTextBlock", "note_text": "short note"}],
    )
    write_table(
        pd.DataFrame(
            [
                {
                    "adsh": "a-annual",
                    "xbrl_fact_count": 2,
                    "xbrl_unique_tags": 2,
                    "xbrl_unique_units": 1,
                }
            ]
        ),
        parquet / "xbrl_fact_summary.parquet",
    )
    write_table(
        pd.DataFrame(
            [
                {
                    "adsh": "a-annual",
                    "tag": "Assets",
                    "unit": "USD",
                    "value": 100.0,
                    "quarters": 4,
                    "fact_date": "2021-12-31",
                    "source_year": 2021,
                },
                {
                    "adsh": "a-annual",
                    "tag": "Liabilities",
                    "unit": "USD",
                    "value": 40.0,
                    "quarters": 4,
                    "fact_date": "2021-12-31",
                    "source_year": 2021,
                },
            ]
        ),
        parquet / "xbrl_core_fact.parquet",
    )
    write_table(
        pd.DataFrame(
            [
                {
                    "adsh": "a-annual",
                    "note_text_count": 1,
                    "note_text_char_count": len("short note"),
                }
            ]
        ),
        parquet / "note_summary.parquet",
    )

    build_gold_panels(
        silver_dir=legacy,
        gold_dir=gold_legacy,
        as_of_date="2026-04-23",
        engine="duckdb",
    )
    build_gold_panels(
        silver_dir=parquet,
        gold_dir=gold_parquet,
        as_of_date="2026-04-23",
        engine="duckdb",
    )

    legacy_panel = read_table(gold_legacy / "issuer_origin_panel.parquet")
    parquet_panel = read_table(gold_parquet / "issuer_origin_panel.parquet")
    compare_cols = [
        "xbrl_fact_count",
        "xbrl_unique_tags",
        "xbrl_ratio_leverage",
        "xbrl_ratio_assets_yoy_change",
        "xbrl_coverage_assets_yoy",
        "xbrl_coverage_assets",
        "note_text_count",
        "note_text_char_count",
    ]
    pd.testing.assert_frame_equal(
        legacy_panel[compare_cols].reset_index(drop=True),
        parquet_panel[compare_cols].reset_index(drop=True),
        check_dtype=False,
    )


def test_public_lake_dag_fresh_build_and_resume(tmp_path: Path, monkeypatch: object) -> None:
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    _write_submissions_zip(bronze / "sec-bulk" / "submissions.zip")

    build_public_lake(
        bronze_dir=bronze,
        silver_dir=silver,
        gold_dir=gold,
        as_of_date="2026-04-23",
        fresh_build=True,
    )
    assert (silver / ".public_lake_dag" / "normalize_submissions.done.json").exists()
    (silver / "stale.txt").write_text("old", encoding="utf-8")
    (gold / "stale.txt").write_text("old", encoding="utf-8")

    build_public_lake(
        bronze_dir=bronze,
        silver_dir=silver,
        gold_dir=gold,
        as_of_date="2026-04-23",
        fresh_build=True,
    )
    assert not (silver / "stale.txt").exists()
    assert not (gold / "stale.txt").exists()

    def fail_submissions(*args: object, **kwargs: object) -> None:
        raise AssertionError("resume should skip completed DAG tasks")

    monkeypatch.setattr("src.public_lake.normalize_submissions_bulk", fail_submissions)
    build_public_lake(
        bronze_dir=bronze,
        silver_dir=silver,
        gold_dir=gold,
        as_of_date="2026-04-23",
        resume=True,
    )


def test_simple_dag_stops_downstream_after_upstream_failure(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail_task() -> dict[str, Path]:
        calls.append("fail")
        raise RuntimeError("planned failure")

    def downstream_task() -> dict[str, Path]:
        calls.append("downstream")
        return {}

    runner = SimpleDagRunner(state_dir=tmp_path / "state", resume=False)
    with pytest.raises(RuntimeError, match="planned failure"):
        runner.run(
            [
                DagTask("fail", (), fail_task),
                DagTask("downstream", ("fail",), downstream_task),
            ]
        )

    assert calls == ["fail"]
    assert not (tmp_path / "state" / "downstream.done.json").exists()
