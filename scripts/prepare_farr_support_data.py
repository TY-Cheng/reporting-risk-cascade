"""
Prepare diagnostics for public farr support datasets.

The farr AAER datasets are validation anchors, not replacement labels. This
script writes overlap artifacts that compare farr AAER firm-years with the
legacy benchmark and, when the bridge and public issuer panel are available,
with the current public-cascade AAER proxy.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_repo_root() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def parse_args() -> argparse.Namespace:
    _bootstrap_repo_root()

    from src import ARTIFACTS_DIR, DATA_DIR, LAKE_GOLD_DIR, RAW_DATASET_PATH
    from src.linkage import DEFAULT_LINKAGE_OUT_DIR

    parser = argparse.ArgumentParser(description="Prepare farr AAER/state-HQ support artifacts")
    parser.add_argument(
        "--aaer-dates",
        type=Path,
        default=DATA_DIR / "external" / "farr_aaer_dates.csv",
    )
    parser.add_argument(
        "--aaer-firm-year",
        type=Path,
        default=DATA_DIR / "external" / "farr_aaer_firm_year.csv",
    )
    parser.add_argument(
        "--state-hq",
        type=Path,
        default=DATA_DIR / "external" / "farr_state_hq.csv",
    )
    parser.add_argument("--raw-data", type=Path, default=RAW_DATASET_PATH)
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=DEFAULT_LINKAGE_OUT_DIR / "gvkey_cik_year.csv",
    )
    parser.add_argument(
        "--issuer-origin",
        type=Path,
        default=LAKE_GOLD_DIR / "issuer_origin_panel.parquet",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ARTIFACTS_DIR / "farr_support",
    )
    return parser.parse_args()


def _normalize_gvkey(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip().str.replace(r"[.]0$", "", regex=True)
    numeric = pd.to_numeric(values, errors="coerce")
    numeric_as_text = numeric.astype("Int64").astype("string").str.zfill(6)
    out = values.mask(numeric.notna(), numeric_as_text)
    return out.mask(out.isin(["", "<NA>", "NA", "nan"]))


def _normalize_cik(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.replace(r"[^0-9]", "", regex=True)
    numeric = pd.to_numeric(values, errors="coerce")
    out = numeric.astype("Int64").astype("string").str.zfill(10)
    return out.mask(numeric.isna())


def _detect_benchmark_label(raw: pd.DataFrame) -> str | None:
    candidates = [
        "misstatement firm-year",
        "misstatement_firm_year",
        "misstatement",
        "fraud",
        "label",
    ]
    return next((col for col in candidates if col in raw.columns), None)


def _expand_aaer_firm_year(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"p_aaer", "gvkey", "min_year", "max_year"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(columns=["p_aaer", "gvkey", "data_year"])
    work = frame.copy()
    work["gvkey"] = _normalize_gvkey(work["gvkey"])
    work["min_year"] = pd.to_numeric(work["min_year"], errors="coerce").astype("Int64")
    work["max_year"] = pd.to_numeric(work["max_year"], errors="coerce").astype("Int64")
    rows: list[dict[str, object]] = []
    for row in work.dropna(subset=["p_aaer", "gvkey", "min_year", "max_year"]).itertuples():
        min_year = int(row.min_year)
        max_year = int(row.max_year)
        if max_year < min_year:
            continue
        for year in range(min_year, max_year + 1):
            rows.append({"p_aaer": str(row.p_aaer), "gvkey": row.gvkey, "data_year": year})
    return pd.DataFrame(rows).drop_duplicates().reset_index(drop=True)


def _empty_csv(path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=columns).to_csv(path, index=False)


def _write_benchmark_overlap(
    *,
    raw_data: Path,
    expanded: pd.DataFrame,
    out_dir: Path,
) -> dict[str, Any]:
    from src.table_io import read_table

    path = out_dir / "farr_aaer_benchmark_overlap.csv"
    if not raw_data.exists():
        _empty_csv(
            path,
            ["gvkey", "data_year", "observed_label", "farr_aaer_firm_year", "p_aaer"],
        )
        return {"status": "blocked_missing_raw_data", "raw_data": str(raw_data)}

    raw = read_table(raw_data, low_memory=False)
    if not {"gvkey", "data_year"}.issubset(raw.columns):
        _empty_csv(
            path,
            ["gvkey", "data_year", "observed_label", "farr_aaer_firm_year", "p_aaer"],
        )
        return {"status": "blocked_missing_raw_keys", "raw_data": str(raw_data)}

    label_col = _detect_benchmark_label(raw)
    work_cols = ["gvkey", "data_year"]
    if label_col is not None:
        work_cols.append(label_col)
    benchmark = raw[work_cols].copy()
    benchmark["gvkey"] = _normalize_gvkey(benchmark["gvkey"])
    benchmark["data_year"] = pd.to_numeric(benchmark["data_year"], errors="coerce").astype("Int64")
    if label_col is None:
        benchmark["observed_label"] = pd.NA
    else:
        benchmark["observed_label"] = pd.to_numeric(benchmark[label_col], errors="coerce")
        benchmark = benchmark.drop(columns=[label_col])

    aaer_hits = (
        expanded.groupby(["gvkey", "data_year"], as_index=False)
        .agg(p_aaer=("p_aaer", lambda values: ";".join(sorted(set(map(str, values))))))
        .assign(farr_aaer_firm_year=1)
    )
    overlap = benchmark.merge(aaer_hits, on=["gvkey", "data_year"], how="left")
    overlap["farr_aaer_firm_year"] = overlap["farr_aaer_firm_year"].fillna(0).astype(int)
    overlap["p_aaer"] = overlap["p_aaer"].fillna("")
    overlap.to_csv(path, index=False)

    observed_positive = overlap["observed_label"].eq(1)
    farr_positive = overlap["farr_aaer_firm_year"].eq(1)
    return {
        "status": "ok",
        "raw_rows": int(len(overlap)),
        "raw_positive_rows": int(observed_positive.sum()),
        "farr_aaer_firm_year_rows": int(farr_positive.sum()),
        "raw_positive_farr_overlap_rows": int((observed_positive & farr_positive).sum()),
        "output": str(path),
    }


def _write_public_proxy_overlap(
    *,
    expanded: pd.DataFrame,
    crosswalk: Path,
    issuer_origin: Path,
    out_dir: Path,
) -> dict[str, Any]:
    from src.table_io import read_table

    path = out_dir / "farr_aaer_public_proxy_overlap.csv"
    columns = [
        "p_aaer",
        "gvkey",
        "data_year",
        "issuer_cik",
        "origin_date",
        "label_aaer_proxy_730",
        "label_comment_thread_365",
        "label_amendment_365",
        "label_8k_402_365",
    ]
    if not crosswalk.exists():
        _empty_csv(path, columns)
        return {"status": "blocked_missing_crosswalk", "crosswalk": str(crosswalk)}
    if not issuer_origin.exists():
        _empty_csv(path, columns)
        return {"status": "blocked_missing_issuer_origin_panel", "issuer_origin": str(issuer_origin)}

    bridge = read_table(crosswalk, low_memory=False)
    if not {"gvkey", "data_year", "issuer_cik"}.issubset(bridge.columns):
        _empty_csv(path, columns)
        return {"status": "blocked_crosswalk_schema", "crosswalk": str(crosswalk)}

    bridge = bridge[["gvkey", "data_year", "issuer_cik"]].copy()
    bridge["gvkey"] = _normalize_gvkey(bridge["gvkey"])
    bridge["data_year"] = pd.to_numeric(bridge["data_year"], errors="coerce").astype("Int64")
    bridge["issuer_cik"] = _normalize_cik(bridge["issuer_cik"])
    aaer_cik_year = (
        expanded.merge(bridge, on=["gvkey", "data_year"], how="left")
        .dropna(subset=["issuer_cik"])
        .drop_duplicates(subset=["p_aaer", "gvkey", "data_year", "issuer_cik"])
    )

    label_cols = [
        "label_aaer_proxy_730",
        "label_comment_thread_365",
        "label_amendment_365",
        "label_8k_402_365",
    ]
    panel_cols = ["issuer_cik", "fiscal_year", "origin_date", *label_cols]
    panel = read_table(issuer_origin, low_memory=False)
    available_cols = [col for col in panel_cols if col in panel.columns]
    if "issuer_cik" not in available_cols or "fiscal_year" not in available_cols:
        _empty_csv(path, columns)
        return {"status": "blocked_issuer_origin_schema", "issuer_origin": str(issuer_origin)}
    panel = panel[available_cols].copy()
    panel["issuer_cik"] = _normalize_cik(panel["issuer_cik"])
    panel["data_year"] = pd.to_numeric(panel["fiscal_year"], errors="coerce").astype("Int64")
    joined = aaer_cik_year.merge(panel, on=["issuer_cik", "data_year"], how="left")
    for col in columns:
        if col not in joined.columns:
            joined[col] = pd.NA
    joined[columns].sort_values(["gvkey", "data_year", "issuer_cik", "p_aaer"]).to_csv(
        path, index=False
    )

    matched_panel = joined["origin_date"].notna()
    aaer_proxy_hit = pd.to_numeric(joined["label_aaer_proxy_730"], errors="coerce").eq(1)
    return {
        "status": "ok",
        "farr_aaer_cik_year_rows": int(len(aaer_cik_year)),
        "matched_issuer_origin_rows": int(matched_panel.sum()),
        "matched_public_aaer_proxy_rows": int((matched_panel & aaer_proxy_hit).sum()),
        "missed_public_aaer_proxy_rows": int((matched_panel & ~aaer_proxy_hit).sum()),
        "output": str(path),
    }


def _summarize_aaer_dates(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    frame = pd.read_csv(path)
    dates = pd.to_datetime(frame.get("aaer_date"), errors="coerce", format="mixed")
    return {
        "status": "ok",
        "rows": int(len(frame)),
        "aaer_numbers": int(frame["aaer_num"].nunique()) if "aaer_num" in frame else 0,
        "date_min": None if dates.dropna().empty else str(dates.min().date()),
        "date_max": None if dates.dropna().empty else str(dates.max().date()),
    }


def _summarize_state_hq(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    frame = pd.read_csv(path)
    dates_min = pd.to_datetime(frame.get("min_date"), errors="coerce", format="mixed")
    dates_max = pd.to_datetime(frame.get("max_date"), errors="coerce", format="mixed")
    return {
        "status": "ok",
        "rows": int(len(frame)),
        "issuer_ciks": int(frame["issuer_cik"].nunique()) if "issuer_cik" in frame else 0,
        "states": int(frame["ba_state"].nunique()) if "ba_state" in frame else 0,
        "min_date": None if dates_min.dropna().empty else str(dates_min.min().date()),
        "max_date": None if dates_max.dropna().empty else str(dates_max.max().date()),
    }


def main() -> None:
    _bootstrap_repo_root()

    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.aaer_firm_year.exists():
        aaer_firm_year = pd.read_csv(args.aaer_firm_year)
    else:
        aaer_firm_year = pd.DataFrame()
    expanded = _expand_aaer_firm_year(aaer_firm_year)
    expanded_path = args.out_dir / "farr_aaer_firm_year_expanded.csv"
    expanded.to_csv(expanded_path, index=False)

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "aaer_dates": _summarize_aaer_dates(args.aaer_dates),
        "aaer_firm_year": {
            "status": "ok" if args.aaer_firm_year.exists() else "missing",
            "rows": int(len(aaer_firm_year)),
            "expanded_rows": int(len(expanded)),
            "expanded_output": str(expanded_path),
        },
        "benchmark_overlap": _write_benchmark_overlap(
            raw_data=args.raw_data,
            expanded=expanded,
            out_dir=args.out_dir,
        ),
        "public_proxy_overlap": _write_public_proxy_overlap(
            expanded=expanded,
            crosswalk=args.crosswalk,
            issuer_origin=args.issuer_origin,
            out_dir=args.out_dir,
        ),
        "state_hq": _summarize_state_hq(args.state_hq),
    }
    summary_path = args.out_dir / "farr_support_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
