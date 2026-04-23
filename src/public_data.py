"""
Public-data acquisition utilities for SEC and PCAOB sources.

These functions implement the immediately accessible part of the research plan:
reference data, public monitoring data, filing indexes, and document downloads.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd
import requests

DEFAULT_USER_AGENT = "Tuoyuan Cheng tuoyuan.cheng@nus.edu.sg"
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
PCAOB_FORM_AP_ZIP_URL = "https://pcaobus.org/assets/PCAOBFiles/FirmFilings.zip"
PCAOB_FORM_AP_DICT_URL = (
    "https://assets.pcaobus.org/pcaob-dev/docs/default-source/rusdocuments/"
    "auditorsearch-form-ap-data-references.pdf"
)


@dataclass(frozen=True)
class DownloadedFiles:
    sec_tickers: Path
    pcaob_zip: Path
    pcaob_csv: Path
    pcaob_dictionary: Path


def _session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    return session


def download_file(
    url: str,
    dest: Path,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = 60,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _session(user_agent).get(url, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    return dest


def download_public_reference_data(
    *,
    sec_dir: Path,
    pcaob_dir: Path,
    user_agent: str = DEFAULT_USER_AGENT,
) -> DownloadedFiles:
    sec_dir.mkdir(parents=True, exist_ok=True)
    pcaob_dir.mkdir(parents=True, exist_ok=True)

    sec_tickers = download_file(
        SEC_TICKER_URL,
        sec_dir / "company_tickers.json",
        user_agent=user_agent,
    )
    pcaob_zip = download_file(
        PCAOB_FORM_AP_ZIP_URL,
        pcaob_dir / "FirmFilings.zip",
        user_agent=user_agent,
    )
    pcaob_dictionary = download_file(
        PCAOB_FORM_AP_DICT_URL,
        pcaob_dir / "auditorsearch_form_ap_data_dictionary.pdf",
        user_agent=user_agent,
    )

    with zipfile.ZipFile(pcaob_zip) as zf:
        members = zf.namelist()
        if "FirmFilings.csv" not in members:
            raise ValueError(f"Unexpected PCAOB zip contents: {members[:5]}")
        zf.extract("FirmFilings.csv", path=pcaob_dir)
    pcaob_csv = pcaob_dir / "FirmFilings.csv"
    return DownloadedFiles(
        sec_tickers=sec_tickers,
        pcaob_zip=pcaob_zip,
        pcaob_csv=pcaob_csv,
        pcaob_dictionary=pcaob_dictionary,
    )


def read_gvkey_cik_link(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError("Only CSV gvkey-CIK link files are currently supported.")

    cols = {c.lower(): c for c in df.columns}
    if "gvkey" not in cols or "cik" not in cols:
        raise ValueError("gvkey-CIK link file must contain columns named gvkey and cik.")
    df = df.rename(columns={cols["gvkey"]: "gvkey", cols["cik"]: "cik"})
    df["gvkey"] = df["gvkey"].astype(str)
    df["cik"] = (
        pd.to_numeric(df["cik"], errors="coerce")
        .astype("Int64")
        .astype(str)
        .str.replace("<NA>", "", regex=False)
        .str.zfill(10)
    )

    for date_col in ["first_date", "last_date"]:
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df


def resolve_gvkey_cik(panel_keys: pd.DataFrame, link_df: pd.DataFrame) -> pd.DataFrame:
    panel = panel_keys.copy()
    panel["gvkey"] = panel["gvkey"].astype(str)
    if "data_year" in link_df.columns:
        link_df = link_df.copy()
        link_df["data_year"] = pd.to_numeric(link_df["data_year"], errors="coerce").astype("Int64")
        work = panel.merge(link_df, on=["gvkey", "data_year"], how="left")
    else:
        work = panel.merge(link_df, on="gvkey", how="left")

    if {"first_date", "last_date"}.issubset(work.columns):
        year_start = work["first_date"].dt.year.fillna(-10_000)
        year_end = work["last_date"].dt.year.fillna(10_000)
        within_range = work["data_year"].astype(int).between(year_start, year_end)
        work = work.loc[within_range | year_start.eq(-10_000) | year_end.eq(10_000)].copy()

    work = work.sort_values(["gvkey", "data_year", "cik"])
    work = work.drop_duplicates(subset=["gvkey", "data_year"], keep="first")
    return work[["gvkey", "data_year", "cik"]]


def fetch_sec_submissions(
    cik: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = 60,
) -> pd.DataFrame:
    cik = str(cik).zfill(10)
    session = _session(user_agent)
    response = session.get(SEC_SUBMISSIONS_URL.format(cik=cik), timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    frames: List[pd.DataFrame] = []
    recent = pd.DataFrame(payload["filings"]["recent"])
    recent["source_file"] = "recent"
    frames.append(recent)

    for file_info in payload["filings"].get("files", []):
        name = file_info.get("name")
        if not name:
            continue
        older = session.get(f"https://data.sec.gov/submissions/{name}", timeout=timeout)
        older.raise_for_status()
        older_df = pd.DataFrame(older.json())
        older_df["source_file"] = name
        frames.append(older_df)

    filings = pd.concat(frames, ignore_index=True)
    filings["cik"] = cik
    filings["filingDate"] = pd.to_datetime(filings["filingDate"], errors="coerce")
    filings["reportDate"] = pd.to_datetime(filings.get("reportDate"), errors="coerce")
    return filings


def build_sec_filing_index(
    *,
    master_panel_csv: Path,
    gvkey_cik_csv: Path,
    out_csv: Path,
    forms: Sequence[str],
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> pd.DataFrame:
    master = pd.read_csv(master_panel_csv, usecols=["gvkey", "data_year"])
    master["gvkey"] = master["gvkey"].astype(str)
    master["data_year"] = pd.to_numeric(master["data_year"], errors="coerce").astype("Int64")

    link_df = read_gvkey_cik_link(gvkey_cik_csv)
    resolved = resolve_gvkey_cik(master, link_df)
    ciks = sorted(resolved["cik"].dropna().astype(str).unique())

    filing_frames: List[pd.DataFrame] = []
    for cik in ciks:
        filings = fetch_sec_submissions(cik, user_agent=user_agent)
        filing_frames.append(filings)

    if not filing_frames:
        empty = pd.DataFrame()
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        empty.to_csv(out_csv, index=False)
        return empty

    filings = pd.concat(filing_frames, ignore_index=True)
    filings = filings.loc[filings["form"].isin(forms)].copy()
    if start_year is not None:
        filings = filings.loc[filings["filingDate"].dt.year >= int(start_year)].copy()
    if end_year is not None:
        filings = filings.loc[filings["filingDate"].dt.year <= int(end_year)].copy()

    filings["report_year"] = filings["reportDate"].dt.year.astype("Int64")
    filings["candidate_data_year"] = filings["report_year"]

    missing_report = filings["candidate_data_year"].isna()
    annual_forms = filings["form"].isin(["10-K", "10-K/A"])
    filings.loc[missing_report & annual_forms, "candidate_data_year"] = (
        filings.loc[missing_report & annual_forms, "filingDate"].dt.year - 1
    )
    filings.loc[missing_report & ~annual_forms, "candidate_data_year"] = filings.loc[
        missing_report & ~annual_forms, "filingDate"
    ].dt.year
    filings["candidate_data_year"] = filings["candidate_data_year"].astype("Int64")

    merged = resolved.merge(
        filings,
        left_on=["cik", "data_year"],
        right_on=["cik", "candidate_data_year"],
        how="left",
    )

    accession = merged["accessionNumber"].fillna("")
    merged["accession_no_dash"] = accession.str.replace("-", "", regex=False)
    merged["filing_url"] = np.where(
        accession.ne(""),
        "https://www.sec.gov/Archives/edgar/data/"
        + merged["cik"].str.lstrip("0")
        + "/"
        + merged["accession_no_dash"]
        + "/"
        + merged["primaryDocument"].fillna(""),
        "",
    )
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_csv, index=False)
    return merged


def download_sec_filings(
    *,
    index_csv: Path,
    out_dir: Path,
    user_agent: str = DEFAULT_USER_AGENT,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    index_df = pd.read_csv(index_csv)
    index_df = index_df.loc[index_df["filing_url"].fillna("").ne("")].copy()
    if limit:
        index_df = index_df.head(int(limit)).copy()

    downloaded_rows = []
    for _, row in index_df.iterrows():
        cik = str(row["cik"]).zfill(10)
        accession = str(row["accession_no_dash"])
        primary_doc = Path(str(row["primaryDocument"])).name
        dest = out_dir / cik / accession / primary_doc
        download_file(str(row["filing_url"]), dest, user_agent=user_agent)
        record = row.to_dict()
        record["local_path"] = str(dest)
        downloaded_rows.append(record)

    downloaded = pd.DataFrame(downloaded_rows)
    if not downloaded.empty:
        downloaded.to_csv(out_dir / "download_manifest.csv", index=False)
    return downloaded
