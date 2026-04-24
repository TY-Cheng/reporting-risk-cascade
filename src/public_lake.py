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
import io
import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd
import requests

DEFAULT_USER_AGENT = "Tuoyuan Cheng tuoyuan.cheng@nus.edu.sg"
PARSER_VERSION = "public-lake-v1"
SCHEMA_VERSION = "public-lake-v1"
SEC_REQUEST_INTERVAL_SECONDS = 0.15
CSV_CHUNKSIZE = 250_000

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
_LAST_REQUEST_AT = 0.0

XBRL_CORE_TAGS: Dict[str, Sequence[str]] = {
    "assets": ("Assets",),
    "liabilities": ("Liabilities", "LiabilitiesAndStockholdersEquity"),
    "revenues": ("Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "receivables": ("AccountsReceivableNetCurrent", "ReceivablesNetCurrent"),
    "inventory": ("InventoryNet", "InventoryFinishedGoodsNetOfReserves"),
    "debt": ("LongTermDebtAndFinanceLeaseObligations", "LongTermDebt"),
    "debt_current": ("ShortTermBorrowings", "LongTermDebtCurrent"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "working_capital": ("WorkingCapital",),
}


@dataclass(frozen=True)
class SourceSpec:
    name: str
    kind: str
    page_url: Optional[str] = None
    direct_urls: Sequence[str] = ()
    note: str = ""


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
    if match:
        work = work.loc[haystack.str.contains(match.lower(), regex=False)].copy()
    if start_year is not None or end_year is not None:
        years = haystack.str.extract(r"(?P<year>20\d{2}|19\d{2})")["year"]
        work["year_hint"] = pd.to_numeric(years, errors="coerce")
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
        return pd.read_csv(path, sep=r"\s{2,}", engine="python", low_memory=False)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".xml":
        return pd.read_xml(path)
    if suffix == ".xlsx":
        return pd.read_excel(path)
    raise ValueError(f"Unsupported table file type: {path}")


def _extract_zip_member_table(zip_path: Path, member: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member) as handle:
            raw = handle.read()
    sample = raw.decode("utf-8", errors="ignore").splitlines()[:20]
    if any("\t" in line for line in sample):
        return pd.read_csv(io.BytesIO(raw), sep="\t", low_memory=False)
    if any("|" in line for line in sample):
        return pd.read_csv(io.BytesIO(raw), sep="|", low_memory=False)
    return pd.read_csv(io.BytesIO(raw), low_memory=False)


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
    issuer_path = silver_dir / "issuer_dim.csv.gz"
    filing_path = silver_dir / "filing_dim.csv.gz"
    issuer_dim.to_csv(issuer_path, index=False, compression="gzip")
    filing_dim.to_csv(filing_path, index=False, compression="gzip")
    return {"issuer_dim": issuer_path, "filing_dim": filing_path}


def normalize_fsds_archive(*, archive_path: Path, silver_dir: Path) -> Dict[str, Path]:
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
        xbrl_fact["fact_date"] = pd.to_datetime(
            xbrl_fact["fact_date"].astype(str), errors="coerce"
        )
    silver_dir.mkdir(parents=True, exist_ok=True)
    filing_path = silver_dir / "filing_xbrl_dim.csv.gz"
    fact_path = silver_dir / "xbrl_fact.csv.gz"
    filing_xbrl.to_csv(filing_path, index=False, compression="gzip")
    xbrl_fact.to_csv(fact_path, index=False, compression="gzip")
    return {"filing_xbrl_dim": filing_path, "xbrl_fact": fact_path}


def normalize_notes_archive(*, archive_path: Path, silver_dir: Path) -> Dict[str, Path]:
    with zipfile.ZipFile(archive_path) as zf:
        txt_members = [name for name in zf.namelist() if Path(name).name.lower().startswith("txt")]
        sub_members = _pick_members(zf, "sub")
        if not txt_members:
            raise ValueError(f"Could not find txt table in {archive_path}")
        note_df = _extract_zip_member_table(archive_path, txt_members[0])
        outputs: Dict[str, Path] = {}
        if sub_members:
            sub_df = _extract_zip_member_table(archive_path, sub_members[0])
            sub_path = silver_dir / "notes_filing_dim.csv.gz"
            sub_df.to_csv(sub_path, index=False, compression="gzip")
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
        note_text["fact_date"] = pd.to_datetime(note_text["fact_date"], errors="coerce")
    silver_dir.mkdir(parents=True, exist_ok=True)
    note_path = silver_dir / "note_text.csv.gz"
    note_text.to_csv(note_path, index=False, compression="gzip")
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
    out_path = silver_dir / "form_ap_event.csv.gz"
    work.to_csv(out_path, index=False, compression="gzip")
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
) -> Dict[str, Path]:
    normalizers = {
        "fsds": normalize_fsds_archive,
        "notes": normalize_notes_archive,
    }
    normalizer = normalizers[normalizer_name]
    manifest = pd.read_csv(manifest_csv)
    outputs: Dict[str, Path] = {}
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
        archive_outputs = normalizer(archive_path=archive_path, silver_dir=tmp_dir)
        for key, tmp_path in archive_outputs.items():
            dest_path = silver_dir / Path(tmp_path).name
            if key not in outputs and dest_path.exists():
                dest_path.unlink()
            _append_csv_gzip(Path(tmp_path), dest_path)
            outputs[key] = dest_path

    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    return outputs


def build_comment_threads(*, filing_dim_csv: Path, silver_dir: Path) -> Path:
    filing_dim = pd.read_csv(filing_dim_csv, parse_dates=["filing_date", "report_date"])
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


def build_correction_events(*, filing_dim_csv: Path, silver_dir: Path) -> Path:
    filing_dim = pd.read_csv(filing_dim_csv, parse_dates=["filing_date", "report_date"])
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
    is_402 = eight_k["items"].str.contains("4.02", regex=False) | eight_k[
        "primary_doc_description"
    ].str.contains("4.02", regex=False)
    for _, row in eight_k.loc[is_402].iterrows():
        rows.append(
            {
                "issuer_cik": row["issuer_cik"],
                "accession": row["accession"],
                "public_date": row["filing_date"],
                "report_date": row["report_date"],
                "correction_type": "nonreliance_8k_402",
                "identified_from": "items_or_description",
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


def normalize_aaer_events(
    *,
    aaer_bronze_dir: Path,
    silver_dir: Path,
    issuer_dim_csv: Optional[Path] = None,
) -> Path:
    listing_html = aaer_bronze_dir / "aaer_listing.html"
    rows: List[Dict[str, Any]] = []
    issuer_dim = None
    if issuer_dim_csv is not None and issuer_dim_csv.exists():
        issuer_dim = pd.read_csv(issuer_dim_csv, usecols=["issuer_cik", "entity_name"])
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
    wide["xbrl_ratio_operating_cash_flow_to_assets"] = _ratio(
        wide["operating_cash_flow"], assets
    )

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


def build_gold_panels(
    *,
    silver_dir: Path,
    gold_dir: Path,
    as_of_date: str,
) -> Dict[str, Path]:
    issuer_dim = pd.read_csv(silver_dir / "issuer_dim.csv.gz")
    issuer_dim["issuer_cik"] = _normalize_cik_series(issuer_dim["issuer_cik"])
    filing_dim = pd.read_csv(
        silver_dir / "filing_dim.csv.gz",
        parse_dates=["filing_date", "report_date", "acceptance_datetime"],
    )
    comment_thread = (
        pd.read_csv(
            silver_dir / "comment_thread.csv.gz",
            parse_dates=["first_public_date", "last_public_date"],
        )
        if (silver_dir / "comment_thread.csv.gz").exists()
        else pd.DataFrame()
    )
    correction_event = (
        _read_csv_with_optional_dates(
            silver_dir / "correction_event.csv.gz",
            ["public_date", "report_date"],
        )
        if (silver_dir / "correction_event.csv.gz").exists()
        else pd.DataFrame()
    )
    form_ap_event = (
        _read_csv_with_optional_dates(
            silver_dir / "form_ap_event.csv.gz",
            ["fiscal_period_end", "report_date", "filing_date"],
        )
        if (silver_dir / "form_ap_event.csv.gz").exists()
        else pd.DataFrame()
    )
    aaer_event = (
        _read_csv_with_optional_dates(silver_dir / "aaer_event.csv.gz", ["event_date"])
        if (silver_dir / "aaer_event.csv.gz").exists()
        else pd.DataFrame()
    )
    xbrl_fact = (
        pd.read_csv(
            silver_dir / "xbrl_fact.csv.gz",
            usecols=lambda c: c in {"adsh", "tag", "unit", "value", "quarters", "fact_date"},
            low_memory=False,
        )
        if (silver_dir / "xbrl_fact.csv.gz").exists()
        else pd.DataFrame()
    )
    note_text = (
        pd.read_csv(
            silver_dir / "note_text.csv.gz", usecols=lambda c: c in {"adsh", "note_text", "tag"}
        )
        if (silver_dir / "note_text.csv.gz").exists()
        else pd.DataFrame()
    )

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

    if not xbrl_fact.empty:
        xbrl_summary = (
            xbrl_fact.groupby("adsh", as_index=False)
            .agg(
                xbrl_fact_count=("tag", "size"),
                xbrl_unique_tags=("tag", "nunique"),
                xbrl_unique_units=("unit", "nunique"),
            )
            .rename(columns={"adsh": "accession"})
        )
        filing = filing.merge(xbrl_summary, on="accession", how="left")
        xbrl_core_features = build_xbrl_core_features(xbrl_fact)
        if not xbrl_core_features.empty:
            filing = filing.merge(xbrl_core_features, on="accession", how="left")
            filing = add_xbrl_yoy_ratio_features(filing)

    if not note_text.empty:
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
    filing["label_8k_402_365"] = _event_within_horizon(
        filing,
        correction_event,
        date_col="public_date",
        horizon_days=365,
        event_type="nonreliance_8k_402",
    )
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
    filing_path = gold_dir / "filing_origin_panel.csv.gz"
    issuer_path = gold_dir / "issuer_origin_panel.csv.gz"
    filing.to_csv(filing_path, index=False, compression="gzip")
    issuer_panel.to_csv(issuer_path, index=False, compression="gzip")
    metadata_path = gold_dir / "gold_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "as_of_date": str(pd.Timestamp(as_of_date).date()),
                "parser_version": PARSER_VERSION,
                "schema_version": SCHEMA_VERSION,
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
) -> Dict[str, Path]:
    outputs: Dict[str, Path] = {}
    silver_dir.mkdir(parents=True, exist_ok=True)

    submissions_zip = bronze_dir / "sec-bulk" / "submissions.zip"
    if submissions_zip.exists():
        _verify_metadata_hash(submissions_zip)
        outputs.update(
            normalize_submissions_bulk(
                submissions_zip=submissions_zip,
                silver_dir=silver_dir,
                max_ciks=submissions_max_ciks,
            )
        )
    else:
        raise FileNotFoundError(
            "Expected bronze/sec-bulk/submissions.zip before building the public lake."
        )

    form_ap_csv = bronze_dir / "form-ap" / "FirmFilings.csv"
    if not form_ap_csv.exists():
        extracted = bronze_dir / "form-ap" / "FirmFilings.zip"
        if extracted.exists():
            _verify_metadata_hash(extracted)
            with zipfile.ZipFile(extracted) as zf:
                if "FirmFilings.csv" in zf.namelist():
                    zf.extract("FirmFilings.csv", path=bronze_dir / "form-ap")
    if form_ap_csv.exists():
        _verify_metadata_hash(form_ap_csv)
        outputs["form_ap_event"] = normalize_form_ap_csv(
            form_ap_csv=form_ap_csv, silver_dir=silver_dir
        )

    inspection_manifest = bronze_dir / "pcaob-inspections" / "manifest.csv"
    if inspection_manifest.exists():
        manifest = pd.read_csv(inspection_manifest)
        for _, row in manifest.iterrows():
            path = Path(row["local_path"])
            if not path.exists():
                continue
            if path.suffix.lower() in {".csv", ".json", ".xml", ".xlsx"}:
                _verify_metadata_hash(path)
                outputs["pcaob_inspection_event"] = normalize_pcaob_inspection_file(
                    inspection_path=path,
                    silver_dir=silver_dir,
                )
                break

    fsds_manifest = bronze_dir / "fsds" / "manifest.csv"
    if fsds_manifest.exists():
        outputs.update(
            _normalize_manifest_archives(
                manifest_csv=fsds_manifest,
                silver_dir=silver_dir,
                normalizer_name="fsds",
            )
        )

    notes_manifest = bronze_dir / "notes" / "manifest.csv"
    if notes_manifest.exists():
        outputs.update(
            _normalize_manifest_archives(
                manifest_csv=notes_manifest,
                silver_dir=silver_dir,
                normalizer_name="notes",
            )
        )

    outputs["comment_thread"] = build_comment_threads(
        filing_dim_csv=silver_dir / "filing_dim.csv.gz",
        silver_dir=silver_dir,
    )
    outputs["correction_event"] = build_correction_events(
        filing_dim_csv=silver_dir / "filing_dim.csv.gz",
        silver_dir=silver_dir,
    )
    outputs["aaer_event"] = normalize_aaer_events(
        aaer_bronze_dir=bronze_dir / "aaer",
        silver_dir=silver_dir,
        issuer_dim_csv=silver_dir / "issuer_dim.csv.gz",
    )
    for filename, cols in EMPTY_TABLE_SCHEMAS.items():
        path = silver_dir / filename
        if not path.exists():
            pd.DataFrame(columns=list(cols)).to_csv(path, index=False, compression="gzip")
        outputs[path.stem.replace(".csv", "")] = path
    outputs.update(
        build_gold_panels(
            silver_dir=silver_dir,
            gold_dir=gold_dir,
            as_of_date=as_of_date,
        )
    )
    return outputs
