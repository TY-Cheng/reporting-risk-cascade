from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from src.public_lake import (
    _event_within_horizon,
    _write_metadata,
    build_gold_panels,
    build_public_lake,
    build_xbrl_core_features,
    fetch_source_assets,
    normalize_aaer_events,
)


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


def _write_fsds_zip(path: Path, adsh: str, tag: str) -> None:
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
                "ddate": "20211231",
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


def _write_notes_zip(path: Path, adsh: str, tag: str) -> None:
    txt = pd.DataFrame(
        [
            {
                "adsh": adsh,
                "tag": tag,
                "version": "us-gaap/2021",
                "ddate": "20211231",
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


def test_build_public_lake_accumulates_all_fsds_and_notes_archives(tmp_path: Path) -> None:
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    _write_submissions_zip(bronze / "sec-bulk" / "submissions.zip")

    fsds_paths = [bronze / "fsds" / "fsds_1.zip", bronze / "fsds" / "fsds_2.zip"]
    _write_fsds_zip(fsds_paths[0], "0000000001-22-000001", "Assets")
    _write_fsds_zip(fsds_paths[1], "0000000001-22-000002", "Liabilities")
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
    )

    xbrl_fact = pd.read_csv(silver / "xbrl_fact.csv.gz")
    note_text = pd.read_csv(silver / "note_text.csv.gz")
    assert set(xbrl_fact["tag"]) == {"Assets", "Liabilities"}
    assert set(note_text["tag"]) == {"DebtTextBlock", "TaxTextBlock"}


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
    issuer_dim = tmp_path / "issuer_dim.csv.gz"
    _write_csv_gz(
        issuer_dim,
        [
            {"issuer_cik": "0000000001", "entity_name": "Apple Inc."},
            {"issuer_cik": "0000000002", "entity_name": "Alpha Beta Corp"},
        ],
    )

    out = normalize_aaer_events(
        aaer_bronze_dir=bronze,
        silver_dir=silver,
        issuer_dim_csv=issuer_dim,
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
    _write_csv_gz(
        silver / "issuer_dim.csv.gz",
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
        ],
    )
    _write_csv_gz(
        silver / "filing_dim.csv.gz",
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
        ],
    )

    build_gold_panels(silver_dir=silver, gold_dir=gold, as_of_date="2026-04-23")
    filing = pd.read_csv(gold / "filing_origin_panel.csv.gz", parse_dates=["fiscal_period_end"])
    issuer = pd.read_csv(gold / "issuer_origin_panel.csv.gz")

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
