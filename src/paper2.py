"""
Paper 2 data-prep and lightweight multimodal scaffolding.

This module focuses on public-data preparation before any GPU-heavy embedding work:
section parsing, cheap text features, compact CPU-friendly embeddings, and PCAOB
monitoring aggregates.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer


TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style).*?>.*?</\\1>", re.IGNORECASE | re.DOTALL)
WHITESPACE_RE = re.compile(r"\s+")
ITEM_RE = re.compile(r"\bitem\s+([0-9]{1,2}[a-z]?|4\.02)\b", re.IGNORECASE)

UNCERTAINTY_WORDS = {
    "risk",
    "risky",
    "uncertain",
    "uncertainty",
    "may",
    "might",
    "could",
    "adverse",
    "material",
    "volatility",
    "weakness",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def normalize_html_text(raw_html: str) -> str:
    text = SCRIPT_RE.sub(" ", raw_html)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def extract_item_section(
    normalized_text: str,
    *,
    item_code: str,
    next_item_codes: Sequence[str],
) -> str:
    item_code = item_code.lower().replace(" ", "")
    next_item_codes = [code.lower().replace(" ", "") for code in next_item_codes]
    lower = normalized_text.lower()

    start_pat = re.compile(rf"\bitem\s+{re.escape(item_code)}\b")
    start_match = start_pat.search(lower)
    if not start_match:
        return ""

    start = start_match.start()
    end = len(lower)
    for next_code in next_item_codes:
        next_pat = re.compile(rf"\bitem\s+{re.escape(next_code)}\b")
        next_match = next_pat.search(lower, pos=start_match.end())
        if next_match:
            end = min(end, next_match.start())
    return normalized_text[start:end].strip()


def compute_text_stats(text: str) -> Dict[str, float]:
    tokens = re.findall(r"[A-Za-z']+", text)
    n_tokens = len(tokens)
    token_lengths = [len(tok) for tok in tokens] or [0]
    lower_tokens = [tok.lower() for tok in tokens]
    uncertainty_count = sum(tok in UNCERTAINTY_WORDS for tok in lower_tokens)

    return {
        "char_count": float(len(text)),
        "token_count": float(n_tokens),
        "avg_token_len": float(np.mean(token_lengths)),
        "digit_share": float(sum(ch.isdigit() for ch in text) / max(len(text), 1)),
        "uppercase_share": float(sum(ch.isupper() for ch in text) / max(len(text), 1)),
        "uncertainty_rate": float(uncertainty_count / max(n_tokens, 1)),
    }


def compute_disclosure_framing(text: str) -> Dict[str, float]:
    lower = text.lower()
    passive_hits = len(re.findall(r"\b(was|were|been|being)\s+\w+ed\b", lower))
    tokens = re.findall(r"[A-Za-z']+", lower)
    n_tokens = max(len(tokens), 1)
    return {
        "mentions_sec": float("sec" in lower or "securities and exchange commission" in lower),
        "mentions_auditor": float("auditor" in lower or "audit firm" in lower),
        "mentions_audit_committee": float("audit committee" in lower),
        "mentions_error": float("error" in lower or "errors" in lower),
        "mentions_irregularity": float("irregularit" in lower),
        "mentions_material_weakness": float("material weakness" in lower),
        "passive_voice_rate": float(passive_hits / n_tokens),
    }


def parse_filing_sections(
    filing_path: Path,
    *,
    form_type: str,
) -> Dict[str, str]:
    normalized = normalize_html_text(read_text(filing_path))
    form = form_type.upper()
    if form in {"10-K", "10-K/A"}:
        item_1a = extract_item_section(normalized, item_code="1a", next_item_codes=["1b", "2"])
        item_7 = extract_item_section(normalized, item_code="7", next_item_codes=["7a", "8"])
        return {"item_1a": item_1a, "item_7": item_7, "item_402": ""}
    if form == "8-K":
        item_402 = extract_item_section(
            normalized,
            item_code="4.02",
            next_item_codes=["5.01", "5.02", "8.01", "9.01", "signature"],
        )
        return {"item_1a": "", "item_7": "", "item_402": item_402}
    return {"item_1a": "", "item_7": "", "item_402": ""}


def build_section_feature_table(
    *,
    download_manifest_csv: Path,
    out_dir: Path,
    max_features: int = 5000,
    svd_components: int = 32,
) -> pd.DataFrame:
    manifest = pd.read_csv(download_manifest_csv)
    rows: List[Dict[str, object]] = []
    section_corpora: Dict[str, List[str]] = {"item_1a": [], "item_7": [], "item_402": []}

    for _, row in manifest.iterrows():
        path = Path(row["local_path"])
        sections = parse_filing_sections(path, form_type=str(row["form"]))
        base = {
            "gvkey": row.get("gvkey"),
            "data_year": row.get("data_year"),
            "cik": row.get("cik"),
            "form": row.get("form"),
            "filingDate": row.get("filingDate"),
            "reportDate": row.get("reportDate"),
            "local_path": str(path),
        }
        for section_name, section_text in sections.items():
            record = base.copy()
            record["section_name"] = section_name
            record["section_text"] = section_text
            record["section_present"] = int(bool(section_text))
            record.update(compute_text_stats(section_text))
            if section_name == "item_402":
                record.update(compute_disclosure_framing(section_text))
            rows.append(record)
            section_corpora[section_name].append(section_text or "")

    features = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    features.to_csv(out_dir / "section_features_raw.csv", index=False)

    for section_name in ["item_1a", "item_7", "item_402"]:
        sub = features.loc[features["section_name"].eq(section_name)].copy()
        corpus = sub["section_text"].fillna("").tolist()
        if not corpus or sum(bool(text.strip()) for text in corpus) < 5:
            continue

        vectorizer = TfidfVectorizer(
            max_features=max_features,
            ngram_range=(1, 2),
            min_df=2,
            stop_words="english",
        )
        matrix = vectorizer.fit_transform(corpus)
        n_comp = int(min(svd_components, max(1, matrix.shape[1] - 1)))
        if n_comp <= 0:
            continue
        svd = TruncatedSVD(n_components=n_comp, random_state=42)
        reduced = svd.fit_transform(matrix)
        embed_cols = [f"{section_name}_svd_{i:02d}" for i in range(reduced.shape[1])]
        embed_df = pd.DataFrame(reduced, columns=embed_cols, index=sub.index)
        features.loc[sub.index, embed_cols] = embed_df
        joblib.dump(vectorizer, out_dir / f"{section_name}_tfidf.joblib")
        joblib.dump(svd, out_dir / f"{section_name}_svd.joblib")

    features.to_csv(out_dir / "section_features_with_embeddings.csv", index=False)
    return features


def aggregate_pcaob_monitoring(form_ap_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(form_ap_csv, low_memory=False)
    df["Issuer CIK"] = pd.to_numeric(df["Issuer CIK"], errors="coerce").astype("Int64")
    df["Fiscal Period End Date"] = pd.to_datetime(
        df["Fiscal Period End Date"], errors="coerce", format="mixed"
    )
    df["fiscal_year"] = df["Fiscal Period End Date"].dt.year.astype("Int64")
    df["Participant Percentage"] = pd.to_numeric(df["Participant Percentage"], errors="coerce")
    df["Number of Participants"] = pd.to_numeric(df["Number of Participants"], errors="coerce")
    df["Engagement Partner ID"] = df["Engagement Partner ID"].astype(str)

    agg = (
        df.groupby(["Issuer CIK", "fiscal_year"], as_index=False)
        .agg(
            pcaob_form_ap_count=("Form Filing ID", "size"),
            pcaob_unique_partners=("Engagement Partner ID", "nunique"),
            pcaob_avg_participants=("Number of Participants", "mean"),
            pcaob_avg_participant_pct=("Participant Percentage", "mean"),
        )
        .rename(columns={"Issuer CIK": "cik", "fiscal_year": "data_year"})
    )
    agg["cik"] = (
        agg["cik"].astype("Int64").astype(str).str.replace("<NA>", "", regex=False).str.zfill(10)
    )
    return agg


def build_paper2_dataset(
    *,
    master_panel_csv: Path,
    section_features_csv: Path,
    pcaob_form_ap_csv: Optional[Path],
    out_csv: Path,
) -> pd.DataFrame:
    panel = pd.read_csv(master_panel_csv)
    panel["gvkey"] = panel["gvkey"].astype(str)
    panel["data_year"] = pd.to_numeric(panel["data_year"], errors="coerce").astype("Int64")

    section = pd.read_csv(section_features_csv)
    section["gvkey"] = section["gvkey"].astype(str)
    section["data_year"] = pd.to_numeric(section["data_year"], errors="coerce").astype("Int64")

    section_wide_parts = []
    meta_cols = {
        "gvkey",
        "data_year",
        "section_name",
        "section_text",
        "local_path",
        "form",
        "filingDate",
        "reportDate",
        "cik",
    }
    for section_name, sub in section.groupby("section_name"):
        keep_cols = [col for col in sub.columns if col not in meta_cols]
        renamed = sub[["gvkey", "data_year"] + keep_cols].copy()
        renamed = renamed.drop_duplicates(subset=["gvkey", "data_year"], keep="first")
        renamed = renamed.rename(columns={col: f"{section_name}_{col}" for col in keep_cols})
        section_wide_parts.append(renamed)

    merged = panel.copy()
    for sub in section_wide_parts:
        merged = merged.merge(sub, on=["gvkey", "data_year"], how="left")

    if pcaob_form_ap_csv is not None and Path(pcaob_form_ap_csv).exists():
        pcaob = aggregate_pcaob_monitoring(Path(pcaob_form_ap_csv))
        if "cik" in merged.columns:
            merged["cik"] = (
                pd.to_numeric(merged["cik"], errors="coerce")
                .astype("Int64")
                .astype(str)
                .str.replace("<NA>", "", regex=False)
                .str.zfill(10)
            )
            merged = merged.merge(pcaob, on=["cik", "data_year"], how="left")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_csv, index=False)
    return merged


def build_paper2_readiness_report(dataset: pd.DataFrame) -> Dict[str, object]:
    report = {
        "rows": int(len(dataset)),
        "text_item_1a_coverage": float(
            dataset.filter(regex=r"^item_1a_section_present$").fillna(0).mean().iloc[0]
        )
        if "item_1a_section_present" in dataset.columns
        else 0.0,
        "text_item_7_coverage": float(
            dataset.filter(regex=r"^item_7_section_present$").fillna(0).mean().iloc[0]
        )
        if "item_7_section_present" in dataset.columns
        else 0.0,
        "text_item_402_coverage": float(
            dataset.filter(regex=r"^item_402_section_present$").fillna(0).mean().iloc[0]
        )
        if "item_402_section_present" in dataset.columns
        else 0.0,
        "has_monitoring_features": bool(
            {"pcaob_form_ap_count", "pcaob_unique_partners"}.intersection(dataset.columns)
        ),
    }
    return report
