"""Build raw-only gvkey-CIK-year linkage tables.

The linkage layer is deliberately outside the SEC/PCAOB public lake. It
normalizes the raw CIK-GVKEY institutional link export that supports the bridge
validation layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from . import DATA_DIR, RAW_DATASET_PATH
from .table_io import read_table, write_table


PROVENANCE_COLUMNS = (
    "source",
    "source_version",
    "extracted_at",
    "match_method",
    "match_score",
)
LINKAGE_OUTPUT_COLUMNS = (
    "gvkey",
    "data_year",
    "issuer_cik",
    *PROVENANCE_COLUMNS,
    "bridge_priority",
    "bridge_origin",
    "raw_link_sources",
    "raw_link_descs",
)
DEFAULT_LINKAGE_SUBDIR = "raw_only"
DEFAULT_RAW_CIK_GVKEY_LINK_PATH = DATA_DIR / "raw" / "CIK-GVKEY Link Table.csv"
DEFAULT_LINKAGE_OUT_DIR = DATA_DIR / "linkage" / DEFAULT_LINKAGE_SUBDIR
VALID_LINK_DESC = "Valid CIK-GVKEY Link"


@dataclass(frozen=True)
class LinkageBuildResult:
    out_dir: Path
    combined_path: Path
    summary_path: Path
    summary: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _normalize_cik(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    numeric = int(digits)
    if numeric <= 0:
        return None
    return str(numeric).zfill(10)


def _normalize_gvkey(value: object) -> str | None:
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


def _normalize_year(value: object) -> int | None:
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


def _first_existing(columns: Iterable[str], candidates: Sequence[str]) -> str | None:
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


def _parse_date(value: object) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def _date_intersection(row: pd.Series, *, date_rule: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    sec_start = _parse_date(row.get("sec_start_date"))
    sec_end = _parse_date(row.get("sec_end_date"))
    link_start = _parse_date(row.get("link_start_date"))
    link_end = _parse_date(row.get("link_end_date"))

    if date_rule == "sec_window":
        starts = [date for date in [sec_start] if date is not None]
        ends = [date for date in [sec_end] if date is not None]
    elif date_rule == "intersection":
        starts = [date for date in [sec_start, link_start] if date is not None]
        ends = [date for date in [sec_end, link_end] if date is not None]
    else:
        raise ValueError("date_rule must be 'intersection' or 'sec_window'")

    if not starts or not ends:
        return None
    start = max(starts)
    end = min(ends)
    if start > end:
        return None
    return start, end


def _years_from_dates(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    raw_year_set: set[int],
) -> list[int]:
    years = range(int(start.year), int(end.year) + 1)
    if raw_year_set:
        return [year for year in years if year in raw_year_set]
    return list(years)


def _raw_year_set(raw_data: pd.DataFrame | None) -> set[int]:
    if raw_data is None or "data_year" not in raw_data.columns:
        return set()
    years = raw_data["data_year"].map(_normalize_year).dropna().astype(int)
    return set(years.tolist())


def _raw_key_frame(raw_data: pd.DataFrame | None) -> pd.DataFrame:
    if raw_data is None or raw_data.empty:
        return pd.DataFrame(columns=["gvkey", "data_year", "legacy_label"])
    if "gvkey" not in raw_data.columns or "data_year" not in raw_data.columns:
        return pd.DataFrame(columns=["gvkey", "data_year", "legacy_label"])
    label_col = "misstatement firm-year" if "misstatement firm-year" in raw_data.columns else None
    frame = raw_data[["gvkey", "data_year", *([label_col] if label_col else [])]].copy()
    frame["gvkey"] = frame["gvkey"].map(_normalize_gvkey)
    frame["data_year"] = frame["data_year"].map(_normalize_year)
    frame["legacy_label"] = (
        pd.to_numeric(frame[label_col], errors="coerce").fillna(0).astype(int)
        if label_col
        else 0
    )
    return frame.loc[frame["gvkey"].notna() & frame["data_year"].notna(), [
        "gvkey",
        "data_year",
        "legacy_label",
    ]].drop_duplicates()


def _source_slug(value: object) -> str:
    text = str(value or "unknown").strip().lower()
    text = text.replace("&", "and").replace("/", "_").replace(" ", "_")
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)


def _join_unique(values: pd.Series) -> str:
    parts = sorted(str(value).strip() for value in values if str(value).strip())
    return ";".join(dict.fromkeys(parts))


def _aggregate_normalized(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=list(LINKAGE_OUTPUT_COLUMNS))
    grouped = (
        frame.fillna("")
        .groupby(["gvkey", "data_year", "issuer_cik"], as_index=False)
        .agg(
            source=("source", _join_unique),
            source_version=("source_version", _join_unique),
            extracted_at=("extracted_at", _join_unique),
            match_method=("match_method", _join_unique),
            match_score=("match_score", _join_unique),
            bridge_priority=("bridge_priority", _join_unique),
            bridge_origin=("bridge_origin", _join_unique),
            raw_link_sources=("raw_link_sources", _join_unique),
            raw_link_descs=("raw_link_descs", _join_unique),
        )
    )
    return grouped.loc[:, list(LINKAGE_OUTPUT_COLUMNS)].sort_values(
        ["gvkey", "data_year", "issuer_cik"]
    )


def normalize_raw_cik_gvkey_links(
    links: pd.DataFrame,
    *,
    raw_data: pd.DataFrame | None = None,
    include_name_mismatch: bool = False,
    date_rule: str = "intersection",
    extracted_at: str | None = None,
) -> pd.DataFrame:
    """Normalize raw CIK-GVKEY link rows to annual gvkey-CIK-year rows."""

    required = {"cik", "gvkey", "link_desc", "source"}
    missing = sorted(required - set(links.columns))
    if missing:
        raise ValueError(f"raw CIK-GVKEY link table is missing columns: {missing}")

    extracted_at = extracted_at or _utc_now()
    raw_years = _raw_year_set(raw_data)
    work = links.copy()
    if not include_name_mismatch:
        work = work.loc[work["link_desc"].eq(VALID_LINK_DESC)].copy()

    rows: list[dict[str, object]] = []
    for _, row in work.iterrows():
        gvkey = _normalize_gvkey(row.get("gvkey"))
        issuer_cik = _normalize_cik(row.get("cik"))
        if gvkey is None or issuer_cik is None:
            continue
        span = _date_intersection(row, date_rule=date_rule)
        if span is None:
            continue
        years = _years_from_dates(*span, raw_year_set=raw_years)
        raw_source = str(row.get("source", "") or "").strip()
        raw_desc = str(row.get("link_desc", "") or "").strip()
        source = f"wrds_sec_analytics_cik_gvkey:{_source_slug(raw_source)}"
        for year in years:
            rows.append(
                {
                    "gvkey": gvkey,
                    "data_year": int(year),
                    "issuer_cik": issuer_cik,
                    "source": source,
                    "source_version": "WRDS SEC Analytics Suite / CIK-GVKEY Link Table.csv",
                    "extracted_at": extracted_at,
                    "match_method": f"wrds_sec_analytics_cik_gvkey_{date_rule}",
                    "match_score": "1.0",
                    "bridge_priority": "raw_primary",
                    "bridge_origin": "raw",
                    "raw_link_sources": raw_source,
                    "raw_link_descs": raw_desc,
                }
            )

    return _aggregate_normalized(pd.DataFrame(rows))


def normalize_external_crosswalk(
    crosswalk: pd.DataFrame,
    *,
    raw_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Normalize an external gvkey-CIK crosswalk to annual rows."""

    if crosswalk.empty:
        return pd.DataFrame(columns=list(LINKAGE_OUTPUT_COLUMNS))

    gvkey_col = _first_existing(crosswalk.columns, ("gvkey", "GVKEY", "global_company_key"))
    cik_col = _first_existing(crosswalk.columns, ("issuer_cik", "cik", "CIK", "cik_number"))
    year_col = _first_existing(crosswalk.columns, ("data_year", "fiscal_year", "fyear", "year"))
    start_col = _first_existing(crosswalk.columns, ("start_year", "start_fiscal_year", "start_fyear"))
    end_col = _first_existing(crosswalk.columns, ("end_year", "end_fiscal_year", "end_fyear"))
    if gvkey_col is None:
        raise ValueError("external crosswalk is missing a gvkey column")
    if cik_col is None:
        raise ValueError("external crosswalk is missing an issuer_cik/cik column")
    if year_col is None and (start_col is None or end_col is None):
        raise ValueError(
            "external crosswalk must include data_year/fiscal_year/fyear or start_year/end_year"
        )

    raw_years = _raw_year_set(raw_data)
    rows: list[dict[str, object]] = []
    for _, row in crosswalk.iterrows():
        gvkey = _normalize_gvkey(row.get(gvkey_col))
        issuer_cik = _normalize_cik(row.get(cik_col))
        if gvkey is None or issuer_cik is None:
            continue
        if year_col is not None:
            years = [_normalize_year(row.get(year_col))]
        else:
            start = _normalize_year(row.get(start_col))
            end = _normalize_year(row.get(end_col))
            years = list(range(start, end + 1)) if start is not None and end is not None else []
        for year in years:
            if year is None:
                continue
            year = int(year)
            if raw_years and year not in raw_years:
                continue
            rows.append(
                {
                    "gvkey": gvkey,
                    "data_year": year,
                    "issuer_cik": issuer_cik,
                    "source": row.get("source", "external_crosswalk") or "external_crosswalk",
                    "source_version": row.get("source_version", "") or "",
                    "extracted_at": row.get("extracted_at", "") or "",
                    "match_method": row.get("match_method", "external_crosswalk")
                    or "external_crosswalk",
                    "match_score": row.get("match_score", "") or "",
                    "bridge_priority": "external_supplement",
                    "bridge_origin": "external",
                    "raw_link_sources": "",
                    "raw_link_descs": "",
                }
            )

    return _aggregate_normalized(pd.DataFrame(rows))


