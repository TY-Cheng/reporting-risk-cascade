"""
Public-only bridge feasibility probe.

This module deliberately does not build an authoritative historical crosswalk.
It reports whether the old gvkey benchmark panel has enough public identifiers to
attempt a candidate gvkey-CIK-year bridge, then writes coverage and multiplicity
reports before any overlap analysis is allowed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd


RAW_CIK_COLS = ("issuer_cik", "cik", "CIK")
RAW_TICKER_COLS = ("ticker", "tic", "TICKER", "TIC")
RAW_NAME_COLS = ("entity_name", "company_name", "conm", "CONM", "name")
RAW_CUSIP_COLS = ("cusip", "CUSIP")
PUBLIC_TICKER_COLS = ("ticker", "tickers", "tickers_json")
PUBLIC_NAME_COLS = ("entity_name", "company_name", "name")
PUBLIC_CIK_COLS = ("issuer_cik", "cik", "CIK")


def _first_existing(columns: Iterable[str], candidates: Sequence[str]) -> Optional[str]:
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
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


def _read_csv_if_exists(path: Optional[Path]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _raw_identifier_columns(raw: pd.DataFrame) -> Dict[str, Optional[str]]:
    return {
        "cik": _first_existing(raw.columns, RAW_CIK_COLS),
        "ticker": _first_existing(raw.columns, RAW_TICKER_COLS),
        "name": _first_existing(raw.columns, RAW_NAME_COLS),
        "cusip": _first_existing(raw.columns, RAW_CUSIP_COLS),
    }


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


def run_bridge_probe(
    *,
    raw_csv: Path,
    out_dir: Path,
    issuer_dim_csv: Optional[Path] = None,
    issuer_origin_panel_csv: Optional[Path] = None,
    firm_col: str = "gvkey",
    year_col: str = "data_year",
    target_col: str = "misstatement firm-year",
) -> Dict[str, object]:
    """Run a public-only bridge feasibility audit and write required reports."""

    out_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(raw_csv, low_memory=False)
    raw_identifier_cols = _raw_identifier_columns(raw)
    if not any(raw_identifier_cols.values()):
        return _write_blocker_outputs(
            out_dir=out_dir,
            raw=raw,
            status="raw_identifier_blocker",
            blocker="raw CSV has no CIK, ticker, company-name, or CUSIP columns",
            firm_col=firm_col,
            year_col=year_col,
            target_col=target_col,
            raw_identifier_cols=raw_identifier_cols,
            public_rows=0,
        )

    public = _read_csv_if_exists(issuer_dim_csv)
    if public.empty:
        public = _read_csv_if_exists(issuer_origin_panel_csv)
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
        "public_rows": int(len(public)),
        "raw_identifier_columns": raw_identifier_cols,
        "candidate_crosswalk_rows": int(len(candidates)),
        "ambiguous_raw_rows": int(len(ambiguous_raw_rows)),
        "candidate_crosswalk_csv": str(candidate_path),
        "coverage_report_csv": str(coverage_path),
        "multiplicity_report_csv": str(multiplicity_path),
        "unmatched_raw_characteristics_csv": str(unmatched_path),
    }
    summary_path = out_dir / "bridge_probe_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary
