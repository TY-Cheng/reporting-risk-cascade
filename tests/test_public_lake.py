from __future__ import annotations

import hashlib
import json
import zipfile
from argparse import Namespace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts import monitor_public_lake
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
    normalize_fsds_archive,
    normalize_notes_archive,
)
from src.table_io import read_table, write_table


FINAL_REPORT_ROW_COUNT_KEYS = {
    "comment_thread",
    "correction_event",
    "filing_dim",
    "filing_origin_panel",
    "filing_xbrl_dim",
    "issuer_dim",
    "issuer_origin_panel",
    "note_summary",
    "notes_filing_dim",
    "xbrl_core_fact",
    "xbrl_fact_summary",
}


def test_monitor_once_reuses_one_row_count_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = Namespace(
        bronze_dir=tmp_path / "bronze",
        silver_dir=tmp_path / "silver",
        gold_dir=tmp_path / "gold",
        log_dir=tmp_path / "logs",
        interval=60.0,
        pid=0,
        once=True,
        report_json=tmp_path / "report.json",
        write_final_report=False,
        as_of_date=None,
    )
    calls = 0

    def fake_row_count_report(
        silver_dir: Path,
        gold_dir: Path,
    ) -> tuple[dict[str, int], dict[str, str]]:
        nonlocal calls
        calls += 1
        assert silver_dir == args.silver_dir
        assert gold_dir == args.gold_dir
        return {"issuer_dim": 7}, {"filing_dim": "unreadable"}

    monkeypatch.setattr(monitor_public_lake, "parse_args", lambda: args)
    monkeypatch.setattr(monitor_public_lake, "_row_count_report", fake_row_count_report)

    monitor_public_lake.main()

    assert calls == 1
    report = json.loads(args.report_json.read_text(encoding="utf-8"))
    assert json.loads(report["snapshot"]["row_counts_json"]) == report["row_counts"]
    assert json.loads(report["snapshot"]["row_count_errors_json"]) == report["row_count_errors"]


def _write_csv_gz(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, compression="gzip")


def test_final_public_lake_report_is_stable_hashed_and_atomically_written(
    tmp_path: Path,
) -> None:
    silver_dir = tmp_path / "silver"
    gold_dir = tmp_path / "gold"
    silver_dir.mkdir()
    gold_dir.mkdir()
    run_metadata = silver_dir / "public_lake_run_metadata.json"
    issuer_panel = gold_dir / "issuer_origin_panel.parquet"
    run_metadata.write_bytes(b'{"as_of_date":"2026-07-06"}')
    issuer_panel.write_bytes(b"bound-panel")
    counts = {key: index for index, key in enumerate(sorted(FINAL_REPORT_ROW_COUNT_KEYS))}

    report_path = monitor_public_lake._write_public_lake_final_report(
        silver_dir=silver_dir,
        as_of_date="2026-07-06",
        run_metadata_path=run_metadata,
        issuer_origin_panel_path=issuer_panel,
        row_counts=counts,
        row_count_errors={},
    )

    assert report_path == silver_dir / "public_lake_final_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report == {
        "schema_version": "public-lake-final-report-v1",
        "as_of_date": "2026-07-06",
        "public_lake_run_metadata_sha256": hashlib.sha256(run_metadata.read_bytes()).hexdigest(),
        "issuer_origin_panel_sha256": hashlib.sha256(issuer_panel.read_bytes()).hexdigest(),
        "row_counts": counts,
        "row_count_errors": {},
    }
    assert list(silver_dir.glob("public_lake_final_report.json.*.tmp")) == []


def _write_final_report_fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    silver_dir = tmp_path / "silver"
    gold_dir = tmp_path / "gold"
    silver_dir.mkdir()
    gold_dir.mkdir()
    run_metadata = silver_dir / "public_lake_run_metadata.json"
    issuer_panel = gold_dir / "issuer_origin_panel.parquet"
    run_metadata.write_bytes(b'{"as_of_date":"2026-07-06"}')
    issuer_panel.write_bytes(b"bound-panel")
    report = {
        "schema_version": "public-lake-final-report-v1",
        "as_of_date": "2026-07-06",
        "public_lake_run_metadata_sha256": hashlib.sha256(run_metadata.read_bytes()).hexdigest(),
        "issuer_origin_panel_sha256": hashlib.sha256(issuer_panel.read_bytes()).hexdigest(),
        "row_counts": {
            key: index for index, key in enumerate(sorted(FINAL_REPORT_ROW_COUNT_KEYS))
        },
        "row_count_errors": {},
    }
    report_path = silver_dir / "public_lake_final_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path, run_metadata, issuer_panel, report


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_count", "row_counts"),
        ("boolean_count", "nonnegative integer"),
        ("float_count", "nonnegative integer"),
        ("string_count", "nonnegative integer"),
        ("negative_count", "nonnegative integer"),
        ("count_error", "row_count_errors"),
        ("as_of_mismatch", "as_of_date"),
        ("metadata_hash_mismatch", "public_lake_run_metadata_sha256"),
        ("panel_hash_mismatch", "issuer_origin_panel_sha256"),
    ],
)
def test_final_public_lake_report_rejects_malformed_or_mismatched_content(
    tmp_path: Path,
    mutation: str,
    match: str,
) -> None:
    report_path, run_metadata, issuer_panel, report = _write_final_report_fixture(tmp_path)
    first_key = sorted(FINAL_REPORT_ROW_COUNT_KEYS)[0]
    if mutation == "missing_count":
        del report["row_counts"][first_key]  # type: ignore[index]
    elif mutation == "boolean_count":
        report["row_counts"][first_key] = True  # type: ignore[index]
    elif mutation == "float_count":
        report["row_counts"][first_key] = 1.0  # type: ignore[index]
    elif mutation == "string_count":
        report["row_counts"][first_key] = "1"  # type: ignore[index]
    elif mutation == "negative_count":
        report["row_counts"][first_key] = -1  # type: ignore[index]
    elif mutation == "count_error":
        report["row_count_errors"] = {first_key: "failed"}
    elif mutation == "as_of_mismatch":
        report["as_of_date"] = "2026-07-05"
    elif mutation == "metadata_hash_mismatch":
        report["public_lake_run_metadata_sha256"] = "0" * 64
    else:
        report["issuer_origin_panel_sha256"] = "0" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        monitor_public_lake._validate_public_lake_final_report(
            report_path,
            run_metadata_path=run_metadata,
            issuer_origin_panel_path=issuer_panel,
        )


def test_final_public_lake_report_rejects_partial_json(tmp_path: Path) -> None:
    report_path, run_metadata, issuer_panel, _ = _write_final_report_fixture(tmp_path)
    report_path.write_text('{"schema_version":', encoding="utf-8")

    with pytest.raises(ValueError, match="valid JSON"):
        monitor_public_lake._validate_public_lake_final_report(
            report_path,
            run_metadata_path=run_metadata,
            issuer_origin_panel_path=issuer_panel,
        )


def test_final_public_lake_report_replace_failure_preserves_prior_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path, run_metadata, issuer_panel, report = _write_final_report_fixture(tmp_path)
    prior = report_path.read_bytes()
    real_replace = Path.replace

    def interrupted_replace(path: Path, target: Path) -> Path:
        if Path(target) == report_path:
            raise OSError("simulated interruption")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupted_replace)

    with pytest.raises(OSError, match="simulated interruption"):
        monitor_public_lake._write_public_lake_final_report(
            silver_dir=report_path.parent,
            as_of_date=str(report["as_of_date"]),
            run_metadata_path=run_metadata,
            issuer_origin_panel_path=issuer_panel,
            row_counts=report["row_counts"],  # type: ignore[arg-type]
            row_count_errors={},
        )

    assert report_path.read_bytes() == prior
    assert list(report_path.parent.glob("public_lake_final_report.json.*.tmp")) == []


def _sort_gold_for_compare(frame: pd.DataFrame) -> pd.DataFrame:
    sort_cols = [
        col
        for col in ["issuer_cik", "fiscal_year", "origin_date", "accession"]
        if col in frame.columns
    ]
    if not sort_cols:
        return frame.reset_index(drop=True)
    return frame.sort_values(sort_cols, kind="mergesort", na_position="last").reset_index(
        drop=True
    )


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


def test_metadata_hash_table_readers_and_link_filters_are_defensive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached = tmp_path / "cached.csv"
    cached.write_text("a,b\n1,2\n", encoding="utf-8")
    assert public_lake._verify_metadata_hash(cached) is False
    _write_metadata(path=cached, source_url="https://example.com/cached.csv", source_name="toy")
    assert public_lake._verify_metadata_hash(cached) is True
    cached.write_text("a,b\n9,9\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Hash mismatch"):
        public_lake._verify_metadata_hash(cached)

    csv_path = tmp_path / "table.csv"
    tab_path = tmp_path / "table.txt"
    pipe_path = tmp_path / "table.idx"
    json_path = tmp_path / "table.json"
    bad_path = tmp_path / "table.bin"
    pd.DataFrame({"a": [1], "b": [2]}).to_csv(csv_path, index=False)
    tab_path.write_text("a\tb\n1\t2\n", encoding="utf-8")
    pipe_path.write_text("a|b\n1|2\n", encoding="utf-8")
    json_path.write_text('[{"a": 1, "b": 2}]', encoding="utf-8")
    bad_path.write_bytes(b"bad")

    for path in [csv_path, tab_path, pipe_path, json_path]:
        assert public_lake._read_table_auto(path).shape == (1, 2)
    with pytest.raises(ValueError, match="Unsupported table file type"):
        public_lake._read_table_auto(bad_path)

    html = """
    <a href="#fragment">skip</a>
    <a href="mailto:test@example.com">skip</a>
    <a href="/files/fsds_2021q1.zip">zip</a>
    <a href="/files/fsds_2021q1.zip">duplicate</a>
    <a href="/files/readme.html">skip suffix</a>
    <a href="/files/notes_2020q4.pdf">pdf</a>
    """
    monkeypatch.setattr(public_lake, "_fetch_html", lambda *args, **kwargs: html)
    links = public_lake._discover_links("https://www.sec.gov/data/")
    assert links["url"].tolist() == [
        "https://www.sec.gov/files/fsds_2021q1.zip",
        "https://www.sec.gov/files/notes_2020q4.pdf",
    ]
    filtered = public_lake._filter_link_frame(
        links,
        start_year=2021,
        end_year=2021,
        match="fsds",
        limit_links=1,
    )
    assert filtered["basename"].tolist() == ["fsds_2021q1.zip"]
    assert [day.isoformat() for day in public_lake._iter_business_days(date(2021, 1, 1), date(2021, 1, 4))] == [
        "2021-01-01",
        "2021-01-04",
    ]
    assert "/QTR2/master.20210405.idx" in public_lake._daily_master_index_url(date(2021, 4, 5))

    no_hash_meta = tmp_path / "no_hash.csv"
    no_hash_meta.write_text("a\n1\n", encoding="utf-8")
    public_lake._metadata_path(no_hash_meta).write_text("{}", encoding="utf-8")
    assert public_lake._verify_metadata_hash(no_hash_meta) is False


def test_low_level_download_and_html_fetch_are_mockable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = public_lake._session("unit-test-agent")
    assert session.headers["User-Agent"] == "unit-test-agent"

    sleeps: list[float] = []
    monkeypatch.setattr(public_lake.time, "sleep", lambda seconds: sleeps.append(float(seconds)))
    public_lake._LAST_REQUEST_AT = public_lake.time.monotonic()

    class FakeResponse:
        def __init__(
            self,
            *,
            status_code: int = 200,
            body: bytes = b"",
            text: str = "",
        ) -> None:
            self.status_code = status_code
            self._body = body
            self.text = text
            self.response = self

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def iter_content(self, chunk_size: int) -> list[bytes]:
            return [self._body[:1], b"", self._body[1:]]

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise public_lake.requests.HTTPError(
                    f"HTTP {self.status_code}", response=self
                )

    class FakeSession:
        def __init__(self, responses: list[FakeResponse]) -> None:
            self.responses = responses
            self.headers: dict[str, str] = {}
            self.calls: list[tuple[str, bool]] = []

        def get(self, url: str, *, timeout: int, stream: bool = False) -> FakeResponse:
            self.calls.append((url, stream))
            return self.responses.pop(0)

    retry_session = FakeSession(
        [
            FakeResponse(status_code=503),
            FakeResponse(status_code=200, body=b"abc"),
        ]
    )
    monkeypatch.setattr(public_lake, "_session", lambda user_agent: retry_session)
    dest = public_lake._download_file(
        "https://example.com/file.csv",
        tmp_path / "file.csv",
        source_name="toy",
        max_retries=2,
        backoff_seconds=0,
        extra_metadata={"kind": "unit"},
    )
    assert dest.read_bytes() == b"abc"
    assert json.loads(public_lake._metadata_path(dest).read_text())["kind"] == "unit"
    assert retry_session.calls == [
        ("https://example.com/file.csv", True),
        ("https://example.com/file.csv", True),
    ]
    assert sleeps

    html_session = FakeSession([FakeResponse(status_code=200, text="<html>ok</html>")])
    monkeypatch.setattr(public_lake, "_session", lambda user_agent: html_session)
    assert public_lake._fetch_html("https://example.com/page") == "<html>ok</html>"


def test_table_reader_routes_cover_supported_suffixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spaced = tmp_path / "spaced.txt"
    xml_path = tmp_path / "table.xml"
    xlsx_path = tmp_path / "table.xlsx"
    comma_path = tmp_path / "comma.dat"
    pipe_header = tmp_path / "pipe_header.txt"
    comma_header = tmp_path / "comma_header.txt"

    spaced.write_text("a  b\n1  2\n", encoding="utf-8")
    xml_path.write_text("<root />", encoding="utf-8")
    xlsx_path.write_bytes(b"not-a-real-xlsx")
    comma_path.write_text("a,b\n1,2\n", encoding="utf-8")
    pipe_header.write_text("a|b\n1|2\n", encoding="utf-8")
    comma_header.write_text("a,b\n1,2\n", encoding="utf-8")

    monkeypatch.setattr(public_lake.pd, "read_xml", lambda path: pd.DataFrame({"a": [1]}))
    monkeypatch.setattr(public_lake.pd, "read_excel", lambda path: pd.DataFrame({"a": [1]}))

    assert public_lake._read_table_auto(spaced).to_dict("records") == [{"a": 1, "b": 2}]
    assert public_lake._read_table_auto(xml_path).shape == (1, 1)
    assert public_lake._read_table_auto(xlsx_path).shape == (1, 1)
    assert public_lake._read_delimited_table(comma_path).to_dict("records") == [
        {"a": 1, "b": 2}
    ]
    assert public_lake._read_header_columns(pipe_header) == ["a", "b"]
    assert public_lake._read_header_columns(comma_header) == ["a", "b"]


def test_fetch_source_assets_list_only_modes_do_not_touch_network_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    direct = fetch_source_assets(mode="sec-bulk", bronze_dir=tmp_path, list_only=True)
    assert set(direct["status"]) == {"listed"}
    assert not any(Path(path).exists() for path in direct["local_path"])

    with pytest.raises(ValueError, match="requires start_date and end_date"):
        fetch_source_assets(mode="comment-letters", bronze_dir=tmp_path, list_only=True)
    daily = fetch_source_assets(
        mode="comment-letters",
        bronze_dir=tmp_path,
        start_date="2021-01-01",
        end_date="2021-01-04",
        list_only=True,
    )
    assert daily["basename"].tolist() == ["master.20210101.idx", "master.20210104.idx"]

    monkeypatch.setattr(
        public_lake,
        "_discover_links",
        lambda *args, **kwargs: pd.DataFrame(
            columns=["page_url", "url", "basename", "suffix"]
        ),
    )
    empty = fetch_source_assets(mode="fsds", bronze_dir=tmp_path, list_only=True)
    assert empty.empty
    assert (tmp_path / "fsds" / "manifest.csv").exists()
    with pytest.raises(ValueError, match="Unsupported source mode"):
        fetch_source_assets(mode="unknown", bronze_dir=tmp_path, list_only=True)


def test_fetch_source_assets_downloads_listing_and_refreshes_invalid_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bronze = tmp_path / "bronze"
    downloaded: list[str] = []

    def fake_download(
        url: str,
        dest: Path,
        *,
        source_name: str,
        user_agent: str = public_lake.DEFAULT_USER_AGENT,
        timeout: int = 120,
        extra_metadata: dict[str, object] | None = None,
        max_retries: int = 5,
        backoff_seconds: float = 2.0,
    ) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f"downloaded from {url}", encoding="utf-8")
        _write_metadata(
            path=dest,
            source_url=url,
            source_name=source_name,
            extra=extra_metadata,
        )
        downloaded.append(dest.name)
        return dest

    monkeypatch.setattr(public_lake, "_download_file", fake_download)
    page_frame = pd.DataFrame(
        [
            {
                "page_url": "https://example.com/page",
                "url": "https://example.com/toy.csv",
                "basename": "toy.csv",
                "suffix": ".csv",
            }
        ]
    )
    monkeypatch.setattr(public_lake, "_discover_links", lambda *args, **kwargs: page_frame)
    monkeypatch.setitem(
        public_lake.SOURCE_SPECS,
        "toy-page",
        public_lake.SourceSpec(name="toy-page", kind="page", page_url="https://example.com/page"),
    )
    stale = bronze / "toy-page" / "toy.csv"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale", encoding="utf-8")
    manifest = fetch_source_assets(mode="toy-page", bronze_dir=bronze, list_only=False)
    assert manifest["status"].tolist() == ["downloaded"]
    assert stale.read_text(encoding="utf-8").startswith("downloaded from")

    monkeypatch.setitem(
        public_lake.SOURCE_SPECS,
        "bad-kind",
        public_lake.SourceSpec(name="bad-kind", kind="unknown-kind"),
    )
    with pytest.raises(ValueError, match="Unsupported source kind"):
        fetch_source_assets(mode="bad-kind", bronze_dir=bronze, list_only=True)


def test_duckdb_empty_source_and_csv_engine_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = _duckdb_connect(threads=1)
    try:
        public_lake._duckdb_source_or_empty(
            con=con,
            view_name="missing_source",
            path=tmp_path / "missing.parquet",
            empty_columns=[("issuer_cik", "VARCHAR"), ("n_rows", "BIGINT")],
        )
        empty = con.execute("SELECT * FROM missing_source").fetchdf()
        assert list(empty.columns) == ["issuer_cik", "n_rows"]
        assert empty.empty
    finally:
        con.close()

    csv_path = tmp_path / "fallback.csv"
    pd.DataFrame({"d": ["2021-01-01"], "value": [1], "drop_me": [2]}).to_csv(
        csv_path, index=False
    )

    def fail_duckdb_read(*args: object, **kwargs: object) -> pd.DataFrame:
        raise RuntimeError("planned duckdb csv failure")

    monkeypatch.setattr(public_lake, "_duckdb_read_csv", fail_duckdb_read)
    loaded = public_lake._read_csv_with_engine(
        csv_path,
        engine="duckdb",
        usecols=["d", "value"],
        date_cols=["d"],
    )
    assert loaded["d"].dt.year.tolist() == [2021]
    assert list(loaded.columns) == ["d", "value"]


def test_duckdb_table_io_helpers_copy_csv_parquet_and_validate_sources(tmp_path: Path) -> None:
    csv_path = tmp_path / "source.csv"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(csv_path, index=False)

    selected = public_lake._duckdb_read_csv(csv_path, threads=1, columns=["a"])
    assert selected.to_dict("records") == [{"a": 1}, {"a": 2}]

    csv_gz = tmp_path / "copy.csv.gz"
    public_lake._duckdb_copy_query_to_csv(
        query="SELECT 1 AS a, 'x' AS b",
        dest=csv_gz,
        threads=1,
    )
    assert pd.read_csv(csv_gz).to_dict("records") == [{"a": 1, "b": "x"}]

    parquet_dir = tmp_path / "partitioned_parquet"
    public_lake._duckdb_copy_query_to_parquet(
        query="SELECT 2021 AS source_year, 1 AS value",
        dest=parquet_dir,
        threads=1,
        partition_by=("source_year",),
    )
    assert read_table(parquet_dir)["value"].tolist() == [1]

    assert public_lake._duckdb_csv_source(csv_path).startswith("read_csv_auto('")
    with pytest.raises(ValueError, match="requires at least one path"):
        public_lake._duckdb_csv_source([])


def test_build_public_lake_validates_config_and_notes_skip_is_lightweight(
    tmp_path: Path,
) -> None:
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    for kwargs, message in [
        ({"engine": "bad"}, "engine must be"),
        ({"storage_format": "bad"}, "storage_format must be"),
        ({"notes_mode": "bad"}, "notes_mode must be"),
        ({"engine": "pandas", "storage_format": "parquet"}, "requires engine='duckdb'"),
        ({"fsds_batch_size": 0}, "must be positive"),
        ({"notes_batch_size": 0}, "must be positive"),
    ]:
        with pytest.raises(ValueError, match=message):
            build_public_lake(
                bronze_dir=bronze,
                silver_dir=silver,
                gold_dir=gold,
                as_of_date="2026-04-23",
                **kwargs,
            )

    with pytest.raises(FileNotFoundError, match="submissions.zip"):
        build_public_lake(
            bronze_dir=bronze,
            silver_dir=silver,
            gold_dir=gold,
            as_of_date="2026-04-23",
        )

    _write_submissions_zip(bronze / "sec-bulk" / "submissions.zip")
    note_path = bronze / "notes" / "notes_1.zip"
    _write_notes_zip(note_path, "0000000001-22-000001", "DebtTextBlock")
    pd.DataFrame({"local_path": [str(note_path)]}).to_csv(
        bronze / "notes" / "manifest.csv", index=False
    )
    outputs = build_public_lake(
        bronze_dir=bronze,
        silver_dir=silver,
        gold_dir=gold,
        as_of_date="2026-04-23",
        notes_mode="skip",
    )
    assert outputs["issuer_origin_panel"].exists()
    assert not (silver / "note_summary.parquet").exists()
    assert not (silver / "note_text").exists()
    run_metadata = json.loads((silver / "public_lake_run_metadata.json").read_text())
    assert run_metadata["notes_mode"] == "skip"
    assert {"commit_sha", "dirty", "config_hash", "input_hash", "uv_lock_hash"}.issubset(
        run_metadata["provenance"]
    )


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
    gold_metadata = json.loads((gold / "gold_metadata.json").read_text())
    assert gold_metadata["issuer_origin_panel_scope"] == (
        "annual_modeling_panel_with_labels_features"
    )
    assert gold_metadata["filing_origin_panel_scope"] == "lightweight_filing_base_panel"
    assert gold_metadata["filing_origin_panel_storage"] == "year_sharded_parquet_dataset"
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


def test_csv_gz_manifest_archives_and_batch_helpers_cover_resume_guards(
    tmp_path: Path,
) -> None:
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    fsds_paths = [bronze / "fsds_1.zip", bronze / "fsds_2.zip"]
    _write_fsds_zip(fsds_paths[0], "0000000001-22-000001", "Assets")
    _write_fsds_zip(fsds_paths[1], "0000000001-22-000002", "Liabilities")
    manifest = tmp_path / "manifest.csv"
    pd.DataFrame(
        {
            "local_path": [
                str(fsds_paths[0]),
                str(tmp_path / "missing.zip"),
                str(fsds_paths[1]),
            ]
        }
    ).to_csv(manifest, index=False)

    extracted = public_lake._extract_manifest_members(
        manifest_csv=manifest,
        staging_dir=tmp_path / "staging",
        required_stem="num",
        optional_stems=("sub",),
    )
    assert len(extracted["num"]) == 2
    assert len(extracted["sub"]) == 2

    outputs = public_lake._normalize_manifest_archives(
        manifest_csv=manifest,
        silver_dir=silver,
        normalizer_name="fsds",
        engine="duckdb",
        duckdb_threads=1,
    )
    assert set(outputs) == {"filing_xbrl_dim", "xbrl_fact"}
    assert read_table(outputs["xbrl_fact"]).shape[0] == 2
    assert not (silver / "._tmp_fsds").exists()

    pd.DataFrame({"other": ["x"]}).to_csv(tmp_path / "no_local_path.csv", index=False)
    assert public_lake._manifest_archive_paths(tmp_path / "no_local_path.csv") == []

    state_dir = tmp_path / "state"
    marker = state_dir / "batch_0000.done.json"
    state_dir.mkdir()
    assert public_lake._batch_marker_outputs_exist(marker) is False
    marker.write_text("{bad json", encoding="utf-8")
    assert public_lake._batch_marker_outputs_exist(marker) is False
    marker.write_text(
        json.dumps({"outputs": {"missing": str(tmp_path / "missing.parquet")}}),
        encoding="utf-8",
    )
    assert public_lake._batch_marker_outputs_exist(marker) is False

    assert public_lake._parquet_files(tmp_path / "missing_parts") == []
    single = tmp_path / "single.parquet"
    write_table(pd.DataFrame({"id": [1]}), single)
    assert public_lake._parquet_files(single) == [single]
    with pytest.raises(ValueError, match="requires at least one file"):
        public_lake._parquet_source_from_files([])
    assert public_lake._copy_parquet_query_from_parts(
        parts_dir=tmp_path / "missing_parts",
        dest=tmp_path / "out.parquet",
        query="SELECT * FROM {source}",
        threads=1,
        memory_limit="128MB",
        temp_directory=tmp_path / "duckdb_tmp",
        max_temp_directory_size="1GB",
    ) is False

    duplicate_parts = tmp_path / "duplicate_parts"
    write_table(pd.DataFrame({"adsh": ["a", "a"]}), duplicate_parts / "part.parquet")
    with pytest.raises(ValueError, match="duplicate adsh"):
        public_lake._assert_no_duplicate_parquet_key(
            parts_dir=duplicate_parts,
            key="adsh",
            label="toy",
            threads=1,
            memory_limit="128MB",
            temp_directory=tmp_path / "duckdb_tmp",
            max_temp_directory_size="1GB",
        )

    empty_zip = tmp_path / "empty_num.zip"
    with zipfile.ZipFile(empty_zip, "w") as zf:
        zf.writestr("sub.txt", "adsh\nabc\n")
    with pytest.raises(ValueError, match="num table"):
        public_lake._extract_archive_members_batch(
            archive_paths=[empty_zip],
            staging_dir=tmp_path / "batch_staging",
            required_stem="num",
            optional_stems=("sub",),
        )


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


def test_archive_normalizers_parse_decimal_suffix_dates(tmp_path: Path) -> None:
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


def test_archive_normalizers_raise_clear_errors_on_missing_required_members(
    tmp_path: Path,
) -> None:
    fsds_bad = tmp_path / "fsds_bad.zip"
    notes_bad = tmp_path / "notes_bad.zip"
    with zipfile.ZipFile(fsds_bad, "w") as zf:
        zf.writestr("readme.txt", "not fsds")
    with zipfile.ZipFile(notes_bad, "w") as zf:
        zf.writestr("sub.txt", "adsh\nabc\n")

    with pytest.raises(ValueError, match="sub/num"):
        normalize_fsds_archive(archive_path=fsds_bad, silver_dir=tmp_path / "fsds_pandas")
    with pytest.raises(ValueError, match="sub/num"):
        normalize_fsds_archive(
            archive_path=fsds_bad,
            silver_dir=tmp_path / "fsds_duckdb",
            engine="duckdb",
            duckdb_threads=1,
        )
    with pytest.raises(ValueError, match="txt table"):
        normalize_notes_archive(archive_path=notes_bad, silver_dir=tmp_path / "notes_pandas")
    with pytest.raises(ValueError, match="txt table"):
        normalize_notes_archive(
            archive_path=notes_bad,
            silver_dir=tmp_path / "notes_duckdb",
            engine="duckdb",
            duckdb_threads=1,
        )


def test_form_ap_materialization_replaces_stale_csv_from_verified_zip(tmp_path: Path) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    silver_dir = tmp_path / "silver"
    form_ap_dir.mkdir(parents=True)
    stale = form_ap_dir / "FirmFilings.csv"
    stale.write_text("Form Filing ID\nold\n", encoding="utf-8")

    archive = form_ap_dir / "FirmFilings.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("FirmFilings.csv", "Form Filing ID\nnew\n")
    public_lake._write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )

    csv_path, metadata_path = public_lake._materialize_form_ap_csv(
        form_ap_dir=form_ap_dir,
        silver_dir=silver_dir,
    )

    assert csv_path == stale
    assert stale.read_text(encoding="utf-8") == "Form Filing ID\nnew\n"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_kind"] == "verified_zip_member"
    assert metadata["member"] == "FirmFilings.csv"
    assert metadata["archive_sha256"] == public_lake._hash_file(archive)
    assert metadata["member_sha256"] == public_lake._hash_file(stale)
    assert public_lake._verify_metadata_hash(stale) is True

    event_path = public_lake.normalize_form_ap_csv(
        form_ap_csv=csv_path,
        silver_dir=silver_dir,
    )
    event = read_table(event_path)
    assert set(event["form_filing_id"].astype(str)) == {"new"}
    assert "old" not in set(event["form_filing_id"].astype(str))


def test_form_ap_materialization_fails_when_verified_zip_lacks_member(tmp_path: Path) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    form_ap_dir.mkdir(parents=True)
    archive = form_ap_dir / "FirmFilings.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("other.csv", "id\n1\n")
    public_lake._write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )

    with pytest.raises(ValueError, match="FirmFilings.csv"):
        public_lake._materialize_form_ap_csv(
            form_ap_dir=form_ap_dir,
            silver_dir=tmp_path / "silver",
        )


def test_form_ap_materialization_rejects_archive_hash_mismatch(tmp_path: Path) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    form_ap_dir.mkdir(parents=True)
    archive = form_ap_dir / "FirmFilings.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("FirmFilings.csv", "filingId\nnew\n")
    public_lake._write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )
    archive.write_bytes(archive.read_bytes() + b"drift")

    with pytest.raises(ValueError, match="Hash mismatch"):
        public_lake._materialize_form_ap_csv(
            form_ap_dir=form_ap_dir,
            silver_dir=tmp_path / "silver",
        )


def test_form_ap_materialization_accepts_standalone_csv_without_sidecar(
    tmp_path: Path,
) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    form_ap_dir.mkdir(parents=True)
    csv_path = form_ap_dir / "FirmFilings.csv"
    csv_path.write_text("filingId\nstandalone\n", encoding="utf-8")

    selected, metadata_path = public_lake._materialize_form_ap_csv(
        form_ap_dir=form_ap_dir,
        silver_dir=tmp_path / "silver",
    )

    assert selected == csv_path
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_kind"] == "standalone_csv_fallback"
    assert metadata["archive_sha256"] is None
    assert metadata["member_sha256"] == public_lake._hash_file(csv_path)


def test_form_ap_materialization_rejects_zip_without_verified_sidecar(
    tmp_path: Path,
) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    form_ap_dir.mkdir(parents=True)
    stale = form_ap_dir / "FirmFilings.csv"
    stale_contents = "Form Filing ID\nold\n"
    stale.write_text(stale_contents, encoding="utf-8")
    archive = form_ap_dir / "FirmFilings.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("FirmFilings.csv", "Form Filing ID\nnew\n")

    with pytest.raises(ValueError, match="Missing verified metadata sidecar"):
        public_lake._materialize_form_ap_csv(
            form_ap_dir=form_ap_dir,
            silver_dir=tmp_path / "silver",
        )

    assert stale.read_text(encoding="utf-8") == stale_contents
    assert not (tmp_path / "silver" / "form_ap_source_metadata.json").exists()


def test_form_ap_materialization_rejects_verified_corrupt_zip_without_touching_stale_csv(
    tmp_path: Path,
) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    form_ap_dir.mkdir(parents=True)
    stale = form_ap_dir / "FirmFilings.csv"
    stale_contents = "Form Filing ID\nold\n"
    stale.write_text(stale_contents, encoding="utf-8")
    archive = form_ap_dir / "FirmFilings.zip"
    archive.write_bytes(b"")
    public_lake._write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )

    with pytest.raises(zipfile.BadZipFile):
        public_lake._materialize_form_ap_csv(
            form_ap_dir=form_ap_dir,
            silver_dir=tmp_path / "silver",
        )

    assert stale.read_text(encoding="utf-8") == stale_contents
    assert not public_lake._metadata_path(stale).exists()
    assert not (tmp_path / "silver" / "form_ap_source_metadata.json").exists()