def raw_primary_external_supplement(
    raw_links: pd.DataFrame,
    external: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Combine annual links with raw rows taking priority over external rows."""

    raw_keys = raw_links[["gvkey", "data_year"]].drop_duplicates()
    raw_keys["_has_raw"] = True
    external_with_flag = external.merge(raw_keys, on=["gvkey", "data_year"], how="left")
    external_supplement = external_with_flag.loc[
        external_with_flag["_has_raw"].ne(True),
        list(LINKAGE_OUTPUT_COLUMNS),
    ].copy()
    combined = pd.concat([raw_links, external_supplement], ignore_index=True)
    combined = combined.sort_values(["gvkey", "data_year", "issuer_cik"]).reset_index(drop=True)

    conflicts = _raw_external_conflicts(raw_links, external)
    return combined, external_supplement.reset_index(drop=True), conflicts


def _raw_external_conflicts(raw_links: pd.DataFrame, external: pd.DataFrame) -> pd.DataFrame:
    if raw_links.empty or external.empty:
        return pd.DataFrame(
            columns=[
                "gvkey",
                "data_year",
                "raw_issuer_ciks",
                "external_issuer_ciks",
                "raw_sources",
                "external_sources",
                "conflict_type",
            ]
        )

    raw_group = raw_links.groupby(["gvkey", "data_year"], as_index=False).agg(
        raw_issuer_ciks=("issuer_cik", _join_unique),
        raw_sources=("source", _join_unique),
    )
    ext_group = external.groupby(["gvkey", "data_year"], as_index=False).agg(
        external_issuer_ciks=("issuer_cik", _join_unique),
        external_sources=("source", _join_unique),
    )
    shared = raw_group.merge(ext_group, on=["gvkey", "data_year"], how="inner")
    rows = []
    for _, row in shared.iterrows():
        raw_ciks = set(str(row["raw_issuer_ciks"]).split(";")) - {""}
        ext_ciks = set(str(row["external_issuer_ciks"]).split(";")) - {""}
        if raw_ciks and ext_ciks and raw_ciks.isdisjoint(ext_ciks):
            rows.append(
                {
                    "gvkey": row["gvkey"],
                    "data_year": row["data_year"],
                    "raw_issuer_ciks": row["raw_issuer_ciks"],
                    "external_issuer_ciks": row["external_issuer_ciks"],
                    "raw_sources": row["raw_sources"],
                    "external_sources": row["external_sources"],
                    "conflict_type": "disjoint_cik_sets",
                }
            )
    return pd.DataFrame(rows)


def _raw_coverage(combined: pd.DataFrame, raw_data: pd.DataFrame | None) -> dict[str, Any]:
    raw_keys = _raw_key_frame(raw_data)
    if raw_keys.empty:
        return {
            "raw_rows": 0,
            "raw_positive_rows": 0,
            "combined_covered_rows": 0,
            "combined_coverage_rate": 0.0,
            "combined_covered_positive_rows": 0,
            "raw_primary_covered_rows": 0,
            "raw_primary_coverage_rate": 0.0,
        }

    link_keys = combined[["gvkey", "data_year", "bridge_origin"]].drop_duplicates()
    combined_keys = link_keys[["gvkey", "data_year"]].drop_duplicates()
    raw_primary_keys = link_keys.loc[link_keys["bridge_origin"].str.contains("raw", na=False), [
        "gvkey",
        "data_year",
    ]].drop_duplicates()
    combined_hit = raw_keys.merge(combined_keys.assign(_covered=True), on=["gvkey", "data_year"], how="left")
    raw_hit = raw_keys.merge(raw_primary_keys.assign(_covered=True), on=["gvkey", "data_year"], how="left")
    combined_covered = combined_hit["_covered"].eq(True)
    raw_covered = raw_hit["_covered"].eq(True)
    total = int(len(raw_keys))
    positives = raw_keys["legacy_label"].eq(1)
    return {
        "raw_rows": total,
        "raw_positive_rows": int(positives.sum()),
        "combined_covered_rows": int(combined_covered.sum()),
        "combined_coverage_rate": float(combined_covered.mean()) if total else 0.0,
        "combined_covered_positive_rows": int((combined_covered & positives).sum()),
        "raw_primary_covered_rows": int(raw_covered.sum()),
        "raw_primary_coverage_rate": float(raw_covered.mean()) if total else 0.0,
        "raw_primary_covered_positive_rows": int((raw_covered & positives).sum()),
    }


def _linkage_stats(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "rows": 0,
            "gvkeys": 0,
            "issuer_ciks": 0,
            "gvkey_years": 0,
            "year_min": None,
            "year_max": None,
        }
    return {
        "rows": int(len(frame)),
        "gvkeys": int(frame["gvkey"].nunique()),
        "issuer_ciks": int(frame["issuer_cik"].nunique()),
        "gvkey_years": int(frame[["gvkey", "data_year"]].drop_duplicates().shape[0]),
        "year_min": int(frame["data_year"].min()),
        "year_max": int(frame["data_year"].max()),
    }


def _conflict_stats(conflicts: pd.DataFrame, raw_data: pd.DataFrame | None) -> dict[str, Any]:
    base = {
        "rows": int(len(conflicts)),
        "gvkey_years": int(conflicts[["gvkey", "data_year"]].drop_duplicates().shape[0])
        if not conflicts.empty
        else 0,
    }
    raw_keys = _raw_key_frame(raw_data)
    if conflicts.empty or raw_keys.empty:
        return {
            **base,
            "raw_benchmark_conflict_rows": 0,
            "raw_benchmark_positive_conflict_rows": 0,
        }
    raw_conflicts = raw_keys.merge(
        conflicts[["gvkey", "data_year"]].drop_duplicates().assign(_conflict=True),
        on=["gvkey", "data_year"],
        how="inner",
    )
    return {
        **base,
        "raw_benchmark_conflict_rows": int(len(raw_conflicts)),
        "raw_benchmark_positive_conflict_rows": int(raw_conflicts["legacy_label"].eq(1).sum()),
    }


def public_overlap_outputs(
    combined: pd.DataFrame,
    *,
    issuer_origin_panel_path: Path,
    out_dir: Path,
    raw_data: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Write overlap rows and summary for one public-lake gold panel."""

    if not issuer_origin_panel_path.exists():
        summary = {
            "issuer_origin_panel": str(issuer_origin_panel_path),
            "status": "missing_issuer_origin_panel",
        }
        _write_json(summary, out_dir / "coverage_summary.json")
        return summary

    public = read_table(
        issuer_origin_panel_path,
        columns=["issuer_cik", "fiscal_year"],
        low_memory=False,
    )
    public["issuer_cik"] = public["issuer_cik"].map(_normalize_cik)
    public["data_year"] = public["fiscal_year"].map(_normalize_year)
    public_keys = public.loc[
        public["issuer_cik"].notna() & public["data_year"].notna(),
        ["issuer_cik", "data_year"],
    ].drop_duplicates()
    overlap = combined.merge(public_keys, on=["issuer_cik", "data_year"], how="inner")
    overlap = overlap.sort_values(["gvkey", "data_year", "issuer_cik"]).reset_index(drop=True)
    write_table(overlap, out_dir / "gvkey_cik_year_public_overlap.csv")
    denominator = combined[["gvkey", "data_year"]].drop_duplicates().shape[0]
    numerator = overlap[["gvkey", "data_year"]].drop_duplicates().shape[0]
    raw_keys = _raw_key_frame(raw_data)
    if raw_keys.empty:
        raw_overlap_summary = {
            "raw_benchmark_rows": 0,
            "raw_benchmark_overlap_rows": 0,
            "raw_benchmark_overlap_rate": 0.0,
            "raw_benchmark_positive_overlap_rows": 0,
        }
    else:
        overlap_keys = overlap[["gvkey", "data_year"]].drop_duplicates()
        raw_hits = raw_keys.merge(
            overlap_keys.assign(_public_overlap=True),
            on=["gvkey", "data_year"],
            how="left",
        )
        hit = raw_hits["_public_overlap"].eq(True)
        positives = raw_hits["legacy_label"].eq(1)
        raw_overlap_summary = {
            "raw_benchmark_rows": int(len(raw_hits)),
            "raw_benchmark_overlap_rows": int(hit.sum()),
            "raw_benchmark_overlap_rate": float(hit.mean()) if len(raw_hits) else 0.0,
            "raw_benchmark_positive_overlap_rows": int((hit & positives).sum()),
        }
    summary = {
        "issuer_origin_panel": str(issuer_origin_panel_path),
        "status": "available",
        "public_rows": int(len(public)),
        "public_key_rows": int(len(public_keys)),
        "overlap_rows": int(len(overlap)),
        "overlap_gvkey_years": int(numerator),
        "linkage_gvkey_years": int(denominator),
        "overlap_gvkey_year_rate": float(numerator / denominator) if denominator else 0.0,
        **raw_overlap_summary,
    }
    _write_json(summary, out_dir / "coverage_summary.json")
    return summary


def build_raw_primary_linkage(
    *,
    raw_link_path: Path = DEFAULT_RAW_CIK_GVKEY_LINK_PATH,
    raw_data_path: Path = RAW_DATASET_PATH,
    out_dir: Path = DEFAULT_LINKAGE_OUT_DIR,
    public_lake_panel_path: Path | None = None,
    public_lake_smoke_panel_path: Path | None = None,
    include_name_mismatch: bool = False,
    date_rule: str = "intersection",
    extracted_at: str | None = None,
) -> LinkageBuildResult:
    """Build the raw-only linkage folder under DATA_DIR/linkage."""

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_data = read_table(raw_data_path, low_memory=False) if raw_data_path.exists() else None
    raw_input = read_table(raw_link_path, low_memory=False)

    raw_normalized = normalize_raw_cik_gvkey_links(
        raw_input,
        raw_data=raw_data,
        include_name_mismatch=include_name_mismatch,
        date_rule=date_rule,
        extracted_at=extracted_at,
    )
    combined = raw_normalized.copy()
    conflicts = _raw_external_conflicts(raw_normalized, pd.DataFrame())

    raw_path = out_dir / "raw_primary_gvkey_cik_year.csv"
    combined_path = out_dir / "gvkey_cik_year.csv"
    conflicts_path = out_dir / "gvkey_cik_year_conflicts.csv"
    write_table(raw_normalized, raw_path)
    write_table(combined, combined_path)
    write_table(conflicts, conflicts_path)

    public_lake_panel_path = public_lake_panel_path or DATA_DIR / "public_lake" / "gold" / "issuer_origin_panel.parquet"
    public_lake_smoke_panel_path = (
        public_lake_smoke_panel_path
        or DATA_DIR / "public_lake_smoke" / "gold" / "issuer_origin_panel.parquet"
    )
    public_lake_summary = public_overlap_outputs(
        combined,
        issuer_origin_panel_path=public_lake_panel_path,
        out_dir=out_dir / "public_lake",
        raw_data=raw_data,
    )
    public_lake_smoke_summary = public_overlap_outputs(
        combined,
        issuer_origin_panel_path=public_lake_smoke_panel_path,
        out_dir=out_dir / "public_lake_smoke",
        raw_data=raw_data,
    )

    summary = {
        "generated_at_utc": _utc_now(),
        "input_paths": {
            "raw_link_path": str(raw_link_path),
            "raw_data_path": str(raw_data_path),
        },
        "output_paths": {
            "raw_primary": str(raw_path),
            "combined": str(combined_path),
            "conflicts": str(conflicts_path),
        },
        "settings": {
            "include_name_mismatch": include_name_mismatch,
            "date_rule": date_rule,
            "linkage_policy": "raw CIK-GVKEY link rows only; external gvkey-CIK rows are not used",
        },
        "raw_input": {"rows": int(len(raw_input))},
        "raw_primary": _linkage_stats(raw_normalized),
        "combined": _linkage_stats(combined),
        "conflicts": _conflict_stats(conflicts, raw_data),
        "raw_benchmark_coverage": _raw_coverage(combined, raw_data),
        "public_lake": public_lake_summary,
        "public_lake_smoke": public_lake_smoke_summary,
    }
    summary_path = out_dir / "gvkey_cik_year_summary.json"
    _write_json(summary, summary_path)
    return LinkageBuildResult(
        out_dir=out_dir,
        combined_path=combined_path,
        summary_path=summary_path,
        summary=summary,
    )
