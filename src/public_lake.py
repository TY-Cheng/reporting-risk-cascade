"""
Filing-native public-data lake utilities.

This module implements the public-data program around bronze/silver/gold layers
and filing-native keys:

- issuer_cik
- accession / adsh
- filing_date
- report_date
- fiscal_period_end
- origin_date
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd
import requests

from .table_io import (
    DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
    DEFAULT_DUCKDB_MEMORY_LIMIT,
    parquet_scan_sql,
    read_table,
    remove_table_path,
    write_table,
)

DEFAULT_USER_AGENT = "Tuoyuan Cheng tuoyuan.cheng@nus.edu.sg"
PARSER_VERSION = "public-lake-v1"
SCHEMA_VERSION = "public-lake-v1"
SEC_REQUEST_INTERVAL_SECONDS = 0.15
CSV_CHUNKSIZE = 250_000
DEFAULT_FSDS_BATCH_SIZE = 4
DEFAULT_NOTES_BATCH_SIZE = 2

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_BULK_SUBMISSIONS_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
)
SEC_BULK_COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SEC_FSDS_PAGE_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets"
)
SEC_NOTES_PAGE_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/financial-statement-notes-data-sets"
)
SEC_REVIEW_PROCESS_URL = (
    "https://www.sec.gov/about/divisions-offices/division-corporation-finance/"
    "filing-review-process-corp-fin"
)
SEC_CORRESPONDENCE_URL = "https://www.sec.gov/answers/how-to-search-for-edgar-correspondence"
SEC_AAER_URL = "https://www.sec.gov/enforcement/accounting-auditing-enforcement-releases"
SEC_INSIDER_PAGE_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
)
SEC_13F_PAGE_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
SEC_EDGAR_LOGS_PAGE_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/edgar-log-file-data-sets"
)
SEC_MARKET_STRUCTURE_PAGE_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/market-structure-data-security-exchange"
)
PCAOB_FORM_AP_ZIP_URL = "https://pcaobus.org/assets/PCAOBFiles/FirmFilings.zip"
PCAOB_FORM_AP_DICT_URL = (
    "https://assets.pcaobus.org/pcaob-dev/docs/default-source/rusdocuments/"
    "auditorsearch-form-ap-data-references.pdf"
)
PCAOB_AUDITORSEARCH_URL = "https://pcaobus.org/resources/auditorsearch"
PCAOB_INSPECTIONS_PAGE_URL = "https://pcaobus.org/oversight/inspections/firm-inspection-reports"

HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)
AAER_LINK_RE = re.compile(
    r'href="([^"]*accounting-auditing-enforcement-releases[^"]+)"', re.IGNORECASE
)
AAER_ROW_RE = re.compile(
    r'<time datetime="(?P<dt>[^"]+)"[^>]*>.*?</time>.*?<a href=[\'"](?P<href>[^\'"]+)[\'"]>'
    r"(?P<title>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)

SOURCE_START_DATES: Dict[str, str] = {
    "xbrl_main_sample": "2011-01-01",
    "notes_monthly": "2020-11-01",
    "form_ap": "2017-01-31",
    "insider": "2006-01-01",
    "13f": "2013-07-01",
    "edgar_logs_gap_start": "2017-07-01",
    "edgar_logs_gap_end": "2020-05-18",
    "market_structure": "2012-01-01",
    "pcaob_inspections_annual": "2018-01-01",
    "pcaob_inspections_triennial": "2019-01-01",
}

EMPTY_TABLE_SCHEMAS: Dict[str, Sequence[str]] = {
    "insider_event.csv.gz": ["issuer_cik", "owner_identifier", "filing_date", "transaction_code"],
    "holder_event.csv.gz": ["ticker", "cusip", "report_date", "manager_cik", "shares"],
    "attention_event.csv.gz": ["issuer_cik", "event_date", "request_count", "source_dataset"],
}

PERIOD_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "40-F"}
ANNUAL_FORMS = {"10-K", "10-K/A"}
FPI_FORMS = {"20-F", "40-F", "6-K"}
EIGHT_K_TARGET_ITEM_CODES = ("3.01", "4.01", "4.02", "5.02")
EIGHT_K_ITEM_CODE_RE = re.compile(r"(?:\bitem\s*)?([0-9]{1,2}\.[0-9]{2})", re.IGNORECASE)
AMENDMENT_NOTE_HEADING_RE = re.compile(
    r"\b(EXPLANATORY NOTES?|NOTE REGARDING AMENDMENT|INTRODUCTORY NOTE)\b",
    re.IGNORECASE,
)
AMENDMENT_MAJOR_HEADING_RE = re.compile(
    r"\b(PART\s+(?:I|II|III|IV)\b|ITEM\s+[0-9]{1,2}(?:\.[0-9]{2})?\b|"
    r"SIGNATURES\b|EXHIBIT INDEX\b|TABLE OF CONTENTS\b)",
    re.IGNORECASE,
)
AMENDMENT_FINANCIAL_KEYWORD_RE = re.compile(
    r"\b(restat(?:e|ed|ement|ing)|correct(?:ed|ion|ing)?|error|misstatement|"
    r"non-reliance|nonreliance|previously issued financial)\b",
    re.IGNORECASE,
)
_LAST_REQUEST_AT = 0.0

XBRL_CORE_TAGS: Dict[str, Sequence[str]] = {
    "assets": ("Assets",),
    "liabilities": ("Liabilities", "LiabilitiesAndStockholdersEquity"),
    "revenues": (
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "receivables": ("AccountsReceivableNetCurrent", "ReceivablesNetCurrent"),
    "inventory": ("InventoryNet", "InventoryFinishedGoodsNetOfReserves"),
    "debt": ("LongTermDebtAndFinanceLeaseObligations", "LongTermDebt"),
    "debt_current": ("ShortTermBorrowings", "LongTermDebtCurrent"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "working_capital": ("WorkingCapital",),
}


def _xbrl_core_tag_sql() -> str:
    core_tags = sorted({tag.lower() for tags in XBRL_CORE_TAGS.values() for tag in tags})
    return ", ".join("'" + tag.replace("'", "''") + "'" for tag in core_tags)


@dataclass(frozen=True)
class SourceSpec:
    name: str
    kind: str
    page_url: Optional[str] = None
    direct_urls: Sequence[str] = ()
    note: str = ""


@dataclass(frozen=True)
class DagTask:
    name: str
    deps: Sequence[str]
    action: Callable[[], Dict[str, Path]]


class SimpleDagRunner:
    def __init__(self, *, state_dir: Path, resume: bool) -> None:
        self.state_dir = state_dir
        self.resume = bool(resume)
        self.completed: set[str] = set()
        self.outputs: Dict[str, Path] = {}
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _marker_path(self, name: str) -> Path:
        return self.state_dir / f"{name}.done.json"

    def _load_marker(self, name: str) -> Dict[str, Path]:
        payload = json.loads(self._marker_path(name).read_text(encoding="utf-8"))
        return {key: Path(value) for key, value in payload.get("outputs", {}).items()}

    def _write_marker(self, name: str, outputs: Dict[str, Path]) -> None:
        self._marker_path(name).write_text(
            json.dumps(
                {
                    "task": name,
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "outputs": {key: str(value) for key, value in outputs.items()},
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def run(self, tasks: Sequence[DagTask]) -> Dict[str, Path]:
        for task in tasks:
            missing = [dep for dep in task.deps if dep not in self.completed]
            if missing:
                raise RuntimeError(f"Task {task.name} cannot run before dependencies {missing}")
            marker = self._marker_path(task.name)
            if self.resume and marker.exists():
                task_outputs = self._load_marker(task.name)
            else:
                task_outputs = task.action()
                self._write_marker(task.name, task_outputs)
            self.outputs.update(task_outputs)
            self.completed.add(task.name)
        return self.outputs


SOURCE_SPECS: Dict[str, SourceSpec] = {
    "sec-bulk": SourceSpec(
        name="sec-bulk",
        kind="direct",
        direct_urls=(SEC_BULK_SUBMISSIONS_URL, SEC_BULK_COMPANYFACTS_URL),
    ),
    "fsds": SourceSpec(name="fsds", kind="page", page_url=SEC_FSDS_PAGE_URL),
    "notes": SourceSpec(name="notes", kind="page", page_url=SEC_NOTES_PAGE_URL),
    "comment-letters": SourceSpec(
        name="comment-letters",
        kind="daily-index",
        page_url=SEC_CORRESPONDENCE_URL,
        note="Uses SEC daily master indexes and filters UPLOAD/CORRESP forms.",
    ),
    "aaer": SourceSpec(name="aaer", kind="aaer", page_url=SEC_AAER_URL),
    "insider": SourceSpec(name="insider", kind="page", page_url=SEC_INSIDER_PAGE_URL),
    "13f": SourceSpec(name="13f", kind="page", page_url=SEC_13F_PAGE_URL),
    "edgar-logs": SourceSpec(name="edgar-logs", kind="page", page_url=SEC_EDGAR_LOGS_PAGE_URL),
    "market-structure": SourceSpec(
        name="market-structure", kind="page", page_url=SEC_MARKET_STRUCTURE_PAGE_URL
    ),
    "form-ap": SourceSpec(
        name="form-ap",
        kind="direct",
        direct_urls=(PCAOB_FORM_AP_ZIP_URL, PCAOB_FORM_AP_DICT_URL),
    ),
    "pcaob-inspections": SourceSpec(
        name="pcaob-inspections", kind="page", page_url=PCAOB_INSPECTIONS_PAGE_URL
    ),
}


def _session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    return session


def _rate_limited_get(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
    stream: bool = False,
) -> requests.Response:
    global _LAST_REQUEST_AT
    elapsed = time.monotonic() - _LAST_REQUEST_AT
    if elapsed < SEC_REQUEST_INTERVAL_SECONDS:
        time.sleep(SEC_REQUEST_INTERVAL_SECONDS - elapsed)
    response = session.get(url, timeout=timeout, stream=stream)
    _LAST_REQUEST_AT = time.monotonic()
    return response


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip()).strip("-").lower()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if chunk:
                digest.update(chunk)
    return digest.hexdigest()


def _metadata_path(path: Path) -> Path:
    return path.parent / f"{path.name}.meta.json"


def _write_metadata(
    *,
    path: Path,
    source_url: str,
    source_name: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    payload = {
        "source_name": source_name,
        "source_url": source_url,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": _hash_file(path),
        "size_bytes": path.stat().st_size,
        "parser_version": PARSER_VERSION,
        "schema_version": SCHEMA_VERSION,
    }
    if extra:
        payload.update(extra)
    meta_path = _metadata_path(path)
    meta_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return meta_path


def _verify_metadata_hash(path: Path) -> bool:
    meta_path = _metadata_path(path)
    if not meta_path.exists():
        return False
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    expected = payload.get("sha256")
    if not expected:
        return False
    actual = _hash_file(path)
    if actual != expected:
        raise ValueError(
            f"Hash mismatch for {path}: metadata sha256={expected}, actual sha256={actual}"
        )
    return True


def _download_file(
    url: str,
    dest: Path,
    *,
    source_name: str,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = 120,
    extra_metadata: Optional[Dict[str, Any]] = None,
    max_retries: int = 5,
    backoff_seconds: float = 2.0,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    session = _session(user_agent)
    tmp_dest = dest.with_name(f"{dest.name}.part")
    transient_statuses = {429, 500, 502, 503, 504}
    last_error: Optional[Exception] = None
    for attempt in range(1, int(max_retries) + 1):
        try:
            with _rate_limited_get(session, url, timeout=timeout, stream=True) as response:
                if response.status_code in transient_statuses:
                    raise requests.HTTPError(
                        f"Transient HTTP {response.status_code} for {url}",
                        response=response,
                    )
                response.raise_for_status()
                with tmp_dest.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            tmp_dest.replace(dest)
            _write_metadata(
                path=dest,
                source_url=url,
                source_name=source_name,
                extra=extra_metadata,
            )
            return dest
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            last_error = exc
            if tmp_dest.exists():
                tmp_dest.unlink()
            status = getattr(getattr(exc, "response", None), "status_code", None)
            should_retry = status in transient_statuses or status is None
            if attempt >= int(max_retries) or not should_retry:
                raise
            time.sleep(float(backoff_seconds) * (2 ** (attempt - 1)))
    if last_error is not None:
        raise last_error
    return dest


def _fetch_html(url: str, *, user_agent: str = DEFAULT_USER_AGENT, timeout: int = 60) -> str:
    session = _session(user_agent)
    response = _rate_limited_get(session, url, timeout=timeout)
    response.raise_for_status()
    return response.text


def _discover_links(
    page_url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    allowed_suffixes: Sequence[str] = (".zip", ".csv", ".json", ".xml", ".txt", ".xlsx", ".pdf"),
) -> pd.DataFrame:
    html = _fetch_html(page_url, user_agent=user_agent)
    links: List[Dict[str, Any]] = []
    for href in HREF_RE.findall(html):
        if href.startswith("#") or href.startswith("mailto:"):
            continue
        full_url = urljoin(page_url, href)
        parsed = urlparse(full_url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in allowed_suffixes:
            continue
        links.append(
            {
                "page_url": page_url,
                "url": full_url,
                "basename": Path(parsed.path).name,
                "suffix": suffix,
            }
        )
    return pd.DataFrame(links).drop_duplicates(subset=["url"]).reset_index(drop=True)


def _extract_aaer_release_links(
    page_url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
) -> pd.DataFrame:
    html = _fetch_html(page_url, user_agent=user_agent)
    rows: List[Dict[str, Any]] = []
    seen = set()
    for match in AAER_ROW_RE.finditer(html):
        full_url = urljoin(page_url, match.group("href"))
        if full_url in seen:
            continue
        seen.add(full_url)
        rows.append(
            {
                "page_url": page_url,
                "url": full_url,
                "basename": Path(urlparse(full_url).path).name or _slug(full_url),
                "suffix": Path(urlparse(full_url).path).suffix.lower() or ".html",
                "event_date": match.group("dt"),
                "title": re.sub(r"<[^>]+>", " ", match.group("title")).strip(),
            }
        )
    for href in AAER_LINK_RE.findall(html):
        full_url = urljoin(page_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        rows.append(
            {
                "page_url": page_url,
                "url": full_url,
                "basename": Path(urlparse(full_url).path).name or _slug(full_url),
                "suffix": Path(urlparse(full_url).path).suffix.lower() or ".html",
                "event_date": None,
                "title": None,
            }
        )
    return pd.DataFrame(rows)


def _filter_link_frame(
    frame: pd.DataFrame,
    *,
    start_year: Optional[int],
    end_year: Optional[int],
    match: Optional[str],
    limit_links: Optional[int],
) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = frame.copy()
    haystack = (work["url"].fillna("") + " " + work["basename"].fillna("")).str.lower()
    work["year_hint"] = pd.to_numeric(
        haystack.str.extract(r"(?P<year>20\d{2}|19\d{2})")["year"],
        errors="coerce",
    )
    if match:
        work = work.loc[haystack.str.contains(match.lower(), regex=False)].copy()
    if start_year is not None or end_year is not None:
        if start_year is not None:
            work = work.loc[
                work["year_hint"].isna() | work["year_hint"].ge(int(start_year))
            ].copy()
        if end_year is not None:
            work = work.loc[work["year_hint"].isna() | work["year_hint"].le(int(end_year))].copy()
    work = work.sort_values(["year_hint", "url"], ascending=[False, True], na_position="last")
    if limit_links:
        work = work.head(int(limit_links)).copy()
    return work.reset_index(drop=True)


def _iter_business_days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def _daily_master_index_url(day: date) -> str:
    quarter = (day.month - 1) // 3 + 1
    return (
        f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{quarter}/"
        f"master.{day.strftime('%Y%m%d')}.idx"
    )


def fetch_source_assets(
    *,
    mode: str,
    bronze_dir: Path,
    user_agent: str = DEFAULT_USER_AGENT,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    match: Optional[str] = None,
    limit_links: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    list_only: bool = False,
    force: bool = False,
) -> pd.DataFrame:
    if mode not in SOURCE_SPECS:
        raise ValueError(f"Unsupported source mode: {mode}")
    spec = SOURCE_SPECS[mode]
    source_dir = bronze_dir / mode
    source_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    if spec.kind == "direct":
        for url in spec.direct_urls:
            basename = Path(urlparse(url).path).name
            rows.append(
                {
                    "page_url": url,
                    "url": url,
                    "basename": basename,
                    "suffix": Path(basename).suffix,
                }
            )
        frame = pd.DataFrame(rows)
    elif spec.kind == "page":
        frame = _discover_links(spec.page_url or "", user_agent=user_agent)
        frame = _filter_link_frame(
            frame,
            start_year=start_year,
            end_year=end_year,
            match=match,
            limit_links=limit_links,
        )
    elif spec.kind == "aaer":
        listing_path = source_dir / "aaer_listing.html"
        if not list_only:
            _download_file(
                spec.page_url or SEC_AAER_URL,
                listing_path,
                source_name=mode,
                user_agent=user_agent,
                extra_metadata={"content_type": "text/html"},
            )
        frame = _extract_aaer_release_links(spec.page_url or SEC_AAER_URL, user_agent=user_agent)
        frame = _filter_link_frame(
            frame,
            start_year=start_year,
            end_year=end_year,
            match=match,
            limit_links=limit_links,
        )
    elif spec.kind == "daily-index":
        if start_date is None or end_date is None:
            raise ValueError("comment-letters mode requires start_date and end_date")
        start = pd.Timestamp(start_date).date()
        end = pd.Timestamp(end_date).date()
        frame = pd.DataFrame(
            [
                {
                    "page_url": spec.page_url,
                    "url": _daily_master_index_url(day),
                    "basename": f"master.{day:%Y%m%d}.idx",
                    "suffix": ".idx",
                }
                for day in _iter_business_days(start, end)
            ]
        )
    else:
        raise ValueError(f"Unsupported source kind: {spec.kind}")

    if frame.empty:
        manifest = pd.DataFrame(
            columns=["source_name", "url", "local_path", "page_url", "basename", "status"]
        )
        manifest.to_csv(source_dir / "manifest.csv", index=False)
        return manifest

    downloads: List[Dict[str, Any]] = []
    for _, row in frame.iterrows():
        parsed = urlparse(str(row["url"]))
        basename = row["basename"] or Path(parsed.path).name or _slug(str(row["url"]))
        dest = source_dir / basename
        status = "listed"
        if not list_only:
            if dest.exists() and not force:
                if _verify_metadata_hash(dest):
                    status = "cached"
                else:
                    _download_file(
                        str(row["url"]),
                        dest,
                        source_name=mode,
                        user_agent=user_agent,
                        extra_metadata={"page_url": row.get("page_url")},
                    )
                    status = "downloaded"
            else:
                _download_file(
                    str(row["url"]),
                    dest,
                    source_name=mode,
                    user_agent=user_agent,
                    extra_metadata={"page_url": row.get("page_url")},
                )
                status = "downloaded"
        downloads.append(
            {
                "source_name": mode,
                "page_url": row.get("page_url"),
                "url": row["url"],
                "basename": basename,
                "local_path": str(dest),
                "status": status,
            }
        )
    manifest = pd.DataFrame(downloads)
    manifest.to_csv(source_dir / "manifest.csv", index=False)
    return manifest


def _read_table_auto(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".csv"}:
        return pd.read_csv(path, low_memory=False)
    if suffix in {".txt", ".idx"}:
        sample = path.read_text(encoding="latin-1", errors="ignore").splitlines()[:20]
        if any("|" in line for line in sample):
            return pd.read_csv(path, sep="|", low_memory=False)
        if any("\t" in line for line in sample):
            return pd.read_csv(path, sep="\t", low_memory=False)
        return pd.read_csv(path, sep=r"\s{2,}", engine="python")
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".xml":
        return pd.read_xml(path)
    if suffix == ".xlsx":
        return pd.read_excel(path)
    raise ValueError(f"Unsupported table file type: {path}")


def _extract_zip_member_table(zip_path: Path, member: str) -> pd.DataFrame:
    with tempfile.TemporaryDirectory(prefix="public-lake-zip-") as tmp:
        tmp_path = Path(tmp) / Path(member).name
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(member) as source, tmp_path.open("wb") as dest:
                shutil.copyfileobj(source, dest)
        return _read_delimited_table(tmp_path)


def _read_table_sample(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]


def _read_delimited_table(path: Path) -> pd.DataFrame:
    sample = _read_table_sample(path)
    if any("\t" in line for line in sample):
        return pd.read_csv(path, sep="\t", low_memory=False)
    if any("|" in line for line in sample):
        return pd.read_csv(path, sep="|", low_memory=False)
    return pd.read_csv(path, low_memory=False)


def _extract_zip_member_to_path(zf: zipfile.ZipFile, member: str, dest_dir: Path) -> Path:
    dest = dest_dir / Path(member).name
    with zf.open(member) as source, dest.open("wb") as handle:
        shutil.copyfileobj(source, handle)
    return dest


def _require_duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("DuckDB engine requested but duckdb is not installed.") from exc
    return duckdb


def _duckdb_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _duckdb_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _duckdb_path_list(paths: Sequence[Path]) -> str:
    return "[" + ", ".join(f"'{_duckdb_path(path)}'" for path in paths) + "]"


def _duckdb_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _duckdb_sec_date_string_expr(sql_expr: str) -> str:
    cleaned = f"regexp_replace(trim(CAST({sql_expr} AS VARCHAR)), '[.]0$', '')"
    return f"CASE WHEN regexp_full_match({cleaned}, '[0-9]{{8}}') THEN {cleaned} ELSE NULL END"


def _duckdb_sec_date_expr(sql_expr: str) -> str:
    return f"try_strptime({_duckdb_sec_date_string_expr(sql_expr)}, '%Y%m%d')"


def _duckdb_sec_year_expr(sql_expr: str) -> str:
    return f"try_cast(substr({_duckdb_sec_date_string_expr(sql_expr)}, 1, 4) AS INTEGER)"


def _duckdb_timestamp_expr(sql_expr: str) -> str:
    return f"try_cast({sql_expr} AS TIMESTAMP)"


def _duckdb_cik_expr(sql_expr: str) -> str:
    digits = f"regexp_replace(CAST({sql_expr} AS VARCHAR), '[^0-9]', '', 'g')"
    return (
        "CASE "
        f"WHEN nullif({digits}, '') IS NULL THEN NULL "
        f"WHEN try_cast({digits} AS BIGINT) IS NULL THEN NULL "
        f"WHEN try_cast({digits} AS BIGINT) <= 0 THEN NULL "
        f"ELSE lpad(CAST(try_cast({digits} AS BIGINT) AS VARCHAR), 10, '0') "
        "END"
    )


def _duckdb_string_expr(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _duckdb_columns(con: Any, source_sql: str) -> List[str]:
    return [str(row[0]) for row in con.execute(f"DESCRIBE SELECT * FROM {source_sql}").fetchall()]


def _duckdb_connect(
    *,
    threads: int,
    memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    temp_directory: Path | str | None = None,
    max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> Any:
    duckdb = _require_duckdb()
    con = duckdb.connect(database=":memory:")
    con.execute(f"PRAGMA threads={max(1, int(threads))}")
    con.execute("SET preserve_insertion_order = false")
    if memory_limit:
        con.execute(f"SET memory_limit = {_duckdb_literal(memory_limit)}")
    if temp_directory:
        Path(temp_directory).mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory = {_duckdb_literal(temp_directory)}")
    if max_temp_directory_size:
        con.execute(f"SET max_temp_directory_size = {_duckdb_literal(max_temp_directory_size)}")
    return con


def _duckdb_read_csv(
    path: Path,
    *,
    threads: int,
    columns: Optional[Sequence[str]] = None,
    memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    temp_directory: Path | str | None = None,
    max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> pd.DataFrame:
    select_expr = "*"
    if columns is not None:
        select_expr = ", ".join(_duckdb_identifier(col) for col in columns)
    con = _duckdb_connect(
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        max_temp_directory_size=max_temp_directory_size,
    )
    try:
        return con.execute(
            f"""
            SELECT {select_expr}
            FROM read_csv_auto('{_duckdb_path(path)}', union_by_name=true, sample_size=-1)
            """
        ).fetchdf()
    finally:
        con.close()


def _duckdb_copy_query_to_csv(
    *,
    query: str,
    dest: Path,
    threads: int,
    memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    temp_directory: Path | str | None = None,
    max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    con = _duckdb_connect(
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        max_temp_directory_size=max_temp_directory_size,
    )
    try:
        con.execute(
            f"""
            COPY ({query})
            TO '{_duckdb_path(dest)}'
            (HEADER, DELIMITER ',', COMPRESSION GZIP)
            """
        )
    finally:
        con.close()


def _duckdb_csv_source(paths: Sequence[Path] | Path) -> str:
    if isinstance(paths, Path):
        source_path = f"'{_duckdb_path(paths)}'"
    else:
        paths = list(paths)
        if not paths:
            raise ValueError("DuckDB CSV source requires at least one path")
        source_path = _duckdb_path_list(paths)
    return f"read_csv_auto({source_path}, union_by_name=true, sample_size=-1)"


def _duckdb_table_source(path: Path) -> str:
    if path.suffix.lower() == ".parquet" or path.is_dir():
        return parquet_scan_sql(path)
    return f"read_csv_auto('{_duckdb_path(path)}', union_by_name=true, sample_size=-1)"


def _preferred_table_path(directory: Path, stem: str) -> Path:
    parquet_path = directory / f"{stem}.parquet"
    legacy_csv_gz_path = directory / f"{stem}.csv.gz"
    if parquet_path.exists() or not legacy_csv_gz_path.exists():
        return parquet_path
    return legacy_csv_gz_path


def _duckdb_copy_query_to_parquet(
    *,
    query: str,
    dest: Path,
    threads: int,
    partition_by: Sequence[str] = (),
    overwrite: bool = True,
    memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    temp_directory: Path | str | None = None,
    max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> None:
    if overwrite:
        remove_table_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    options = ["FORMAT PARQUET", "COMPRESSION ZSTD"]
    if partition_by:
        options.append("PARTITION_BY (" + ", ".join(partition_by) + ")")
    con = _duckdb_connect(
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        max_temp_directory_size=max_temp_directory_size,
    )
    try:
        con.execute(
            f"""
            COPY ({query})
            TO '{_duckdb_path(dest)}'
            ({", ".join(options)})
            """
        )
    finally:
        con.close()


def _read_header_columns(path: Path) -> List[str]:
    first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    if "\t" in first_line:
        return first_line.split("\t")
    if "|" in first_line:
        return first_line.split("|")
    return first_line.split(",")


def _parse_sec_date_series(series: pd.Series) -> pd.Series:
    as_string = series.astype(str).str.replace(r"\.0$", "", regex=True)
    parsed = pd.to_datetime(as_string, format="%Y%m%d", errors="coerce")
    fallback = pd.to_datetime(series, errors="coerce", format="mixed")
    return parsed.fillna(fallback)


def _read_csv_with_engine(
    path: Path,
    *,
    date_cols: Sequence[str] = (),
    engine: str = "pandas",
    duckdb_threads: int = 4,
    duckdb_memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | str | None = None,
    duckdb_max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
    usecols: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet" or path.is_dir():
        return read_table(
            path,
            columns=usecols,
            date_cols=date_cols,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
            low_memory=False,
        )
    if engine == "duckdb":
        try:
            frame = _duckdb_read_csv(
                path,
                threads=duckdb_threads,
                columns=usecols,
                memory_limit=duckdb_memory_limit,
                temp_directory=duckdb_temp_directory,
                max_temp_directory_size=duckdb_max_temp_directory_size,
            )
        except Exception:
            read_kwargs: Dict[str, Any] = {"low_memory": False}
            if usecols is not None:
                read_kwargs["usecols"] = list(usecols)
            frame = pd.read_csv(path, **read_kwargs)
    else:
        read_kwargs: Dict[str, Any] = {"low_memory": False}
        if usecols is not None:
            read_kwargs["usecols"] = list(usecols)
        frame = pd.read_csv(path, **read_kwargs)
    for col in date_cols:
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], errors="coerce", format="mixed")
    return frame


def _pick_members(zf: zipfile.ZipFile, stem: str) -> List[str]:
    stem = stem.lower()
    return [name for name in zf.namelist() if Path(name).name.lower().startswith(stem)]


def _clean_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name).upper())
    clean = re.sub(
        r"\b(INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|HOLDINGS|HOLDING|THE)\b",
        " ",
        clean,
    )
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _normalize_cik_series(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").astype("Int64")
    out = numeric.astype(str).str.replace("<NA>", "", regex=False)
    out = out.mask(out.eq(""))
    return out.map(lambda value: str(value).zfill(10) if pd.notna(value) else pd.NA)


def _name_tokens(name: str) -> set[str]:
    clean = _clean_name(name)
    return {token for token in clean.split() if len(token) >= 3}


def _best_aaer_issuer_match(
    title: str,
    issuer_pairs: pd.DataFrame,
) -> Dict[str, object]:
    title_tokens = _name_tokens(title)
    best: Dict[str, object] = {"issuer_cik": "", "score": 0.0, "method": "unmatched"}
    if len(title_tokens) < 2:
        return best

    for _, issuer in issuer_pairs.iterrows():
        issuer_tokens = issuer["entity_tokens"]
        if len(issuer_tokens) < 2:
            continue
        overlap = issuer_tokens & title_tokens
        score = len(overlap) / len(issuer_tokens)
        if score == 1.0 and len(overlap) >= 2:
            return {
                "issuer_cik": issuer["issuer_cik"],
                "score": float(score),
                "method": "token_all",
            }
        if score > float(best["score"]):
            best = {
                "issuer_cik": issuer["issuer_cik"],
                "score": float(score),
                "method": "token_partial",
            }
    if float(best["score"]) < 1.0:
        best["issuer_cik"] = ""
        best["method"] = "unmatched_low_confidence"
    return best


def normalize_submissions_bulk(
    *,
    submissions_zip: Path,
    silver_dir: Path,
    max_ciks: Optional[int] = None,
) -> Dict[str, Path]:
    issuer_rows: List[Dict[str, Any]] = []
    filing_rows: List[Dict[str, Any]] = []

    with zipfile.ZipFile(submissions_zip) as zf:
        members = [name for name in zf.namelist() if Path(name).suffix.lower() == ".json"]
        members = sorted(members)
        if max_ciks:
            members = members[: int(max_ciks)]
        for name in members:
            with zf.open(name) as handle:
                payload = json.load(handle)

            cik = str(payload.get("cik", "")).zfill(10)
            issuer_rows.append(
                {
                    "issuer_cik": cik,
                    "entity_name": payload.get("name"),
                    "sic": payload.get("sic"),
                    "sic_description": payload.get("sicDescription"),
                    "owner_org": payload.get("ownerOrg"),
                    "ein": payload.get("ein"),
                    "description": payload.get("description"),
                    "state_of_incorporation": payload.get("stateOfIncorporation"),
                    "state_of_incorporation_description": payload.get(
                        "stateOfIncorporationDescription"
                    ),
                    "fiscal_year_end": payload.get("fiscalYearEnd"),
                    "entity_type": payload.get("entityType"),
                    "phone": payload.get("phone"),
                    "flags": payload.get("flags"),
                    "tickers_json": json.dumps(payload.get("tickers", [])),
                    "exchanges_json": json.dumps(payload.get("exchanges", [])),
                    "former_names_json": json.dumps(payload.get("formerNames", [])),
                    "source_file": name,
                }
            )

            recent = payload.get("filings", {}).get("recent", {})
            if not recent:
                continue
            recent_df = pd.DataFrame(recent)
            if recent_df.empty:
                continue
            recent_df["issuer_cik"] = cik
            recent_df["source_file"] = name
            filing_rows.extend(recent_df.to_dict(orient="records"))

    issuer_dim = pd.DataFrame(issuer_rows).drop_duplicates(subset=["issuer_cik"])
    filing_dim = pd.DataFrame(filing_rows)
    if filing_dim.empty:
        filing_dim = pd.DataFrame(
            columns=[
                "issuer_cik",
                "accessionNumber",
                "filingDate",
                "reportDate",
                "acceptanceDateTime",
                "act",
                "form",
                "fileNumber",
                "filmNumber",
                "items",
                "size",
                "isXBRL",
                "isInlineXBRL",
                "primaryDocument",
                "primaryDocDescription",
                "source_file",
            ]
        )
    filing_dim = filing_dim.rename(
        columns={
            "accessionNumber": "accession",
            "filingDate": "filing_date",
            "reportDate": "report_date",
            "acceptanceDateTime": "acceptance_datetime",
            "fileNumber": "file_number",
            "filmNumber": "film_number",
            "primaryDocument": "primary_document",
            "primaryDocDescription": "primary_doc_description",
        }
    )
    filing_dim["issuer_cik"] = filing_dim["issuer_cik"].astype(str).str.zfill(10)
    filing_dim["accession"] = filing_dim["accession"].astype(str)
    filing_dim["accession_nodash"] = filing_dim["accession"].str.replace("-", "", regex=False)
    for col in ["filing_date", "report_date", "acceptance_datetime"]:
        filing_dim[col] = pd.to_datetime(filing_dim[col], errors="coerce")
    if "items" in filing_dim.columns:
        filing_dim["items"] = filing_dim["items"].fillna("").astype(str)
    filing_dim["form"] = filing_dim["form"].fillna("").astype(str)
    filing_dim = filing_dim.drop_duplicates(subset=["issuer_cik", "accession"])

    silver_dir.mkdir(parents=True, exist_ok=True)
    issuer_path = silver_dir / "issuer_dim.parquet"
    filing_path = silver_dir / "filing_dim.parquet"
    write_table(issuer_dim, issuer_path)
    write_table(filing_dim, filing_path)
    return {"issuer_dim": issuer_path, "filing_dim": filing_path}


def normalize_fsds_archive(
    *,
    archive_path: Path,
    silver_dir: Path,
    engine: str = "pandas",
    duckdb_threads: int = 4,
) -> Dict[str, Path]:
    if engine == "duckdb":
        return _normalize_fsds_archive_duckdb(
            archive_path=archive_path,
            silver_dir=silver_dir,
            duckdb_threads=duckdb_threads,
        )

    with zipfile.ZipFile(archive_path) as zf:
        sub_members = _pick_members(zf, "sub")
        num_members = _pick_members(zf, "num")
        if not sub_members or not num_members:
            raise ValueError(f"Could not find sub/num tables in {archive_path}")
        sub_df = _extract_zip_member_table(archive_path, sub_members[0])
        num_df = _extract_zip_member_table(archive_path, num_members[0])

    filing_xbrl = sub_df.rename(
        columns={
            "adsh": "adsh",
            "cik": "issuer_cik",
            "name": "entity_name",
            "sic": "sic",
            "countryba": "country_business",
            "stprba": "state_business",
            "form": "form",
            "period": "fiscal_period_end",
            "filed": "filing_date",
            "accepted": "acceptance_datetime",
            "fy": "fiscal_year",
            "fp": "fiscal_period",
        }
    )
    for col in ["issuer_cik"]:
        if col in filing_xbrl.columns:
            filing_xbrl[col] = _normalize_cik_series(filing_xbrl[col])
    for col in ["fiscal_period_end", "filing_date"]:
        if col in filing_xbrl.columns:
            filing_xbrl[col] = pd.to_datetime(filing_xbrl[col], errors="coerce")
    xbrl_fact = num_df.rename(
        columns={
            "adsh": "adsh",
            "tag": "tag",
            "version": "taxonomy_version",
            "ddate": "fact_date",
            "qtrs": "quarters",
            "uom": "unit",
            "value": "value",
            "coreg": "coreg",
            "footnote": "footnote",
        }
    )
    if "fact_date" in xbrl_fact.columns:
        xbrl_fact["fact_date"] = _parse_sec_date_series(xbrl_fact["fact_date"])
    silver_dir.mkdir(parents=True, exist_ok=True)
    filing_path = silver_dir / "filing_xbrl_dim.parquet"
    fact_path = silver_dir / "xbrl_fact.parquet"
    write_table(filing_xbrl, filing_path)
    write_table(xbrl_fact, fact_path)
    return {"filing_xbrl_dim": filing_path, "xbrl_fact": fact_path}


def _normalize_fsds_archive_duckdb(
    *,
    archive_path: Path,
    silver_dir: Path,
    duckdb_threads: int,
) -> Dict[str, Path]:
    with tempfile.TemporaryDirectory(prefix="public-lake-fsds-") as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(archive_path) as zf:
            sub_members = _pick_members(zf, "sub")
            num_members = _pick_members(zf, "num")
            if not sub_members or not num_members:
                raise ValueError(f"Could not find sub/num tables in {archive_path}")
            sub_path_tmp = _extract_zip_member_to_path(zf, sub_members[0], tmp_dir)
            num_path_tmp = _extract_zip_member_to_path(zf, num_members[0], tmp_dir)

        sub_df = _read_delimited_table(sub_path_tmp)
        filing_xbrl = sub_df.rename(
            columns={
                "adsh": "adsh",
                "cik": "issuer_cik",
                "name": "entity_name",
                "sic": "sic",
                "countryba": "country_business",
                "stprba": "state_business",
                "form": "form",
                "period": "fiscal_period_end",
                "filed": "filing_date",
                "accepted": "acceptance_datetime",
                "fy": "fiscal_year",
                "fp": "fiscal_period",
            }
        )
        if "issuer_cik" in filing_xbrl.columns:
            filing_xbrl["issuer_cik"] = _normalize_cik_series(filing_xbrl["issuer_cik"])
        for col in ["fiscal_period_end", "filing_date"]:
            if col in filing_xbrl.columns:
                filing_xbrl[col] = _parse_sec_date_series(filing_xbrl[col])
        if "acceptance_datetime" in filing_xbrl.columns:
            filing_xbrl["acceptance_datetime"] = pd.to_datetime(
                filing_xbrl["acceptance_datetime"], errors="coerce", format="mixed"
            )

        silver_dir.mkdir(parents=True, exist_ok=True)
        filing_path = silver_dir / "filing_xbrl_dim.parquet"
        fact_path = silver_dir / "xbrl_fact.parquet"
        write_table(filing_xbrl, filing_path)

        source = (
            f"read_csv_auto('{_duckdb_path(num_path_tmp)}', union_by_name=true, sample_size=-1)"
        )
        fact_query = f"""
            SELECT
                adsh,
                tag,
                version AS taxonomy_version,
                {_duckdb_sec_date_expr("ddate")} AS fact_date,
                qtrs AS quarters,
                uom AS unit,
                try_cast(value AS DOUBLE) AS value,
                coreg,
                footnote
            FROM {source}
        """
        _duckdb_copy_query_to_parquet(query=fact_query, dest=fact_path, threads=duckdb_threads)
    return {"filing_xbrl_dim": filing_path, "xbrl_fact": fact_path}


def normalize_notes_archive(
    *,
    archive_path: Path,
    silver_dir: Path,
    engine: str = "pandas",
    duckdb_threads: int = 4,
) -> Dict[str, Path]:
    if engine == "duckdb":
        return _normalize_notes_archive_duckdb(
            archive_path=archive_path,
            silver_dir=silver_dir,
            duckdb_threads=duckdb_threads,
        )

    with zipfile.ZipFile(archive_path) as zf:
        txt_members = [name for name in zf.namelist() if Path(name).name.lower().startswith("txt")]
        sub_members = _pick_members(zf, "sub")
        if not txt_members:
            raise ValueError(f"Could not find txt table in {archive_path}")
        note_df = _extract_zip_member_table(archive_path, txt_members[0])
        outputs: Dict[str, Path] = {}
        silver_dir.mkdir(parents=True, exist_ok=True)
        if sub_members:
            sub_df = _extract_zip_member_table(archive_path, sub_members[0])
            sub_path = silver_dir / "notes_filing_dim.parquet"
            write_table(sub_df, sub_path)
            outputs["notes_filing_dim"] = sub_path
    note_text = note_df.rename(
        columns={
            "adsh": "adsh",
            "tag": "tag",
            "version": "taxonomy_version",
            "ddate": "fact_date",
            "qtrs": "quarters",
            "text": "note_text",
            "txt": "note_text",
        }
    )
    if "fact_date" in note_text.columns:
        note_text["fact_date"] = _parse_sec_date_series(note_text["fact_date"])
    note_path = silver_dir / "note_text.parquet"
    write_table(note_text, note_path)
    outputs["note_text"] = note_path
    return outputs


def _normalize_notes_archive_duckdb(
    *,
    archive_path: Path,
    silver_dir: Path,
    duckdb_threads: int,
) -> Dict[str, Path]:
    outputs: Dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="public-lake-notes-") as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(archive_path) as zf:
            txt_members = [
                name for name in zf.namelist() if Path(name).name.lower().startswith("txt")
            ]
            sub_members = _pick_members(zf, "sub")
            if not txt_members:
                raise ValueError(f"Could not find txt table in {archive_path}")
            txt_path_tmp = _extract_zip_member_to_path(zf, txt_members[0], tmp_dir)
            sub_path_tmp = (
                _extract_zip_member_to_path(zf, sub_members[0], tmp_dir) if sub_members else None
            )

        silver_dir.mkdir(parents=True, exist_ok=True)
        if sub_path_tmp is not None:
            sub_df = _read_delimited_table(sub_path_tmp)
            sub_path = silver_dir / "notes_filing_dim.parquet"
            write_table(sub_df, sub_path)
            outputs["notes_filing_dim"] = sub_path

        columns = set(_read_header_columns(txt_path_tmp))
        text_col = "txt" if "txt" in columns else "text" if "text" in columns else None
        note_expr = _duckdb_identifier(text_col) if text_col else "NULL"
        source = (
            f"read_csv_auto('{_duckdb_path(txt_path_tmp)}', union_by_name=true, sample_size=-1)"
        )
        note_query = f"""
            SELECT
                adsh,
                tag,
                version AS taxonomy_version,
                {_duckdb_sec_date_expr("ddate")} AS fact_date,
                qtrs AS quarters,
                {note_expr} AS note_text
            FROM {source}
        """
        note_path = silver_dir / "note_text.parquet"
        _duckdb_copy_query_to_parquet(query=note_query, dest=note_path, threads=duckdb_threads)
        outputs["note_text"] = note_path
    return outputs


def normalize_form_ap_csv(*, form_ap_csv: Path, silver_dir: Path) -> Path:
    df = pd.read_csv(form_ap_csv, low_memory=False)
    col_map = {
        "Form Filing ID": "form_filing_id",
        "Issuer CIK": "issuer_cik",
        "Issuer Name": "issuer_name",
        "Firm ID": "pcaob_firm_id",
        "Firm Name": "pcaob_firm_name",
        "Engagement Partner ID": "engagement_partner_id",
        "Engagement Partner Name": "engagement_partner_name",
        "Fiscal Period End Date": "fiscal_period_end",
        "Report Date": "report_date",
        "Filing Date": "filing_date",
        "Number of Participants": "number_of_participants",
        "Participant Percentage": "participant_percentage",
    }
    work = df.rename(columns={src: dst for src, dst in col_map.items() if src in df.columns})
    if "issuer_cik" in work.columns:
        work["issuer_cik"] = _normalize_cik_series(work["issuer_cik"])
    for col in ["fiscal_period_end", "report_date", "filing_date"]:
        if col in work.columns:
            work[col] = pd.to_datetime(work[col], errors="coerce", format="mixed")
    silver_dir.mkdir(parents=True, exist_ok=True)
    out_path = silver_dir / "form_ap_event.parquet"
    write_table(work, out_path)
    return out_path


def normalize_pcaob_inspection_file(*, inspection_path: Path, silver_dir: Path) -> Path:
    frame = _read_table_auto(inspection_path)
    lower_map = {col.lower(): col for col in frame.columns}
    standardized = pd.DataFrame()
    col_candidates = {
        "pcaob_firm_id": ["firm id", "firmid", "firm_id", "firm number"],
        "inspection_public_date": [
            "publication date",
            "public release date",
            "report date",
            "date",
        ],
        "inspection_year": ["inspection year", "year"],
        "part_ia_findings": ["part i.a", "part ia", "part i a", "part1a"],
        "part_ib_findings": ["part i.b", "part ib", "part i b", "part1b"],
        "inspection_cycle": ["inspection cycle", "cycle"],
        "firm_name": ["firm name"],
    }
    for target, names in col_candidates.items():
        for name in names:
            if name in lower_map:
                standardized[target] = frame[lower_map[name]]
                break
    if "inspection_public_date" in standardized.columns:
        standardized["inspection_public_date"] = pd.to_datetime(
            standardized["inspection_public_date"], errors="coerce", format="mixed"
        )
    if "pcaob_firm_id" in standardized.columns:
        standardized["pcaob_firm_id"] = pd.to_numeric(
            standardized["pcaob_firm_id"], errors="coerce"
        ).astype("Int64")
    standardized["source_file"] = str(inspection_path)
    silver_dir.mkdir(parents=True, exist_ok=True)
    out_path = silver_dir / "pcaob_inspection_event.csv.gz"
    standardized.to_csv(out_path, index=False, compression="gzip")
    return out_path


def _append_csv_gzip(source_csv: Path, dest_csv: Path) -> None:
    dest_csv.parent.mkdir(parents=True, exist_ok=True)
    header = not dest_csv.exists()
    for chunk in pd.read_csv(source_csv, chunksize=CSV_CHUNKSIZE, low_memory=False):
        chunk.to_csv(
            dest_csv,
            mode="a",
            index=False,
            header=header,
            compression="gzip",
        )
        header = False


def _normalize_manifest_archives(
    *,
    manifest_csv: Path,
    silver_dir: Path,
    normalizer_name: str,
    engine: str = "pandas",
    duckdb_threads: int = 4,
) -> Dict[str, Path]:
    normalizers = {
        "fsds": normalize_fsds_archive,
        "notes": normalize_notes_archive,
    }
    normalizer = normalizers[normalizer_name]
    manifest = pd.read_csv(manifest_csv)
    outputs: Dict[str, Path] = {}
    parquet_parts: Dict[str, List[Path]] = {}
    temporary_root = silver_dir / f"._tmp_{normalizer_name}"
    if temporary_root.exists():
        shutil.rmtree(temporary_root)

    for idx, row in manifest.iterrows():
        archive_path = Path(row["local_path"])
        if not archive_path.exists() or archive_path.suffix.lower() != ".zip":
            continue
        _verify_metadata_hash(archive_path)
        tmp_dir = temporary_root / str(idx)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        archive_outputs = normalizer(
            archive_path=archive_path,
            silver_dir=tmp_dir,
            engine=engine,
            duckdb_threads=duckdb_threads,
        )
        for key, tmp_path in archive_outputs.items():
            dest_path = silver_dir / Path(tmp_path).name
            tmp_path = Path(tmp_path)
            if tmp_path.suffix.lower() == ".parquet" or tmp_path.is_dir():
                parquet_parts.setdefault(key, []).append(tmp_path)
            else:
                if key not in outputs and dest_path.exists():
                    dest_path.unlink()
                _append_csv_gzip(tmp_path, dest_path)
            outputs[key] = dest_path

    for key, parts in parquet_parts.items():
        dest_path = outputs[key]
        _duckdb_copy_query_to_parquet(
            query=f"SELECT * FROM {_parquet_source_from_files(parts)}",
            dest=dest_path,
            threads=duckdb_threads,
        )

    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    return outputs


def _extract_manifest_members(
    *,
    manifest_csv: Path,
    staging_dir: Path,
    required_stem: str,
    optional_stems: Sequence[str] = (),
) -> Dict[str, List[Path]]:
    manifest = pd.read_csv(manifest_csv)
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    extracted: Dict[str, List[Path]] = {required_stem: []}
    for stem in optional_stems:
        extracted[stem] = []

    for idx, row in manifest.iterrows():
        archive_path = Path(row["local_path"])
        if not archive_path.exists() or archive_path.suffix.lower() != ".zip":
            continue
        _verify_metadata_hash(archive_path)
        archive_dir = staging_dir / f"archive_{idx}"
        archive_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as zf:
            required_members = _pick_members(zf, required_stem)
            if not required_members:
                raise ValueError(f"Could not find {required_stem} table in {archive_path}")
            extracted[required_stem].append(
                _extract_zip_member_to_path(zf, required_members[0], archive_dir)
            )
            for stem in optional_stems:
                members = _pick_members(zf, stem)
                if members:
                    extracted[stem].append(
                        _extract_zip_member_to_path(zf, members[0], archive_dir)
                    )
    return extracted


def _manifest_archive_paths(manifest_csv: Path) -> List[Path]:
    manifest = pd.read_csv(manifest_csv)
    paths: List[Path] = []
    if "local_path" not in manifest.columns:
        return paths
    for raw_path in manifest["local_path"].dropna():
        archive_path = Path(str(raw_path))
        if archive_path.exists() and archive_path.suffix.lower() == ".zip":
            paths.append(archive_path)
    return paths


def _batch_name(batch_index: int) -> str:
    return f"batch_{batch_index:04d}"


def _batched_paths(paths: Sequence[Path], batch_size: int) -> Iterable[Tuple[str, List[Path]]]:
    size = max(1, int(batch_size))
    for batch_index, start in enumerate(range(0, len(paths), size)):
        yield _batch_name(batch_index), list(paths[start : start + size])


def _extract_archive_members_batch(
    *,
    archive_paths: Sequence[Path],
    staging_dir: Path,
    required_stem: str,
    optional_stems: Sequence[str] = (),
) -> Dict[str, List[Path]]:
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    extracted: Dict[str, List[Path]] = {required_stem: []}
    for stem in optional_stems:
        extracted[stem] = []

    for idx, archive_path in enumerate(archive_paths):
        _verify_metadata_hash(archive_path)
        archive_dir = staging_dir / f"archive_{idx:04d}"
        archive_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as zf:
            required_members = _pick_members(zf, required_stem)
            if not required_members:
                raise ValueError(f"Could not find {required_stem} table in {archive_path}")
            extracted[required_stem].append(
                _extract_zip_member_to_path(zf, required_members[0], archive_dir)
            )
            for stem in optional_stems:
                members = _pick_members(zf, stem)
                if members:
                    extracted[stem].append(
                        _extract_zip_member_to_path(zf, members[0], archive_dir)
                    )
    return extracted


def _batch_marker_path(state_dir: Path, batch_name: str) -> Path:
    return state_dir / f"{batch_name}.done.json"


def _batch_marker_outputs_exist(marker_path: Path) -> bool:
    if not marker_path.exists():
        return False
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    for value in payload.get("outputs", {}).values():
        if not Path(value).exists():
            return False
    return True


def _write_batch_marker(
    *,
    state_dir: Path,
    batch_name: str,
    archive_paths: Sequence[Path],
    outputs: Dict[str, Path],
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    _batch_marker_path(state_dir, batch_name).write_text(
        json.dumps(
            {
                "batch": batch_name,
                "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "inputs": [str(path) for path in archive_paths],
                "outputs": {key: str(path) for key, path in outputs.items()},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _parquet_files(path: Path) -> List[Path]:
    if not path.exists():
        return []
    if path.is_dir():
        return sorted(path.rglob("*.parquet"))
    if path.suffix.lower() == ".parquet":
        return [path]
    return []


def _parquet_source_from_files(files: Sequence[Path]) -> str:
    paths = list(files)
    if not paths:
        raise ValueError("Parquet source requires at least one file")
    return f"read_parquet({_duckdb_path_list(paths)}, hive_partitioning=true)"


def _copy_parquet_query_from_parts(
    *,
    parts_dir: Path,
    dest: Path,
    query: str,
    threads: int,
    memory_limit: str | None,
    temp_directory: Path | str | None,
    max_temp_directory_size: str | None,
) -> bool:
    files = _parquet_files(parts_dir)
    if not files:
        return False
    source = _parquet_source_from_files(files)
    _duckdb_copy_query_to_parquet(
        query=query.format(source=source),
        dest=dest,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        max_temp_directory_size=max_temp_directory_size,
    )
    return True


def _assert_no_duplicate_parquet_key(
    *,
    parts_dir: Path,
    key: str,
    label: str,
    threads: int,
    memory_limit: str | None,
    temp_directory: Path | str | None,
    max_temp_directory_size: str | None,
) -> None:
    files = _parquet_files(parts_dir)
    if not files:
        return
    source = _parquet_source_from_files(files)
    con = _duckdb_connect(
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        max_temp_directory_size=max_temp_directory_size,
    )
    try:
        duplicate_rows = con.execute(
            f"""
            SELECT count(*)::BIGINT
            FROM (
                SELECT {_duckdb_identifier(key)}
                FROM {source}
                GROUP BY {_duckdb_identifier(key)}
                HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
    finally:
        con.close()
    if int(duplicate_rows) > 0:
        raise ValueError(
            f"{label} has {duplicate_rows} duplicate {key} keys across archive batches; "
            "cannot finalize exact Parquet summary from batch-level aggregates."
        )


def _normalize_fsds_manifest_parquet(
    *,
    manifest_csv: Path,
    silver_dir: Path,
    duckdb_threads: int,
    duckdb_memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | str | None = None,
    duckdb_max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
    batch_size: int = DEFAULT_FSDS_BATCH_SIZE,
    resume: bool = False,
) -> Dict[str, Path]:
    outputs: Dict[str, Path] = {}
    archive_paths = _manifest_archive_paths(manifest_csv)
    if not archive_paths:
        return outputs
    silver_dir.mkdir(parents=True, exist_ok=True)
    staging_root = silver_dir / "._staging_fsds"
    batch_state_dir = silver_dir / ".public_lake_dag" / "normalize_fsds_batches"
    parts_root = silver_dir / "._fsds_parquet_parts"
    filing_parts = parts_root / "filing_xbrl_dim"
    summary_parts = parts_root / "xbrl_fact_summary"
    core_path = silver_dir / "xbrl_core_fact"

    if not resume:
        remove_table_path(parts_root)
        remove_table_path(core_path)
        remove_table_path(silver_dir / "filing_xbrl_dim.parquet")
        remove_table_path(silver_dir / "xbrl_fact_summary.parquet")
        remove_table_path(batch_state_dir)

    for batch_name, batch_paths in _batched_paths(archive_paths, batch_size):
        marker = _batch_marker_path(batch_state_dir, batch_name)
        if resume and _batch_marker_outputs_exist(marker):
            continue
        batch_staging = staging_root / batch_name
        batch_outputs: Dict[str, Path] = {}
        try:
            extracted = _extract_archive_members_batch(
                archive_paths=batch_paths,
                staging_dir=batch_staging,
                required_stem="num",
                optional_stems=("sub",),
            )
            num_paths = extracted["num"]
            sub_paths = extracted.get("sub", [])
            if not num_paths:
                _write_batch_marker(
                    state_dir=batch_state_dir,
                    batch_name=batch_name,
                    archive_paths=batch_paths,
                    outputs=batch_outputs,
                )
                continue

            if sub_paths:
                filing_part = filing_parts / f"part_batch={batch_name}" / "data.parquet"
                sub_source = _duckdb_csv_source(sub_paths)
                filing_query = f"""
                    SELECT
                        adsh,
                        CASE
                            WHEN try_cast(cik AS BIGINT) IS NULL THEN NULL
                            ELSE lpad(CAST(try_cast(cik AS BIGINT) AS VARCHAR), 10, '0')
                        END AS issuer_cik,
                        name AS entity_name,
                        sic,
                        countryba AS country_business,
                        stprba AS state_business,
                        form,
                        try_strptime(CAST(period AS VARCHAR), '%Y%m%d') AS fiscal_period_end,
                        try_strptime(CAST(filed AS VARCHAR), '%Y%m%d') AS filing_date,
                        try_cast(accepted AS TIMESTAMP) AS acceptance_datetime,
                        fy AS fiscal_year,
                        fp AS fiscal_period
                    FROM {sub_source}
                """
                _duckdb_copy_query_to_parquet(
                    query=filing_query,
                    dest=filing_part,
                    threads=duckdb_threads,
                    memory_limit=duckdb_memory_limit,
                    temp_directory=duckdb_temp_directory,
                    max_temp_directory_size=duckdb_max_temp_directory_size,
                )
                batch_outputs["filing_xbrl_dim_part"] = filing_part

            num_source = _duckdb_csv_source(num_paths)
            summary_part = summary_parts / f"part_batch={batch_name}" / "data.parquet"
            summary_query = f"""
                SELECT
                    adsh,
                    count(tag)::BIGINT AS xbrl_fact_count,
                    count(DISTINCT tag)::BIGINT AS xbrl_unique_tags,
                    count(DISTINCT uom)::BIGINT AS xbrl_unique_units
                FROM {num_source}
                GROUP BY adsh
            """
            _duckdb_copy_query_to_parquet(
                query=summary_query,
                dest=summary_part,
                threads=duckdb_threads,
                memory_limit=duckdb_memory_limit,
                temp_directory=duckdb_temp_directory,
                max_temp_directory_size=duckdb_max_temp_directory_size,
            )
            batch_outputs["xbrl_fact_summary_part"] = summary_part

            core_part = core_path / f"part_batch={batch_name}" / "data.parquet"
            core_query = f"""
                SELECT
                    adsh,
                    tag,
                    uom AS unit,
                    try_cast(value AS DOUBLE) AS value,
                    try_cast(qtrs AS DOUBLE) AS quarters,
                    {_duckdb_sec_date_expr("ddate")} AS fact_date,
                    {_duckdb_sec_year_expr("ddate")} AS source_year
                FROM {num_source}
                WHERE lower(CAST(tag AS VARCHAR)) IN ({_xbrl_core_tag_sql()})
                  AND try_cast(value AS DOUBLE) IS NOT NULL
                  AND (
                        uom IS NULL
                        OR upper(CAST(uom AS VARCHAR)) IN ('', 'USD')
                      )
            """
            _duckdb_copy_query_to_parquet(
                query=core_query,
                dest=core_part,
                threads=duckdb_threads,
                memory_limit=duckdb_memory_limit,
                temp_directory=duckdb_temp_directory,
                max_temp_directory_size=duckdb_max_temp_directory_size,
            )
            batch_outputs["xbrl_core_fact_part"] = core_part
            _write_batch_marker(
                state_dir=batch_state_dir,
                batch_name=batch_name,
                archive_paths=batch_paths,
                outputs=batch_outputs,
            )
        finally:
            if batch_staging.exists():
                shutil.rmtree(batch_staging)

    if staging_root.exists():
        shutil.rmtree(staging_root)

    filing_path = silver_dir / "filing_xbrl_dim.parquet"
    _assert_no_duplicate_parquet_key(
        parts_dir=filing_parts,
        key="adsh",
        label="filing_xbrl_dim",
        threads=duckdb_threads,
        memory_limit=duckdb_memory_limit,
        temp_directory=duckdb_temp_directory,
        max_temp_directory_size=duckdb_max_temp_directory_size,
    )
    if _copy_parquet_query_from_parts(
        parts_dir=filing_parts,
        dest=filing_path,
        query="""
            SELECT
                adsh,
                issuer_cik,
                entity_name,
                sic,
                country_business,
                state_business,
                form,
                fiscal_period_end,
                filing_date,
                acceptance_datetime,
                fiscal_year,
                fiscal_period
            FROM {source}
            ORDER BY adsh
        """,
        threads=duckdb_threads,
        memory_limit=duckdb_memory_limit,
        temp_directory=duckdb_temp_directory,
        max_temp_directory_size=duckdb_max_temp_directory_size,
    ):
        outputs["filing_xbrl_dim"] = filing_path

    summary_path = silver_dir / "xbrl_fact_summary.parquet"
    _assert_no_duplicate_parquet_key(
        parts_dir=summary_parts,
        key="adsh",
        label="xbrl_fact_summary",
        threads=duckdb_threads,
        memory_limit=duckdb_memory_limit,
        temp_directory=duckdb_temp_directory,
        max_temp_directory_size=duckdb_max_temp_directory_size,
    )
    if _copy_parquet_query_from_parts(
        parts_dir=summary_parts,
        dest=summary_path,
        query="""
            SELECT
                adsh,
                sum(xbrl_fact_count)::BIGINT AS xbrl_fact_count,
                sum(xbrl_unique_tags)::BIGINT AS xbrl_unique_tags,
                sum(xbrl_unique_units)::BIGINT AS xbrl_unique_units
            FROM {source}
            GROUP BY adsh
            ORDER BY adsh
        """,
        threads=duckdb_threads,
        memory_limit=duckdb_memory_limit,
        temp_directory=duckdb_temp_directory,
        max_temp_directory_size=duckdb_max_temp_directory_size,
    ):
        outputs["xbrl_fact_summary"] = summary_path

    if _parquet_files(core_path):
        outputs["xbrl_core_fact"] = core_path
    return outputs


def _normalize_notes_manifest_parquet(
    *,
    manifest_csv: Path,
    silver_dir: Path,
    duckdb_threads: int,
    notes_mode: str,
    duckdb_memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | str | None = None,
    duckdb_max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
    batch_size: int = DEFAULT_NOTES_BATCH_SIZE,
    resume: bool = False,
) -> Dict[str, Path]:
    if notes_mode not in {"summary", "raw", "skip"}:
        raise ValueError("notes_mode must be 'summary', 'raw', or 'skip'")
    if notes_mode == "skip":
        return {}
    outputs: Dict[str, Path] = {}
    archive_paths = _manifest_archive_paths(manifest_csv)
    if not archive_paths:
        return outputs
    silver_dir.mkdir(parents=True, exist_ok=True)

    staging_root = silver_dir / "._staging_notes"
    batch_state_dir = silver_dir / ".public_lake_dag" / "normalize_notes_batches"
    parts_root = silver_dir / "._notes_parquet_parts"
    filing_parts = parts_root / "notes_filing_dim"
    summary_parts = parts_root / "note_summary"
    note_text_path = silver_dir / "note_text"

    if not resume:
        remove_table_path(parts_root)
        remove_table_path(note_text_path)
        remove_table_path(silver_dir / "notes_filing_dim.parquet")
        remove_table_path(silver_dir / "note_summary.parquet")
        remove_table_path(batch_state_dir)

    for batch_name, batch_paths in _batched_paths(archive_paths, batch_size):
        marker = _batch_marker_path(batch_state_dir, batch_name)
        if resume and _batch_marker_outputs_exist(marker):
            continue
        batch_staging = staging_root / batch_name
        batch_outputs: Dict[str, Path] = {}
        try:
            extracted = _extract_archive_members_batch(
                archive_paths=batch_paths,
                staging_dir=batch_staging,
                required_stem="txt",
                optional_stems=("sub",),
            )
            txt_paths = extracted["txt"]
            sub_paths = extracted.get("sub", [])
            if not txt_paths:
                _write_batch_marker(
                    state_dir=batch_state_dir,
                    batch_name=batch_name,
                    archive_paths=batch_paths,
                    outputs=batch_outputs,
                )
                continue

            if sub_paths:
                notes_filing_part = filing_parts / f"part_batch={batch_name}" / "data.parquet"
                _duckdb_copy_query_to_parquet(
                    query=f"SELECT * FROM {_duckdb_csv_source(sub_paths)}",
                    dest=notes_filing_part,
                    threads=duckdb_threads,
                    memory_limit=duckdb_memory_limit,
                    temp_directory=duckdb_temp_directory,
                    max_temp_directory_size=duckdb_max_temp_directory_size,
                )
                batch_outputs["notes_filing_dim_part"] = notes_filing_part

            columns = set(_read_header_columns(txt_paths[0]))
            text_col = "txt" if "txt" in columns else "text" if "text" in columns else None
            note_expr = _duckdb_identifier(text_col) if text_col else "NULL"
            txt_source = _duckdb_csv_source(txt_paths)
            summary_part = summary_parts / f"part_batch={batch_name}" / "data.parquet"
            summary_query = f"""
                SELECT
                    adsh,
                    count(tag)::BIGINT AS note_text_count,
                    sum(length(coalesce(CAST({note_expr} AS VARCHAR), '')))::BIGINT
                        AS note_text_char_count
                FROM {txt_source}
                GROUP BY adsh
            """
            _duckdb_copy_query_to_parquet(
                query=summary_query,
                dest=summary_part,
                threads=duckdb_threads,
                memory_limit=duckdb_memory_limit,
                temp_directory=duckdb_temp_directory,
                max_temp_directory_size=duckdb_max_temp_directory_size,
            )
            batch_outputs["note_summary_part"] = summary_part

            if notes_mode == "raw":
                note_part = note_text_path / f"part_batch={batch_name}" / "data.parquet"
                note_query = f"""
                    SELECT
                        adsh,
                        tag,
                        version AS taxonomy_version,
                        {_duckdb_sec_date_expr("ddate")} AS fact_date,
                        qtrs AS quarters,
                        {note_expr} AS note_text,
                        {_duckdb_sec_year_expr("ddate")} AS source_year
                    FROM {txt_source}
                """
                _duckdb_copy_query_to_parquet(
                    query=note_query,
                    dest=note_part,
                    threads=duckdb_threads,
                    memory_limit=duckdb_memory_limit,
                    temp_directory=duckdb_temp_directory,
                    max_temp_directory_size=duckdb_max_temp_directory_size,
                )
                batch_outputs["note_text_part"] = note_part

            _write_batch_marker(
                state_dir=batch_state_dir,
                batch_name=batch_name,
                archive_paths=batch_paths,
                outputs=batch_outputs,
            )
        finally:
            if batch_staging.exists():
                shutil.rmtree(batch_staging)

    if staging_root.exists():
        shutil.rmtree(staging_root)

    notes_filing_path = silver_dir / "notes_filing_dim.parquet"
    if _copy_parquet_query_from_parts(
        parts_dir=filing_parts,
        dest=notes_filing_path,
        query="SELECT * FROM {source} ORDER BY adsh",
        threads=duckdb_threads,
        memory_limit=duckdb_memory_limit,
        temp_directory=duckdb_temp_directory,
        max_temp_directory_size=duckdb_max_temp_directory_size,
    ):
        outputs["notes_filing_dim"] = notes_filing_path

    summary_path = silver_dir / "note_summary.parquet"
    if _copy_parquet_query_from_parts(
        parts_dir=summary_parts,
        dest=summary_path,
        query="""
            SELECT
                adsh,
                sum(note_text_count)::BIGINT AS note_text_count,
                sum(note_text_char_count)::BIGINT AS note_text_char_count
            FROM {source}
            GROUP BY adsh
            ORDER BY adsh
        """,
        threads=duckdb_threads,
        memory_limit=duckdb_memory_limit,
        temp_directory=duckdb_temp_directory,
        max_temp_directory_size=duckdb_max_temp_directory_size,
    ):
        outputs["note_summary"] = summary_path

    if notes_mode == "raw" and _parquet_files(note_text_path):
        outputs["note_text"] = note_text_path
    return outputs


def build_comment_threads(*, filing_dim_csv: Path, silver_dir: Path) -> Path:
    filing_dim = read_table(filing_dim_csv, date_cols=["filing_date", "report_date"])
    comment = filing_dim.loc[filing_dim["form"].isin(["UPLOAD", "CORRESP"])].copy()
    if comment.empty:
        out_path = silver_dir / "comment_thread.csv.gz"
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
        ).to_csv(out_path, index=False, compression="gzip")
        return out_path

    comment = comment.sort_values(["issuer_cik", "filing_date", "accession"])
    gap = comment.groupby("issuer_cik")["filing_date"].diff().dt.days.fillna(9999)
    comment["new_thread"] = gap.gt(120).astype(int)
    comment["thread_seq"] = comment.groupby("issuer_cik")["new_thread"].cumsum()
    comment["thread_id"] = (
        comment["issuer_cik"].astype(str) + "-" + comment["thread_seq"].astype(str)
    )
    thread = (
        comment.groupby(["issuer_cik", "thread_id"], as_index=False)
        .agg(
            first_public_date=("filing_date", "min"),
            last_public_date=("filing_date", "max"),
            upload_count=("form", lambda s: int((s == "UPLOAD").sum())),
            corresp_count=("form", lambda s: int((s == "CORRESP").sum())),
            filing_count=("accession", "nunique"),
        )
        .sort_values(["issuer_cik", "first_public_date"])
    )
    silver_dir.mkdir(parents=True, exist_ok=True)
    out_path = silver_dir / "comment_thread.csv.gz"
    thread.to_csv(out_path, index=False, compression="gzip")
    return out_path


def parse_8k_item_codes(items: object) -> Tuple[str, ...]:
    """Parse structured SEC 8-K item metadata without consulting filing text."""

    if items is None or (isinstance(items, float) and pd.isna(items)):
        return ()
    text = str(items).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return ()
    return tuple(sorted({match.group(1) for match in EIGHT_K_ITEM_CODE_RE.finditer(text)}))


def _is_missing_items_value(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    text = str(value).strip()
    return not text or text.lower() in {"nan", "none", "null"}


def build_issuer_8k_item_events(*, filing_dim_csv: Path, silver_dir: Path) -> Path:
    filing_dim = read_table(filing_dim_csv, date_cols=["filing_date", "report_date"])
    required_cols = {"issuer_cik", "accession", "filing_date", "report_date", "form", "items"}
    for col in required_cols.difference(filing_dim.columns):
        filing_dim[col] = pd.NA
    if "accession_nodash" not in filing_dim.columns:
        filing_dim["accession_nodash"] = (
            filing_dim["accession"].fillna("").astype(str).str.replace("-", "", regex=False)
        )
    eight_k = filing_dim.loc[filing_dim["form"].eq("8-K")].copy()
    columns = [
        "issuer_cik",
        "accession",
        "accession_nodash",
        "public_date",
        "report_date",
        "item_code",
        "event_type",
        "item_metadata_missing",
        "identified_from",
    ]
    if eight_k.empty:
        event = pd.DataFrame(columns=columns)
    else:
        eight_k["issuer_cik"] = _normalize_cik_series(eight_k["issuer_cik"])
        eight_k["item_metadata_missing"] = eight_k["items"].map(_is_missing_items_value)
        eight_k["parsed_item_codes"] = eight_k["items"].map(parse_8k_item_codes)
        identified = eight_k.loc[~eight_k["item_metadata_missing"]].copy()
        identified = identified.explode("parsed_item_codes")
        identified = identified.loc[
            identified["parsed_item_codes"].isin(EIGHT_K_TARGET_ITEM_CODES)
        ].copy()
        if not identified.empty:
            identified["item_code"] = identified["parsed_item_codes"].astype(str)
            identified["event_type"] = "8k_item_" + identified["item_code"].str.replace(
                ".", "_", regex=False
            )
            identified["item_metadata_missing"] = 0
        missing = eight_k.loc[eight_k["item_metadata_missing"]].copy()
        if not missing.empty:
            missing["item_code"] = pd.NA
            missing["event_type"] = "item_metadata_missing"
            missing["item_metadata_missing"] = 1
        event = pd.concat([identified, missing], ignore_index=True, sort=False)
        if not event.empty:
            event = event.rename(columns={"filing_date": "public_date"})
            event["identified_from"] = "items_metadata"
            event = event[columns]
            event = event.drop_duplicates(
                subset=["issuer_cik", "accession", "item_code", "event_type"]
            ).sort_values(["issuer_cik", "public_date", "accession", "event_type"])
        else:
            event = pd.DataFrame(columns=columns)
    silver_dir.mkdir(parents=True, exist_ok=True)
    out_path = silver_dir / "issuer_8k_item_event.csv.gz"
    event.to_csv(out_path, index=False, compression="gzip")
    return out_path


def _html_or_text_to_plain_text(document_text: str) -> str:
    text = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        str(document_text),
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*", "\n", text)


def extract_amendment_explanatory_note_window(
    document_text: str,
    *,
    heading_search_chars: int = 20_000,
    max_window_chars: int = 3_000,
) -> Tuple[str, bool]:
    plain = _html_or_text_to_plain_text(document_text)
    search_region = plain[: int(heading_search_chars)]
    heading = AMENDMENT_NOTE_HEADING_RE.search(search_region)
    if heading is None:
        return "", True
    start = heading.start()
    after_heading = plain[heading.end() : min(len(plain), start + int(max_window_chars))]
    major_heading = AMENDMENT_MAJOR_HEADING_RE.search(after_heading)
    end = heading.end() + major_heading.start() if major_heading else start + int(max_window_chars)
    return plain[start:end].strip(), False


def _read_optional_amendment_document_text(row: pd.Series, amendment_text_dir: Optional[Path]) -> str:
    if amendment_text_dir is None:
        return ""
    candidates = []
    for col in ["accession_nodash", "accession", "primary_document"]:
        value = row.get(col)
        if pd.notna(value) and str(value).strip():
            candidates.append(str(value).strip())
    suffixes = ["", ".txt", ".htm", ".html"]
    for candidate in candidates:
        safe_candidate = candidate.replace("/", "_")
        for suffix in suffixes:
            path = amendment_text_dir / f"{safe_candidate}{suffix}"
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def build_amendment_annotations(
    *,
    filing_dim_csv: Path,
    silver_dir: Path,
    amendment_text_dir: Optional[Path] = None,
) -> Path:
    filing_dim = read_table(filing_dim_csv, date_cols=["filing_date", "report_date"])
    for col in [
        "issuer_cik",
        "accession",
        "accession_nodash",
        "filing_date",
        "report_date",
        "form",
        "primary_document",
        "primary_doc_description",
    ]:
        if col not in filing_dim.columns:
            filing_dim[col] = pd.NA
    amendments = filing_dim.loc[filing_dim["form"].isin({"10-K/A", "10-Q/A"})].copy()
    rows: List[Dict[str, Any]] = []
    admin_re = re.compile(r"\b(part\s+iii|proxy|def\s*14a|exhibit)\b", re.IGNORECASE)
    for _, row in amendments.iterrows():
        description = str(row.get("primary_doc_description") or "")
        document_text = _read_optional_amendment_document_text(row, amendment_text_dir)
        note_window, note_missing = extract_amendment_explanatory_note_window(document_text)
        financial_override = bool(note_window and AMENDMENT_FINANCIAL_KEYWORD_RE.search(note_window))
        admin_candidate = bool(admin_re.search(description))
        mixed = bool(admin_candidate and financial_override)
        if financial_override:
            annotation = "non_admin_financial_correction"
            reason = (
                "mixed_content_classified_as_nonadmin"
                if mixed
                else "explanatory_note_financial_keyword"
            )
        elif admin_candidate:
            annotation = "admin_part_iii_proxy"
            reason = "admin_candidate_metadata"
        else:
            annotation = "broad_amendment_unclassified"
            reason = "explanatory_note_missing" if note_missing else "no_financial_keyword"
        rows.append(
            {
                "issuer_cik": row["issuer_cik"],
                "accession": row["accession"],
                "accession_nodash": row["accession_nodash"],
                "public_date": row["filing_date"],
                "report_date": row["report_date"],
                "form": row["form"],
                "primary_document": row["primary_document"],
                "admin_candidate_part_iii": int(admin_candidate),
                "financial_override": int(financial_override),
                "mixed_content": int(mixed),
                "amendment_annotation": annotation,
                "annotation_reason": reason,
                "explanatory_note_missing": int(note_missing),
                "explanatory_note_char_count": int(len(note_window)),
            }
        )
    columns = [
        "issuer_cik",
        "accession",
        "accession_nodash",
        "public_date",
        "report_date",
        "form",
        "primary_document",
        "admin_candidate_part_iii",
        "financial_override",
        "mixed_content",
        "amendment_annotation",
        "annotation_reason",
        "explanatory_note_missing",
        "explanatory_note_char_count",
    ]
    annotation = pd.DataFrame(rows, columns=columns)
    silver_dir.mkdir(parents=True, exist_ok=True)
    out_path = silver_dir / "amendment_annotation.csv.gz"
    annotation.to_csv(out_path, index=False, compression="gzip")
    return out_path


def build_correction_events(*, filing_dim_csv: Path, silver_dir: Path) -> Path:
    filing_dim = read_table(filing_dim_csv, date_cols=["filing_date", "report_date"])
    filing_dim["items"] = filing_dim.get("items", "").fillna("").astype(str)
    filing_dim["primary_doc_description"] = (
        filing_dim.get("primary_doc_description", "").fillna("").astype(str)
    )

    rows: List[Dict[str, Any]] = []
    amend_forms = {"10-K/A", "10-Q/A"}
    for _, row in filing_dim.loc[filing_dim["form"].isin(amend_forms)].iterrows():
        rows.append(
            {
                "issuer_cik": row["issuer_cik"],
                "accession": row["accession"],
                "public_date": row["filing_date"],
                "report_date": row["report_date"],
                "correction_type": "amendment_10x_a",
                "identified_from": "form",
            }
        )

    eight_k = filing_dim.loc[filing_dim["form"].eq("8-K")].copy()
    is_402 = eight_k["items"].map(lambda value: "4.02" in parse_8k_item_codes(value))
    for _, row in eight_k.loc[is_402].iterrows():
        rows.append(
            {
                "issuer_cik": row["issuer_cik"],
                "accession": row["accession"],
                "public_date": row["filing_date"],
                "report_date": row["report_date"],
                "correction_type": "nonreliance_8k_402",
                "identified_from": "items_metadata",
            }
        )

    revision_mask = filing_dim["primary_doc_description"].str.contains(
        "revision", case=False, regex=False
    ) | filing_dim["items"].str.contains("revision", case=False, regex=False)
    revision_forms = filing_dim["form"].isin(["10-K", "10-Q", "10-K/A", "10-Q/A"])
    for _, row in filing_dim.loc[revision_mask & revision_forms].iterrows():
        rows.append(
            {
                "issuer_cik": row["issuer_cik"],
                "accession": row["accession"],
                "public_date": row["filing_date"],
                "report_date": row["report_date"],
                "correction_type": "revision_if_identifiable",
                "identified_from": "revision_keyword",
            }
        )

    columns = [
        "issuer_cik",
        "accession",
        "public_date",
        "report_date",
        "correction_type",
        "identified_from",
    ]
    correction = pd.DataFrame(rows, columns=columns)
    if not correction.empty:
        correction = correction.drop_duplicates(
            subset=["issuer_cik", "accession", "correction_type"]
        )
    silver_dir.mkdir(parents=True, exist_ok=True)
    out_path = silver_dir / "correction_event.csv.gz"
    correction.to_csv(out_path, index=False, compression="gzip")
    return out_path


def _empty_partner_history_outputs(silver_dir: Path) -> Dict[str, Path]:
    outputs = {
        "partner_issuer_engagement": silver_dir / "partner_issuer_engagement.csv.gz",
        "partner_risk_history": silver_dir / "partner_risk_history.csv.gz",
        "partner_issuer_risk_history": silver_dir / "partner_issuer_risk_history.csv.gz",
    }
    schemas = {
        "partner_issuer_engagement": [
            "issuer_cik",
            "fiscal_period_end",
            "form_ap_public_date",
            "form_filing_id",
            "pcaob_firm_id",
            "engagement_partner_id",
            "engagement_partner_name",
            "number_of_participants",
        ],
        "partner_risk_history": [
            "engagement_partner_id",
            "event_date",
            "partner_prior_8k_402_count",
            "partner_prior_nonadmin_amendment_count",
            "partner_prior_total_count",
        ],
        "partner_issuer_risk_history": [
            "engagement_partner_id",
            "issuer_cik",
            "event_date",
            "partner_issuer_prior_8k_402_count",
            "partner_issuer_prior_nonadmin_amendment_count",
            "partner_issuer_prior_total_count",
        ],
    }
    silver_dir.mkdir(parents=True, exist_ok=True)
    for name, path in outputs.items():
        pd.DataFrame(columns=schemas[name]).to_csv(path, index=False, compression="gzip")
    return outputs


def build_partner_risk_histories(
    *,
    form_ap_event_path: Path,
    issuer_8k_item_event_path: Path,
    amendment_annotation_path: Path,
    silver_dir: Path,
) -> Dict[str, Path]:
    if not form_ap_event_path.exists():
        return _empty_partner_history_outputs(silver_dir)
    form_ap = read_table(
        form_ap_event_path,
        date_cols=["fiscal_period_end", "report_date", "filing_date"],
        low_memory=False,
    )
    if form_ap.empty or "engagement_partner_id" not in form_ap.columns:
        return _empty_partner_history_outputs(silver_dir)
    for col in [
        "issuer_cik",
        "fiscal_period_end",
        "filing_date",
        "form_filing_id",
        "pcaob_firm_id",
        "engagement_partner_id",
        "engagement_partner_name",
        "number_of_participants",
    ]:
        if col not in form_ap.columns:
            form_ap[col] = pd.NA
    engagement = form_ap.copy()
    engagement["issuer_cik"] = _normalize_cik_series(engagement["issuer_cik"])
    engagement["form_ap_public_date"] = pd.to_datetime(engagement["filing_date"], errors="coerce")
    engagement["engagement_partner_id"] = (
        engagement["engagement_partner_id"].fillna("").astype(str).str.strip()
    )
    engagement = engagement.loc[
        engagement["issuer_cik"].notna()
        & engagement["form_ap_public_date"].notna()
        & engagement["engagement_partner_id"].ne("")
    ].copy()
    engagement_cols = [
        "issuer_cik",
        "fiscal_period_end",
        "form_ap_public_date",
        "form_filing_id",
        "pcaob_firm_id",
        "engagement_partner_id",
        "engagement_partner_name",
        "number_of_participants",
    ]
    engagement = engagement[engagement_cols].drop_duplicates()

    risk_frames: List[pd.DataFrame] = []
    if issuer_8k_item_event_path.exists():
        item_event = read_table(
            issuer_8k_item_event_path,
            date_cols=["public_date", "report_date"],
            low_memory=False,
        )
        if not item_event.empty and {"issuer_cik", "public_date", "item_code"}.issubset(
            item_event.columns
        ):
            k402 = item_event.loc[item_event["item_code"].astype(str).eq("4.02")].copy()
            if not k402.empty:
                k402["risk_type"] = "8k_402"
                risk_frames.append(
                    k402[["issuer_cik", "public_date", "risk_type"]].rename(
                        columns={"public_date": "event_date"}
                    )
                )
    if amendment_annotation_path.exists():
        annotation = read_table(
            amendment_annotation_path,
            date_cols=["public_date", "report_date"],
            low_memory=False,
        )
        if not annotation.empty and {"issuer_cik", "public_date", "amendment_annotation"}.issubset(
            annotation.columns
        ):
            nonadmin = annotation.loc[
                annotation["amendment_annotation"].eq("non_admin_financial_correction")
            ].copy()
            if not nonadmin.empty:
                nonadmin["risk_type"] = "nonadmin_amendment"
                risk_frames.append(
                    nonadmin[["issuer_cik", "public_date", "risk_type"]].rename(
                        columns={"public_date": "event_date"}
                    )
                )
    if risk_frames:
        risk_events = pd.concat(risk_frames, ignore_index=True)
    else:
        risk_events = pd.DataFrame(columns=["issuer_cik", "event_date", "risk_type"])
    risk_events["issuer_cik"] = _normalize_cik_series(risk_events["issuer_cik"])
    risk_events["event_date"] = pd.to_datetime(risk_events["event_date"], errors="coerce")
    risk_events = risk_events.loc[
        risk_events["issuer_cik"].notna() & risk_events["event_date"].notna()
    ].copy()

    silver_dir.mkdir(parents=True, exist_ok=True)
    engagement_path = silver_dir / "partner_issuer_engagement.csv.gz"
    engagement.to_csv(engagement_path, index=False, compression="gzip")
    if engagement.empty or risk_events.empty:
        outputs = _empty_partner_history_outputs(silver_dir)
        outputs["partner_issuer_engagement"] = engagement_path
        engagement.to_csv(engagement_path, index=False, compression="gzip")
        return outputs

    risk_events = risk_events.sort_values(["event_date", "issuer_cik"], kind="mergesort")
    engagement_sorted = engagement.sort_values(
        ["form_ap_public_date", "issuer_cik"], kind="mergesort"
    )
    matched = pd.merge_asof(
        risk_events,
        engagement_sorted,
        left_on="event_date",
        right_on="form_ap_public_date",
        by="issuer_cik",
        direction="backward",
        allow_exact_matches=True,
    )
    matched = matched.loc[matched["engagement_partner_id"].notna()].copy()
    matched["engagement_partner_id"] = matched["engagement_partner_id"].astype(str)

    risk_types = ["8k_402", "nonadmin_amendment"]
    if matched.empty:
        outputs = _empty_partner_history_outputs(silver_dir)
        outputs["partner_issuer_engagement"] = engagement_path
        engagement.to_csv(engagement_path, index=False, compression="gzip")
        return outputs

    daily_partner = (
        matched.groupby(["engagement_partner_id", "event_date", "risk_type"], as_index=False)
        .size()
        .rename(columns={"size": "event_count"})
    )
    partner_wide = (
        daily_partner.pivot_table(
            index=["engagement_partner_id", "event_date"],
            columns="risk_type",
            values="event_count",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for risk_type in risk_types:
        if risk_type not in partner_wide.columns:
            partner_wide[risk_type] = 0
    partner_wide = partner_wide.sort_values(
        ["engagement_partner_id", "event_date"], kind="mergesort"
    )
    for risk_type in risk_types:
        partner_wide[f"partner_prior_{risk_type}_count"] = partner_wide.groupby(
            "engagement_partner_id"
        )[risk_type].cumsum()
    partner_wide["partner_prior_total_count"] = partner_wide[
        [f"partner_prior_{risk_type}_count" for risk_type in risk_types]
    ].sum(axis=1)
    partner_history = partner_wide[
        [
            "engagement_partner_id",
            "event_date",
            "partner_prior_8k_402_count",
            "partner_prior_nonadmin_amendment_count",
            "partner_prior_total_count",
        ]
    ]

    daily_partner_issuer = (
        matched.groupby(
            ["engagement_partner_id", "issuer_cik", "event_date", "risk_type"],
            as_index=False,
        )
        .size()
        .rename(columns={"size": "event_count"})
    )
    issuer_wide = (
        daily_partner_issuer.pivot_table(
            index=["engagement_partner_id", "issuer_cik", "event_date"],
            columns="risk_type",
            values="event_count",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for risk_type in risk_types:
        if risk_type not in issuer_wide.columns:
            issuer_wide[risk_type] = 0
    issuer_wide = issuer_wide.sort_values(
        ["engagement_partner_id", "issuer_cik", "event_date"], kind="mergesort"
    )
    for risk_type in risk_types:
        issuer_wide[f"partner_issuer_prior_{risk_type}_count"] = issuer_wide.groupby(
            ["engagement_partner_id", "issuer_cik"]
        )[risk_type].cumsum()
    issuer_wide["partner_issuer_prior_total_count"] = issuer_wide[
        [f"partner_issuer_prior_{risk_type}_count" for risk_type in risk_types]
    ].sum(axis=1)
    issuer_history = issuer_wide[
        [
            "engagement_partner_id",
            "issuer_cik",
            "event_date",
            "partner_issuer_prior_8k_402_count",
            "partner_issuer_prior_nonadmin_amendment_count",
            "partner_issuer_prior_total_count",
        ]
    ]

    partner_history_path = silver_dir / "partner_risk_history.csv.gz"
    issuer_history_path = silver_dir / "partner_issuer_risk_history.csv.gz"
    partner_history.to_csv(partner_history_path, index=False, compression="gzip")
    issuer_history.to_csv(issuer_history_path, index=False, compression="gzip")
    return {
        "partner_issuer_engagement": engagement_path,
        "partner_risk_history": partner_history_path,
        "partner_issuer_risk_history": issuer_history_path,
    }


def normalize_aaer_events(
    *,
    aaer_bronze_dir: Path,
    silver_dir: Path,
    issuer_dim_path: Optional[Path] = None,
    issuer_dim_csv: Optional[Path] = None,
) -> Path:
    if issuer_dim_path is not None and issuer_dim_csv is not None:
        if Path(issuer_dim_path) != Path(issuer_dim_csv):
            raise ValueError("Pass only one of issuer_dim_path or deprecated issuer_dim_csv.")
    issuer_dim_path = issuer_dim_path or issuer_dim_csv
    listing_html = aaer_bronze_dir / "aaer_listing.html"
    rows: List[Dict[str, Any]] = []
    issuer_dim = None
    if issuer_dim_path is not None and issuer_dim_path.exists():
        issuer_dim = read_table(issuer_dim_path, columns=["issuer_cik", "entity_name"])
        issuer_dim["issuer_cik"] = _normalize_cik_series(issuer_dim["issuer_cik"])
        issuer_dim["entity_tokens"] = issuer_dim["entity_name"].map(_name_tokens)
        issuer_dim = issuer_dim.loc[issuer_dim["entity_tokens"].map(len).ge(2)].copy()

    if listing_html.exists():
        html = listing_html.read_text(encoding="utf-8", errors="ignore")
        for match in AAER_ROW_RE.finditer(html):
            url = urljoin(SEC_AAER_URL, match.group("href"))
            title = re.sub(r"<[^>]+>", " ", match.group("title")).strip()
            rows.append(
                {
                    "release_url": url,
                    "release_title": title,
                    "event_date": pd.to_datetime(match.group("dt"), errors="coerce"),
                }
            )

    aaer = pd.DataFrame(rows).drop_duplicates(subset=["release_url"])
    if aaer.empty:
        aaer = pd.DataFrame(
            columns=[
                "release_url",
                "release_title",
                "event_date",
                "issuer_cik",
                "aaer_match_score",
                "aaer_match_method",
            ]
        )
    else:
        if "event_date" not in aaer.columns:
            aaer["event_date"] = pd.NaT
        aaer["issuer_cik"] = ""
        aaer["aaer_match_score"] = 0.0
        aaer["aaer_match_method"] = "unmatched"
        if issuer_dim is not None:
            issuer_pairs = issuer_dim[["issuer_cik", "entity_tokens"]].drop_duplicates(
                subset=["issuer_cik"]
            )
            for idx, row in aaer.iterrows():
                match = _best_aaer_issuer_match(str(row["release_title"]), issuer_pairs)
                aaer.at[idx, "issuer_cik"] = match["issuer_cik"]
                aaer.at[idx, "aaer_match_score"] = match["score"]
                aaer.at[idx, "aaer_match_method"] = match["method"]

    silver_dir.mkdir(parents=True, exist_ok=True)
    out_path = silver_dir / "aaer_event.csv.gz"
    aaer.to_csv(out_path, index=False, compression="gzip")
    return out_path


def _availability_date(series_len: int, date_string: str) -> pd.Series:
    return pd.Series(pd.Timestamp(date_string), index=range(series_len))


def _read_csv_with_optional_dates(path: Path, date_cols: Sequence[str]) -> pd.DataFrame:
    preview = pd.read_csv(path, nrows=0)
    parse_cols = [col for col in date_cols if col in preview.columns]
    frame = pd.read_csv(path, parse_dates=parse_cols, low_memory=False)
    for col in parse_cols:
        frame[col] = pd.to_datetime(frame[col], errors="coerce", format="mixed")
    return frame


def _ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denom = pd.to_numeric(denominator, errors="coerce").replace(0, np.nan)
    return pd.to_numeric(numerator, errors="coerce") / denom


def build_xbrl_core_features(xbrl_fact: pd.DataFrame) -> pd.DataFrame:
    if xbrl_fact.empty or "adsh" not in xbrl_fact.columns or "tag" not in xbrl_fact.columns:
        return pd.DataFrame(columns=["accession"])

    tag_lookup: Dict[str, Tuple[str, int]] = {}
    for concept, tags in XBRL_CORE_TAGS.items():
        for priority, tag in enumerate(tags):
            tag_lookup[tag.lower()] = (concept, priority)

    work = xbrl_fact.copy()
    work["tag_key"] = work["tag"].astype(str).str.lower()
    work = work.loc[work["tag_key"].isin(tag_lookup)].copy()
    if work.empty:
        return pd.DataFrame(columns=["accession"])

    work["concept"] = work["tag_key"].map(lambda tag: tag_lookup[tag][0])
    work["tag_priority"] = work["tag_key"].map(lambda tag: tag_lookup[tag][1])
    if "value" not in work.columns:
        return pd.DataFrame(columns=["accession"])
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.loc[work["value"].notna()].copy()
    if "unit" in work.columns:
        unit = work["unit"].fillna("").astype(str).str.upper()
        work = work.loc[unit.isin({"", "USD"})].copy()
    if work.empty:
        return pd.DataFrame(columns=["accession"])

    if "quarters" in work.columns:
        work["quarters"] = pd.to_numeric(work["quarters"], errors="coerce").fillna(-1)
    else:
        work["quarters"] = -1
    if "fact_date" in work.columns:
        work["fact_date"] = pd.to_datetime(work["fact_date"], errors="coerce")
    else:
        work["fact_date"] = pd.NaT
    work = work.sort_values(
        ["adsh", "concept", "tag_priority", "quarters", "fact_date"],
        ascending=[True, True, True, False, False],
    )
    selected = work.drop_duplicates(subset=["adsh", "concept"], keep="first")
    wide = selected.pivot(index="adsh", columns="concept", values="value").reset_index()
    wide = wide.rename(columns={"adsh": "accession"})

    for concept in XBRL_CORE_TAGS:
        if concept not in wide.columns:
            wide[concept] = np.nan
        wide[f"xbrl_coverage_{concept}"] = wide[concept].notna().astype(int)

    wide["working_capital"] = wide["working_capital"].fillna(
        wide["current_assets"] - wide["current_liabilities"]
    )
    wide.loc[wide["working_capital"].notna(), "xbrl_coverage_working_capital"] = 1
    debt_available = wide[["debt", "debt_current"]].notna().any(axis=1)
    wide["debt"] = wide["debt"].fillna(0) + wide["debt_current"].fillna(0)
    wide.loc[~debt_available, "debt"] = np.nan
    wide.loc[debt_available, "xbrl_coverage_debt"] = 1

    assets = wide["assets"]
    revenues = wide["revenues"]
    wide["xbrl_ratio_log_assets"] = np.where(assets > 0, np.log1p(assets), np.nan)
    wide["xbrl_ratio_leverage"] = _ratio(wide["liabilities"], assets)
    wide["xbrl_ratio_profitability"] = _ratio(wide["net_income"], assets)
    wide["xbrl_ratio_working_capital_to_assets"] = _ratio(wide["working_capital"], assets)
    wide["xbrl_ratio_receivables_to_revenue"] = _ratio(wide["receivables"], revenues)
    wide["xbrl_ratio_inventory_to_assets"] = _ratio(wide["inventory"], assets)
    wide["xbrl_ratio_cash_to_assets"] = _ratio(wide["cash"], assets)
    wide["xbrl_ratio_debt_to_assets"] = _ratio(wide["debt"], assets)
    wide["xbrl_ratio_operating_cash_flow_to_assets"] = _ratio(wide["operating_cash_flow"], assets)

    value_cols = {concept: f"xbrl_value_{concept}" for concept in XBRL_CORE_TAGS}
    wide = wide.rename(columns=value_cols)
    ordered_cols = (
        ["accession"]
        + [f"xbrl_value_{concept}" for concept in XBRL_CORE_TAGS]
        + [f"xbrl_coverage_{concept}" for concept in XBRL_CORE_TAGS]
        + [col for col in wide.columns if col.startswith("xbrl_ratio_")]
    )
    return wide[[col for col in ordered_cols if col in wide.columns]]


def add_xbrl_yoy_ratio_features(filing: pd.DataFrame) -> pd.DataFrame:
    if "issuer_cik" not in filing.columns or "fiscal_year" not in filing.columns:
        return filing
    work = filing.sort_values(["issuer_cik", "fiscal_year", "origin_date", "accession"]).copy()
    for concept, out_col in [
        ("revenues", "xbrl_ratio_revenue_yoy_change"),
        ("assets", "xbrl_ratio_assets_yoy_change"),
    ]:
        value_col = f"xbrl_value_{concept}"
        if value_col not in work.columns:
            continue
        previous = work.groupby("issuer_cik")[value_col].shift(1)
        work[out_col] = _ratio(work[value_col] - previous, previous.abs())
        work[f"xbrl_coverage_{concept}_yoy"] = (
            work[value_col].notna() & previous.notna() & previous.ne(0)
        ).astype(int)
    return work


def _event_within_horizon(
    base: pd.DataFrame,
    events: pd.DataFrame,
    *,
    date_col: str,
    horizon_days: int,
    event_type: Optional[str] = None,
    type_col: str = "correction_type",
) -> pd.Series:
    if events.empty:
        return pd.Series(np.zeros(len(base), dtype=int), index=base.index)
    work = events.copy()
    if "issuer_cik" not in work.columns or "issuer_cik" not in base.columns:
        return pd.Series(np.zeros(len(base), dtype=int), index=base.index)
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    if event_type is not None:
        work = work.loc[work[type_col].eq(event_type)].copy()
    work = work.loc[work[date_col].notna()].copy()
    if work.empty:
        return pd.Series(np.zeros(len(base), dtype=int), index=base.index)
    work["issuer_cik"] = _normalize_cik_series(work["issuer_cik"])
    work = work.loc[work["issuer_cik"].notna()].copy()
    event_dates_by_cik = {
        cik: np.sort(group[date_col].to_numpy(dtype="datetime64[ns]"))
        for cik, group in work.groupby("issuer_cik", sort=False)
    }

    flags = pd.Series(np.zeros(len(base), dtype=int), index=base.index)
    base_work = base[["issuer_cik", "origin_date"]].copy()
    base_work["issuer_cik"] = _normalize_cik_series(base_work["issuer_cik"])
    base_work = base_work.loc[base_work["issuer_cik"].notna()].copy()
    base_work["origin_date"] = pd.to_datetime(base_work["origin_date"], errors="coerce")
    for cik, group in base_work.groupby("issuer_cik", sort=False):
        event_dates = event_dates_by_cik.get(cik)
        if event_dates is None or len(event_dates) == 0:
            continue
        valid = group["origin_date"].notna()
        if not valid.any():
            continue
        origins = group.loc[valid, "origin_date"]
        lo = origins.to_numpy(dtype="datetime64[ns]")
        hi = (origins + pd.Timedelta(days=int(horizon_days))).to_numpy(dtype="datetime64[ns]")
        left = np.searchsorted(event_dates, lo, side="right")
        right = np.searchsorted(event_dates, hi, side="right")
        flags.loc[origins.index] = (right > left).astype(int)
    return flags


def _event_count_prior_window(
    base: pd.DataFrame,
    events: pd.DataFrame,
    *,
    date_col: str,
    window_days: int,
    event_type: Optional[str] = None,
    type_col: str = "correction_type",
) -> pd.Series:
    if events.empty or "issuer_cik" not in events.columns or "issuer_cik" not in base.columns:
        return pd.Series(np.zeros(len(base), dtype="int64"), index=base.index)
    work = events.copy()
    if date_col not in work.columns:
        return pd.Series(np.zeros(len(base), dtype="int64"), index=base.index)
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    if event_type is not None:
        if type_col not in work.columns:
            return pd.Series(np.zeros(len(base), dtype="int64"), index=base.index)
        work = work.loc[work[type_col].astype(str).eq(str(event_type))].copy()
    work = work.loc[work[date_col].notna()].copy()
    if work.empty:
        return pd.Series(np.zeros(len(base), dtype="int64"), index=base.index)
    work["issuer_cik"] = _normalize_cik_series(work["issuer_cik"])
    event_dates_by_cik = {
        cik: np.sort(group[date_col].to_numpy(dtype="datetime64[ns]"))
        for cik, group in work.groupby("issuer_cik", sort=False)
    }
    counts = pd.Series(np.zeros(len(base), dtype="int64"), index=base.index)
    base_work = base[["issuer_cik", "origin_date"]].copy()
    base_work["issuer_cik"] = _normalize_cik_series(base_work["issuer_cik"])
    base_work["origin_date"] = pd.to_datetime(base_work["origin_date"], errors="coerce")
    base_work = base_work.loc[base_work["issuer_cik"].notna() & base_work["origin_date"].notna()]
    for cik, group in base_work.groupby("issuer_cik", sort=False):
        event_dates = event_dates_by_cik.get(cik)
        if event_dates is None or len(event_dates) == 0:
            continue
        origins = group["origin_date"]
        lo = (origins - pd.Timedelta(days=int(window_days))).to_numpy(dtype="datetime64[ns]")
        hi = origins.to_numpy(dtype="datetime64[ns]")
        left = np.searchsorted(event_dates, lo, side="left")
        right = np.searchsorted(event_dates, hi, side="left")
        counts.loc[origins.index] = (right - left).astype("int64")
    return counts


def _add_public_history_and_filing_friction_features(
    filing: pd.DataFrame,
    *,
    comment_thread: pd.DataFrame,
    correction_event: pd.DataFrame,
    issuer_8k_item_event: pd.DataFrame,
) -> pd.DataFrame:
    item_event = issuer_8k_item_event.copy()
    if not item_event.empty and "item_code" in item_event.columns:
        item_event["item_code"] = item_event["item_code"].map(
            lambda value: "" if pd.isna(value) else str(value).strip()
        )
    public_history_specs = [
        ("public_history_comment_thread", comment_thread.rename(columns={"first_public_date": "event_date"}), "event_date", None, "correction_type"),
        ("public_history_amendment", correction_event, "public_date", "amendment_10x_a", "correction_type"),
        ("public_history_8k_301", item_event, "public_date", "3.01", "item_code"),
        ("public_history_8k_401", item_event, "public_date", "4.01", "item_code"),
        ("public_history_8k_402", item_event, "public_date", "4.02", "item_code"),
        ("public_history_8k_502", item_event, "public_date", "5.02", "item_code"),
    ]
    for prefix, events, date_col, event_type, type_col in public_history_specs:
        for label, days in [("1y", 365), ("3y", 365 * 3)]:
            filing[f"{prefix}_{label}_count"] = _event_count_prior_window(
                filing,
                events,
                date_col=date_col,
                window_days=days,
                event_type=event_type,
                type_col=type_col,
            )

    filing["filing_friction_is_nt"] = filing["form"].fillna("").astype(str).str.startswith("NT ").astype(int)
    nt_forms = {"NT 10-K", "NT 10-Q"}
    nt = filing.loc[filing["form"].isin(nt_forms), ["issuer_cik", "report_date", "origin_date"]].copy()
    if nt.empty:
        filing["filing_friction_nt_pre_origin"] = 0
        filing["filing_friction_nt_delay_days"] = np.nan
        return filing
    nt = (
        nt.dropna(subset=["issuer_cik", "report_date", "origin_date"])
        .rename(columns={"origin_date": "nt_public_date"})
        .sort_values(["issuer_cik", "report_date", "nt_public_date"], kind="mergesort")
        .drop_duplicates(subset=["issuer_cik", "report_date"], keep="last")
    )
    filing = filing.merge(nt, on=["issuer_cik", "report_date"], how="left")
    filing["filing_friction_nt_pre_origin"] = (
        filing["nt_public_date"].notna() & filing["nt_public_date"].le(filing["origin_date"])
    ).astype(int)
    filing["filing_friction_nt_delay_days"] = np.where(
        filing["filing_friction_nt_pre_origin"].eq(1),
        (filing["origin_date"] - filing["nt_public_date"]).dt.days,
        np.nan,
    )
    return filing.drop(columns=["nt_public_date"])


def _k402_label_and_unknown(base: pd.DataFrame, issuer_8k_item_event: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    if issuer_8k_item_event.empty:
        labels = pd.Series(np.zeros(len(base), dtype="int64"), index=base.index)
        unknown = pd.Series(np.zeros(len(base), dtype="int64"), index=base.index)
        return labels, unknown
    events = issuer_8k_item_event.copy()
    for col in ["issuer_cik", "public_date", "item_code", "event_type", "item_metadata_missing"]:
        if col not in events.columns:
            events[col] = pd.NA
    events["item_code"] = events["item_code"].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    positive = _event_within_horizon(
        base,
        events,
        date_col="public_date",
        horizon_days=365,
        event_type="4.02",
        type_col="item_code",
    )
    missing_events = events.loc[
        events["item_metadata_missing"].fillna(0).astype(str).isin({"1", "1.0", "True", "true"})
        | events["event_type"].astype(str).eq("item_metadata_missing")
    ].copy()
    missing = _event_within_horizon(
        base,
        missing_events,
        date_col="public_date",
        horizon_days=365,
    )
    unknown = (positive.eq(0) & missing.eq(1)).astype("int64")
    labels = positive.astype("Int64")
    labels.loc[unknown.eq(1)] = pd.NA
    return labels, unknown


def _add_partner_prior_features(
    filing: pd.DataFrame,
    *,
    silver_dir: Path,
    engine: str = "pandas",
    duckdb_threads: int = 4,
    duckdb_memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | str | None = None,
    duckdb_max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> pd.DataFrame:
    feature_cols = [
        "auditor_partner_prior_other_issuer_8k_402_count",
        "auditor_partner_prior_other_issuer_nonadmin_amendment_count",
        "auditor_partner_prior_other_issuer_total_count",
    ]
    for col in feature_cols:
        filing[col] = 0
    engagement_path = silver_dir / "partner_issuer_engagement.csv.gz"
    partner_history_path = silver_dir / "partner_risk_history.csv.gz"
    issuer_history_path = silver_dir / "partner_issuer_risk_history.csv.gz"
    if not (engagement_path.exists() and partner_history_path.exists() and issuer_history_path.exists()):
        return filing
    engagement = _read_csv_with_engine(
        engagement_path,
        date_cols=["fiscal_period_end", "form_ap_public_date"],
        engine=engine,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit,
        duckdb_temp_directory=duckdb_temp_directory,
        duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
    )
    partner_history = _read_csv_with_engine(
        partner_history_path,
        date_cols=["event_date"],
        engine=engine,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit,
        duckdb_temp_directory=duckdb_temp_directory,
        duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
    )
    issuer_history = _read_csv_with_engine(
        issuer_history_path,
        date_cols=["event_date"],
        engine=engine,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit,
        duckdb_temp_directory=duckdb_temp_directory,
        duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
    )
    if engagement.empty or partner_history.empty:
        return filing
    work = filing.reset_index().rename(columns={"index": "_filing_index"}).copy()
    work["issuer_cik"] = _normalize_cik_series(work["issuer_cik"])
    work["origin_date"] = pd.to_datetime(work["origin_date"], errors="coerce")
    engagement["issuer_cik"] = _normalize_cik_series(engagement["issuer_cik"])
    engagement["form_ap_public_date"] = pd.to_datetime(
        engagement["form_ap_public_date"], errors="coerce"
    )
    engagement["engagement_partner_id"] = (
        engagement["engagement_partner_id"].fillna("").astype(str).str.strip()
    )
    work = work.sort_values(["origin_date", "issuer_cik"], kind="mergesort")
    engagement = engagement.sort_values(["form_ap_public_date", "issuer_cik"], kind="mergesort")
    assigned = pd.merge_asof(
        work,
        engagement[["issuer_cik", "form_ap_public_date", "engagement_partner_id"]],
        left_on="origin_date",
        right_on="form_ap_public_date",
        by="issuer_cik",
        direction="backward",
        allow_exact_matches=False,
    )
    assigned = assigned.sort_values("_filing_index", kind="mergesort")
    assigned["engagement_partner_id"] = assigned["engagement_partner_id"].fillna("").astype(str)

    partner_cols = [
        "partner_prior_8k_402_count",
        "partner_prior_nonadmin_amendment_count",
        "partner_prior_total_count",
    ]
    issuer_cols = [
        "partner_issuer_prior_8k_402_count",
        "partner_issuer_prior_nonadmin_amendment_count",
        "partner_issuer_prior_total_count",
    ]
    if not partner_history.empty:
        partner_history["engagement_partner_id"] = (
            partner_history["engagement_partner_id"].fillna("").astype(str)
        )
        partner_history = partner_history.sort_values(
            ["event_date", "engagement_partner_id"], kind="mergesort"
        )
        assigned = pd.merge_asof(
            assigned.sort_values(["origin_date", "engagement_partner_id"], kind="mergesort"),
            partner_history[["engagement_partner_id", "event_date", *partner_cols]],
            left_on="origin_date",
            right_on="event_date",
            by="engagement_partner_id",
            direction="backward",
            allow_exact_matches=False,
        ).sort_values("_filing_index", kind="mergesort")
    for col in partner_cols:
        if col not in assigned.columns:
            assigned[col] = 0
        assigned[col] = pd.to_numeric(assigned[col], errors="coerce").fillna(0)

    if not issuer_history.empty:
        issuer_history["engagement_partner_id"] = (
            issuer_history["engagement_partner_id"].fillna("").astype(str)
        )
        issuer_history["issuer_cik"] = _normalize_cik_series(issuer_history["issuer_cik"])
        issuer_history = issuer_history.sort_values(
            ["event_date", "engagement_partner_id", "issuer_cik"], kind="mergesort"
        )
        assigned = pd.merge_asof(
            assigned.sort_values(
                ["origin_date", "engagement_partner_id", "issuer_cik"], kind="mergesort"
            ),
            issuer_history[["engagement_partner_id", "issuer_cik", "event_date", *issuer_cols]],
            left_on="origin_date",
            right_on="event_date",
            by=["engagement_partner_id", "issuer_cik"],
            direction="backward",
            allow_exact_matches=False,
        ).sort_values("_filing_index", kind="mergesort")
    for col in issuer_cols:
        if col not in assigned.columns:
            assigned[col] = 0
        assigned[col] = pd.to_numeric(assigned[col], errors="coerce").fillna(0)

    deltas = {
        "auditor_partner_prior_other_issuer_8k_402_count": (
            assigned["partner_prior_8k_402_count"] - assigned["partner_issuer_prior_8k_402_count"]
        ),
        "auditor_partner_prior_other_issuer_nonadmin_amendment_count": (
            assigned["partner_prior_nonadmin_amendment_count"]
            - assigned["partner_issuer_prior_nonadmin_amendment_count"]
        ),
        "auditor_partner_prior_other_issuer_total_count": (
            assigned["partner_prior_total_count"] - assigned["partner_issuer_prior_total_count"]
        ),
    }
    for col, values in deltas.items():
        if (values < 0).any():
            raise ValueError(f"{col} became negative before clipping; check partner risk joins.")
        filing[col] = values.clip(lower=0).to_numpy(dtype="int64")
    return filing


def _duckdb_xbrl_summary(
    path: Path,
    *,
    threads: int,
    memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    temp_directory: Path | str | None = None,
    max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> pd.DataFrame:
    con = _duckdb_connect(
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        max_temp_directory_size=max_temp_directory_size,
    )
    try:
        return con.execute(
            f"""
            SELECT
                adsh,
                count(tag)::BIGINT AS xbrl_fact_count,
                count(DISTINCT tag)::BIGINT AS xbrl_unique_tags,
                count(DISTINCT unit)::BIGINT AS xbrl_unique_units
            FROM {_duckdb_table_source(path)}
            GROUP BY adsh
            """
        ).fetchdf()
    finally:
        con.close()


def _duckdb_xbrl_core_facts(
    path: Path,
    *,
    threads: int,
    memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    temp_directory: Path | str | None = None,
    max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> pd.DataFrame:
    con = _duckdb_connect(
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        max_temp_directory_size=max_temp_directory_size,
    )
    try:
        frame = con.execute(
            f"""
            SELECT
                adsh,
                tag,
                unit,
                try_cast(value AS DOUBLE) AS value,
                try_cast(quarters AS DOUBLE) AS quarters,
                fact_date
            FROM {_duckdb_table_source(path)}
            WHERE lower(CAST(tag AS VARCHAR)) IN ({_xbrl_core_tag_sql()})
              AND try_cast(value AS DOUBLE) IS NOT NULL
              AND (
                    unit IS NULL
                    OR upper(CAST(unit AS VARCHAR)) IN ('', 'USD')
                  )
            """
        ).fetchdf()
    finally:
        con.close()
    if "fact_date" in frame.columns:
        frame["fact_date"] = pd.to_datetime(frame["fact_date"], errors="coerce", format="mixed")
    return frame


def _duckdb_note_summary(
    path: Path,
    *,
    threads: int,
    memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    temp_directory: Path | str | None = None,
    max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> pd.DataFrame:
    con = _duckdb_connect(
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        max_temp_directory_size=max_temp_directory_size,
    )
    try:
        return con.execute(
            f"""
            SELECT
                adsh,
                count(tag)::BIGINT AS note_text_count,
                sum(length(coalesce(CAST(note_text AS VARCHAR), '')))::BIGINT
                    AS note_text_char_count
            FROM {_duckdb_table_source(path)}
            GROUP BY adsh
            """
        ).fetchdf()
    finally:
        con.close()


def _duckdb_source_or_empty(
    *,
    con: Any,
    view_name: str,
    path: Path,
    empty_columns: Sequence[Tuple[str, str]],
) -> None:
    if path.exists():
        con.execute(f"CREATE OR REPLACE TEMP VIEW {view_name} AS SELECT * FROM {_duckdb_table_source(path)}")
        return
    empty_select = ", ".join(
        f"CAST(NULL AS {sql_type}) AS {_duckdb_identifier(col)}"
        for col, sql_type in empty_columns
    )
    con.execute(f"CREATE OR REPLACE TEMP VIEW {view_name} AS SELECT {empty_select} WHERE false")


def _duckdb_copy_query_to_parquet_on_connection(con: Any, *, query: str, dest: Path) -> None:
    dest = Path(dest)
    remove_table_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    con.execute(
        f"""
        COPY ({query})
        TO '{_duckdb_path(dest)}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )


def _duckdb_xbrl_core_features_query(path: Path) -> str:
    values = []
    for concept, tags in XBRL_CORE_TAGS.items():
        for priority, tag in enumerate(tags):
            values.append(
                "("
                f"{_duckdb_string_expr(concept)}, "
                f"{_duckdb_string_expr(tag.lower())}, "
                f"{int(priority)}"
                ")"
            )
    tag_map = ",\n                ".join(values)
    raw_cols = [
        f"max(CASE WHEN concept = {_duckdb_string_expr(concept)} THEN value END) AS raw_{concept}"
        for concept in XBRL_CORE_TAGS
    ]
    value_cols = []
    coverage_cols = []
    for concept in XBRL_CORE_TAGS:
        if concept == "working_capital":
            value_expr = "calc_working_capital"
            coverage_expr = "CASE WHEN calc_working_capital IS NOT NULL THEN 1 ELSE 0 END"
        elif concept == "debt":
            value_expr = "calc_debt"
            coverage_expr = "CASE WHEN debt_available THEN 1 ELSE 0 END"
        else:
            value_expr = f"raw_{concept}"
            coverage_expr = f"CASE WHEN raw_{concept} IS NOT NULL THEN 1 ELSE 0 END"
        value_cols.append(f"{value_expr} AS xbrl_value_{concept}")
        coverage_cols.append(f"{coverage_expr} AS xbrl_coverage_{concept}")

    ratio = lambda num, denom: (  # noqa: E731
        f"CASE WHEN {denom} IS NOT NULL AND {denom} <> 0 THEN {num} / {denom} END"
    )
    return f"""
        WITH tag_map(concept, tag_key, tag_priority) AS (
            VALUES
                {tag_map}
        ),
        filtered AS (
            SELECT
                CAST(adsh AS VARCHAR) AS adsh,
                tag_map.concept,
                tag_map.tag_priority,
                try_cast(value AS DOUBLE) AS value,
                try_cast(quarters AS DOUBLE) AS quarters,
                try_cast(fact_date AS TIMESTAMP) AS fact_date
            FROM {_duckdb_table_source(path)} facts
            INNER JOIN tag_map
                ON lower(CAST(facts.tag AS VARCHAR)) = tag_map.tag_key
            WHERE try_cast(value AS DOUBLE) IS NOT NULL
              AND (
                    facts.unit IS NULL
                    OR upper(CAST(facts.unit AS VARCHAR)) IN ('', 'USD')
                  )
        ),
        ranked AS (
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY adsh, concept
                    ORDER BY tag_priority ASC, quarters DESC NULLS LAST, fact_date DESC NULLS LAST
                ) AS rn
            FROM filtered
        ),
        wide AS (
            SELECT
                adsh AS accession,
                {", ".join(raw_cols)}
            FROM ranked
            WHERE rn = 1
            GROUP BY adsh
        ),
        calculated AS (
            SELECT
                *,
                COALESCE(raw_working_capital, raw_current_assets - raw_current_liabilities)
                    AS calc_working_capital,
                raw_debt IS NOT NULL OR raw_debt_current IS NOT NULL AS debt_available,
                CASE
                    WHEN raw_debt IS NOT NULL OR raw_debt_current IS NOT NULL
                    THEN COALESCE(raw_debt, 0) + COALESCE(raw_debt_current, 0)
                    ELSE NULL
                END AS calc_debt
            FROM wide
        )
        SELECT
            accession,
            {", ".join(value_cols)},
            {", ".join(coverage_cols)},
            CASE WHEN raw_assets > 0 THEN ln(1 + raw_assets) END AS xbrl_ratio_log_assets,
            {ratio("raw_liabilities", "raw_assets")} AS xbrl_ratio_leverage,
            {ratio("raw_net_income", "raw_assets")} AS xbrl_ratio_profitability,
            {ratio("calc_working_capital", "raw_assets")} AS xbrl_ratio_working_capital_to_assets,
            {ratio("raw_receivables", "raw_revenues")} AS xbrl_ratio_receivables_to_revenue,
            {ratio("raw_inventory", "raw_assets")} AS xbrl_ratio_inventory_to_assets,
            {ratio("raw_cash", "raw_assets")} AS xbrl_ratio_cash_to_assets,
            {ratio("calc_debt", "raw_assets")} AS xbrl_ratio_debt_to_assets,
            {ratio("raw_operating_cash_flow", "raw_assets")}
                AS xbrl_ratio_operating_cash_flow_to_assets
        FROM calculated
    """


def _create_duckdb_xbrl_summary_view(con: Any, *, silver_dir: Path) -> bool:
    summary_path = silver_dir / "xbrl_fact_summary.parquet"
    legacy_xbrl_path = _preferred_table_path(silver_dir, "xbrl_fact")
    if summary_path.exists():
        source = parquet_scan_sql(summary_path)
        cols = set(_duckdb_columns(con, source))
        accession_expr = _duckdb_identifier("accession") if "accession" in cols else "adsh"
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW xbrl_summary_gold AS
            SELECT
                CAST({accession_expr} AS VARCHAR) AS accession,
                xbrl_fact_count,
                xbrl_unique_tags,
                xbrl_unique_units
            FROM {source}
            """
        )
        return True
    if legacy_xbrl_path.exists():
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW xbrl_summary_gold AS
            SELECT
                CAST(adsh AS VARCHAR) AS accession,
                count(tag)::BIGINT AS xbrl_fact_count,
                count(DISTINCT tag)::BIGINT AS xbrl_unique_tags,
                count(DISTINCT unit)::BIGINT AS xbrl_unique_units
            FROM {_duckdb_table_source(legacy_xbrl_path)}
            GROUP BY adsh
            """
        )
        return True
    return False


def _create_duckdb_xbrl_core_features_view(con: Any, *, silver_dir: Path) -> bool:
    xbrl_core_path = silver_dir / "xbrl_core_fact"
    xbrl_core_file_path = silver_dir / "xbrl_core_fact.parquet"
    legacy_xbrl_path = _preferred_table_path(silver_dir, "xbrl_fact")
    if xbrl_core_path.exists():
        source_path = xbrl_core_path
    elif xbrl_core_file_path.exists():
        source_path = xbrl_core_file_path
    elif legacy_xbrl_path.exists():
        source_path = legacy_xbrl_path
    else:
        return False
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW xbrl_core_features_gold AS
        {_duckdb_xbrl_core_features_query(source_path)}
        """
    )
    return True


def _create_duckdb_note_summary_view(con: Any, *, silver_dir: Path) -> bool:
    note_summary_path = silver_dir / "note_summary.parquet"
    legacy_note_path = _preferred_table_path(silver_dir, "note_text")
    note_text_dir = silver_dir / "note_text"
    if note_summary_path.exists():
        source = parquet_scan_sql(note_summary_path)
        cols = set(_duckdb_columns(con, source))
        accession_expr = _duckdb_identifier("accession") if "accession" in cols else "adsh"
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW note_summary_gold AS
            SELECT
                CAST({accession_expr} AS VARCHAR) AS accession,
                note_text_count,
                note_text_char_count
            FROM {source}
            """
        )
        return True
    if legacy_note_path.exists() or note_text_dir.exists():
        source_path = note_text_dir if note_text_dir.exists() else legacy_note_path
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW note_summary_gold AS
            SELECT
                CAST(adsh AS VARCHAR) AS accession,
                count(tag)::BIGINT AS note_text_count,
                sum(length(coalesce(CAST(note_text AS VARCHAR), '')))::BIGINT
                    AS note_text_char_count
            FROM {_duckdb_table_source(source_path)}
            GROUP BY adsh
            """
        )
        return True
    return False


def _build_gold_panels_duckdb(
    *,
    silver_dir: Path,
    gold_dir: Path,
    as_of_date: str,
    duckdb_threads: int = 4,
    duckdb_memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | str | None = None,
    duckdb_max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> Dict[str, Path]:
    con = _duckdb_connect(
        threads=duckdb_threads,
        memory_limit=duckdb_memory_limit,
        temp_directory=duckdb_temp_directory,
        max_temp_directory_size=duckdb_max_temp_directory_size,
    )
    try:
        issuer_source = _duckdb_table_source(_preferred_table_path(silver_dir, "issuer_dim"))
        filing_source = _duckdb_table_source(_preferred_table_path(silver_dir, "filing_dim"))
        issuer_cols = _duckdb_columns(con, issuer_source)
        filing_cols = _duckdb_columns(con, filing_source)

        issuer_selects = []
        for col in issuer_cols:
            if col == "issuer_cik":
                issuer_selects.append(f"{_duckdb_cik_expr(_duckdb_identifier(col))} AS issuer_cik")
            else:
                issuer_selects.append(_duckdb_identifier(col))
        filing_selects = []
        for col in filing_cols:
            ident = _duckdb_identifier(col)
            if col == "issuer_cik":
                filing_selects.append(f"{_duckdb_cik_expr(ident)} AS issuer_cik")
            elif col in {"filing_date", "report_date", "acceptance_datetime"}:
                filing_selects.append(f"{_duckdb_timestamp_expr(ident)} AS {ident}")
            else:
                filing_selects.append(ident)

        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW issuer_dim_gold AS
            SELECT {", ".join(issuer_selects)}
            FROM {issuer_source}
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW filing_dim_gold AS
            SELECT {", ".join(filing_selects)}
            FROM {filing_source}
            """
        )

        period_forms = ", ".join(_duckdb_string_expr(form) for form in sorted(PERIOD_FORMS))
        annual_forms = ", ".join(_duckdb_string_expr(form) for form in sorted(ANNUAL_FORMS))
        fpi_forms = ", ".join(_duckdb_string_expr(form) for form in sorted(FPI_FORMS))
        as_of_timestamp = f"try_cast({_duckdb_string_expr(as_of_date)} AS TIMESTAMP)"
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW filing_base_gold AS
            SELECT
                *,
                report_date AS event_report_date,
                CASE WHEN form IN ({period_forms}) THEN report_date ELSE NULL::TIMESTAMP END
                    AS fiscal_period_end,
                try_cast(date_part(
                    'year',
                    CASE WHEN form IN ({period_forms}) THEN report_date ELSE NULL::TIMESTAMP END
                ) AS INTEGER) AS fiscal_year,
                filing_date AS origin_date,
                {as_of_timestamp} AS as_of_date,
                CASE WHEN date_part('year', filing_date) >= 2011 THEN 1 ELSE 0 END
                    AS source_available_xbrl,
                CASE WHEN filing_date >= TIMESTAMP '2020-11-01' THEN 1 ELSE 0 END
                    AS source_available_notes,
                CASE WHEN filing_date >= TIMESTAMP '2017-01-31' THEN 1 ELSE 0 END
                    AS source_available_form_ap,
                CASE WHEN date_part('year', filing_date) >= 2018 THEN 1 ELSE 0 END
                    AS source_available_pcaob_inspections,
                CASE WHEN date_part('year', filing_date) >= 2006 THEN 1 ELSE 0 END
                    AS source_available_insider,
                CASE WHEN filing_date >= TIMESTAMP '2013-07-01' THEN 1 ELSE 0 END
                    AS source_available_13f,
                CASE
                    WHEN date_part('year', filing_date) >= 2003
                     AND NOT (
                        filing_date BETWEEN TIMESTAMP '2017-07-01' AND TIMESTAMP '2020-05-18'
                     )
                    THEN 1 ELSE 0
                END AS source_available_edgar_logs,
                CASE WHEN date_part('year', filing_date) >= 2012 THEN 1 ELSE 0 END
                    AS source_available_market_structure,
                TIMESTAMP '2017-01-31' AS public_date_form_ap,
                TIMESTAMP '2020-11-01' AS public_date_notes,
                TIMESTAMP '2013-07-01' AS public_date_13f,
                TIMESTAMP '2012-01-01' AS public_date_market_structure,
                '2011+' AS vintage_xbrl_main_sample,
                '2020-11+' AS vintage_notes,
                '2017-01-31+' AS vintage_form_ap
            FROM filing_dim_gold
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP VIEW filing_windowed_gold AS
            SELECT
                *,
                date_diff(
                    'day',
                    lag(origin_date) OVER (
                        PARTITION BY issuer_cik
                        ORDER BY origin_date, accession
                    ),
                    origin_date
                ) AS days_since_previous_filing,
                row_number() OVER (
                    PARTITION BY issuer_cik
                    ORDER BY origin_date, accession
                ) - 1 AS prior_filing_count
            FROM filing_base_gold
            """
        )

        _duckdb_source_or_empty(
            con=con,
            view_name="comment_thread_gold",
            path=silver_dir / "comment_thread.csv.gz",
            empty_columns=(
                ("issuer_cik", "VARCHAR"),
                ("first_public_date", "TIMESTAMP"),
                ("last_public_date", "TIMESTAMP"),
            ),
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW comment_thread_norm_gold AS
            SELECT
                {_duckdb_cik_expr("issuer_cik")} AS issuer_cik,
                {_duckdb_timestamp_expr("first_public_date")} AS first_public_date
            FROM comment_thread_gold
            """
        )
        _duckdb_source_or_empty(
            con=con,
            view_name="correction_event_gold",
            path=silver_dir / "correction_event.csv.gz",
            empty_columns=(
                ("issuer_cik", "VARCHAR"),
                ("public_date", "TIMESTAMP"),
                ("correction_type", "VARCHAR"),
            ),
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW correction_event_norm_gold AS
            SELECT
                {_duckdb_cik_expr("issuer_cik")} AS issuer_cik,
                {_duckdb_timestamp_expr("public_date")} AS public_date,
                CAST(correction_type AS VARCHAR) AS correction_type
            FROM correction_event_gold
            """
        )
        _duckdb_source_or_empty(
            con=con,
            view_name="issuer_8k_item_event_gold",
            path=silver_dir / "issuer_8k_item_event.csv.gz",
            empty_columns=(
                ("issuer_cik", "VARCHAR"),
                ("public_date", "TIMESTAMP"),
                ("report_date", "TIMESTAMP"),
                ("item_code", "VARCHAR"),
                ("event_type", "VARCHAR"),
                ("item_metadata_missing", "INTEGER"),
            ),
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW issuer_8k_item_event_norm_gold AS
            SELECT
                {_duckdb_cik_expr("issuer_cik")} AS issuer_cik,
                {_duckdb_timestamp_expr("public_date")} AS public_date,
                CAST(item_code AS VARCHAR) AS item_code,
                CAST(event_type AS VARCHAR) AS event_type,
                COALESCE(try_cast(item_metadata_missing AS INTEGER), 0)
                    AS item_metadata_missing
            FROM issuer_8k_item_event_gold
            """
        )
        _duckdb_source_or_empty(
            con=con,
            view_name="aaer_event_gold",
            path=silver_dir / "aaer_event.csv.gz",
            empty_columns=(
                ("issuer_cik", "VARCHAR"),
                ("event_date", "TIMESTAMP"),
                ("release_url", "VARCHAR"),
            ),
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW aaer_event_norm_gold AS
            SELECT
                {_duckdb_cik_expr("issuer_cik")} AS issuer_cik,
                {_duckdb_timestamp_expr("event_date")} AS event_date
            FROM aaer_event_gold
            """
        )
        _duckdb_source_or_empty(
            con=con,
            view_name="form_ap_event_gold",
            path=_preferred_table_path(silver_dir, "form_ap_event"),
            empty_columns=(
                ("issuer_cik", "VARCHAR"),
                ("fiscal_period_end", "TIMESTAMP"),
                ("form_filing_id", "VARCHAR"),
                ("engagement_partner_id", "VARCHAR"),
                ("number_of_participants", "DOUBLE"),
            ),
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW form_ap_summary_gold AS
            SELECT
                {_duckdb_cik_expr("issuer_cik")} AS issuer_cik,
                try_cast(date_part('year', {_duckdb_timestamp_expr("fiscal_period_end")})
                    AS INTEGER) AS fiscal_year,
                count(DISTINCT form_filing_id)::BIGINT AS form_ap_filing_count,
                count(DISTINCT engagement_partner_id)::BIGINT AS form_ap_unique_partners,
                avg(try_cast(number_of_participants AS DOUBLE)) AS form_ap_avg_participants
            FROM form_ap_event_gold
            GROUP BY 1, 2
            """
        )
        for view_name, filename, empty_columns in [
            (
                "partner_issuer_engagement_gold",
                "partner_issuer_engagement.csv.gz",
                (
                    ("issuer_cik", "VARCHAR"),
                    ("form_ap_public_date", "TIMESTAMP"),
                    ("engagement_partner_id", "VARCHAR"),
                ),
            ),
            (
                "partner_risk_history_gold",
                "partner_risk_history.csv.gz",
                (
                    ("engagement_partner_id", "VARCHAR"),
                    ("event_date", "TIMESTAMP"),
                    ("partner_prior_8k_402_count", "BIGINT"),
                    ("partner_prior_nonadmin_amendment_count", "BIGINT"),
                    ("partner_prior_total_count", "BIGINT"),
                ),
            ),
            (
                "partner_issuer_risk_history_gold",
                "partner_issuer_risk_history.csv.gz",
                (
                    ("engagement_partner_id", "VARCHAR"),
                    ("issuer_cik", "VARCHAR"),
                    ("event_date", "TIMESTAMP"),
                    ("partner_issuer_prior_8k_402_count", "BIGINT"),
                    ("partner_issuer_prior_nonadmin_amendment_count", "BIGINT"),
                    ("partner_issuer_prior_total_count", "BIGINT"),
                ),
            ),
        ]:
            _duckdb_source_or_empty(
                con=con,
                view_name=view_name,
                path=silver_dir / filename,
                empty_columns=empty_columns,
            )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW partner_issuer_engagement_norm_gold AS
            SELECT
                {_duckdb_cik_expr("issuer_cik")} AS issuer_cik,
                {_duckdb_timestamp_expr("form_ap_public_date")} AS form_ap_public_date,
                CAST(engagement_partner_id AS VARCHAR) AS engagement_partner_id
            FROM partner_issuer_engagement_gold
            WHERE engagement_partner_id IS NOT NULL
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP VIEW partner_risk_history_norm_gold AS
            SELECT
                CAST(engagement_partner_id AS VARCHAR) AS engagement_partner_id,
                try_cast(event_date AS TIMESTAMP) AS event_date,
                COALESCE(try_cast(partner_prior_8k_402_count AS BIGINT), 0)
                    AS partner_prior_8k_402_count,
                COALESCE(try_cast(partner_prior_nonadmin_amendment_count AS BIGINT), 0)
                    AS partner_prior_nonadmin_amendment_count,
                COALESCE(try_cast(partner_prior_total_count AS BIGINT), 0)
                    AS partner_prior_total_count
            FROM partner_risk_history_gold
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW partner_issuer_risk_history_norm_gold AS
            SELECT
                CAST(engagement_partner_id AS VARCHAR) AS engagement_partner_id,
                {_duckdb_cik_expr("issuer_cik")} AS issuer_cik,
                try_cast(event_date AS TIMESTAMP) AS event_date,
                COALESCE(try_cast(partner_issuer_prior_8k_402_count AS BIGINT), 0)
                    AS partner_issuer_prior_8k_402_count,
                COALESCE(try_cast(partner_issuer_prior_nonadmin_amendment_count AS BIGINT), 0)
                    AS partner_issuer_prior_nonadmin_amendment_count,
                COALESCE(try_cast(partner_issuer_prior_total_count AS BIGINT), 0)
                    AS partner_issuer_prior_total_count
            FROM partner_issuer_risk_history_gold
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP VIEW filing_partner_prior_raw_gold AS
            SELECT
                f.accession,
                COALESCE((
                    SELECT max(hist.partner_prior_8k_402_count)
                    FROM partner_risk_history_norm_gold hist
                    WHERE hist.engagement_partner_id = partner.engagement_partner_id
                      AND hist.event_date < f.origin_date
                ), 0) AS partner_total_prior_8k_402_count,
                COALESCE((
                    SELECT max(hist.partner_prior_nonadmin_amendment_count)
                    FROM partner_risk_history_norm_gold hist
                    WHERE hist.engagement_partner_id = partner.engagement_partner_id
                      AND hist.event_date < f.origin_date
                ), 0) AS partner_total_prior_nonadmin_amendment_count,
                COALESCE((
                    SELECT max(hist.partner_prior_total_count)
                    FROM partner_risk_history_norm_gold hist
                    WHERE hist.engagement_partner_id = partner.engagement_partner_id
                      AND hist.event_date < f.origin_date
                ), 0) AS partner_total_prior_total_count,
                COALESCE((
                    SELECT max(hist.partner_issuer_prior_8k_402_count)
                    FROM partner_issuer_risk_history_norm_gold hist
                    WHERE hist.engagement_partner_id = partner.engagement_partner_id
                      AND hist.issuer_cik = f.issuer_cik
                      AND hist.event_date < f.origin_date
                ), 0) AS current_issuer_prior_8k_402_count,
                COALESCE((
                    SELECT max(hist.partner_issuer_prior_nonadmin_amendment_count)
                    FROM partner_issuer_risk_history_norm_gold hist
                    WHERE hist.engagement_partner_id = partner.engagement_partner_id
                      AND hist.issuer_cik = f.issuer_cik
                      AND hist.event_date < f.origin_date
                ), 0) AS current_issuer_prior_nonadmin_amendment_count,
                COALESCE((
                    SELECT max(hist.partner_issuer_prior_total_count)
                    FROM partner_issuer_risk_history_norm_gold hist
                    WHERE hist.engagement_partner_id = partner.engagement_partner_id
                      AND hist.issuer_cik = f.issuer_cik
                      AND hist.event_date < f.origin_date
                ), 0) AS current_issuer_prior_total_count
            FROM filing_windowed_gold f
            LEFT JOIN LATERAL (
                SELECT engagement_partner_id
                FROM partner_issuer_engagement_norm_gold engagement
                WHERE engagement.issuer_cik = f.issuer_cik
                  AND engagement.form_ap_public_date < f.origin_date
                ORDER BY engagement.form_ap_public_date DESC, engagement_partner_id
                LIMIT 1
            ) partner ON TRUE
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TEMP VIEW filing_partner_prior_gold AS
            SELECT
                accession,
                partner_total_prior_8k_402_count - current_issuer_prior_8k_402_count
                    AS raw_other_issuer_8k_402_count,
                partner_total_prior_nonadmin_amendment_count
                    - current_issuer_prior_nonadmin_amendment_count
                    AS raw_other_issuer_nonadmin_amendment_count,
                partner_total_prior_total_count - current_issuer_prior_total_count
                    AS raw_other_issuer_total_count,
                greatest(
                    partner_total_prior_8k_402_count - current_issuer_prior_8k_402_count,
                    0
                ) AS auditor_partner_prior_other_issuer_8k_402_count,
                greatest(
                    partner_total_prior_nonadmin_amendment_count
                        - current_issuer_prior_nonadmin_amendment_count,
                    0
                ) AS auditor_partner_prior_other_issuer_nonadmin_amendment_count,
                greatest(
                    partner_total_prior_total_count - current_issuer_prior_total_count,
                    0
                ) AS auditor_partner_prior_other_issuer_total_count
            FROM filing_partner_prior_raw_gold
            """
        )
        negative_partner_rows = int(
            con.execute(
                """
                SELECT count(*)
                FROM filing_partner_prior_gold
                WHERE raw_other_issuer_8k_402_count < 0
                   OR raw_other_issuer_nonadmin_amendment_count < 0
                   OR raw_other_issuer_total_count < 0
                """
            ).fetchone()[0]
        )
        if negative_partner_rows:
            raise ValueError("Partner other-issuer prior exposure became negative before clipping.")

        has_xbrl_summary = _create_duckdb_xbrl_summary_view(con, silver_dir=silver_dir)
        has_xbrl_features = _create_duckdb_xbrl_core_features_view(con, silver_dir=silver_dir)
        has_note_summary = _create_duckdb_note_summary_view(con, silver_dir=silver_dir)

        filing_from = "filing_windowed_gold f"
        joins = [
            "LEFT JOIN form_ap_summary_gold form_ap USING (issuer_cik, fiscal_year)",
            "LEFT JOIN filing_partner_prior_gold partner_prior USING (accession)",
        ]
        if has_xbrl_summary:
            joins.append("LEFT JOIN xbrl_summary_gold xbrl_summary USING (accession)")
        if has_xbrl_features:
            joins.append("LEFT JOIN xbrl_core_features_gold xbrl_core USING (accession)")
        if has_note_summary:
            joins.append("LEFT JOIN note_summary_gold note_summary USING (accession)")
        joined_sql = "\n                ".join(joins)
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW filing_joined_gold AS
            SELECT
                f.*,
                form_ap.form_ap_filing_count,
                form_ap.form_ap_unique_partners,
                form_ap.form_ap_avg_participants,
                COALESCE(partner_prior.auditor_partner_prior_other_issuer_8k_402_count, 0)
                    AS auditor_partner_prior_other_issuer_8k_402_count,
                COALESCE(
                    partner_prior.auditor_partner_prior_other_issuer_nonadmin_amendment_count,
                    0
                ) AS auditor_partner_prior_other_issuer_nonadmin_amendment_count,
                COALESCE(partner_prior.auditor_partner_prior_other_issuer_total_count, 0)
                    AS auditor_partner_prior_other_issuer_total_count,
                CASE WHEN CAST(f.form AS VARCHAR) LIKE 'NT %' THEN 1 ELSE 0 END
                    AS filing_friction_is_nt,
                CASE WHEN EXISTS (
                    SELECT 1
                    FROM filing_windowed_gold nt
                    WHERE nt.issuer_cik = f.issuer_cik
                      AND nt.form IN ('NT 10-K', 'NT 10-Q')
                      AND nt.report_date = f.report_date
                      AND nt.origin_date <= f.origin_date
                ) THEN 1 ELSE 0 END AS filing_friction_nt_pre_origin,
                date_diff(
                    'day',
                    (
                        SELECT max(nt.origin_date)
                        FROM filing_windowed_gold nt
                        WHERE nt.issuer_cik = f.issuer_cik
                          AND nt.form IN ('NT 10-K', 'NT 10-Q')
                          AND nt.report_date = f.report_date
                          AND nt.origin_date <= f.origin_date
                    ),
                    f.origin_date
                ) AS filing_friction_nt_delay_days,
                (
                    SELECT count(*)
                    FROM comment_thread_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.first_public_date >= f.origin_date - INTERVAL 365 DAY
                      AND event.first_public_date < f.origin_date
                ) AS public_history_comment_thread_1y_count,
                (
                    SELECT count(*)
                    FROM comment_thread_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.first_public_date >= f.origin_date - INTERVAL 1095 DAY
                      AND event.first_public_date < f.origin_date
                ) AS public_history_comment_thread_3y_count,
                (
                    SELECT count(*)
                    FROM correction_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.correction_type = 'amendment_10x_a'
                      AND event.public_date >= f.origin_date - INTERVAL 365 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_amendment_1y_count,
                (
                    SELECT count(*)
                    FROM correction_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.correction_type = 'amendment_10x_a'
                      AND event.public_date >= f.origin_date - INTERVAL 1095 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_amendment_3y_count,
                (
                    SELECT count(*)
                    FROM issuer_8k_item_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.item_code = '3.01'
                      AND event.public_date >= f.origin_date - INTERVAL 365 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_8k_301_1y_count,
                (
                    SELECT count(*)
                    FROM issuer_8k_item_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.item_code = '3.01'
                      AND event.public_date >= f.origin_date - INTERVAL 1095 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_8k_301_3y_count,
                (
                    SELECT count(*)
                    FROM issuer_8k_item_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.item_code = '4.01'
                      AND event.public_date >= f.origin_date - INTERVAL 365 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_8k_401_1y_count,
                (
                    SELECT count(*)
                    FROM issuer_8k_item_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.item_code = '4.01'
                      AND event.public_date >= f.origin_date - INTERVAL 1095 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_8k_401_3y_count,
                (
                    SELECT count(*)
                    FROM issuer_8k_item_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.item_code = '4.02'
                      AND event.public_date >= f.origin_date - INTERVAL 365 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_8k_402_1y_count,
                (
                    SELECT count(*)
                    FROM issuer_8k_item_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.item_code = '4.02'
                      AND event.public_date >= f.origin_date - INTERVAL 1095 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_8k_402_3y_count,
                (
                    SELECT count(*)
                    FROM issuer_8k_item_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.item_code = '5.02'
                      AND event.public_date >= f.origin_date - INTERVAL 365 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_8k_502_1y_count,
                (
                    SELECT count(*)
                    FROM issuer_8k_item_event_norm_gold event
                    WHERE event.issuer_cik = f.issuer_cik
                      AND event.item_code = '5.02'
                      AND event.public_date >= f.origin_date - INTERVAL 1095 DAY
                      AND event.public_date < f.origin_date
                ) AS public_history_8k_502_3y_count
                {", xbrl_summary.* EXCLUDE (accession)" if has_xbrl_summary else ""}
                {", xbrl_core.* EXCLUDE (accession)" if has_xbrl_features else ""}
                {", note_summary.* EXCLUDE (accession)" if has_note_summary else ""}
            FROM {filing_from}
                {joined_sql}
            """
        )
        if has_xbrl_features:
            con.execute(
                """
                CREATE OR REPLACE TEMP VIEW filing_featured_gold AS
                SELECT
                    * EXCLUDE (prev_xbrl_value_revenues, prev_xbrl_value_assets),
                    CASE
                        WHEN prev_xbrl_value_revenues IS NOT NULL
                         AND prev_xbrl_value_revenues <> 0
                        THEN (xbrl_value_revenues - prev_xbrl_value_revenues)
                             / abs(prev_xbrl_value_revenues)
                    END AS xbrl_ratio_revenue_yoy_change,
                    CASE
                        WHEN xbrl_value_revenues IS NOT NULL
                         AND prev_xbrl_value_revenues IS NOT NULL
                         AND prev_xbrl_value_revenues <> 0
                        THEN 1 ELSE 0
                    END AS xbrl_coverage_revenues_yoy,
                    CASE
                        WHEN prev_xbrl_value_assets IS NOT NULL
                         AND prev_xbrl_value_assets <> 0
                        THEN (xbrl_value_assets - prev_xbrl_value_assets)
                             / abs(prev_xbrl_value_assets)
                    END AS xbrl_ratio_assets_yoy_change,
                    CASE
                        WHEN xbrl_value_assets IS NOT NULL
                         AND prev_xbrl_value_assets IS NOT NULL
                         AND prev_xbrl_value_assets <> 0
                        THEN 1 ELSE 0
                    END AS xbrl_coverage_assets_yoy
                FROM (
                    SELECT
                        *,
                        lag(xbrl_value_revenues) OVER (
                            PARTITION BY issuer_cik
                            ORDER BY fiscal_year, origin_date, accession
                        ) AS prev_xbrl_value_revenues,
                        lag(xbrl_value_assets) OVER (
                            PARTITION BY issuer_cik
                            ORDER BY fiscal_year, origin_date, accession
                        ) AS prev_xbrl_value_assets
                    FROM filing_joined_gold
                )
                """
            )
        else:
            con.execute(
                """
                CREATE OR REPLACE TEMP VIEW filing_featured_gold AS
                SELECT * FROM filing_joined_gold
                """
            )
        con.execute(
            """
            CREATE OR REPLACE TEMP VIEW filing_labeled_gold AS
            SELECT
                *,
                CASE WHEN EXISTS (
                    SELECT 1
                    FROM comment_thread_norm_gold event
                    WHERE event.issuer_cik = filing_featured_gold.issuer_cik
                      AND event.first_public_date > filing_featured_gold.origin_date
                      AND event.first_public_date
                            <= filing_featured_gold.origin_date + INTERVAL 365 DAY
                ) THEN 1 ELSE 0 END AS label_comment_thread_365,
                CASE WHEN EXISTS (
                    SELECT 1
                    FROM correction_event_norm_gold event
                    WHERE event.issuer_cik = filing_featured_gold.issuer_cik
                      AND event.correction_type = 'amendment_10x_a'
                      AND event.public_date > filing_featured_gold.origin_date
                      AND event.public_date <= filing_featured_gold.origin_date + INTERVAL 365 DAY
                ) THEN 1 ELSE 0 END AS label_amendment_365,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM issuer_8k_item_event_norm_gold event
                        WHERE event.issuer_cik = filing_featured_gold.issuer_cik
                          AND event.item_code = '4.02'
                          AND event.public_date > filing_featured_gold.origin_date
                          AND event.public_date
                                <= filing_featured_gold.origin_date + INTERVAL 365 DAY
                    ) THEN 1
                    WHEN EXISTS (
                        SELECT 1
                        FROM issuer_8k_item_event_norm_gold event
                        WHERE event.issuer_cik = filing_featured_gold.issuer_cik
                          AND event.item_metadata_missing = 1
                          AND event.public_date > filing_featured_gold.origin_date
                          AND event.public_date
                                <= filing_featured_gold.origin_date + INTERVAL 365 DAY
                    ) THEN NULL
                    ELSE 0
                END AS label_8k_402_365,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM issuer_8k_item_event_norm_gold event
                        WHERE event.issuer_cik = filing_featured_gold.issuer_cik
                          AND event.item_code = '4.02'
                          AND event.public_date > filing_featured_gold.origin_date
                          AND event.public_date
                                <= filing_featured_gold.origin_date + INTERVAL 365 DAY
                    ) THEN 0
                    WHEN EXISTS (
                        SELECT 1
                        FROM issuer_8k_item_event_norm_gold event
                        WHERE event.issuer_cik = filing_featured_gold.issuer_cik
                          AND event.item_metadata_missing = 1
                          AND event.public_date > filing_featured_gold.origin_date
                          AND event.public_date
                                <= filing_featured_gold.origin_date + INTERVAL 365 DAY
                    ) THEN 1
                    ELSE 0
                END AS k402_item_metadata_unknown_365,
                CASE WHEN EXISTS (
                    SELECT 1
                    FROM aaer_event_norm_gold event
                    WHERE event.issuer_cik = filing_featured_gold.issuer_cik
                      AND event.event_date > filing_featured_gold.origin_date
                      AND event.event_date <= filing_featured_gold.origin_date + INTERVAL 730 DAY
                ) THEN 1 ELSE 0 END AS label_aaer_proxy_730,
                CASE
                    WHEN origin_date + INTERVAL 365 DAY > as_of_date THEN 1 ELSE 0
                END AS censored_365,
                CASE
                    WHEN origin_date + INTERVAL 730 DAY > as_of_date THEN 1 ELSE 0
                END AS censored_730
            FROM filing_featured_gold
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW issuer_annual_candidates_gold AS
            SELECT
                *,
                CASE WHEN form = '10-K' THEN 0 WHEN form = '10-K/A' THEN 1 ELSE 99 END
                    AS annual_form_priority,
                row_number() OVER (
                    PARTITION BY issuer_cik, fiscal_year
                    ORDER BY
                        CASE WHEN form = '10-K' THEN 0 WHEN form = '10-K/A' THEN 1 ELSE 99 END,
                        origin_date,
                        form
                ) AS annual_row_number
            FROM filing_labeled_gold
            WHERE form IN ({annual_forms})
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW foreign_forms_gold AS
            SELECT DISTINCT
                issuer_cik,
                COALESCE(fiscal_year, try_cast(date_part('year', event_report_date) AS INTEGER))
                    AS fpi_year
            FROM filing_labeled_gold
            WHERE form IN ({fpi_forms})
              AND COALESCE(fiscal_year, try_cast(date_part('year', event_report_date) AS INTEGER))
                    IS NOT NULL
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW issuer_origin_gold AS
            SELECT
                annual.* EXCLUDE (annual_form_priority, annual_row_number),
                CASE WHEN foreign_forms.fpi_year IS NULL THEN 0 ELSE 1 END
                    AS issuer_has_fpi_form_year,
                CASE
                    WHEN foreign_forms.fpi_year IS NULL AND annual.form IN ({annual_forms})
                    THEN 1 ELSE 0
                END AS is_domestic_us_gaap_proxy,
                issuer.entity_name,
                issuer.sic,
                issuer.sic_description,
                issuer.entity_type
            FROM issuer_annual_candidates_gold annual
            LEFT JOIN foreign_forms_gold foreign_forms
                ON annual.issuer_cik = foreign_forms.issuer_cik
               AND annual.fiscal_year = foreign_forms.fpi_year
            LEFT JOIN issuer_dim_gold issuer
                ON annual.issuer_cik = issuer.issuer_cik
            WHERE annual.annual_row_number = 1
            """
        )

        gold_dir.mkdir(parents=True, exist_ok=True)
        filing_path = gold_dir / "filing_origin_panel.parquet"
        issuer_path = gold_dir / "issuer_origin_panel.parquet"
        _duckdb_copy_query_to_parquet_on_connection(
            con,
            query="SELECT * FROM filing_labeled_gold",
            dest=filing_path,
        )
        _duckdb_copy_query_to_parquet_on_connection(
            con,
            query="SELECT * FROM issuer_origin_gold",
            dest=issuer_path,
        )
        filing_rows = int(con.execute("SELECT count(*) FROM filing_labeled_gold").fetchone()[0])
        issuer_rows = int(con.execute("SELECT count(*) FROM issuer_origin_gold").fetchone()[0])
    finally:
        con.close()

    metadata_path = gold_dir / "gold_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "as_of_date": str(pd.Timestamp(as_of_date).date()),
                "parser_version": PARSER_VERSION,
                "schema_version": SCHEMA_VERSION,
                "engine": "duckdb",
                "duckdb_threads": int(duckdb_threads),
                "xbrl_core_tag_scope": "controlled_core_tags",
                "filing_rows": filing_rows,
                "issuer_origin_rows": issuer_rows,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "filing_origin_panel": filing_path,
        "issuer_origin_panel": issuer_path,
        "gold_metadata": metadata_path,
    }


def build_gold_panels(
    *,
    silver_dir: Path,
    gold_dir: Path,
    as_of_date: str,
    engine: str = "pandas",
    duckdb_threads: int = 4,
    duckdb_memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | str | None = None,
    duckdb_max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
) -> Dict[str, Path]:
    if engine not in {"pandas", "duckdb"}:
        raise ValueError("engine must be 'pandas' or 'duckdb'")
    if engine == "duckdb":
        return _build_gold_panels_duckdb(
            silver_dir=silver_dir,
            gold_dir=gold_dir,
            as_of_date=as_of_date,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
        )
    issuer_dim = _read_csv_with_engine(
        _preferred_table_path(silver_dir, "issuer_dim"),
        engine=engine,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit,
        duckdb_temp_directory=duckdb_temp_directory,
        duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
    )
    issuer_dim["issuer_cik"] = _normalize_cik_series(issuer_dim["issuer_cik"])
    for col in ["entity_name", "sic", "sic_description", "entity_type"]:
        if col not in issuer_dim.columns:
            issuer_dim[col] = pd.NA
    filing_dim = _read_csv_with_engine(
        _preferred_table_path(silver_dir, "filing_dim"),
        date_cols=["filing_date", "report_date", "acceptance_datetime"],
        engine=engine,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit,
        duckdb_temp_directory=duckdb_temp_directory,
        duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
    )
    comment_thread = (
        _read_csv_with_engine(
            silver_dir / "comment_thread.csv.gz",
            date_cols=["first_public_date", "last_public_date"],
            engine=engine,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
        )
        if (silver_dir / "comment_thread.csv.gz").exists()
        else pd.DataFrame()
    )
    correction_event = (
        _read_csv_with_engine(
            silver_dir / "correction_event.csv.gz",
            date_cols=["public_date", "report_date"],
            engine=engine,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
        )
        if (silver_dir / "correction_event.csv.gz").exists()
        else pd.DataFrame()
    )
    issuer_8k_item_event = (
        _read_csv_with_engine(
            silver_dir / "issuer_8k_item_event.csv.gz",
            date_cols=["public_date", "report_date"],
            engine=engine,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
        )
        if (silver_dir / "issuer_8k_item_event.csv.gz").exists()
        else pd.DataFrame()
    )
    form_ap_event = (
        _read_csv_with_engine(
            _preferred_table_path(silver_dir, "form_ap_event"),
            date_cols=["fiscal_period_end", "report_date", "filing_date"],
            engine=engine,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
        )
        if _preferred_table_path(silver_dir, "form_ap_event").exists()
        else pd.DataFrame()
    )
    aaer_event = (
        _read_csv_with_engine(
            silver_dir / "aaer_event.csv.gz",
            date_cols=["event_date"],
            engine=engine,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
        )
        if (silver_dir / "aaer_event.csv.gz").exists()
        else pd.DataFrame()
    )
    xbrl_summary = pd.DataFrame()
    xbrl_core_fact = pd.DataFrame()
    xbrl_summary_path = silver_dir / "xbrl_fact_summary.parquet"
    xbrl_core_path = silver_dir / "xbrl_core_fact"
    xbrl_core_file_path = silver_dir / "xbrl_core_fact.parquet"
    legacy_xbrl_path = _preferred_table_path(silver_dir, "xbrl_fact")
    if xbrl_summary_path.exists():
        xbrl_summary = read_table(
            xbrl_summary_path,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
        )
        if xbrl_core_path.exists():
            xbrl_core_fact = _duckdb_xbrl_core_facts(
                xbrl_core_path,
                threads=duckdb_threads,
                memory_limit=duckdb_memory_limit,
                temp_directory=duckdb_temp_directory,
                max_temp_directory_size=duckdb_max_temp_directory_size,
            )
        elif xbrl_core_file_path.exists():
            xbrl_core_fact = _duckdb_xbrl_core_facts(
                xbrl_core_file_path,
                threads=duckdb_threads,
                memory_limit=duckdb_memory_limit,
                temp_directory=duckdb_temp_directory,
                max_temp_directory_size=duckdb_max_temp_directory_size,
            )
    elif legacy_xbrl_path.exists():
        if (
            engine == "duckdb"
            or legacy_xbrl_path.suffix.lower() == ".parquet"
            or legacy_xbrl_path.is_dir()
        ):
            xbrl_summary = _duckdb_xbrl_summary(
                legacy_xbrl_path,
                threads=duckdb_threads,
                memory_limit=duckdb_memory_limit,
                temp_directory=duckdb_temp_directory,
                max_temp_directory_size=duckdb_max_temp_directory_size,
            )
            xbrl_core_fact = _duckdb_xbrl_core_facts(
                legacy_xbrl_path,
                threads=duckdb_threads,
                memory_limit=duckdb_memory_limit,
                temp_directory=duckdb_temp_directory,
                max_temp_directory_size=duckdb_max_temp_directory_size,
            )
        else:
            xbrl_fact = pd.read_csv(
                legacy_xbrl_path,
                usecols=lambda c: c in {"adsh", "tag", "unit", "value", "quarters", "fact_date"},
                low_memory=False,
            )
            xbrl_summary = (
                xbrl_fact.groupby("adsh", as_index=False)
                .agg(
                    xbrl_fact_count=("tag", "size"),
                    xbrl_unique_tags=("tag", "nunique"),
                    xbrl_unique_units=("unit", "nunique"),
                )
                .rename(columns={"adsh": "accession"})
            )
            xbrl_core_fact = xbrl_fact
    if not xbrl_summary.empty and "adsh" in xbrl_summary.columns:
        xbrl_summary = xbrl_summary.rename(columns={"adsh": "accession"})
    note_summary = pd.DataFrame()
    note_summary_path = silver_dir / "note_summary.parquet"
    legacy_note_path = _preferred_table_path(silver_dir, "note_text")
    if note_summary_path.exists():
        note_summary = read_table(
            note_summary_path,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
        )
    elif legacy_note_path.exists():
        if (
            engine == "duckdb"
            or legacy_note_path.suffix.lower() == ".parquet"
            or legacy_note_path.is_dir()
        ):
            note_summary = _duckdb_note_summary(
                legacy_note_path,
                threads=duckdb_threads,
                memory_limit=duckdb_memory_limit,
                temp_directory=duckdb_temp_directory,
                max_temp_directory_size=duckdb_max_temp_directory_size,
            )
        else:
            note_text = pd.read_csv(
                legacy_note_path, usecols=lambda c: c in {"adsh", "note_text", "tag"}
            )
            note_summary = (
                note_text.groupby("adsh", as_index=False)
                .agg(
                    note_text_count=("tag", "size"),
                    note_text_char_count=(
                        "note_text",
                        lambda s: int(s.fillna("").astype(str).str.len().sum()),
                    ),
                )
                .rename(columns={"adsh": "accession"})
            )
    if not note_summary.empty and "adsh" in note_summary.columns:
        note_summary = note_summary.rename(columns={"adsh": "accession"})

    filing = filing_dim.copy()
    filing["issuer_cik"] = _normalize_cik_series(filing["issuer_cik"])
    filing["event_report_date"] = filing["report_date"]
    filing["fiscal_period_end"] = pd.NaT
    period_mask = filing["form"].isin(PERIOD_FORMS)
    filing.loc[period_mask, "fiscal_period_end"] = filing.loc[period_mask, "report_date"]
    filing["fiscal_period_end"] = pd.to_datetime(filing["fiscal_period_end"], errors="coerce")
    filing["fiscal_year"] = filing["fiscal_period_end"].dt.year.astype("Int64")
    filing["origin_date"] = filing["filing_date"]
    filing["as_of_date"] = pd.Timestamp(as_of_date)
    filing["source_available_xbrl"] = filing["origin_date"].dt.year.fillna(0).ge(2011).astype(int)
    filing["source_available_notes"] = (
        filing["origin_date"].ge(pd.Timestamp("2020-11-01")).fillna(0).astype(int)
    )
    filing["source_available_form_ap"] = (
        filing["origin_date"].ge(pd.Timestamp("2017-01-31")).fillna(0).astype(int)
    )
    filing["source_available_pcaob_inspections"] = (
        filing["origin_date"].dt.year.fillna(0).ge(2018).astype(int)
    )
    filing["source_available_insider"] = (
        filing["origin_date"].dt.year.fillna(0).ge(2006).astype(int)
    )
    filing["source_available_13f"] = (
        filing["origin_date"].ge(pd.Timestamp("2013-07-01")).fillna(0).astype(int)
    )
    filing["source_available_edgar_logs"] = (
        (
            filing["origin_date"].dt.year.fillna(0).ge(2003)
            & ~filing["origin_date"].between(
                pd.Timestamp("2017-07-01"), pd.Timestamp("2020-05-18")
            )
        )
        .fillna(0)
        .astype(int)
    )
    filing["source_available_market_structure"] = (
        filing["origin_date"].dt.year.fillna(0).ge(2012).astype(int)
    )
    filing["public_date_form_ap"] = pd.Timestamp("2017-01-31")
    filing["public_date_notes"] = pd.Timestamp("2020-11-01")
    filing["public_date_13f"] = pd.Timestamp("2013-07-01")
    filing["public_date_market_structure"] = pd.Timestamp("2012-01-01")
    filing["vintage_xbrl_main_sample"] = "2011+"
    filing["vintage_notes"] = "2020-11+"
    filing["vintage_form_ap"] = "2017-01-31+"

    filing = filing.sort_values(["issuer_cik", "origin_date", "accession"])
    filing["days_since_previous_filing"] = (
        filing.groupby("issuer_cik")["origin_date"].diff().dt.days
    )
    filing["prior_filing_count"] = filing.groupby("issuer_cik").cumcount()

    if not xbrl_summary.empty:
        filing = filing.merge(xbrl_summary, on="accession", how="left")
        xbrl_core_features = build_xbrl_core_features(xbrl_core_fact)
        if not xbrl_core_features.empty:
            filing = filing.merge(xbrl_core_features, on="accession", how="left")
            filing = add_xbrl_yoy_ratio_features(filing)

    if not note_summary.empty:
        filing = filing.merge(note_summary, on="accession", how="left")

    if not form_ap_event.empty:
        form_ap_event["issuer_cik"] = _normalize_cik_series(form_ap_event["issuer_cik"])
        form_ap_event["fiscal_year"] = form_ap_event["fiscal_period_end"].dt.year.astype("Int64")
        form_ap_summary = form_ap_event.groupby(["issuer_cik", "fiscal_year"], as_index=False).agg(
            form_ap_filing_count=("form_filing_id", "nunique"),
            form_ap_unique_partners=("engagement_partner_id", "nunique"),
            form_ap_avg_participants=("number_of_participants", "mean"),
        )
        filing = filing.merge(
            form_ap_summary,
            left_on=["issuer_cik", "fiscal_year"],
            right_on=["issuer_cik", "fiscal_year"],
            how="left",
        )

    filing = _add_partner_prior_features(
        filing,
        silver_dir=silver_dir,
        engine=engine,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit,
        duckdb_temp_directory=duckdb_temp_directory,
        duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
    )
    filing = _add_public_history_and_filing_friction_features(
        filing,
        comment_thread=comment_thread,
        correction_event=correction_event,
        issuer_8k_item_event=issuer_8k_item_event,
    )

    filing["label_comment_thread_365"] = _event_within_horizon(
        filing,
        comment_thread.rename(columns={"first_public_date": "event_date"}),
        date_col="event_date",
        horizon_days=365,
    )
    filing["label_amendment_365"] = _event_within_horizon(
        filing,
        correction_event,
        date_col="public_date",
        horizon_days=365,
        event_type="amendment_10x_a",
    )
    label_8k_402, k402_unknown = _k402_label_and_unknown(filing, issuer_8k_item_event)
    filing["label_8k_402_365"] = label_8k_402
    filing["k402_item_metadata_unknown_365"] = k402_unknown
    filing["label_aaer_proxy_730"] = _event_within_horizon(
        filing,
        aaer_event.rename(columns={"event_date": "public_date", "issuer_cik": "issuer_cik"}),
        date_col="public_date",
        horizon_days=730,
        event_type=None,
        type_col="release_url",
    )
    filing["censored_365"] = (
        filing["origin_date"] + pd.Timedelta(days=365) > filing["as_of_date"]
    ).astype(int)
    filing["censored_730"] = (
        filing["origin_date"] + pd.Timedelta(days=730) > filing["as_of_date"]
    ).astype(int)

    issuer_panel = filing.loc[filing["form"].isin(ANNUAL_FORMS)].copy()
    issuer_panel["annual_form_priority"] = issuer_panel["form"].map({"10-K": 0, "10-K/A": 1})
    issuer_panel = issuer_panel.sort_values(
        ["issuer_cik", "fiscal_year", "annual_form_priority", "origin_date", "form"]
    )
    issuer_panel = issuer_panel.drop_duplicates(subset=["issuer_cik", "fiscal_year"], keep="first")
    issuer_panel = issuer_panel.drop(columns=["annual_form_priority"])

    foreign_forms = filing.loc[
        filing["form"].isin(FPI_FORMS), ["issuer_cik", "fiscal_year"]
    ].copy()
    foreign_forms["fpi_year"] = foreign_forms["fiscal_year"]
    event_year = filing.loc[filing["form"].isin(FPI_FORMS), "event_report_date"].dt.year.astype(
        "Int64"
    )
    foreign_forms.loc[foreign_forms["fpi_year"].isna(), "fpi_year"] = event_year
    foreign_forms = foreign_forms[["issuer_cik", "fpi_year"]].dropna().drop_duplicates()
    foreign_forms["issuer_has_fpi_form_year"] = 1
    issuer_panel = issuer_panel.merge(
        foreign_forms,
        left_on=["issuer_cik", "fiscal_year"],
        right_on=["issuer_cik", "fpi_year"],
        how="left",
    )
    issuer_panel = issuer_panel.drop(columns=["fpi_year"])
    issuer_panel["issuer_has_fpi_form_year"] = (
        issuer_panel["issuer_has_fpi_form_year"].fillna(0).astype(int)
    )
    issuer_panel["is_domestic_us_gaap_proxy"] = (
        issuer_panel["issuer_has_fpi_form_year"].eq(0) & issuer_panel["form"].isin(ANNUAL_FORMS)
    ).astype(int)

    issuer_panel = issuer_panel.merge(
        issuer_dim[["issuer_cik", "entity_name", "sic", "sic_description", "entity_type"]],
        on="issuer_cik",
        how="left",
        suffixes=("", "_issuer"),
    )

    gold_dir.mkdir(parents=True, exist_ok=True)
    filing_path = gold_dir / "filing_origin_panel.parquet"
    issuer_path = gold_dir / "issuer_origin_panel.parquet"
    write_table(filing, filing_path)
    write_table(issuer_panel, issuer_path)
    metadata_path = gold_dir / "gold_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "as_of_date": str(pd.Timestamp(as_of_date).date()),
                "parser_version": PARSER_VERSION,
                "schema_version": SCHEMA_VERSION,
                "engine": engine,
                "duckdb_threads": int(duckdb_threads) if engine == "duckdb" else None,
                "xbrl_core_tag_scope": "controlled_core_tags",
                "filing_rows": int(len(filing)),
                "issuer_origin_rows": int(len(issuer_panel)),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "filing_origin_panel": filing_path,
        "issuer_origin_panel": issuer_path,
        "gold_metadata": metadata_path,
    }


def build_public_lake(
    *,
    bronze_dir: Path,
    silver_dir: Path,
    gold_dir: Path,
    as_of_date: str,
    submissions_max_ciks: Optional[int] = None,
    engine: str = "duckdb",
    duckdb_threads: int = 4,
    duckdb_memory_limit: str | None = DEFAULT_DUCKDB_MEMORY_LIMIT,
    duckdb_temp_directory: Path | str | None = None,
    duckdb_max_temp_directory_size: str | None = DEFAULT_DUCKDB_MAX_TEMP_DIRECTORY_SIZE,
    storage_format: str = "parquet",
    notes_mode: str = "summary",
    fsds_batch_size: int = DEFAULT_FSDS_BATCH_SIZE,
    notes_batch_size: int = DEFAULT_NOTES_BATCH_SIZE,
    fresh_build: bool = False,
    resume: bool = False,
) -> Dict[str, Path]:
    if engine not in {"pandas", "duckdb"}:
        raise ValueError("engine must be 'pandas' or 'duckdb'")
    if storage_format not in {"parquet", "csv-gz"}:
        raise ValueError("storage_format must be 'parquet' or 'csv-gz'")
    if notes_mode not in {"summary", "raw", "skip"}:
        raise ValueError("notes_mode must be 'summary', 'raw', or 'skip'")
    if storage_format == "parquet" and engine != "duckdb":
        raise ValueError("storage_format='parquet' requires engine='duckdb'")
    if fsds_batch_size < 1 or notes_batch_size < 1:
        raise ValueError("fsds_batch_size and notes_batch_size must be positive")

    resolved_duckdb_temp_directory = duckdb_temp_directory
    if engine == "duckdb" and resolved_duckdb_temp_directory is None:
        resolved_duckdb_temp_directory = silver_dir / "._duckdb_tmp"

    if fresh_build:
        remove_table_path(silver_dir)
        remove_table_path(gold_dir)
    silver_dir.mkdir(parents=True, exist_ok=True)

    def normalize_submissions_task() -> Dict[str, Path]:
        submissions_zip = bronze_dir / "sec-bulk" / "submissions.zip"
        if not submissions_zip.exists():
            raise FileNotFoundError(
                "Expected bronze/sec-bulk/submissions.zip before building the public lake."
            )
        _verify_metadata_hash(submissions_zip)
        return normalize_submissions_bulk(
            submissions_zip=submissions_zip,
            silver_dir=silver_dir,
            max_ciks=submissions_max_ciks,
        )

    def normalize_form_ap_task() -> Dict[str, Path]:
        form_ap_csv = bronze_dir / "form-ap" / "FirmFilings.csv"
        if not form_ap_csv.exists():
            extracted = bronze_dir / "form-ap" / "FirmFilings.zip"
            if extracted.exists():
                _verify_metadata_hash(extracted)
                with zipfile.ZipFile(extracted) as zf:
                    if "FirmFilings.csv" in zf.namelist():
                        zf.extract("FirmFilings.csv", path=bronze_dir / "form-ap")
        if not form_ap_csv.exists():
            return {}
        _verify_metadata_hash(form_ap_csv)
        return {
            "form_ap_event": normalize_form_ap_csv(form_ap_csv=form_ap_csv, silver_dir=silver_dir)
        }

    def normalize_inspections_task() -> Dict[str, Path]:
        inspection_manifest = bronze_dir / "pcaob-inspections" / "manifest.csv"
        if not inspection_manifest.exists():
            return {}
        manifest = pd.read_csv(inspection_manifest)
        for _, row in manifest.iterrows():
            path = Path(row["local_path"])
            if not path.exists():
                continue
            if path.suffix.lower() in {".csv", ".json", ".xml", ".xlsx"}:
                _verify_metadata_hash(path)
                return {
                    "pcaob_inspection_event": normalize_pcaob_inspection_file(
                        inspection_path=path,
                        silver_dir=silver_dir,
                    )
                }
        return {}

    def normalize_fsds_task() -> Dict[str, Path]:
        fsds_manifest = bronze_dir / "fsds" / "manifest.csv"
        if not fsds_manifest.exists():
            return {}
        if storage_format == "parquet":
            return _normalize_fsds_manifest_parquet(
                manifest_csv=fsds_manifest,
                silver_dir=silver_dir,
                duckdb_threads=duckdb_threads,
                duckdb_memory_limit=duckdb_memory_limit,
                duckdb_temp_directory=resolved_duckdb_temp_directory,
                duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
                batch_size=fsds_batch_size,
                resume=resume,
            )
        return _normalize_manifest_archives(
            manifest_csv=fsds_manifest,
            silver_dir=silver_dir,
            normalizer_name="fsds",
            engine=engine,
            duckdb_threads=duckdb_threads,
        )

    def normalize_notes_task() -> Dict[str, Path]:
        notes_manifest = bronze_dir / "notes" / "manifest.csv"
        if not notes_manifest.exists():
            return {}
        if storage_format == "parquet":
            return _normalize_notes_manifest_parquet(
                manifest_csv=notes_manifest,
                silver_dir=silver_dir,
                duckdb_threads=duckdb_threads,
                notes_mode=notes_mode,
                duckdb_memory_limit=duckdb_memory_limit,
                duckdb_temp_directory=resolved_duckdb_temp_directory,
                duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
                batch_size=notes_batch_size,
                resume=resume,
            )
        return _normalize_manifest_archives(
            manifest_csv=notes_manifest,
            silver_dir=silver_dir,
            normalizer_name="notes",
            engine=engine,
            duckdb_threads=duckdb_threads,
        )

    def derived_tables_task() -> Dict[str, Path]:
        filing_dim_path = _preferred_table_path(silver_dir, "filing_dim")
        issuer_8k_item_event = build_issuer_8k_item_events(
            filing_dim_csv=filing_dim_path,
            silver_dir=silver_dir,
        )
        amendment_annotation = build_amendment_annotations(
            filing_dim_csv=filing_dim_path,
            silver_dir=silver_dir,
            amendment_text_dir=(
                bronze_dir / "amendment-primary-docs"
                if (bronze_dir / "amendment-primary-docs").exists()
                else None
            ),
        )
        outputs: Dict[str, Path] = {
            "comment_thread": build_comment_threads(
                filing_dim_csv=filing_dim_path,
                silver_dir=silver_dir,
            ),
            "correction_event": build_correction_events(
                filing_dim_csv=filing_dim_path,
                silver_dir=silver_dir,
            ),
            "issuer_8k_item_event": issuer_8k_item_event,
            "amendment_annotation": amendment_annotation,
            "aaer_event": normalize_aaer_events(
                aaer_bronze_dir=bronze_dir / "aaer",
                silver_dir=silver_dir,
                issuer_dim_path=_preferred_table_path(silver_dir, "issuer_dim"),
            ),
        }
        outputs.update(
            build_partner_risk_histories(
                form_ap_event_path=_preferred_table_path(silver_dir, "form_ap_event"),
                issuer_8k_item_event_path=issuer_8k_item_event,
                amendment_annotation_path=amendment_annotation,
                silver_dir=silver_dir,
            )
        )
        return outputs

    def empty_tables_task() -> Dict[str, Path]:
        task_outputs: Dict[str, Path] = {}
        for filename, cols in EMPTY_TABLE_SCHEMAS.items():
            path = silver_dir / filename
            if not path.exists():
                pd.DataFrame(columns=list(cols)).to_csv(path, index=False, compression="gzip")
            task_outputs[path.stem.replace(".csv", "")] = path
        return task_outputs

    def gold_task() -> Dict[str, Path]:
        return build_gold_panels(
            silver_dir=silver_dir,
            gold_dir=gold_dir,
            as_of_date=as_of_date,
            engine=engine,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit=duckdb_memory_limit,
            duckdb_temp_directory=resolved_duckdb_temp_directory,
            duckdb_max_temp_directory_size=duckdb_max_temp_directory_size,
        )

    def metadata_task() -> Dict[str, Path]:
        run_metadata = silver_dir / "public_lake_run_metadata.json"
        run_metadata.write_text(
            json.dumps(
                {
                    "as_of_date": str(pd.Timestamp(as_of_date).date()),
                    "engine": engine,
                    "duckdb_threads": int(duckdb_threads) if engine == "duckdb" else None,
                    "duckdb_memory_limit": duckdb_memory_limit if engine == "duckdb" else None,
                    "duckdb_temp_directory": str(resolved_duckdb_temp_directory)
                    if engine == "duckdb"
                    else None,
                    "duckdb_max_temp_directory_size": duckdb_max_temp_directory_size
                    if engine == "duckdb"
                    else None,
                    "parser_version": PARSER_VERSION,
                    "schema_version": SCHEMA_VERSION,
                    "storage_format": storage_format,
                    "notes_mode": notes_mode,
                    "fsds_batch_size": int(fsds_batch_size),
                    "notes_batch_size": int(notes_batch_size),
                    "fresh_build": bool(fresh_build),
                    "resume": bool(resume),
                    "xbrl_core_tag_scope": "controlled_core_tags",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return {"public_lake_run_metadata": run_metadata}

    tasks = [
        DagTask("normalize_submissions", (), normalize_submissions_task),
        DagTask("normalize_form_ap", (), normalize_form_ap_task),
        DagTask("normalize_inspections", (), normalize_inspections_task),
        DagTask("normalize_fsds", (), normalize_fsds_task),
        DagTask("normalize_notes", (), normalize_notes_task),
        DagTask("derived_tables", ("normalize_submissions", "normalize_form_ap"), derived_tables_task),
        DagTask("empty_tables", ("derived_tables",), empty_tables_task),
        DagTask(
            "build_gold",
            (
                "normalize_submissions",
                "normalize_form_ap",
                "normalize_inspections",
                "normalize_fsds",
                "normalize_notes",
                "derived_tables",
                "empty_tables",
            ),
            gold_task,
        ),
        DagTask("write_metadata", ("build_gold",), metadata_task),
    ]
    runner = SimpleDagRunner(state_dir=silver_dir / ".public_lake_dag", resume=resume)
    return runner.run(tasks)