def test_form_ap_materialization_cleans_temp_after_verified_member_crc_failure(
    tmp_path: Path,
) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    silver_dir = tmp_path / "silver"
    form_ap_dir.mkdir(parents=True)
    stale = form_ap_dir / "FirmFilings.csv"
    stale_contents = "Form Filing ID\nold\n"
    stale.write_text(stale_contents, encoding="utf-8")

    archive = form_ap_dir / "FirmFilings.zip"
    payload = b"Form Filing ID\nnew\n"
    damaged_payload = b"Form Filing ID\nbad\n"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("FirmFilings.csv", payload)
    archive_bytes = archive.read_bytes()
    assert archive_bytes.count(payload) == 1
    archive.write_bytes(archive_bytes.replace(payload, damaged_payload, 1))
    public_lake._write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )

    with pytest.raises(zipfile.BadZipFile, match="Bad CRC-32"):
        public_lake._materialize_form_ap_csv(
            form_ap_dir=form_ap_dir,
            silver_dir=silver_dir,
        )

    assert stale.read_text(encoding="utf-8") == stale_contents
    assert not public_lake._metadata_path(stale).exists()
    assert not (silver_dir / "form_ap_source_metadata.json").exists()
    assert list(form_ap_dir.glob("FirmFilings.*.tmp")) == []


def test_form_ap_materialization_rejects_duplicate_basename_members_before_mutation(
    tmp_path: Path,
) -> None:
    form_ap_dir = tmp_path / "bronze" / "form-ap"
    silver_dir = tmp_path / "silver"
    form_ap_dir.mkdir(parents=True)
    stale = form_ap_dir / "FirmFilings.csv"
    stale_contents = "Form Filing ID\nold\n"
    stale.write_text(stale_contents, encoding="utf-8")

    archive = form_ap_dir / "FirmFilings.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("FirmFilings.csv", "Form Filing ID\nroot\n")
        zf.writestr("nested/FirmFilings.csv", "Form Filing ID\nnested\n")
    public_lake._write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )

    with pytest.raises(
        ValueError,
        match=r"exactly one FirmFilings\.csv member; found 2",
    ):
        public_lake._materialize_form_ap_csv(
            form_ap_dir=form_ap_dir,
            silver_dir=silver_dir,
        )

    assert stale.read_text(encoding="utf-8") == stale_contents
    assert not public_lake._metadata_path(stale).exists()
    assert not (silver_dir / "form_ap_source_metadata.json").exists()
    assert list(form_ap_dir.glob("FirmFilings.*.tmp")) == []


def test_form_ap_and_pcaob_inspection_normalizers_standardize_fields(tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    form_ap_csv = tmp_path / "FirmFilings.csv"
    pd.DataFrame(
        [
            {
                "Form Filing ID": "F1",
                "Issuer CIK": 1,
                "Issuer Name": "Alpha Beta Corp",
                "Firm ID": "100",
                "Firm Name": "Audit Firm",
                "Engagement Partner ID": "P1",
                "Engagement Partner Name": "Partner",
                "Fiscal Period End Date": "2021-12-31",
                "Report Date": "2022-02-28",
                "Filing Date": "2022-03-01",
                "Number of Participants": 2,
                "Participant Percentage": 100.0,
            }
        ]
    ).to_csv(form_ap_csv, index=False)

    form_ap_path = public_lake.normalize_form_ap_csv(form_ap_csv=form_ap_csv, silver_dir=silver)
    form_ap = read_table(form_ap_path)
    assert form_ap.loc[0, "issuer_cik"] == "0000000001"
    assert pd.Timestamp(form_ap.loc[0, "filing_date"]).date().isoformat() == "2022-03-01"

    inspection_csv = tmp_path / "inspection.csv"
    pd.DataFrame(
        [
            {
                "Firm ID": "100",
                "Publication Date": "2023-01-15",
                "Inspection Year": 2022,
                "Part I.A": "yes",
                "Part I.B": "no",
                "Inspection Cycle": "annual",
                "Firm Name": "Audit Firm",
            }
        ]
    ).to_csv(inspection_csv, index=False)
    inspection_path = public_lake.normalize_pcaob_inspection_file(
        inspection_path=inspection_csv,
        silver_dir=silver,
    )
    inspection = pd.read_csv(inspection_path)
    assert inspection.loc[0, "pcaob_firm_id"] == 100
    assert inspection.loc[0, "firm_name"] == "Audit Firm"


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


def test_xbrl_and_event_helpers_cover_empty_and_filter_branches(tmp_path: Path) -> None:
    assert build_xbrl_core_features(pd.DataFrame({"tag": ["Assets"]})).empty
    assert build_xbrl_core_features(pd.DataFrame({"adsh": ["a"], "tag": ["NotCore"]})).empty
    assert build_xbrl_core_features(pd.DataFrame({"adsh": ["a"], "tag": ["Assets"]})).empty
    assert build_xbrl_core_features(
        pd.DataFrame(
            {
                "adsh": ["a"],
                "tag": ["Assets"],
                "value": [1.0],
                "unit": ["EUR"],
            }
        )
    ).empty
    features = build_xbrl_core_features(
        pd.DataFrame({"adsh": ["a"], "tag": ["Assets"], "value": [1.0]})
    )
    assert features.loc[0, "xbrl_coverage_assets"] == 1

    filing = pd.DataFrame({"issuer_cik": ["0000000001"], "origin_date": ["2021-01-01"]})
    unchanged = public_lake.add_xbrl_yoy_ratio_features(filing)
    assert "xbrl_ratio_assets_yoy_change" not in unchanged.columns

    assert public_lake._availability_date(2, "2026-04-23").dt.date.astype(str).tolist() == [
        "2026-04-23",
        "2026-04-23",
    ]
    optional_csv = tmp_path / "optional_dates.csv"
    pd.DataFrame({"event_date": ["2022-01-01"], "value": [1]}).to_csv(optional_csv, index=False)
    optional = public_lake._read_csv_with_optional_dates(optional_csv, ["event_date", "missing"])
    assert optional["event_date"].dt.year.tolist() == [2022]

    base = pd.DataFrame({"issuer_cik": ["0000000001"], "origin_date": ["2021-01-01"]})
    assert public_lake._event_within_horizon(
        base,
        pd.DataFrame(),
        date_col="event_date",
        horizon_days=365,
    ).tolist() == [0]
    assert public_lake._event_within_horizon(
        pd.DataFrame({"origin_date": ["2021-01-01"]}),
        pd.DataFrame({"event_date": ["2021-02-01"]}),
        date_col="event_date",
        horizon_days=365,
    ).tolist() == [0]
    assert public_lake._event_within_horizon(
        base,
        pd.DataFrame(
            {
                "issuer_cik": ["0000000001"],
                "event_date": ["2021-02-01"],
                "correction_type": ["other"],
            }
        ),
        date_col="event_date",
        horizon_days=365,
        event_type="amendment_10x_a",
    ).tolist() == [0]
    assert public_lake._event_within_horizon(
        pd.DataFrame({"issuer_cik": ["0000000001"], "origin_date": [pd.NaT]}),
        pd.DataFrame({"issuer_cik": ["0000000001"], "event_date": ["2021-02-01"]}),
        date_col="event_date",
        horizon_days=365,
    ).tolist() == [0]


def test_xbrl_yoy_uses_prior_fiscal_year_not_same_year_amendment() -> None:
    filing = pd.DataFrame(
        [
            {
                "issuer_cik": "0000000001",
                "fiscal_year": 2020,
                "origin_date": "2021-02-15",
                "accession": "a-2020",
                "form": "10-K",
                "xbrl_value_assets": 100.0,
                "xbrl_value_revenues": 50.0,
            },
            {
                "issuer_cik": "0000000001",
                "fiscal_year": 2021,
                "origin_date": "2022-02-15",
                "accession": "a-2021",
                "form": "10-K",
                "xbrl_value_assets": 120.0,
                "xbrl_value_revenues": 70.0,
            },
            {
                "issuer_cik": "0000000001",
                "fiscal_year": 2021,
                "origin_date": "2022-03-15",
                "accession": "a-2021-amend",
                "form": "10-K/A",
                "xbrl_value_assets": 121.0,
                "xbrl_value_revenues": 71.0,
            },
        ]
    )

    featured = public_lake.add_xbrl_yoy_ratio_features(filing).set_index("accession")

    assert featured.loc["a-2021", "xbrl_ratio_assets_yoy_change"] == pytest.approx(0.20)
    assert featured.loc["a-2021-amend", "xbrl_ratio_assets_yoy_change"] == pytest.approx(0.21)
    assert featured.loc["a-2021-amend", "xbrl_ratio_revenue_yoy_change"] == pytest.approx(0.42)
    assert featured.loc["a-2021-amend", "xbrl_coverage_assets_yoy"] == 1


def test_8k_item_parser_uses_items_metadata_only(tmp_path: Path) -> None:
    assert public_lake.parse_8k_item_codes("3.01, 4.01, Item 4.02") == (
        "3.01",
        "4.01",
        "4.02",
    )
    assert public_lake.parse_8k_item_codes("Item 5.02 Item 4.02") == ("4.02", "5.02")
    assert public_lake.parse_8k_item_codes("4.02 5.02") == ("4.02", "5.02")
    assert public_lake.parse_8k_item_codes("") == ()

    silver = tmp_path / "silver"
    filing_dim = tmp_path / "filing_dim.parquet"
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "1",
                    "accession": "a-items",
                    "accession_nodash": "aitems",
                    "filing_date": "2022-01-02",
                    "report_date": "2022-01-01",
                    "form": "8-K",
                    "items": "Item 4.02, 5.02",
                    "primary_doc_description": "",
                },
                {
                    "issuer_cik": "1",
                    "accession": "a-missing",
                    "accession_nodash": "amissing",
                    "filing_date": "2022-01-03",
                    "report_date": "2022-01-01",
                    "form": "8-K",
                    "items": "",
                    "primary_doc_description": "",
                },
                {
                    "issuer_cik": "1",
                    "accession": "a-description-only",
                    "accession_nodash": "adescriptiononly",
                    "filing_date": "2022-01-04",
                    "report_date": "2022-01-01",
                    "form": "8-K",
                    "items": "1.01",
                    "primary_doc_description": "Item 4.02 in text-like description",
                },
            ]
        ),
        filing_dim,
    )

    path = public_lake.build_issuer_8k_item_events(filing_dim_csv=filing_dim, silver_dir=silver)
    events = pd.read_csv(path)

    assert set(
        events.loc[events["accession"].eq("a-items"), "item_code"].dropna().astype(str)
    ) == {"4.02", "5.02"}
    assert events.loc[events["accession"].eq("a-missing"), "event_type"].tolist() == [
        "item_metadata_missing"
    ]
    assert not events["accession"].eq("a-description-only").any()


