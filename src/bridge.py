"""
Public-only bridge feasibility probe.

This module deliberately does not infer an authoritative historical crosswalk.
It can use a provenance-tagged gvkey-CIK-year crosswalk, or it can report
whether the old gvkey benchmark panel has enough public identifiers to attempt a
bridge. In both cases it writes coverage and multiplicity reports before any
overlap analysis is allowed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from .table_io import read_table, write_table


RAW_CIK_COLS = ("issuer_cik", "cik", "CIK")
RAW_TICKER_COLS = ("ticker", "tic", "TICKER", "TIC")
RAW_NAME_COLS = ("entity_name", "company_name", "conm", "CONM", "name")
RAW_CUSIP_COLS = ("cusip", "CUSIP")
PUBLIC_TICKER_COLS = ("ticker", "tickers", "tickers_json")
PUBLIC_NAME_COLS = ("entity_name", "company_name", "name")
PUBLIC_CIK_COLS = ("issuer_cik", "cik", "CIK")
CROSSWALK_GVKEY_COLS = ("gvkey", "GVKEY", "global_company_key")
CROSSWALK_CIK_COLS = ("issuer_cik", "cik", "CIK", "cik_number")
CROSSWALK_YEAR_COLS = ("data_year", "fiscal_year", "fyear", "year")
CROSSWALK_START_YEAR_COLS = ("start_year", "start_fiscal_year", "start_fyear")
CROSSWALK_END_YEAR_COLS = ("end_year", "end_fiscal_year", "end_fyear")
PROVENANCE_COLUMNS = (
    "source",
    "source_version",
    "extracted_at",
    "match_method",
    "match_score",
)


def _first_existing(columns: Iterable[str], candidates: Sequence[str]) -> Optional[str]:
    column_list = list(columns)
    column_set = set(column_list)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    lower_map = {str(column).lower(): column for column in column_list}
    for candidate in candidates:
        found = lower_map.get(str(candidate).lower())
        if found is not None:
            return found
    return None


def _normalize_cik(value: object) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    try:
        numeric = int(float(text))
    except ValueError:
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return None
        numeric = int(digits)
    if numeric <= 0:
        return None
    return str(numeric).zfill(10)


def _normalize_gvkey(value: object) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    try:
        numeric = int(float(text))
    except ValueError:
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return None
        numeric = int(digits)
    if numeric < 0:
        return None
    return str(numeric)


def _normalize_year(value: object) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    try:
        year = int(float(text))
    except ValueError:
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) < 4:
            return None
        year = int(digits[:4])
    if year < 1800 or year > 2200:
        return None
    return year


def _normalize_ticker(value: object) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper()
    if not text or text in {"NAN", "NONE"}:
        return None
    return text.replace(".", "-")


def _normalize_name(value: object) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = " ".join(str(value).upper().split())
    if not text or text in {"NAN", "NONE"}:
        return None
    for suffix in [" CORPORATION", " CORP", " INCORPORATED", " INC", " LIMITED", " LTD"]:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text.strip() or None


def _parse_tickers(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        if pd.isna(value):
            return []
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "[]"}:
            return []
        try:
            parsed = json.loads(text)
            raw_values = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            raw_values = [part.strip() for part in text.replace(";", ",").split(",")]
    tickers = [_normalize_ticker(item) for item in raw_values]
    return [ticker for ticker in tickers if ticker]


def _read_table_if_exists(path: Optional[Path]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    return read_table(path, low_memory=False)


def _raw_years(raw: Optional[pd.DataFrame], *, year_col: str) -> List[int]:
    if raw is None or year_col not in raw.columns:
        return []
    years = raw[year_col].map(_normalize_year).dropna().astype(int)
    return sorted(years.unique().tolist())


def _raw_identifier_columns(raw: pd.DataFrame) -> Dict[str, Optional[str]]:
    return {
        "cik": _first_existing(raw.columns, RAW_CIK_COLS),
        "ticker": _first_existing(raw.columns, RAW_TICKER_COLS),
        "name": _first_existing(raw.columns, RAW_NAME_COLS),
        "cusip": _first_existing(raw.columns, RAW_CUSIP_COLS),
    }


def _external_crosswalk_frame(
    crosswalk: pd.DataFrame,
    *,
    raw: Optional[pd.DataFrame] = None,
    firm_col: str = "gvkey",
    year_col: str = "data_year",
    source: Optional[str] = None,
    source_version: Optional[str] = None,
    extracted_at: Optional[str] = None,
    match_method: Optional[str] = None,
    match_score: Optional[float] = None,
) -> pd.DataFrame:
    """Normalize a gvkey-CIK crosswalk to annual rows with provenance."""

    columns = crosswalk.columns
    gvkey_col = _first_existing(columns, CROSSWALK_GVKEY_COLS)
    cik_col = _first_existing(columns, CROSSWALK_CIK_COLS)
    year_value_col = _first_existing(columns, CROSSWALK_YEAR_COLS)
    start_year_col = _first_existing(columns, CROSSWALK_START_YEAR_COLS)
    end_year_col = _first_existing(columns, CROSSWALK_END_YEAR_COLS)
    if gvkey_col is None:
        raise ValueError("external crosswalk is missing a gvkey column")
    if cik_col is None:
        raise ValueError("external crosswalk is missing an issuer_cik/cik column")
    if year_value_col is None and (start_year_col is None or end_year_col is None):
        raise ValueError(
            "external crosswalk must include data_year/fiscal_year/fyear or start_year/end_year"
        )

    raw_year_values = _raw_years(raw, year_col=year_col)
    raw_year_set = set(raw_year_values)
    min_raw_year = min(raw_year_values) if raw_year_values else None
    max_raw_year = max(raw_year_values) if raw_year_values else None

    rows: List[Dict[str, object]] = []
    for _, row in crosswalk.iterrows():
        gvkey = _normalize_gvkey(row.get(gvkey_col))
        issuer_cik = _normalize_cik(row.get(cik_col))
        if gvkey is None or issuer_cik is None:
            continue

        if year_value_col is not None:
            years = [_normalize_year(row.get(year_value_col))]
        else:
            start_year = _normalize_year(row.get(start_year_col))
            end_year = _normalize_year(row.get(end_year_col))
            if start_year is None or end_year is None:
                years = []
            else:
                if min_raw_year is not None:
                    start_year = max(start_year, min_raw_year)
                if max_raw_year is not None:
                    end_year = min(end_year, max_raw_year)
                years = list(range(start_year, end_year + 1)) if end_year >= start_year else []

        for year in years:
            if year is None:
                continue
            year = int(year)
            if raw_year_set and year not in raw_year_set:
                continue
            record: Dict[str, object] = {
                "gvkey": gvkey,
                "data_year": year,
                "issuer_cik": issuer_cik,
                "source": row.get("source", source or "external_crosswalk"),
                "source_version": row.get("source_version", source_version or ""),
                "extracted_at": row.get("extracted_at", extracted_at or ""),
                "match_method": row.get("match_method", match_method or "external_crosswalk"),
                "match_score": row.get("match_score", match_score if match_score is not None else ""),
                "_bridge_gvkey": gvkey,
                "_bridge_year": year,
            }
            rows.append(record)

    if not rows:
        return pd.DataFrame(
            columns=[
                "gvkey",
                "data_year",
                "issuer_cik",
                *PROVENANCE_COLUMNS,
                "_bridge_gvkey",
                "_bridge_year",
            ]
        )
    normalized = pd.DataFrame(rows)
    return normalized.drop_duplicates(
        subset=["gvkey", "data_year", "issuer_cik", *PROVENANCE_COLUMNS]
    ).reset_index(drop=True)


def prepare_gvkey_cik_crosswalk(
    *,
    input_path: Path,
    output_path: Path,
    raw_data_path: Optional[Path] = None,
    source: Optional[str] = None,
    source_version: Optional[str] = None,
    extracted_at: Optional[str] = None,
    match_method: Optional[str] = None,
    match_score: Optional[float] = None,
) -> Dict[str, object]:
    """Normalize an external WRDS/Compustat gvkey-CIK export for bridge use."""

    crosswalk = read_table(input_path, low_memory=False)
    raw = read_table(raw_data_path, low_memory=False) if raw_data_path and raw_data_path.exists() else None
    normalized = _external_crosswalk_frame(
        crosswalk,
        raw=raw,
        source=source,
        source_version=source_version,
        extracted_at=extracted_at,
        match_method=match_method,
        match_score=match_score,
    )
    output = normalized[
        ["gvkey", "data_year", "issuer_cik", *PROVENANCE_COLUMNS]
    ].sort_values(["gvkey", "data_year", "issuer_cik"])
    write_table(output, output_path)
    summary = {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "raw_data_path": str(raw_data_path) if raw_data_path else None,
        "input_rows": int(len(crosswalk)),
        "output_rows": int(len(output)),
        "gvkeys": int(output["gvkey"].nunique()) if not output.empty else 0,
        "issuer_ciks": int(output["issuer_cik"].nunique()) if not output.empty else 0,
        "year_min": int(output["data_year"].min()) if not output.empty else None,
        "year_max": int(output["data_year"].max()) if not output.empty else None,
    }
    return summary


def _public_identifier_frame(public: pd.DataFrame) -> pd.DataFrame:
    if public.empty:
        return pd.DataFrame()

    cik_col = _first_existing(public.columns, PUBLIC_CIK_COLS)
    ticker_col = _first_existing(public.columns, PUBLIC_TICKER_COLS)
    name_col = _first_existing(public.columns, PUBLIC_NAME_COLS)
    if cik_col is None:
        return pd.DataFrame()

    base_cols = [cik_col]
    if ticker_col:
        base_cols.append(ticker_col)
    if name_col:
        base_cols.append(name_col)
    if "sic" in public.columns:
        base_cols.append("sic")

    work = public[base_cols].drop_duplicates().copy()
    work["issuer_cik"] = work[cik_col].map(_normalize_cik)
    work = work.loc[work["issuer_cik"].notna()].copy()
    if work.empty:
        return pd.DataFrame()

    rows: List[Dict[str, object]] = []
    for _, row in work.iterrows():
        issuer_cik = row["issuer_cik"]
        name_key = _normalize_name(row[name_col]) if name_col else None
        sic = row["sic"] if "sic" in work.columns else None
        if ticker_col:
            for ticker in _parse_tickers(row[ticker_col]):
                rows.append(
                    {
                        "issuer_cik": issuer_cik,
                        "match_type": "ticker",
                        "match_value": ticker,
                        "public_entity_name_key": name_key,
                        "public_sic": sic,
                    }
                )
        if name_key:
            rows.append(
                {
                    "issuer_cik": issuer_cik,
                    "match_type": "name",
                    "match_value": name_key,
                    "public_entity_name_key": name_key,
                    "public_sic": sic,
                }
            )
    cik_rows = [
        {
            "issuer_cik": cik,
            "match_type": "cik",
            "match_value": cik,
            "public_entity_name_key": None,
            "public_sic": None,
        }
        for cik in work["issuer_cik"].dropna().unique()
    ]
    result = pd.DataFrame(cik_rows + rows)
    if result.empty:
        return result
    return result.drop_duplicates(
        subset=["issuer_cik", "match_type", "match_value"]
    ).reset_index(drop=True)


def _public_year_key_frame(public: pd.DataFrame) -> pd.DataFrame:
    if public.empty:
        return pd.DataFrame(columns=["issuer_cik", "_bridge_year"])

    cik_col = _first_existing(public.columns, PUBLIC_CIK_COLS)
    year_col = _first_existing(public.columns, ("fiscal_year", "data_year", "year", "fyear"))
    if cik_col is None or year_col is None:
        return pd.DataFrame(columns=["issuer_cik", "_bridge_year"])

    keys = public[[cik_col, year_col]].copy()
    keys["issuer_cik"] = keys[cik_col].map(_normalize_cik)
    keys["_bridge_year"] = keys[year_col].map(_normalize_year)
    keys = keys.loc[keys["issuer_cik"].notna() & keys["_bridge_year"].notna()].copy()
    return keys[["issuer_cik", "_bridge_year"]].drop_duplicates()


def _public_overlap_stats(candidates: pd.DataFrame, public: pd.DataFrame) -> Dict[str, object]:
    empty = {
        "public_overlap_candidate_rows": 0,
        "public_overlap_raw_rows": 0,
        "public_overlap_rate": 0.0,
    }
    if candidates.empty or public.empty or "issuer_cik" not in candidates.columns:
        return empty

    public_keys = _public_year_key_frame(public)
    if public_keys.empty:
        return empty

    candidate_keys = candidates.copy()
    candidate_keys["issuer_cik"] = candidate_keys["issuer_cik"].map(_normalize_cik)
    if "_bridge_year" not in candidate_keys.columns:
        year_source = _first_existing(candidate_keys.columns, CROSSWALK_YEAR_COLS)
        candidate_keys["_bridge_year"] = (
            candidate_keys[year_source].map(_normalize_year)
            if year_source is not None
            else pd.NA
        )
    candidate_keys = candidate_keys.loc[
        candidate_keys["issuer_cik"].notna() & candidate_keys["_bridge_year"].notna()
    ].copy()
    if candidate_keys.empty:
        return empty

    overlap = candidate_keys.merge(public_keys, on=["issuer_cik", "_bridge_year"], how="inner")
    raw_denominator = candidates["raw_row_id"].nunique() if "raw_row_id" in candidates else 0
    raw_numerator = overlap["raw_row_id"].nunique() if "raw_row_id" in overlap else 0
    return {
        "public_overlap_candidate_rows": int(len(overlap)),
        "public_overlap_raw_rows": int(raw_numerator),
        "public_overlap_rate": float(raw_numerator / raw_denominator)
        if raw_denominator
        else 0.0,
    }


def _raw_identifier_frame(
    raw: pd.DataFrame,
    *,
    firm_col: str,
    year_col: str,
    target_col: str,
) -> pd.DataFrame:
    ids = _raw_identifier_columns(raw)
    rows: List[Dict[str, object]] = []
    for raw_row_id, row in raw.reset_index(drop=True).iterrows():
        base = {
            "raw_row_id": int(raw_row_id),
            firm_col: row.get(firm_col),
            year_col: row.get(year_col),
            target_col: row.get(target_col),
        }
        if ids["cik"]:
            cik = _normalize_cik(row[ids["cik"]])
            if cik:
                rows.append({**base, "match_type": "cik", "match_value": cik})
        if ids["ticker"]:
            ticker = _normalize_ticker(row[ids["ticker"]])
            if ticker:
                rows.append({**base, "match_type": "ticker", "match_value": ticker})
        if ids["name"]:
            name = _normalize_name(row[ids["name"]])
            if name:
                rows.append({**base, "match_type": "name", "match_value": name})
    return pd.DataFrame(rows)


def _external_crosswalk_candidates(
    raw: pd.DataFrame,
    crosswalk: pd.DataFrame,
    *,
    firm_col: str,
    year_col: str,
    target_col: str,
) -> pd.DataFrame:
    normalized = _external_crosswalk_frame(
        crosswalk,
        raw=raw,
        firm_col=firm_col,
        year_col=year_col,
    )
    if normalized.empty:
        return pd.DataFrame()

    raw_work = raw.reset_index(drop=True).copy()
    raw_work["raw_row_id"] = raw_work.index.astype(int)
    raw_work["_bridge_gvkey"] = raw_work[firm_col].map(_normalize_gvkey)
    raw_work["_bridge_year"] = raw_work[year_col].map(_normalize_year)
    base_cols = ["raw_row_id", firm_col, year_col, "_bridge_gvkey", "_bridge_year"]
    if target_col in raw_work.columns:
        base_cols.append(target_col)
    else:
        raw_work[target_col] = pd.NA
        base_cols.append(target_col)
    raw_work = raw_work.loc[
        raw_work["_bridge_gvkey"].notna() & raw_work["_bridge_year"].notna(), base_cols
    ].copy()
    if raw_work.empty:
        return pd.DataFrame()

    normalized_merge = normalized.drop(columns=["gvkey", "data_year"], errors="ignore")
    candidates = raw_work.merge(
        normalized_merge,
        on=["_bridge_gvkey", "_bridge_year"],
        how="inner",
    )
    if candidates.empty:
        return candidates
    candidates["match_type"] = "external_crosswalk"
    candidates["match_value"] = candidates["issuer_cik"]
    candidates["provenance"] = candidates["source"].fillna("external_crosswalk")
    columns = [
        "raw_row_id",
        firm_col,
        year_col,
        target_col,
        "issuer_cik",
        "match_type",
        "match_value",
        "provenance",
        *PROVENANCE_COLUMNS,
    ]
    return candidates[columns].drop_duplicates(
        subset=["raw_row_id", "issuer_cik", "match_type", "match_value", *PROVENANCE_COLUMNS]
    )


def _coverage_report(
    raw: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    firm_col: str,
    target_col: str,
) -> pd.DataFrame:
    raw_rows = int(len(raw))
    raw_firms = int(raw[firm_col].nunique()) if firm_col in raw.columns else 0
    matched_row_ids = set(candidates["raw_row_id"]) if "raw_row_id" in candidates.columns else set()
    matched_firms = (
        candidates[firm_col].dropna().nunique() if firm_col in candidates.columns else 0
    )
    positives = (
        pd.to_numeric(raw[target_col], errors="coerce").fillna(0).astype(int)
        if target_col in raw.columns
        else pd.Series(dtype=int)
    )
    matched_mask = raw.reset_index(drop=True).index.to_series().isin(matched_row_ids)
    return pd.DataFrame(
        [
            {"metric": "raw_rows", "value": raw_rows},
            {"metric": "raw_firms", "value": raw_firms},
            {"metric": "matched_raw_rows", "value": int(matched_mask.sum())},
            {"metric": "matched_raw_firms", "value": int(matched_firms)},
            {
                "metric": "row_coverage_rate",
                "value": float(matched_mask.mean()) if raw_rows else 0.0,
            },
            {
                "metric": "firm_coverage_rate",
                "value": float(matched_firms / raw_firms) if raw_firms else 0.0,
            },
            {"metric": "raw_positive_rows", "value": int(positives.sum())},
            {
                "metric": "matched_positive_rows",
                "value": int(positives.loc[matched_mask.to_numpy()].sum())
                if len(positives)
                else 0,
            },
        ]
    )


def _multiplicity_report(candidates: pd.DataFrame, *, firm_col: str) -> pd.DataFrame:
    columns = ["grain", "key", "candidate_count"]
    if candidates.empty:
        return pd.DataFrame(columns=columns)
    raw_mult = (
        candidates.groupby("raw_row_id")["issuer_cik"]
        .nunique()
        .reset_index(name="candidate_count")
        .rename(columns={"raw_row_id": "key"})
    )
    raw_mult["grain"] = "raw_row"
    firm_mult = (
        candidates.groupby(firm_col)["issuer_cik"]
        .nunique()
        .reset_index(name="candidate_count")
        .rename(columns={firm_col: "key"})
    )
    firm_mult["grain"] = firm_col
    cik_mult = (
        candidates.groupby("issuer_cik")[firm_col]
        .nunique()
        .reset_index(name="candidate_count")
        .rename(columns={"issuer_cik": "key"})
    )
    cik_mult["grain"] = "issuer_cik"
    return pd.concat([raw_mult, firm_mult, cik_mult], ignore_index=True)[columns]


def _unmatched_raw_characteristics(
    raw: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    year_col: str,
    target_col: str,
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=[year_col, "unmatched_rows", "unmatched_positive_rate"])
    matched_row_ids = set(candidates["raw_row_id"]) if "raw_row_id" in candidates.columns else set()
    work = raw.reset_index(drop=True).copy()
    work["matched_bridge_candidate"] = work.index.to_series().isin(matched_row_ids).to_numpy()
    unmatched = work.loc[~work["matched_bridge_candidate"]].copy()
    if unmatched.empty:
        return pd.DataFrame(columns=[year_col, "unmatched_rows", "unmatched_positive_rate"])
    if year_col not in unmatched.columns:
        return pd.DataFrame(
            [
                {
                    year_col: "",
                    "unmatched_rows": int(len(unmatched)),
                    "unmatched_positive_rate": float(
                        pd.to_numeric(unmatched.get(target_col), errors="coerce").fillna(0).mean()
                    )
                    if target_col in unmatched.columns
                    else 0.0,
                }
            ]
        )
    target = pd.to_numeric(unmatched.get(target_col), errors="coerce").fillna(0)
    unmatched = unmatched.assign(_target=target)
    return (
        unmatched.groupby(year_col, as_index=False)
        .agg(unmatched_rows=("_target", "size"), unmatched_positive_rate=("_target", "mean"))
        .sort_values(year_col)
    )


def _write_blocker_outputs(
    *,
    out_dir: Path,
    raw: pd.DataFrame,
    status: str,
    blocker: str,
    firm_col: str,
    year_col: str,
    target_col: str,
    raw_identifier_cols: Dict[str, Optional[str]],
    public_rows: int,
) -> Dict[str, object]:
    coverage = _coverage_report(
        raw,
        pd.DataFrame(),
        firm_col=firm_col,
        target_col=target_col,
    )
    multiplicity = _multiplicity_report(pd.DataFrame(), firm_col=firm_col)
    unmatched = _unmatched_raw_characteristics(
        raw,
        pd.DataFrame(),
        year_col=year_col,
        target_col=target_col,
    )
    coverage_path = out_dir / "coverage_report.csv"
    multiplicity_path = out_dir / "multiplicity_report.csv"
    unmatched_path = out_dir / "unmatched_raw_characteristics.csv"
    coverage.to_csv(coverage_path, index=False)
    multiplicity.to_csv(multiplicity_path, index=False)
    unmatched.to_csv(unmatched_path, index=False)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "blocker": blocker,
        "raw_rows": int(len(raw)),
        "public_rows": int(public_rows),
        "raw_identifier_columns": raw_identifier_cols,
        "candidate_crosswalk_rows": 0,
        "coverage_report_csv": str(coverage_path),
        "multiplicity_report_csv": str(multiplicity_path),
        "unmatched_raw_characteristics_csv": str(unmatched_path),
    }
    summary_path = out_dir / "bridge_probe_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _write_candidate_outputs(
    *,
    out_dir: Path,
    raw: pd.DataFrame,
    candidates: pd.DataFrame,
    status: str,
    firm_col: str,
    year_col: str,
    target_col: str,
    raw_identifier_cols: Dict[str, Optional[str]],
    public_rows: int,
    candidate_source: str,
    blocker: Optional[str] = None,
    extra_summary: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    candidate_path = out_dir / "candidate_crosswalk.csv"
    candidates.to_csv(candidate_path, index=False)

    coverage = _coverage_report(raw, candidates, firm_col=firm_col, target_col=target_col)
    multiplicity = _multiplicity_report(candidates, firm_col=firm_col)
    unmatched = _unmatched_raw_characteristics(
        raw,
        candidates,
        year_col=year_col,
        target_col=target_col,
    )
    coverage_path = out_dir / "coverage_report.csv"
    multiplicity_path = out_dir / "multiplicity_report.csv"
    unmatched_path = out_dir / "unmatched_raw_characteristics.csv"
    coverage.to_csv(coverage_path, index=False)
    multiplicity.to_csv(multiplicity_path, index=False)
    unmatched.to_csv(unmatched_path, index=False)

    ambiguous_raw_rows = (
        multiplicity.loc[
            multiplicity["grain"].eq("raw_row") & multiplicity["candidate_count"].gt(1)
        ]
        if not multiplicity.empty
        else pd.DataFrame()
    )
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "raw_rows": int(len(raw)),
        "public_rows": int(public_rows),
        "raw_identifier_columns": raw_identifier_cols,
        "candidate_source": candidate_source,
        "candidate_crosswalk_rows": int(len(candidates)),
        "ambiguous_raw_rows": int(len(ambiguous_raw_rows)),
        "candidate_crosswalk_csv": str(candidate_path),
        "coverage_report_csv": str(coverage_path),
        "multiplicity_report_csv": str(multiplicity_path),
        "unmatched_raw_characteristics_csv": str(unmatched_path),
    }
    if blocker:
        summary["blocker"] = blocker
    if extra_summary:
        summary.update(extra_summary)
    summary_path = out_dir / "bridge_probe_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def run_bridge_probe(
    *,
    raw_data_path: Optional[Path] = None,
    out_dir: Path,
    issuer_dim_path: Optional[Path] = None,
    issuer_origin_panel_path: Optional[Path] = None,
    crosswalk_path: Optional[Path] = None,
    firm_col: str = "gvkey",
    year_col: str = "data_year",
    target_col: str = "misstatement firm-year",
) -> Dict[str, object]:
    """Run a public-only bridge feasibility audit and write required reports."""

    out_dir.mkdir(parents=True, exist_ok=True)
    if raw_data_path is None:
        raise ValueError("raw_data_path is required.")

    raw = read_table(raw_data_path, low_memory=False)
    raw_identifier_cols = _raw_identifier_columns(raw)
    bridge_crosswalk = _read_table_if_exists(crosswalk_path)
    if not bridge_crosswalk.empty:
        candidates = _external_crosswalk_candidates(
            raw,
            bridge_crosswalk,
            firm_col=firm_col,
            year_col=year_col,
            target_col=target_col,
        )
        public = _read_table_if_exists(issuer_origin_panel_path)
        if public.empty:
            public = _read_table_if_exists(issuer_dim_path)
        status = "crosswalk_available" if not candidates.empty else "crosswalk_no_matches"
        return _write_candidate_outputs(
            out_dir=out_dir,
            raw=raw,
            candidates=candidates,
            status=status,
            firm_col=firm_col,
            year_col=year_col,
            target_col=target_col,
            raw_identifier_cols=raw_identifier_cols,
            public_rows=int(len(public)),
            candidate_source="gvkey_cik_year_crosswalk",
            blocker="gvkey-CIK-year crosswalk did not match raw gvkey-year rows"
            if candidates.empty
            else None,
            extra_summary=_public_overlap_stats(candidates, public),
        )

    if not any(raw_identifier_cols.values()):
        return _write_blocker_outputs(
            out_dir=out_dir,
            raw=raw,
            status="raw_identifier_blocker",
            blocker="raw table has no CIK, ticker, company-name, or CUSIP columns",
            firm_col=firm_col,
            year_col=year_col,
            target_col=target_col,
            raw_identifier_cols=raw_identifier_cols,
            public_rows=0,
        )

    public = _read_table_if_exists(issuer_dim_path)
    if public.empty:
        public = _read_table_if_exists(issuer_origin_panel_path)
    public_ids = _public_identifier_frame(public)
    if public_ids.empty:
        return _write_blocker_outputs(
            out_dir=out_dir,
            raw=raw,
            status="public_identifier_blocker",
            blocker="public issuer table is missing usable CIK/ticker/name identifiers",
            firm_col=firm_col,
            year_col=year_col,
            target_col=target_col,
            raw_identifier_cols=raw_identifier_cols,
            public_rows=int(len(public)),
        )

    raw_ids = _raw_identifier_frame(
        raw,
        firm_col=firm_col,
        year_col=year_col,
        target_col=target_col,
    )
    if raw_ids.empty:
        return _write_blocker_outputs(
            out_dir=out_dir,
            raw=raw,
            status="raw_identifier_blocker",
            blocker="raw identifier columns exist but contain no usable values",
            firm_col=firm_col,
            year_col=year_col,
            target_col=target_col,
            raw_identifier_cols=raw_identifier_cols,
            public_rows=int(len(public)),
        )

    candidates = raw_ids.merge(public_ids, on=["match_type", "match_value"], how="inner")
    if candidates.empty:
        status = "no_candidate_matches"
    else:
        status = "candidate_crosswalk_available"
    candidates = candidates.drop_duplicates(
        subset=["raw_row_id", "issuer_cik", "match_type", "match_value"]
    )
    candidates["provenance"] = "public_probe"
    return _write_candidate_outputs(
        out_dir=out_dir,
        raw=raw,
        candidates=candidates,
        status=status,
        firm_col=firm_col,
        year_col=year_col,
        target_col=target_col,
        raw_identifier_cols=raw_identifier_cols,
        public_rows=int(len(public)),
        candidate_source="public_probe",
    )