def test_8k_402_label_unknown_uses_task_level_censoring(tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    write_table(
        pd.DataFrame(
            [
                {"issuer_cik": "0000000001", "entity_name": "A", "sic": 1000},
                {"issuer_cik": "0000000002", "entity_name": "B", "sic": 1000},
                {"issuer_cik": "0000000003", "entity_name": "C", "sic": 1000},
            ]
        ),
        silver / "issuer_dim.parquet",
    )
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": f"{issuer_id:010d}",
                    "accession": f"base-{issuer_id}",
                    "accession_nodash": f"base{issuer_id}",
                    "filing_date": "2022-01-01",
                    "report_date": "2021-12-31",
                    "acceptance_datetime": "2022-01-01",
                    "form": "10-K",
                    "items": "",
                    "primary_document": "base.htm",
                    "primary_doc_description": "10-K",
                }
                for issuer_id in [1, 2, 3]
            ]
        ),
        silver / "filing_dim.parquet",
    )
    _write_csv_gz(
        silver / "issuer_8k_item_event.csv.gz",
        [
            {
                "issuer_cik": "0000000001",
                "accession": "k402-positive",
                "accession_nodash": "k402positive",
                "public_date": "2022-03-01",
                "report_date": "2022-03-01",
                "item_code": "4.02",
                "event_type": "8k_item_4_02",
                "item_metadata_missing": 0,
                "identified_from": "items_metadata",
            },
            {
                "issuer_cik": "0000000001",
                "accession": "missing-overridden",
                "accession_nodash": "missingoverridden",
                "public_date": "2022-04-01",
                "report_date": "2022-04-01",
                "item_code": None,
                "event_type": "item_metadata_missing",
                "item_metadata_missing": 1,
                "identified_from": "items_metadata",
            },
            {
                "issuer_cik": "0000000002",
                "accession": "missing-only",
                "accession_nodash": "missingonly",
                "public_date": "2022-03-01",
                "report_date": "2022-03-01",
                "item_code": None,
                "event_type": "item_metadata_missing",
                "item_metadata_missing": 1,
                "identified_from": "items_metadata",
            },
        ],
    )

    build_gold_panels(silver_dir=silver, gold_dir=gold, as_of_date="2026-04-23", engine="pandas")
    panel = read_table(gold / "issuer_origin_panel.parquet").sort_values("issuer_cik")

    assert panel["label_8k_402_365"].tolist()[0] == 1
    assert panel["k402_item_metadata_unknown_365"].tolist()[0] == 0
    assert pd.isna(panel["label_8k_402_365"].tolist()[1])
    assert panel["k402_item_metadata_unknown_365"].tolist()[1] == 1
    assert panel["label_8k_402_365"].tolist()[2] == 0
    assert panel["k402_item_metadata_unknown_365"].tolist()[2] == 0


def test_amendment_annotation_bounded_explanatory_note_rules(tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    texts = tmp_path / "texts"
    texts.mkdir()
    fixtures = {
        "adminonly": "EXPLANATORY NOTE This amendment only provides Part III information. ITEM 1. Business",
        "financialonly": (
            "Intro EXPLANATORY NOTES We correct an error in the financial statements. SIGNATURES"
        ),
        "mixed": "EXPLANATORY NOTE We restate a note disclosure. PART II",
        "missingnote": "This amendment has no bounded explanatory heading but says restate elsewhere.",
        "bounded": "EXPLANATORY NOTE This amendment updates governance. ITEM 1. Later we correct an error.",
        "cutoff": "EXPLANATORY NOTE " + ("A" * 3_100) + " restatement",
    }
    for stem, text in fixtures.items():
        (texts / f"{stem}.txt").write_text(text, encoding="utf-8")
    filing_dim = tmp_path / "filing_dim.parquet"
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "1",
                    "accession": stem,
                    "accession_nodash": stem,
                    "filing_date": "2022-03-01",
                    "report_date": "2021-12-31",
                    "form": "10-K/A",
                    "primary_document": f"{stem}.txt",
                    "primary_doc_description": description,
                }
                for stem, description in [
                    ("adminonly", "Part III proxy amendment"),
                    ("financialonly", "10-K/A"),
                    ("mixed", "Part III proxy amendment"),
                    ("missingnote", "10-K/A"),
                    ("bounded", "10-K/A"),
                    ("cutoff", "10-K/A"),
                ]
            ]
        ),
        filing_dim,
    )

    path = public_lake.build_amendment_annotations(
        filing_dim_csv=filing_dim,
        silver_dir=silver,
        amendment_text_dir=texts,
    )
    annotations = pd.read_csv(path).set_index("accession")

    assert annotations.loc["adminonly", "amendment_annotation"] == "admin_part_iii_proxy"
    assert (
        annotations.loc["financialonly", "amendment_annotation"]
        == "non_admin_financial_correction"
    )
    assert annotations.loc["mixed", "annotation_reason"] == "mixed_content_classified_as_nonadmin"
    assert annotations.loc["missingnote", "explanatory_note_missing"] == 1
    assert annotations.loc["bounded", "financial_override"] == 0
    assert annotations.loc["cutoff", "explanatory_note_char_count"] <= 3_000
    assert annotations.loc["cutoff", "financial_override"] == 0


def test_partner_risk_history_uses_preaggregation_and_strict_pre_origin(tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "0000000001",
                    "fiscal_period_end": "2020-12-31",
                    "report_date": "2021-02-01",
                    "filing_date": "2021-02-01",
                    "form_filing_id": "ap-1",
                    "pcaob_firm_id": "firm",
                    "engagement_partner_id": "P1",
                    "engagement_partner_name": "Partner One",
                    "number_of_participants": 1,
                },
                {
                    "issuer_cik": "0000000002",
                    "fiscal_period_end": "2020-12-31",
                    "report_date": "2021-02-01",
                    "filing_date": "2021-02-01",
                    "form_filing_id": "ap-2",
                    "pcaob_firm_id": "firm",
                    "engagement_partner_id": "P1",
                    "engagement_partner_name": "Partner One",
                    "number_of_participants": 1,
                },
                {
                    "issuer_cik": "0000000003",
                    "fiscal_period_end": "2020-12-31",
                    "report_date": "2021-07-01",
                    "filing_date": "2021-07-01",
                    "form_filing_id": "ap-3",
                    "pcaob_firm_id": "firm",
                    "engagement_partner_id": "P2",
                    "engagement_partner_name": "Partner Two",
                    "number_of_participants": 1,
                },
            ]
        ),
        silver / "form_ap_event.parquet",
    )
    _write_csv_gz(
        silver / "issuer_8k_item_event.csv.gz",
        [
            {
                "issuer_cik": "0000000002",
                "accession": "other-prior",
                "accession_nodash": "otherprior",
                "public_date": "2021-04-01",
                "report_date": "2021-04-01",
                "item_code": "4.02",
                "event_type": "8k_item_4_02",
                "item_metadata_missing": 0,
                "identified_from": "items_metadata",
            },
            {
                "issuer_cik": "0000000001",
                "accession": "current-prior",
                "accession_nodash": "currentprior",
                "public_date": "2021-06-01",
                "report_date": "2021-06-01",
                "item_code": "4.02",
                "event_type": "8k_item_4_02",
                "item_metadata_missing": 0,
                "identified_from": "items_metadata",
            },
            {
                "issuer_cik": "0000000001",
                "accession": "same-day",
                "accession_nodash": "sameday",
                "public_date": "2022-01-01",
                "report_date": "2022-01-01",
                "item_code": "4.02",
                "event_type": "8k_item_4_02",
                "item_metadata_missing": 0,
                "identified_from": "items_metadata",
            },
            {
                "issuer_cik": "0000000003",
                "accession": "same-day-form-ap",
                "accession_nodash": "samedayformap",
                "public_date": "2021-07-01",
                "report_date": "2021-07-01",
                "item_code": "4.02",
                "event_type": "8k_item_4_02",
                "item_metadata_missing": 0,
                "identified_from": "items_metadata",
            },
        ],
    )
    pd.DataFrame(
        columns=["issuer_cik", "public_date", "amendment_annotation"]
    ).to_csv(silver / "amendment_annotation.csv.gz", index=False, compression="gzip")

    outputs = public_lake.build_partner_risk_histories(
        form_ap_event_path=silver / "form_ap_event.parquet",
        issuer_8k_item_event_path=silver / "issuer_8k_item_event.csv.gz",
        amendment_annotation_path=silver / "amendment_annotation.csv.gz",
        silver_dir=silver,
    )
    assert set(outputs) == {
        "partner_issuer_engagement",
        "partner_risk_history",
        "partner_issuer_risk_history",
    }
    partner_history = pd.read_csv(outputs["partner_risk_history"])
    assert "P2" not in set(partner_history["engagement_partner_id"].astype(str))
    filing = pd.DataFrame(
        [
            {
                "issuer_cik": "0000000001",
                "accession": "origin",
                "origin_date": pd.Timestamp("2022-01-01"),
            }
        ]
    )
    featured = public_lake._add_partner_prior_features(filing.copy(), silver_dir=silver)

    assert len(featured) == len(filing)
    assert featured.loc[0, "auditor_partner_prior_other_issuer_8k_402_count"] == 1
    assert featured.loc[0, "auditor_partner_prior_other_issuer_total_count"] == 1


def test_comment_threads_and_correction_events_nonempty_branches(tmp_path: Path) -> None:
    silver = tmp_path / "silver"
    filing_dim = tmp_path / "filing_dim.parquet"
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "0000000001",
                    "accession": "upload-1",
                    "filing_date": "2022-01-01",
                    "report_date": "2021-12-31",
                    "form": "UPLOAD",
                    "items": "",
                    "primary_doc_description": "",
                },
                {
                    "issuer_cik": "0000000001",
                    "accession": "corresp-1",
                    "filing_date": "2022-02-01",
                    "report_date": "2021-12-31",
                    "form": "CORRESP",
                    "items": "",
                    "primary_doc_description": "",
                },
                {
                    "issuer_cik": "0000000001",
                    "accession": "amend-1",
                    "filing_date": "2022-03-01",
                    "report_date": "2021-12-31",
                    "form": "10-K/A",
                    "items": "",
                    "primary_doc_description": "",
                },
                {
                    "issuer_cik": "0000000001",
                    "accession": "8k-1",
                    "filing_date": "2022-04-01",
                    "report_date": "2021-12-31",
                    "form": "8-K",
                    "items": "4.02",
                    "primary_doc_description": "",
                },
                {
                    "issuer_cik": "0000000001",
                    "accession": "rev-1",
                    "filing_date": "2022-05-01",
                    "report_date": "2021-12-31",
                    "form": "10-Q",
                    "items": "",
                    "primary_doc_description": "Revision note",
                },
            ]
        ),
        filing_dim,
    )

    comment_path = public_lake.build_comment_threads(filing_dim_csv=filing_dim, silver_dir=silver)
    correction_path = public_lake.build_correction_events(
        filing_dim_csv=filing_dim,
        silver_dir=silver,
    )
    comment = pd.read_csv(comment_path)
    correction = pd.read_csv(correction_path)
    assert comment.loc[0, "upload_count"] == 1
    assert comment.loc[0, "corresp_count"] == 1
    assert set(correction["correction_type"]) == {
        "amendment_10x_a",
        "nonreliance_8k_402",
        "revision_if_identifiable",
    }


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
        silver / "issuer_8k_item_event.csv.gz",
        [
            {
                "issuer_cik": "0000000001",
                "accession": "a-8k",
                "accession_nodash": "a8k",
                "public_date": "2022-07-01",
                "report_date": "2022-07-01",
                "item_code": "4.02",
                "event_type": "8k_item_4_02",
                "item_metadata_missing": 0,
                "identified_from": "items_metadata",
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
    pandas_panel = _sort_gold_for_compare(read_table(gold_pandas / "issuer_origin_panel.parquet"))
    duckdb_panel = _sort_gold_for_compare(read_table(gold_duckdb / "issuer_origin_panel.parquet"))
    compare_cols = [
        "fiscal_year",
        "label_comment_thread_365",
        "label_amendment_365",
        "label_8k_402_365",
        "k402_item_metadata_unknown_365",
        "censored_365",
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


def test_pandas_gold_build_reads_parquet_summaries_core_file_and_form_ap(
    tmp_path: Path,
) -> None:
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "1",
                    "entity_name": "Alpha Beta Corp",
                    "sic": 1234,
                    "sic_description": "A",
                    "entity_type": "operating",
                },
                {
                    "issuer_cik": "2",
                    "entity_name": "Beta Gamma Corp",
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
                    "issuer_cik": "1",
                    "accession": "a-2020",
                    "accession_nodash": "a2020",
                    "filing_date": "2021-03-01",
                    "report_date": "2020-12-31",
                    "acceptance_datetime": "2021-03-01",
                    "form": "10-K",
                    "items": "",
                    "primary_document": "a.htm",
                    "primary_doc_description": "10-K",
                },
                {
                    "issuer_cik": "1",
                    "accession": "a-2021",
                    "accession_nodash": "a2021",
                    "filing_date": "2022-03-01",
                    "report_date": "2021-12-31",
                    "acceptance_datetime": "2022-03-01",
                    "form": "10-K",
                    "items": "",
                    "primary_document": "b.htm",
                    "primary_doc_description": "10-K",
                },
                {
                    "issuer_cik": "2",
                    "accession": "a-2021",
                    "accession_nodash": "a2021",
                    "filing_date": "2022-03-01",
                    "report_date": "2021-12-31",
                    "acceptance_datetime": "2022-03-01",
                    "form": "10-K",
                    "items": "",
                    "primary_document": "c.htm",
                    "primary_doc_description": "10-K",
                },
            ]
        ),
        silver / "filing_dim.parquet",
    )
    for filename, cols in {
        "comment_thread.csv.gz": [
            "issuer_cik",
            "thread_id",
            "first_public_date",
            "last_public_date",
            "upload_count",
            "corresp_count",
            "filing_count",
        ],
        "correction_event.csv.gz": [
            "issuer_cik",
            "accession",
            "public_date",
            "report_date",
            "correction_type",
            "identified_from",
        ],
    }.items():
        pd.DataFrame(columns=cols).to_csv(silver / filename, index=False, compression="gzip")
    write_table(
        pd.DataFrame(
            [
                {"accession": "a-2020", "xbrl_fact_count": 2, "xbrl_unique_tags": 2, "xbrl_unique_units": 1},
                {"accession": "a-2021", "xbrl_fact_count": 2, "xbrl_unique_tags": 2, "xbrl_unique_units": 1},
            ]
        ),
        silver / "xbrl_fact_summary.parquet",
    )
    write_table(
        pd.DataFrame(
            [
                {
                    "adsh": "a-2020",
                    "tag": "Assets",
                    "unit": "USD",
                    "value": 100.0,
                    "quarters": 4,
                    "fact_date": "2020-12-31",
                },
                {
                    "adsh": "a-2020",
                    "tag": "Liabilities",
                    "unit": "USD",
                    "value": 40.0,
                    "quarters": 4,
                    "fact_date": "2020-12-31",
                },
                {
                    "adsh": "a-2021",
                    "tag": "Assets",
                    "unit": "USD",
                    "value": 120.0,
                    "quarters": 4,
                    "fact_date": "2021-12-31",
                },
                {
                    "adsh": "a-2021",
                    "tag": "Liabilities",
                    "unit": "USD",
                    "value": 60.0,
                    "quarters": 4,
                    "fact_date": "2021-12-31",
                },
            ]
        ),
        silver / "xbrl_core_fact.parquet",
    )
    write_table(
        pd.DataFrame(
            [
                {"accession": "a-2020", "note_text_count": 1, "note_text_char_count": 5},
                {"accession": "a-2021", "note_text_count": 2, "note_text_char_count": 10},
            ]
        ),
        silver / "note_summary.parquet",
    )
    write_table(
        pd.DataFrame(
            [
                {
                    "issuer_cik": "1",
                    "fiscal_period_end": "2021-12-31",
                    "filing_date": "2022-02-15",
                    "form_filing_id": "F-pre",
                    "engagement_partner_id": "P1",
                    "number_of_participants": 2,
                },
                {
                    "issuer_cik": "1",
                    "fiscal_period_end": "2021-12-31",
                    "filing_date": "2022-03-15",
                    "form_filing_id": "F-post",
                    "engagement_partner_id": "P2",
                    "number_of_participants": 10,
                },
                {
                    "issuer_cik": "2",
                    "fiscal_period_end": "2021-12-31",
                    "filing_date": "2022-03-15",
                    "form_filing_id": "F-other-post",
                    "engagement_partner_id": "P3",
                    "number_of_participants": 20,
                }
            ]
        ),
        silver / "form_ap_event.parquet",
    )

    with pytest.raises(ValueError, match="engine must be"):
        build_gold_panels(silver_dir=silver, gold_dir=gold, as_of_date="2026-04-23", engine="bad")
    build_gold_panels(silver_dir=silver, gold_dir=gold, as_of_date="2026-04-23", engine="pandas")
    issuer = read_table(gold / "issuer_origin_panel.parquet")
    panel = issuer.sort_values(["issuer_cik", "fiscal_year"]).reset_index(drop=True)
    alpha_2020 = panel.loc[panel["accession"].eq("a-2020")].iloc[0]
    alpha_2021 = panel.loc[
        panel["issuer_cik"].eq("0000000001") & panel["fiscal_year"].eq(2021)
    ].iloc[0]
    beta_2021 = panel.loc[
        panel["issuer_cik"].eq("0000000002") & panel["fiscal_year"].eq(2021)
    ].iloc[0]
    assert alpha_2021["xbrl_ratio_assets_yoy_change"] == 0.2
    assert alpha_2021["note_text_count"] == 2
    assert pd.isna(alpha_2020["form_ap_filing_count"])
    assert alpha_2021["form_ap_filing_count"] == 1
    assert alpha_2021["form_ap_unique_partners"] == 1
    assert alpha_2021["form_ap_avg_participants"] == 2
    assert pd.isna(beta_2021["form_ap_filing_count"])


def test_parquet_gold_build_matches_csv_gz_gold_build(tmp_path: Path) -> None:
    csv_gz = tmp_path / "csv_gz"
    parquet = tmp_path / "parquet"
    gold_csv_gz = tmp_path / "gold_csv_gz"
    gold_parquet = tmp_path / "gold_parquet"
    for silver in [csv_gz, parquet]:
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
    _write_csv_gz(
        csv_gz / "xbrl_fact.csv.gz",
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
        csv_gz / "note_text.csv.gz",
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
        silver_dir=csv_gz,
        gold_dir=gold_csv_gz,
        as_of_date="2026-04-23",
        engine="duckdb",
    )
    build_gold_panels(
        silver_dir=parquet,
        gold_dir=gold_parquet,
        as_of_date="2026-04-23",
        engine="duckdb",
    )

    csv_gz_panel = _sort_gold_for_compare(read_table(gold_csv_gz / "issuer_origin_panel.parquet"))
    parquet_panel = _sort_gold_for_compare(read_table(gold_parquet / "issuer_origin_panel.parquet"))
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
        csv_gz_panel[compare_cols].reset_index(drop=True),
        parquet_panel[compare_cols].reset_index(drop=True),
        check_dtype=False,
    )


def test_build_public_lake_csv_gz_path_extracts_form_ap_and_inspection_sources(
    tmp_path: Path,
) -> None:
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    _write_submissions_zip(bronze / "sec-bulk" / "submissions.zip")

    form_ap_dir = bronze / "form-ap"
    form_ap_dir.mkdir(parents=True)
    firm_filings = pd.DataFrame(
        [
            {
                "Form Filing ID": "F1",
                "Issuer CIK": 1,
                "Fiscal Period End Date": "2021-12-31",
                "Filing Date": "2022-03-01",
                "Engagement Partner ID": "P1",
                "Number of Participants": 2,
            }
        ]
    )
    archive = form_ap_dir / "FirmFilings.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("FirmFilings.csv", firm_filings.to_csv(index=False))
    _write_metadata(
        path=archive,
        source_url=public_lake.PCAOB_FORM_AP_ZIP_URL,
        source_name="form-ap",
    )

    inspection_dir = bronze / "pcaob-inspections"
    inspection_dir.mkdir(parents=True)
    inspection_path = inspection_dir / "inspection.csv"
    pd.DataFrame(
        [
            {
                "Firm ID": 100,
                "Publication Date": "2022-01-01",
                "Inspection Year": 2021,
                "Firm Name": "Audit Firm",
            }
        ]
    ).to_csv(inspection_path, index=False)
    pd.DataFrame({"local_path": [str(inspection_path)]}).to_csv(
        inspection_dir / "manifest.csv",
        index=False,
    )

    outputs = build_public_lake(
        bronze_dir=bronze,
        silver_dir=silver,
        gold_dir=gold,
        as_of_date="2026-04-23",
        storage_format="csv-gz",
        engine="duckdb",
    )

    assert outputs["form_ap_event"].exists()
    assert outputs["form_ap_source_metadata"].exists()
    assert outputs["pcaob_inspection_event"].exists()
    assert (gold / "issuer_origin_panel.parquet").exists()


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
