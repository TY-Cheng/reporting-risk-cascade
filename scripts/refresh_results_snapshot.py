"""Refresh the docs results snapshot from a completed study artifact directory."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import ARTIFACTS_DIR, DOCS_DIR, PROJECT_ROOT  # noqa: E402
from src.linkage import WRDS_VALIDATED_TIER  # noqa: E402
from src.provenance import sha256_path  # noqa: E402
from scripts.build_manuscript_package import _reporting_contract  # noqa: E402
from scripts.monitor_public_lake import _validate_public_lake_final_report  # noqa: E402


CANONICAL_PUBLIC_DATA_AS_OF_DATE = "2026-07-06"
INPUT_SOURCE_ROLES = [
    ("Detected-misstatement benchmark input", "raw_data"),
    ("Public issuer dimension input", "issuer_dim"),
    ("Public issuer-origin panel input", "issuer_origin_panel"),
    ("Public-lake final report input", "public_lake_final_report"),
    ("CIK-GVKEY bridge input", "crosswalk"),
    ("Public-lake run metadata input", "public_lake_run_metadata"),
    ("Form AP source metadata input", "form_ap_source_metadata"),
]
MODERN_PUBLIC_LAKE_INPUT_LABELS = {
    "public_lake_final_report": "public-lake final report",
    "public_lake_run_metadata": "public-lake run metadata",
    "issuer_origin_panel": "issuer-origin panel",
    "form_ap_source_metadata": "Form AP source metadata",
}

FULL_REQUIRED_ARTIFACTS = [
    "study_run_manifest.json",
    "benchmark/benchmark_summary.md",
    "benchmark/rolling_metrics.csv",
    "benchmark/window_summary.csv",
    "benchmark/structural_breaks.csv",
    "benchmark/feature_family_importance.csv",
    "benchmark/timing_coverage.csv",
    "public_cascade/public_cascade_summary.json",
    "public_cascade/public_cascade_metrics.csv",
    "public_cascade/public_cascade_task_status.csv",
    "public_cascade/public_opacity_dml.csv",
    "bridge_probe/bridge_probe_summary.json",
    "bridge_probe/coverage_report.csv",
    "bridge_probe/multiplicity_report.csv",
    "peer_comparison/peer_comparison_summary.md",
    "peer_comparison/detected_misstatement_model_family_metrics.csv",
    "peer_comparison/peer_task_status.csv",
    "public_peer_comparison/public_model_family_summary.md",
    "public_peer_comparison/public_model_family_metrics.csv",
    "public_peer_comparison/public_model_family_task_status.csv",
    "construct_overlap/construct_overlap_manifest.json",
    "construct_overlap/construct_overlap_summary.md",
    "construct_overlap/overlap_sample_flow.csv",
    "construct_overlap/public_score_benchmark_ranking.csv",
    "construct_overlap/reciprocal_alignment.csv",
    "construct_overlap/label_contingency_lift.csv",
    "construct_overlap/event_time_concentration.csv",
    "construct_overlap/benchmark_positive_public_label_cooccurrence.csv",
    "construct_overlap/aggregation_sensitivity.csv",
]


PARTIAL_REQUIRED_ARTIFACTS = [
    "study_run_manifest.json",
    "benchmark/benchmark_summary.md",
    "benchmark/rolling_metrics.csv",
    "public_cascade/public_cascade_summary.json",
    "public_cascade/public_cascade_metrics.csv",
    "public_cascade/public_cascade_task_status.csv",
]


FIGURE_EXPLANATIONS = {
    "figure_01_public_task_pr_auc": {
        "title": "Public task PR-AUC",
        "claim": "The revision-frozen primary public specification ranks later public review-and-correction states above task prevalence.",
        "evidence": "Figure 1 receives only the declared `all + expanding` rows also owned by generated Table 3.",
        "boundary": "This is ranking evidence, not calibrated deployment evidence; Brier Skill Score and ECE remain the calibration gate.",
    },
    "figure_02_feature_family_pr_auc": {
        "title": "Feature-family PR-AUC",
        "claim": "Feature-family comparisons provide sensitivity evidence around the frozen public specification.",
        "evidence": "The figure compares all-feature, metadata, XBRL, auditor, oversight, and visibility/history information sets under the same public-label evaluation frame.",
        "boundary": "Interpret as information-set evidence rather than a structural source-importance or mechanism claim.",
    },
    "figure_03_detected_misstatement_peer_pr_auc": {
        "title": "Detected-misstatement peer-family PR-AUC",
        "claim": "Detected-misstatement peer-compatible model families provide benchmark-side metric-language context.",
        "evidence": "The figure reports Dechow-, Perols-, Bao-, and Bertomeu-style families on the detected-misstatement benchmark task.",
        "boundary": "These rows are transferred model-family diagnostics, not original-paper numeric replications.",
    },
    "figure_04_public_peer_pr_auc": {
        "title": "Public-label peer-family PR-AUC",
        "claim": "Familiar accounting ML model-family vocabularies can be evaluated on public review-and-correction labels.",
        "evidence": "The figure moves the peer-compatible families to the public-label task and keeps the metric vocabulary comparable.",
        "boundary": "Do not compare these values as same-estimand superiority over detected-misstatement studies.",
    },
    "figure_05_construct_overlap_lift": {
        "title": "Construct-overlap lift",
        "claim": "The WRDS-validated bridge supports related-but-non-identical overlap between public labels and detected-misstatement labels.",
        "evidence": "Figure 5 receives exactly the two declared primary alignment rows owned by generated Table 9, alongside precision/FDR context in the table.",
        "boundary": "Item 4.02 lift is a severe-tail diagnostic, not the sole construct-validity basis or event-identification proof.",
    },
}

FOLD_FIGURE_NOTE = (
    "Colored bars or dots encode mean PR-AUC; grey points encode valid annual test "
    "folds; capped black lines encode descriptive fold-dispersion intervals."
)
CONSTRUCT_FIGURE_NOTE = (
    "Blue bars encode top-decile lift; capped black lines encode row-level "
    "percentile-bootstrap intervals; the dashed vertical line marks lift = 1; "
    "annotations report top-decile precision and FDR."
)
FIGURE_NOTES = {
    **{f"figure_{index:02d}": FOLD_FIGURE_NOTE for index in range(1, 5)},
    "figure_05": CONSTRUCT_FIGURE_NOTE,
    **{
        key: CONSTRUCT_FIGURE_NOTE if key.startswith("figure_05") else FOLD_FIGURE_NOTE
        for key in FIGURE_EXPLANATIONS
    },
}


TABLE_EXPLANATIONS = {
    "table_01_component_status": {
        "claim": "All paper-facing study components are available for the current artifact-backed run.",
        "evidence": "Component statuses are read from the peer-enabled study manifest.",
        "boundary": "Component completion is a reproducibility status, not by itself a substantive empirical claim.",
    },
    "table_02_public_lake_scale": {
        "claim": "The public SEC/PCAOB lake supports the filing-origin measurement surface at scale.",
        "evidence": "Silver and gold row counts show filing, issuer, XBRL, notes, comment-thread, correction, and annual origin coverage.",
        "boundary": "Scale and coverage establish feasibility, not causal interpretation or complete regulatory review coverage.",
    },
    "table_03_public_task_metrics": {
        "claim": "The revision-frozen primary public specification produces above-prevalence ranking evidence for the three public labels.",
        "evidence": "Generated Table 3 owns the `all + expanding` primary rows and reports PR-AUC, ROC-AUC, fold support, calibration diagnostics, and prevalence by task.",
        "boundary": "Weak Brier Skill Score and ECE keep the claim to ranking/prioritization rather than calibrated probability rules.",
    },
    "table_04_feature_family_metrics": {
        "claim": "Feature-family comparisons provide sensitivity evidence around the frozen primary public specification.",
        "evidence": "Feature counts and PR-AUC dispersion are shown across the configured public feature-family grid.",
        "boundary": "Feature-family summaries are aggregation evidence and should not be read as causal source dominance.",
    },
    "table_05_benchmark_timing_metrics": {
        "claim": "Detected-misstatement benchmark performance is sensitive to label observability and timing assumptions.",
        "evidence": "Naive, proxy-imputed, and proxy-drop timing modes are compared under annual out-of-time folds.",
        "boundary": "This is benchmark-validity evidence, not a hidden-misconduct detector result.",
    },
    "table_06_detected_misstatement_peer_metrics": {
        "claim": "Peer-compatible model families provide benchmark-side metric-language alignment.",
        "evidence": "Detected-misstatement peer-family PR-AUC and ROC-AUC are reported across valid folds.",
        "boundary": "These are model-family transfer checks, not exact replications of prior samples or private data settings.",
    },
    "table_07_public_peer_metrics": {
        "claim": "Peer-compatible families also rank public-label outcomes under the public-cascade estimand.",
        "evidence": "Public-label peer-family PR-AUC and ROC-AUC are reported under the same public-label task design.",
        "boundary": "These values are within-public-label diagnostics, not cross-estimand superiority claims.",
    },
    "table_08_bridge_coverage": {
        "claim": "The bridge covers most benchmark rows and firms before overlap claims are made.",
        "evidence": "Row, firm, and positive-row coverage are reported for the raw-only WRDS gvkey-CIK-year bridge.",
        "boundary": "Construct-overlap claims remain bounded to matched bridge rows.",
    },
    "table_09_construct_alignment": {
        "claim": "Public scores and detected-misstatement scores show reciprocal severe-tail enrichment under the bridge gate.",
        "evidence": "Generated Table 9 is the sole owner of the two declared primary alignment rows and their top-decile lift, precision, FDR, and bootstrap intervals.",
        "boundary": "Lift above one supports enrichment, while low absolute precision and high FDR rule out event-identification claims.",
    },
    "table_12_public_opacity_dml": {
        "claim": "Opacity/missingness has at most diagnostic adjusted-association evidence in the current public-label setting.",
        "evidence": "DML-style coefficients, robust standard errors, intervals, and p-values are reported by public label.",
        "boundary": "These are adjusted associations and do not identify causal selection or strategic silence.",
    },
    "table_13_public_fold_support": {
        "claim": "Annual public-label test folds have sufficient positive support for reported dispersion summaries.",
        "evidence": "Task-year rows, positives, prevalence, and sparse-fold flags are reported.",
        "boundary": "Fold support makes dispersion auditable; it does not remove class-imbalance or calibration concerns.",
    },
    "table_14_task_feature_family_metrics": {
        "claim": "Task-level feature-family rankings provide sensitivity evidence around the frozen primary rows.",
        "evidence": "Task-by-feature-family PR-AUC, ROC-AUC, calibration diagnostics, and fold support are reported across the configured grid.",
        "boundary": "Use this table for label-specific prose rather than a single global feature-family ranking.",
    },
    "table_15_bridge_overlap_matrix": {
        "claim": "Public labels and detected-misstatement labels are related but not identical across bridge tiers.",
        "evidence": "The matrix reports benchmark/public rates, co-occurrence, and lifts by label and bridge tier.",
        "boundary": "The typed pattern is construct-validity evidence; it does not establish label equivalence.",
    },
    "table_16_bridge_sample_boundaries": {
        "claim": "The bridge exercise has explicit covered, ambiguous, dropped, and unmatched sample boundaries.",
        "evidence": "Benchmark rows and positives are shown by bridge-overlap boundary.",
        "boundary": "Generalization beyond high-confidence mapped rows should be qualified.",
    },
    "table_17_selection_profile": {
        "claim": "Public labels partly reflect selected public scrutiny and issuer visibility states.",
        "evidence": "Public-label rates are profiled across filing size, XBRL assets, filing history, prior comments, form type, and FPI proxy strata.",
        "boundary": "This descriptive profile is not a causal SEC-selection correction.",
    },
    "table_18_public_sample_attrition": {
        "claim": "The public sample has an explicit sequential construction path and task-specific eligibility branches.",
        "evidence": "Generated Table 18 reports source, year, domestic-status, observability, and task-eligibility row counts with parent-relative attrition.",
        "boundary": "Task rows branch from the shared observable horizon and must not be read as sequential losses from one another.",
    },
}


def _bridge_language(
    manifest: dict[str, Any],
    construct_manifest: dict[str, Any],
) -> dict[str, str]:
    component = manifest.get("components", {}).get("construct_overlap", {})
    component_tier = component.get("validation_tier") if isinstance(component, dict) else None
    artifact_tier = construct_manifest.get("validation_tier")
    tiers_match = component_tier == artifact_tier
    component_tier_label = str(component_tier or "none")
    artifact_tier_label = str(artifact_tier or "none")
    tier = artifact_tier_label if tiers_match else ""
    if not tiers_match:
        tier = f"component={component_tier_label}; manifest={artifact_tier_label}"
    if tiers_match and artifact_tier == WRDS_VALIDATED_TIER:
        return {
            "tier": tier,
            "status": "validated",
            "component_tier": component_tier_label,
            "artifact_tier": artifact_tier_label,
            "overview_data": ("a raw-only `gvkey-CIK-year` bridge for overlap validation"),
            "overview_boundary": (
                f"Construct overlap is `{tier}` using the confirmed WRDS SEC Analytics "
                "Suite CIK-GVKEY bridge."
            ),
            "headline_guidance": (
                "Headline claims should describe filing-origin measurement, prevalence-aware "
                "ranking, and construct overlap within the stated bridge tier."
            ),
            "key_reading": (
                "The evidence supports a filing-origin measurement and ranking contribution, "
                "not a hidden-misconduct detector or calibrated deployment rule. The frozen "
                "public specification is interpreted against prevalence and calibration, while "
                "WRDS-validated overlap establishes related but non-identical constructs."
            ),
            "primary_alignment_interpretation": (
                "The declared primary ranking-alignment rows are severe-tail diagnostics. "
                "Lift above one shows enrichment, while low absolute precision and high FDR "
                "keep the interpretation bounded to construct overlap rather than event "
                "identification."
            ),
            "experiment_intro": (
                "This experiment is the integrated-paper gate. The current bridge is the "
                "confirmed WRDS SEC Analytics Suite CIK-GVKEY link export, used as a "
                "raw-only `gvkey-CIK-year` bridge."
            ),
            "contingency": (
                "The contingency matrix is the broader construct-validity evidence. Comment "
                "threads are broad public scrutiny, amendments show stronger correction/friction "
                "alignment, and Item 4.02 is a rare severe-tail state; the integrated claim rests "
                "on this typed pattern plus the bridge gate, not on Item 4.02 alone."
            ),
            "experiment_close": (
                "Overlap results determine whether the benchmark and public cascade are related "
                "enough for an integrated construct argument. The evidence can support a "
                "related-but-non-identical interpretation only when bridge coverage, "
                "multiplicity, reciprocal alignment, and event-time concentration are all "
                "reported."
            ),
            "discussion_answer": (
                f"`{tier}` bridge evidence supports the integrated benchmark-to-public "
                "construct-overlap interpretation."
            ),
            "discussion_relation": (
                "- Public labels and detected-misstatement benchmark labels are related but "
                "non-identical constructs."
            ),
            "discussion_reciprocal": (
                "- Public-cascade scores can rank benchmark positives in the matched overlap; "
                "detected-misstatement scores can also rank severe public correction labels."
            ),
            "generalizability": (
                f"Construct-overlap findings generalize only to the covered `{tier}` bridge "
                "sample."
            ),
            "claim_text": (
                "Public and detected-misstatement constructs are related but non-identical."
            ),
            "claim_evidence": (
                "WRDS bridge coverage, generated Table 9, Figure 5, and contingency matrix."
            ),
        }
    return {
        "tier": tier,
        "status": "diagnostic",
        "component_tier": component_tier_label,
        "artifact_tier": artifact_tier_label,
        "overview_data": (f"a `{tier}` crosswalk retained for diagnostic overlap analysis only"),
        "overview_boundary": (
            f"Construct overlap tier is `{tier}`; the evidence remains diagnostic and the "
            "cross-construct claim is deferred."
        ),
        "headline_guidance": (
            "Headline claims should describe filing-origin measurement and prevalence-aware "
            "ranking; construct-overlap headline claims are deferred, and candidate bridge "
            "rows remain diagnostic."
        ),
        "key_reading": (
            "The evidence supports a filing-origin measurement and ranking contribution, "
            "not a hidden-misconduct detector or calibrated deployment rule. The frozen public "
            "specification is interpreted against prevalence and calibration; overlap rows "
            "remain diagnostic until the exact raw bridge contract is validated."
        ),
        "primary_alignment_interpretation": (
            "Lift above one is a numeric pattern in the diagnostic rows; it does not establish "
            "enrichment, and the cross-construct claim is deferred."
        ),
        "experiment_intro": (
            f"This experiment reports `{tier}` bridge diagnostics. It does not mature a "
            "cross-construct manuscript claim, which remains deferred pending exact raw bridge "
            "validation."
        ),
        "contingency": (
            "The contingency matrix remains diagnostic. Its label patterns do not mature a "
            "cross-construct claim while the bridge tier is unvalidated."
        ),
        "experiment_close": (
            "Overlap rows are retained as diagnostic evidence only. Bridge coverage, "
            "multiplicity, reciprocal alignment, and event-time concentration cannot mature a "
            "cross-construct claim until the exact raw bridge contract is validated."
        ),
        "discussion_answer": (
            f"`{tier}` bridge evidence is diagnostic; the benchmark-to-public construct claim "
            "is deferred."
        ),
        "discussion_relation": (
            "- Candidate bridge rows show diagnostic public/benchmark patterns; a "
            "related-construct claim is deferred."
        ),
        "discussion_reciprocal": (
            "- Reciprocal score-alignment rows remain diagnostic and do not mature a "
            "cross-construct claim."
        ),
        "generalizability": (
            f"The `{tier}` overlap rows are diagnostic only; cross-construct generalization is "
            "deferred."
        ),
        "claim_text": (
            "Candidate bridge rows provide diagnostic public/benchmark overlap patterns."
        ),
        "claim_evidence": (
            "Candidate bridge coverage, generated Table 9, Figure 5, and contingency matrix."
        ),
    }


def _validate_package_bridge_claim_boundary(
    package_dir: Path,
    bridge_language: dict[str, str],
) -> None:
    package_manifest = _read_json(package_dir / "manifest.json")
    boundary = package_manifest.get("claim_boundary")
    if not isinstance(boundary, dict):
        raise ValueError("manuscript package claim boundary is missing or malformed")
    expected = {
        "construct_overlap_tier": bridge_language["tier"],
        "construct_overlap_status": bridge_language["status"],
        "construct_overlap_component_tier": bridge_language["component_tier"],
        "construct_overlap_artifact_tier": bridge_language["artifact_tier"],
    }
    mismatches = [
        f"{field}: expected {value!r}, got {boundary.get(field)!r}"
        for field, value in expected.items()
        if boundary.get(field) != value
    ]
    if mismatches:
        raise ValueError(
            "manuscript package claim boundary does not match live bridge evidence: "
            + "; ".join(mismatches)
        )


def _bridge_artifact_explanations(
    bridge_language: dict[str, str],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    figures = {key: dict(value) for key, value in FIGURE_EXPLANATIONS.items()}
    tables = {key: dict(value) for key, value in TABLE_EXPLANATIONS.items()}
    if bridge_language["status"] == "validated":
        return figures, tables
    figures["figure_05_construct_overlap_lift"] = {
        "title": "Construct-overlap lift",
        "claim": "Candidate bridge lift rows are diagnostic; the construct claim is deferred.",
        "evidence": (
            "Figure 5 displays the two declared alignment rows alongside precision/FDR context."
        ),
        "boundary": "The rows cannot support a cross-construct manuscript claim.",
    }
    tables["table_08_bridge_coverage"] = {
        "claim": "Candidate bridge coverage is diagnostic; the construct claim is deferred.",
        "evidence": "Row, firm, and positive-row coverage describe the candidate crosswalk.",
        "boundary": "Coverage does not validate bridge provenance or construct overlap.",
    }
    tables["table_09_construct_alignment"] = {
        "claim": "Alignment rows remain diagnostic under the candidate bridge tier.",
        "evidence": "Table 9 reports lift, precision, FDR, and bootstrap intervals.",
        "boundary": "No cross-construct manuscript claim matures from these rows.",
    }
    tables["table_15_bridge_overlap_matrix"] = {
        "claim": "The candidate overlap matrix is diagnostic; the construct claim is deferred.",
        "evidence": "The matrix reports benchmark/public rates and co-occurrence by label.",
        "boundary": "The patterns do not validate provenance or establish label equivalence.",
    }
    tables["table_16_bridge_sample_boundaries"] = {
        "claim": "Candidate bridge sample boundaries are explicit and diagnostic.",
        "evidence": "Rows and positives are shown across covered, ambiguous, and dropped groups.",
        "boundary": "Cross-construct generalization is deferred.",
    }
    return figures, tables


def _resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, list | tuple | set):
        return ", ".join(_fmt(item, digits=digits) for item in value) or "none"
    if pd.isna(value):
        return ""
    if isinstance(value, bool):
        return "`True`" if value else "`False`"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer() and abs(value) >= 100:
            return f"{int(value):,}"
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_p_value(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _fmt(value)
    if pd.isna(numeric):
        return ""
    if 0 <= numeric < 0.001:
        return "<0.001"
    return _fmt(numeric)


def _summarize_wrds_sources(source_values: Any) -> str:
    if isinstance(source_values, list | tuple | set):
        combinations = {str(value).strip() for value in source_values if str(value).strip()}
    elif source_values is None or (isinstance(source_values, float) and pd.isna(source_values)):
        combinations = set()
    else:
        value = str(source_values).strip()
        combinations = {value} if value else set()
    if not combinations:
        return "none"

    families = {
        token.rsplit(":", 1)[-1].strip()
        for combination in combinations
        for token in combination.split(";")
        if token.strip()
    }
    combination_label = "combination" if len(combinations) == 1 else "combinations"
    family_label = "family" if len(families) == 1 else "families"
    return (
        f"{len(combinations)} observed {combination_label} across {len(families)} WRDS "
        f"source {family_label} in the current run; full values remain hash-bound in "
        "the study manifest"
    )


def _fmt_year(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(int(value))


def _code(value: Any) -> str:
    text = _fmt(value)
    return f"`{text}`" if text else ""


def _rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return f"<external>/{resolved.name or 'root'}"


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        rows = [["" for _ in headers]]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def _missing_artifacts(study_dir: Path, *, allow_partial: bool) -> list[Path]:
    required = PARTIAL_REQUIRED_ARTIFACTS if allow_partial else FULL_REQUIRED_ARTIFACTS
    return [study_dir / rel_path for rel_path in required if not (study_dir / rel_path).exists()]


def _latest_public_lake_report() -> dict[str, Any]:
    report_root = ARTIFACTS_DIR / "logs" / "public_lake_full"
    reports = sorted(report_root.glob("*/run_report.json"), key=lambda path: path.stat().st_mtime)
    if not reports:
        return {}
    report = _read_json(reports[-1])
    report["_path"] = str(reports[-1])
    snapshot = report.get("snapshot", {})
    if isinstance(snapshot, dict) and not report.get("timestamp_utc"):
        report["timestamp_utc"] = snapshot.get("timestamp_utc")
    row_counts = report.get("row_counts_json") or report.get("row_counts")
    if row_counts is None and isinstance(snapshot, dict):
        row_counts = snapshot.get("row_counts_json") or snapshot.get("row_counts")
    if isinstance(row_counts, str):
        report["row_counts"] = json.loads(row_counts)
    else:
        report["row_counts"] = row_counts or {}
    manifest_rows = report.get("manifest_rows_json")
    if manifest_rows is None and isinstance(snapshot, dict):
        manifest_rows = snapshot.get("manifest_rows_json") or snapshot.get("manifest_rows")
    if isinstance(manifest_rows, str):
        report["manifest_rows"] = json.loads(manifest_rows)
    else:
        report["manifest_rows"] = manifest_rows or {}
    return report


def _resolve_input_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        inputs = {}
    provenance = manifest.get("provenance")
    records = provenance.get("input_files", []) if isinstance(provenance, dict) else []
    if not isinstance(records, list):
        records = []
    records_by_path: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            records_by_path.setdefault(record["path"], []).append(record)

    resolved = {}
    for _, input_key in INPUT_SOURCE_ROLES:
        path = inputs.get(input_key)
        matches = records_by_path.get(path, []) if isinstance(path, str) else []
        if len(matches) == 1:
            resolved[input_key] = matches[0]

    if "public_lake_inputs" not in manifest:
        return resolved
    public_lake_inputs = manifest["public_lake_inputs"]
    if not isinstance(public_lake_inputs, dict):
        raise ValueError("pinned public-lake inputs are malformed")
    for key, label in MODERN_PUBLIC_LAKE_INPUT_LABELS.items():
        if key not in public_lake_inputs:
            raise ValueError(f"pinned public-lake inputs missing {key}")
        record = public_lake_inputs[key]
        if not isinstance(record, dict):
            raise ValueError(f"pinned {label} record is malformed")
        raw_path = record.get("path")
        expected_sha256 = record.get("sha256")
        if (
            record.get("exists") is not True
            or not isinstance(raw_path, str)
            or not raw_path
            or not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        ):
            raise ValueError(f"pinned {label} record is malformed")
        if inputs.get(key) != raw_path:
            raise ValueError(f"pinned {label} path does not match manifest.inputs")
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(f"pinned {label} is missing: {path}")
        if sha256_path(path) != expected_sha256:
            raise ValueError(f"pinned {label} hash mismatch")
        provenance_matches = records_by_path.get(raw_path, [])
        if not provenance_matches:
            raise ValueError(f"pinned {label} provenance record is missing")
        if len(provenance_matches) != 1:
            raise ValueError(f"pinned {label} provenance record is ambiguous")
        provenance_record = provenance_matches[0]
        provenance_sha256 = provenance_record.get("sha256")
        if (
            provenance_record.get("exists") is not True
            or not isinstance(provenance_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", provenance_sha256) is None
        ):
            raise ValueError(f"pinned {label} provenance record is malformed")
        if provenance_sha256 != expected_sha256:
            raise ValueError(f"pinned {label} SHA does not match provenance")
        resolved[key] = provenance_record
    return resolved


def _load_public_lake_report(
    manifest: dict[str, Any],
    resolved_inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if "public_lake_inputs" not in manifest:
        return _latest_public_lake_report()
    paths = {key: Path(resolved_inputs[key]["path"]) for key in MODERN_PUBLIC_LAKE_INPUT_LABELS}

    return dict(
        _validate_public_lake_final_report(
            paths["public_lake_final_report"],
            run_metadata_path=paths["public_lake_run_metadata"],
            issuer_origin_panel_path=paths["issuer_origin_panel"],
        )
    )


def _source_role_rows(resolved_inputs: dict[str, dict[str, Any]]) -> list[list[str]]:
    rows = []
    for role, input_key in INPUT_SOURCE_ROLES:
        record = resolved_inputs.get(input_key, {})
        rows.append(
            [
                role,
                _code(str(record.get("exists") is True)),
                _code(record.get("sha256")),
            ]
        )
    return rows


def _claim_maturity_rows(
    manifest: dict[str, Any],
    bridge_language: dict[str, str] | None = None,
) -> list[list[str]]:
    maturity = manifest.get("claim_maturity", {})
    if not isinstance(maturity, dict):
        return []
    return [
        [
            str(claim),
            _code(
                "deferred"
                if claim == "construct_alignment"
                and bridge_language
                and bridge_language["status"] != "validated"
                else status
            ),
        ]
        for claim, status in maturity.items()
    ]


def _canonical_status(
    manifest: dict[str, Any],
    construct_manifest: dict[str, Any],
) -> tuple[str, list[str]]:
    provenance = dict(manifest.get("provenance", {}))
    public_lake = dict(manifest.get("public_lake_provenance", {}))
    study_commit = manifest.get("repo_commit")
    failures = []
    if manifest.get("git_dirty") is not False:
        failures.append("dirty-state: study git_dirty is not false")
    if public_lake.get("git_dirty") is not False:
        failures.append("dirty-state: public-lake git_dirty is not false")
    if public_lake.get("fresh_build") is not True:
        failures.append("freshness: public-lake fresh_build is not true")
    if public_lake.get("as_of_date") != CANONICAL_PUBLIC_DATA_AS_OF_DATE:
        failures.append("date: public-data as-of date is not " + CANONICAL_PUBLIC_DATA_AS_OF_DATE)
    if not study_commit:
        failures.append("identity: study commit is missing")
    if study_commit != provenance.get("commit_sha"):
        failures.append("identity: study and provenance commits differ")
    if study_commit != public_lake.get("commit_sha"):
        failures.append("identity: study and public-lake commits differ")
    construct_component = manifest.get("components", {}).get("construct_overlap", {})
    component_tier = (
        construct_component.get("validation_tier")
        if isinstance(construct_component, dict)
        else None
    )
    manifest_tier = construct_manifest.get("validation_tier")
    if component_tier != WRDS_VALIDATED_TIER:
        failures.append("bridge: construct component validation tier is not `wrds_validated`")
    if manifest_tier != WRDS_VALIDATED_TIER:
        failures.append("bridge: construct manifest validation tier is not `wrds_validated`")
    return ("CANONICAL" if not failures else "NON-CANONICAL", failures)


def _public_task_frame(manuscript_package: Path) -> pd.DataFrame:
    frame = _read_csv(manuscript_package / "tables" / "table_03_public_task_metrics.csv")
    required = {
        "Task",
        "Panel_Positives",
        "Mean_Prevalence",
        "Mean_PR_AUC",
        "Mean_ROC_AUC",
        "Mean_Brier_Skill",
        "Mean_ECE",
        "n_folds",
        "metric_rows",
    }
    error = "generated Table 3 must contain nonempty unique task rows with display columns"
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError(error)
    tasks = frame["Task"].astype("string").str.strip()
    if tasks.isna().any() or tasks.eq("").any() or tasks.duplicated().any():
        raise ValueError(error)
    return frame


def _public_task_rows(manuscript_package: Path) -> list[list[str]]:
    frame = _public_task_frame(manuscript_package)
    return [
        [
            _code(row["Task"]),
            _fmt(row["Panel_Positives"]),
            _fmt(row["Mean_Prevalence"]),
            _fmt(row["Mean_PR_AUC"]),
            _fmt(row["Mean_ROC_AUC"]),
            _fmt(row["Mean_Brier_Skill"]),
            _fmt(row["Mean_ECE"]),
            _fmt(row["n_folds"], digits=0),
            _fmt(row["metric_rows"], digits=0),
        ]
        for _, row in frame.iterrows()
    ]


def _benchmark_panel_rows(study_dir: Path) -> list[list[str]]:
    summary = _read_text(study_dir / "benchmark" / "benchmark_summary.md")
    if not summary:
        return []
    rows = []
    for label in [
        "Rows",
        "Firms",
        "Years",
        "Positive rate",
        "Positive rows without timing proxy",
        "Timing claim status",
    ]:
        match = re.search(rf"^- {re.escape(label)}: (.+)$", summary, flags=re.MULTILINE)
        if match:
            rows.append([label, match.group(1)])
    return rows


def _public_peer_task_rows(path: Path) -> list[list[str]]:
    metrics = _read_csv(path)
    if metrics.empty or "task" not in metrics.columns:
        return []
    grouped = (
        metrics.groupby("task", dropna=False)
        .agg(
            rows=("pr_auc", "size"),
            mean_prevalence=("prevalence", "mean")
            if "prevalence" in metrics.columns
            else ("pr_auc", "size"),
            mean_pr_auc=("pr_auc", "mean"),
            mean_roc_auc=("roc_auc", "mean"),
        )
        .reset_index()
    )
    rows = []
    for _, row in grouped.sort_values("mean_pr_auc", ascending=False).iterrows():
        rows.append(
            [
                _code(row["task"]),
                _fmt(row["rows"], digits=0),
                _fmt(row["mean_prevalence"]),
                _fmt(row["mean_pr_auc"]),
                _fmt(row["mean_roc_auc"]),
            ]
        )
    return rows


def _status_count_rows(path: Path) -> list[list[str]]:
    frame = _read_csv(path)
    if frame.empty or "status" not in frame.columns:
        return []
    group_cols = ["status"]
    if "reason_code" in frame.columns:
        group_cols.append("reason_code")
    grouped = frame.groupby(group_cols, dropna=False).size().reset_index(name="rows")
    rows = []
    for _, row in grouped.sort_values("rows", ascending=False).iterrows():
        reason = row.get("reason_code", "")
        rows.append([_code(row["status"]), _code(reason), _fmt(row["rows"], digits=0)])
    return rows


def _benchmark_window_rows(study_dir: Path) -> list[list[str]]:
    frame = _read_csv(study_dir / "benchmark" / "rolling_metrics.csv")
    required = {
        "label_mode",
        "window",
        "pr_auc",
        "roc_auc",
        "brier_skill_score",
        "ece",
        "top_100_precision",
        "top_decile_precision",
    }
    if frame.empty or not required.issubset(frame.columns):
        return []
    grouped = (
        frame.groupby(["label_mode", "window"], dropna=False)
        .agg(
            pr_auc=("pr_auc", "mean"),
            roc_auc=("roc_auc", "mean"),
            brier_skill_score=("brier_skill_score", "mean"),
            ece=("ece", "mean"),
            top_100_precision=("top_100_precision", "mean"),
            top_decile_precision=("top_decile_precision", "mean"),
        )
        .reset_index()
    )
    rows = []
    for _, row in grouped.sort_values(
        ["label_mode", "pr_auc"], ascending=[True, False]
    ).iterrows():
        rows.append(
            [
                _code(row["label_mode"]),
                _code(row["window"]),
                _fmt(row["pr_auc"]),
                _fmt(row["roc_auc"]),
                _fmt(row["brier_skill_score"]),
                _fmt(row["ece"]),
                _fmt(row["top_100_precision"]),
                _fmt(row["top_decile_precision"]),
            ]
        )
    return rows


def _structural_break_rows(study_dir: Path, *, max_rows: int = 12) -> list[list[str]]:
    frame = _read_csv(study_dir / "benchmark" / "structural_breaks.csv")
    if frame.empty or not {
        "window",
        "label_mode",
        "family",
        "break_year",
        "f_stat",
        "p_value",
    }.issubset(frame.columns):
        return []
    frame = frame.copy()
    frame["p_value_num"] = pd.to_numeric(frame["p_value"], errors="coerce")
    rows = []
    for _, row in frame.sort_values("p_value_num").head(max_rows).iterrows():
        rows.append(
            [
                _code(row["window"]),
                _code(row["label_mode"]),
                _code(row["family"]),
                _fmt_year(row["break_year"]),
                _fmt(row["f_stat"]),
                _fmt_p_value(row["p_value"]),
            ]
        )
    return rows


def _feature_importance_rows(study_dir: Path, *, max_rows: int = 12) -> list[list[str]]:
    frame = _read_csv(study_dir / "benchmark" / "feature_family_importance.csv")
    if frame.empty or not {"label_mode", "family", "importance_share"}.issubset(frame.columns):
        return []
    grouped = (
        frame.groupby(["label_mode", "family"], dropna=False)["importance_share"]
        .mean()
        .reset_index()
        .sort_values("importance_share", ascending=False)
    )
    rows = []
    for _, row in grouped.head(max_rows).iterrows():
        rows.append(
            [_code(row["label_mode"]), _code(row["family"]), _fmt(row["importance_share"])]
        )
    return rows


def _simple_csv_rows(
    path: Path, columns: list[str], *, max_rows: int | None = None
) -> list[list[str]]:
    frame = _read_csv(path)
    if frame.empty or not set(columns).issubset(frame.columns):
        return []
    if max_rows is not None:
        frame = frame.head(max_rows)
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _fmt(row.get(col))
                if col not in {"public_label", "bridge_tier", "label_pattern", "metric_status"}
                else _code(row.get(col))
                for col in columns
            ]
        )
    return rows


def _event_time_rows(study_dir: Path) -> list[list[str]]:
    frame = _read_csv(study_dir / "construct_overlap" / "event_time_concentration.csv")
    if frame.empty:
        return []
    columns = [
        "relative_year",
        "public_label",
        "n_benchmark_positive",
        "n_benchmark_negative",
        "public_label_rate_benchmark_positive",
        "public_label_rate_benchmark_negative",
        "raw_difference",
        "balanced_window",
    ]
    if not set(columns).issubset(frame.columns):
        return []
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _fmt(row["relative_year"]),
                _code(row["public_label"]),
                _fmt(row["n_benchmark_positive"]),
                _fmt(row["n_benchmark_negative"]),
                _fmt(row["public_label_rate_benchmark_positive"]),
                _fmt(row["public_label_rate_benchmark_negative"]),
                _fmt(row["raw_difference"]),
                _fmt(bool(row["balanced_window"])),
            ]
        )
    return rows


def _copy_inline_figures(package_dir: Path) -> dict[str, str]:
    """Copy generated PNG figures into docs assets and return doc-relative paths."""
    src_dir = package_dir / "figures"
    asset_dir = DOCS_DIR / "assets" / "results_snapshot"
    asset_dir.mkdir(parents=True, exist_ok=True)

    copied: dict[str, str] = {}
    for src in sorted(src_dir.glob("figure_*.png")):
        target = asset_dir / src.name
        shutil.copy2(src, target)
        copied[src.stem] = f"assets/results_snapshot/{target.name}"
    return copied


def _manifest_format_path(
    package_dir: Path,
    entry: Any,
    format_name: str,
    fallback: Path,
) -> Path:
    """Resolve a canonical manifest format record without exposing external paths."""
    root = package_dir.resolve()
    if not fallback.resolve().is_relative_to(root):
        raise ValueError("manifest fallback escapes manuscript package")
    declared: Any = None
    strict_record = False
    if isinstance(entry, dict):
        declared = entry.get(format_name)
    if isinstance(declared, dict):
        declared = declared.get("path")
        strict_record = True
    if strict_record:
        if not isinstance(declared, str) or not declared:
            raise ValueError(
                f"canonical manuscript package manifest is missing {format_name} path"
            )
        relative = Path(declared)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("canonical manifest path escapes manuscript package")
        candidate = (package_dir / relative).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("canonical manifest path escapes manuscript package")
        if not candidate.is_file():
            raise ValueError(
                f"manuscript package manifest declares missing {format_name}: {declared}"
            )
        return candidate
    if isinstance(declared, str) and declared:
        relative = Path(declared)
        if not relative.is_absolute() and ".." not in relative.parts:
            candidate = (package_dir / relative).resolve()
            if candidate.is_relative_to(root):
                if candidate.is_file():
                    return candidate
    return fallback


def _explanation_block(explanation: dict[str, str]) -> list[str]:
    return [
        f"- **Claim.** {explanation['claim']}",
        f"- **Evidence.** {explanation['evidence']}",
        f"- **Boundary.** {explanation['boundary']}",
    ]


def _construct_alignment_frame(manuscript_package: Path) -> pd.DataFrame:
    frame = _read_csv(manuscript_package / "tables" / "table_09_construct_alignment.csv")
    required = {
        "Direction",
        "Model",
        "Target",
        "PR_AUC",
        "ROC_AUC",
        "Top_10pct_Precision",
        "Top_10pct_FDR",
        "Top_Decile_Lift",
        "Lift_Bootstrap_Interval",
    }
    if len(frame) != 2 or not required.issubset(frame.columns):
        raise ValueError("generated Table 9 must contain exactly two primary rows")
    return frame


def _construct_alignment_rows(manuscript_package: Path) -> list[list[str]]:
    frame = _construct_alignment_frame(manuscript_package)
    return [
        [
            row["Direction"],
            _code(row["Model"]),
            _code(row["Target"]),
            _fmt(row["PR_AUC"]),
            _fmt(row["ROC_AUC"]),
            _fmt(row["Top_10pct_Precision"]),
            _fmt(row["Top_10pct_FDR"]),
            _fmt(row["Top_Decile_Lift"]),
            str(row["Lift_Bootstrap_Interval"]),
        ]
        for _, row in frame.iterrows()
    ]


def _exploratory_maxima_rows(
    study_dir: Path,
    manuscript_package: Path,
    construct_manifest: dict[str, Any],
) -> list[list[str]]:
    primary = _construct_alignment_frame(manuscript_package)
    public_mask = primary["Direction"].astype(str).str.lower().str.startswith("public")
    if int(public_mask.sum()) != 1:
        raise ValueError("generated Table 9 must identify one public-to-benchmark row")
    primary_by_direction = {
        "public_to_benchmark": primary.loc[public_mask].iloc[0],
        "benchmark_to_public": primary.loc[~public_mask].iloc[0],
    }
    raw_paths = {
        "public_to_benchmark": (
            study_dir / "construct_overlap" / "public_score_benchmark_ranking.csv"
        ),
        "benchmark_to_public": (study_dir / "construct_overlap" / "reciprocal_alignment.csv"),
    }
    declared_maxima = construct_manifest.get("exploratory_maxima", {})
    search_universe = construct_manifest.get("search_universe_rows", {})
    rows = []
    for direction, path in raw_paths.items():
        frame = _read_csv(path)
        if frame.empty or "top_decile_lift" not in frame.columns:
            continue
        lifts = pd.to_numeric(frame["top_decile_lift"], errors="coerce")
        if "metric_status" in frame.columns:
            lifts = lifts.where(frame["metric_status"].eq("fit"))
        if not lifts.notna().any():
            continue
        maximum = frame.loc[lifts.idxmax()]
        maximum_lift = float(lifts.loc[lifts.idxmax()])
        primary_lift = float(primary_by_direction[direction]["Top_Decile_Lift"])
        declared = declared_maxima.get(direction, {})
        key_names = list(declared.get("keys", {})) if isinstance(declared, dict) else []
        maximum_keys = {name: str(maximum.get(name, "")) for name in key_names}
        rows.append(
            [
                _code(direction),
                _fmt(search_universe.get(direction)),
                _code(maximum_keys),
                _fmt(maximum_lift),
                _fmt(primary_lift),
                _fmt(maximum_lift - primary_lift),
            ]
        )
    return rows


def build_snapshot(
    study_dir: Path,
    *,
    manuscript_package: Path | None = None,
    allow_partial: bool,
) -> str:
    manuscript_package = manuscript_package or ARTIFACTS_DIR / "manuscript_package"
    study_manifest_path = study_dir / "study_run_manifest.json"
    manifest = _read_json(study_manifest_path)
    resolved_inputs = _resolve_input_records(manifest)
    public_summary = _read_json(study_dir / "public_cascade" / "public_cascade_summary.json")
    bridge_summary = _read_json(study_dir / "bridge_probe" / "bridge_probe_summary.json")
    construct_manifest = _read_json(
        study_dir / "construct_overlap" / "construct_overlap_manifest.json"
    )
    public_lake_report = _load_public_lake_report(manifest, resolved_inputs)
    public_task_positive_counts = public_summary.get("task_positive_counts") or {}
    public_task_exclusion_counts = public_summary.get("task_exclusion_counts") or {}
    zero_positive_tasks = public_summary.get("zero_positive_tasks") or []

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    study_rel = _rel(study_dir)
    bridge_language = _bridge_language(manifest, construct_manifest)
    validation_tier = bridge_language["tier"]
    figure_explanations, table_explanations = _bridge_artifact_explanations(bridge_language)
    package_manifest = _read_json(manuscript_package / "manifest.json")
    if package_manifest.get("schema_version") != "manuscript-package-v2":
        raise ValueError("results snapshot requires manuscript-package-v2")

    def full_commit(value: object, context: str) -> str:
        if (
            type(value) is not str
            or len(value) != 40
            or any(character not in "0123456789abcdefABCDEF" for character in value)
        ):
            raise ValueError(f"{context} must be a full 40-character hexadecimal commit")
        return value.lower()

    package_commit = full_commit(package_manifest.get("study_commit"), "package study_commit")
    study_commit = full_commit(manifest.get("repo_commit"), "study repo_commit")
    if package_commit != study_commit:
        raise ValueError("package study_commit does not match exact study commit")
    if package_manifest.get("study_manifest_sha256") != sha256_path(study_manifest_path):
        raise ValueError("package study_manifest_sha256 does not match exact study manifest bytes")

    reporting_contract = package_manifest.get("reporting_contract")
    if type(reporting_contract) is not dict:
        raise ValueError("manuscript package reporting_contract must be an object")
    artifact_ownership = reporting_contract.get("artifact_ownership")
    owner_names = {"reproducibility", *(f"experiment_{index}" for index in range(1, 7))}
    if type(artifact_ownership) is not dict or set(artifact_ownership) != owner_names:
        raise ValueError("reporting contract artifact_ownership must declare six experiments")
    if any(
        type(owner) is not dict
        or set(owner) != {"tables", "figures"}
        or type(owner["tables"]) is not list
        or type(owner["figures"]) is not list
        for owner in artifact_ownership.values()
    ):
        raise ValueError(
            "reporting contract artifact_ownership members must be objects with tables/figures lists"
        )
    if reporting_contract != _reporting_contract(manifest, public_summary):
        raise ValueError(
            "manuscript package reporting contract must exactly match upstream study facts"
        )
    _validate_package_bridge_claim_boundary(manuscript_package, bridge_language)
    owned_tables = [key for owner in artifact_ownership.values() for key in owner["tables"]]
    owned_figures = [key for owner in artifact_ownership.values() for key in owner["figures"]]
    if (
        len(owned_tables) != len(set(owned_tables))
        or set(owned_tables) != set(package_manifest.get("tables", {}))
        or len(owned_figures) != len(set(owned_figures))
        or set(owned_figures) != set(package_manifest.get("figures", {}))
    ):
        raise ValueError("reporting contract must own every package artifact exactly once")
    copied_figures = _copy_inline_figures(manuscript_package)
    rendered_tables: set[str] = set()
    rendered_figures: set[str] = set()

    def render_table(key: str) -> list[str]:
        if key in rendered_tables:
            raise ValueError(f"package table rendered more than once: {key}")
        rendered_tables.add(key)
        entry = package_manifest["tables"][key]
        path = _manifest_format_path(
            manuscript_package,
            entry,
            "md",
            manuscript_package / "tables" / f"{key}.md",
        )
        explanation = table_explanations.get(path.stem, table_explanations.get(key))
        if explanation is None:
            raise ValueError(f"missing table explanation: {key}")
        return [
            f"#### `{path.stem}`",
            "",
            *_explanation_block(explanation),
            "",
            _read_text(path).strip(),
            "",
        ]

    def render_figure(key: str) -> list[str]:
        if key in rendered_figures:
            raise ValueError(f"package figure rendered more than once: {key}")
        rendered_figures.add(key)
        entry = package_manifest["figures"][key]
        path = _manifest_format_path(
            manuscript_package,
            entry,
            "png",
            manuscript_package / "figures" / f"{key}.png",
        )
        explanation = figure_explanations.get(path.stem, figure_explanations.get(key))
        if explanation is None:
            raise ValueError(f"missing figure explanation: {key}")
        image_path = copied_figures.get(path.stem)
        if image_path is None:
            raise ValueError(f"missing copied PNG preview: {key}")
        return [
            f"#### {explanation['title']}",
            "",
            *_explanation_block(explanation),
            "",
            f"![{explanation['title']}]({image_path})",
            "",
            f"**Figure note.** {FIGURE_NOTES.get(key, FIGURE_NOTES.get(path.stem, ''))}",
            "",
        ]

    def render_owner(owner: str) -> list[str]:
        owned = artifact_ownership[owner]
        return [
            *(line for key in owned["tables"] for line in render_table(key)),
            *(line for key in owned["figures"] for line in render_figure(key)),
        ]

    # Preserve strict parsing of the two package-owned primary result surfaces.
    _public_task_rows(manuscript_package)
    _construct_alignment_rows(manuscript_package)
    bridge_status = bridge_summary.get("status") or manifest.get("bridge", {}).get("status") or ""
    peer_status = manifest.get("runtime", {}).get("peer_comparison_mode") or ""
    provenance = dict(manifest.get("provenance") or {})
    public_lake = dict(manifest.get("public_lake_provenance") or {})
    wrds = dict(provenance.get("wrds_export_metadata") or {})
    form_ap = dict(public_lake.get("form_ap") or {})
    canonical_status, canonical_failures = _canonical_status(manifest, construct_manifest)
    claim_maturity = dict(manifest.get("claim_maturity") or {})
    construct_claim_maturity = (
        claim_maturity.get("construct_alignment", "deferred")
        if bridge_language["status"] == "validated"
        else "deferred"
    )
    reporting_boundaries = reporting_contract["reporting_boundaries"]
    oversight = reporting_contract["feature_family_summary"]["oversight"]
    sample_proxy = reporting_boundaries["sample_proxy"]
    inspection = reporting_boundaries["pcaob_inspection_predictors"]
    partner = reporting_boundaries["partner_nonadministrative_amendment"]
    dml_evidence = reporting_contract["opacity_dml_evidence"]
    dml_maturity = reporting_contract["claim_maturity"]["opacity_dml"]
    dml_statuses = ", ".join(
        f"{outcome}={dml_evidence['status_by_outcome'][outcome]}"
        for outcome in dml_evidence["required_outcomes"]
    )
    dml_fit_outcomes = ", ".join(dml_evidence["fit_outcomes"]) or "none"
    if (
        inspection["inspection_event_joined_to_gold"] is not False
        or inspection["model_eligible_features"] != []
    ):
        raise ValueError("reporting contract cannot present PCAOB inspections as predictors")

    lines = [
        "---",
        "hide:",
        "  - navigation",
        "---",
        "",
        "# Results and Discussion",
        "",
        f"_Generated by `just snapshot` from `{study_rel}` at `{generated_at}`._",
        "",
        "## Connection to Paper Plan",
        "",
        "This page is the artifact-backed Results and Discussion companion to "
        "`docs/paper_plan.md`. The paper plan defines the research question, "
        "Materials and Methods, metric choices, and expected experiments; this "
        "snapshot reports the realized outcomes from those experiments using the "
        "current study artifacts.",
        "",
        "The structure below follows the planned experiment sequence: benchmark "
        "timing, concept drift, opacity, public-cascade construction, public-cascade "
        "prediction, and benchmark-public construct overlap. Each package table and "
        "figure is rendered once in the experiment that owns it.",
        "",
        "When using this page for manuscript prose, read it as an interpretation "
        "guide rather than a model leaderboard.",
        bridge_language["headline_guidance"],
        "Alternative windows and exploratory maxima remain diagnostics; the sole "
        "headline public specification is `all + expanding`.",
        "",
        "## Results Overview",
        "",
        "- **Research question.** Can filing-origin public SEC/PCAOB information predict "
        "whether an issuer later enters observable public review-and-correction channels, "
        "and how does this public reporting-risk construct relate to, but differ from, "
        "the detected-misstatement benchmark?",
        "",
        "- **Data.** The workflow combines the `gvkey x data_year` "
        "detected-misstatement benchmark, the public SEC/PCAOB lake, the gold "
        "`issuer_origin_panel` and `filing_origin_panel`, and "
        + bridge_language["overview_data"]
        + ".",
        "",
        "- **Models.** The core public cascade uses XGBoost over metadata, XBRL, "
        "auditor, oversight, visibility/history, and all-feature sets. "
        "Note/disclosure-breadth variables enter `all` without a standalone ablation. "
        "Peer-compatible "
        "Dechow, Perols, Bao, and Bertomeu-style suites are included when the "
        "peer-enabled study directory is present.",
        "",
        "- **Metrics.** The common metric vocabulary is PR-AUC relative to prevalence, "
        "ROC-AUC, Brier, Brier Skill Score, ECE, top-k precision, top-decile lift, "
        "and Bao-style top-fraction precision, sensitivity, specificity, BAC, and NDCG.",
        "",
        "- **Bridge boundary.** " + bridge_language["overview_boundary"],
        "",
        "- **Bounded contribution.** The study develops a filing-origin measurement of "
        "public reporting-risk states and evaluates prevalence-aware ranking. It does not "
        "identify hidden misconduct, causal regulatory effects, or same-estimand "
        "superiority over detected-misstatement studies.",
        "",
        "## Results for Experiment 1: Label Observability and Detection Timing",
        "",
        "This experiment reads detected-misstatement benchmark performance as an "
        "observability diagnostic rather than a hidden-misconduct detection result.",
        "",
        *render_owner("experiment_1"),
        "### Detected-Misstatement Peer Fit and Skip Status",
        "",
        _table(
            ["Status", "Reason", "Rows"],
            _status_count_rows(study_dir / "peer_comparison" / "peer_task_status.csv"),
        ),
        "",
        "### Detected-Misstatement Benchmark Panel",
        "",
        _table(["Field", "Value"], _benchmark_panel_rows(study_dir)),
        "",
        "### Full Window Summary",
        "",
        _table(
            [
                "Label mode",
                "Window",
                "PR-AUC",
                "ROC-AUC",
                "Brier Skill Score",
                "ECE",
                "Top-100 precision",
                "Top-decile precision",
            ],
            _benchmark_window_rows(study_dir),
        ),
        "",
        "### Interpretation",
        "",
        "These outcomes show how much the detected-misstatement benchmark depends on "
        "label-timing assumptions and retained-positive coverage. The discussion should "
        "treat timing-sensitive performance as evidence about observability, not as a "
        "direct estimate of hidden misconduct.",
        "",
        "## Results for Experiment 2: Concept Drift and Model Shelf-Life",
        "",
        "This experiment compares rolling and expanding windows and checks whether "
        "feature-family importance shifts around candidate regime breaks.",
        "",
        "### Strongest Structural-Break Diagnostics",
        "",
        _table(
            ["Window", "Label mode", "Feature family", "Break year", "F-stat", "p-value"],
            _structural_break_rows(study_dir),
        ),
        "",
        "### Mean Feature-Family Importance",
        "",
        _table(
            ["Label mode", "Feature family", "Mean importance share"],
            _feature_importance_rows(study_dir),
        ),
        "",
        "### Interpretation",
        "",
        "These tables translate the paper-plan shelf-life question into realized "
        "window-level and feature-family evidence. Large window differences or "
        "breakpoint rows should be read as model-maintenance evidence rather than "
        "causal regime-shift proof.",
        "",
        "## Results for Experiment 3: Opacity and Public Review/Correction Risk",
        "",
        "The opacity analysis reports adjusted associations from DML partially linear "
        "regressions. These estimates are not causal effects.",
        "",
        *render_owner("experiment_3"),
        "### Interpretation",
        "",
        "The DML rows report adjusted association between filing-origin opacity and "
        "later public review/correction outcomes. They distinguish source-availability "
        "and missingness diagnostics from silent-imputation claims. Opacity DML is an "
        "adjusted-association diagnostic only when at least one required outcome is fitted. "
        "Required-outcome "
        f"statuses are {dml_statuses}; fitted outcomes are {dml_fit_outcomes}; aggregate "
        f"maturity is `{dml_maturity}`. "
        + (
            "With at least one fitted required outcome, opacity DML is an adjusted-association "
            "diagnostic only."
            if dml_maturity == "diagnostic"
            else "All-skipped or disabled required outcomes leave the analysis deferred."
        ),
        "",
        "## Results for Experiment 4: Public Cascade Construction",
        "",
        "This experiment validates whether public SEC/PCAOB data can support the "
        "filing-origin review-and-correction measurement surface.",
        "",
        *render_owner("experiment_4"),
        "### Public Cascade Readiness",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Main sample rows", _fmt(public_summary.get("n_rows"))],
                ["Fiscal-year span", "-".join(map(str, public_summary.get("sample_years", [])))],
                [
                    "Sample proxy",
                    "10-K/10-K/A with no observed same-year FPI-form proxy; validates neither "
                    "FPI status, domicile, nor US GAAP",
                ],
                ["Task positive counts", _code(public_task_positive_counts)],
                ["Task exclusion counts", _code(public_task_exclusion_counts)],
                ["Zero-positive tasks", _code(zero_positive_tasks or "none")],
                ["Task status counts", _code(public_summary.get("task_status_counts"))],
                ["Readiness level", _code(public_summary.get("cascade_readiness_level"))],
            ],
        ),
        "",
        "### Public Cascade Fit and Skip Status",
        "",
        _table(
            ["Status", "Reason", "Rows"],
            _status_count_rows(study_dir / "public_cascade" / "public_cascade_task_status.csv"),
        ),
        "",
        "### Interpretation",
        "",
        "Construction results document whether the public lake has enough coverage, "
        "nonzero positive labels, and feature-family availability to support the "
        "planned public-cascade experiments.",
        "",
        "## Results for Experiment 5: Public Cascade Prediction",
        "",
        "This experiment estimates the filing-origin public reporting-risk state and "
        "compares the revision-frozen `all + expanding` headline with feature-family, "
        "window, calibration, selection, and peer-transfer sensitivity evidence.",
        "",
        *render_owner("experiment_5"),
        "### Public Peer Task Summary",
        "",
        _table(
            ["Task", "Metric rows", "Mean prevalence", "Mean PR-AUC", "Mean ROC-AUC"],
            _public_peer_task_rows(
                study_dir / "public_peer_comparison" / "public_model_family_metrics.csv"
            ),
        ),
        "",
        "### Public Peer Fit and Skip Status",
        "",
        _table(
            ["Status", "Reason", "Rows"],
            _status_count_rows(
                study_dir / "public_peer_comparison" / "public_model_family_task_status.csv"
            ),
        ),
        "",
        "### Interpretation",
        "",
        "Prediction results should be read within each label, prevalence, feature "
        "family, training window, and model-family mapping. Public peer rows provide "
        "model-language transfer evidence, not same-estimand superiority over the "
        "detected-misstatement literature. Alternative configurations remain sensitivity "
        "evidence rather than headline selections.",
        "",
        "## Results for Experiment 6: Detected-Misstatement Benchmark and Public Cascade Overlap",
        "",
        bridge_language["experiment_intro"],
        "",
        *render_owner("experiment_6"),
        bridge_language["primary_alignment_interpretation"],
        "",
        "### Exploratory maxima (post-hoc)",
        "",
        "These exploratory, post-hoc maxima summarize the searched raw alignment grids. "
        "They disclose search-universe size and model-selection spread but never replace "
        "the generated Table 9 primary rows.",
        "",
        _table(
            [
                "Direction",
                "Search-universe rows",
                "Maximum-row keys",
                "Maximum lift",
                "Primary lift",
                "max_minus_primary",
            ],
            _exploratory_maxima_rows(study_dir, manuscript_package, construct_manifest),
        ),
        "",
        bridge_language["contingency"],
        "",
        "### Aggregation Sensitivity",
        "",
        _table(
            [
                "Public label",
                "Bridge tier",
                "Aggregation rule",
                "Rows",
                "Pre-agg rate",
                "Post-agg rate",
                "Rate delta",
                "Sensitive",
            ],
            _simple_csv_rows(
                study_dir / "construct_overlap" / "aggregation_sensitivity.csv",
                [
                    "public_label",
                    "bridge_tier",
                    "aggregation_rule",
                    "rows",
                    "pre_agg_pos_rate",
                    "post_agg_pos_rate",
                    "pos_rate_delta",
                    "aggregation_sensitive",
                ],
            ),
        ),
        "",
        "### Benchmark-Positive Public-Label Co-occurrence",
        "",
        _table(
            [
                "Pattern",
                "Comment",
                "Amendment",
                "8-K 4.02",
                "Benchmark positives",
                "Share",
                "Display count",
            ],
            _simple_csv_rows(
                study_dir
                / "construct_overlap"
                / "benchmark_positive_public_label_cooccurrence.csv",
                [
                    "label_pattern",
                    "label_comment_thread_365",
                    "label_amendment_365",
                    "label_8k_402_365",
                    "n_benchmark_positives",
                    "pct_of_benchmark_positives",
                    "display_count",
                ],
            ),
        ),
        "",
        "### Event-Time Concentration",
        "",
        _table(
            [
                "Relative year",
                "Public label",
                "Benchmark pos rows",
                "Benchmark neg rows",
                "Rate if benchmark pos",
                "Rate if benchmark neg",
                "Difference",
                "Balanced window",
            ],
            _event_time_rows(study_dir),
        ),
        "",
        "### Interpretation",
        "",
        bridge_language["experiment_close"],
        "",
        "## Discussion",
        "",
        bridge_language["key_reading"],
        "",
        "### Answers to the research questions",
        "",
        "- Public task results support a prevalence-aware ranking claim for three "
        "public cascade labels, but calibration diagnostics keep the interpretation "
        "to ranking and prioritization.",
        bridge_language["discussion_relation"],
        bridge_language["discussion_reciprocal"],
        "- Selection-profile rows show that public comment-thread outcomes are "
        "partly public-scrutiny states, not a clean issuer-risk-only label.",
        "- " + bridge_language["discussion_answer"],
        "",
        "### Comparison with prior literature",
        "",
        "The detected-misstatement and public-label peer suites align model-family and "
        "metric language with prior accounting prediction work. They are transferred "
        "family diagnostics, not original-sample replications or same-estimand leaderboard "
        "comparisons.",
        "",
        "### Accounting and institutional interpretation",
        "",
        "The public outcomes capture observable review, correction, and filing-friction "
        "states. The accounting contribution is therefore a filing-origin measurement and "
        "prioritization design, with machine learning serving as measurement infrastructure.",
        "",
        "### Selection and visibility",
        "",
        "Comment-thread and correction labels are partly selected by issuer visibility, "
        "filing history, source availability, and public scrutiny. Selection-profile and "
        "opacity rows describe those boundaries without claiming a causal selection correction.",
        "",
        f"`{oversight['display_name']}` means `prior_filing_count`, not PCAOB inspection. "
        f"`{sample_proxy['artifact_field']}` means "
        f"`{sample_proxy['display_name']}` and validates neither FPI status, domicile, nor "
        "US GAAP. PCAOB inspection archives are provenance inputs; inspection events are "
        "not joined to Gold, and there are no model-eligible inspection features.",
        "",
        f"Partner nonadministrative-amendment facts use the `{partner['scope']}`: "
        f"{partner['rows_evaluated']} rows evaluated, {partner['nonmissing_rows']} nonmissing, "
        f"{partner['nonzero_rows']} nonzero, range [{partner['minimum']}, {partner['maximum']}], "
        f"is_constant_zero={str(partner['is_constant_zero']).lower()}, and "
        "equality to Item 4.02 is "
        f"{str(partner['total_equals_item_402_for_all_rows']).lower()} "
        f"across {partner['total_equals_item_402_rows']} rows.",
        "",
        "### Generalizability",
        "",
        "Public-cascade findings generalize to the documented fiscal-year, filing-origin, "
        "and observability frame. " + bridge_language["generalizability"],
        "",
        "### Limitations and future work",
        "",
        "- The evidence supports measurement and decision-useful ranking claims, not causal "
        "proof of hidden misconduct.",
        "- Comment letters are public scrutiny signals, not the complete SEC review universe.",
        "- Negative Brier Skill Score or large ECE remains evidence against deployment-ready "
        "probability rules.",
        "- External temporal validation and identified selection corrections remain future "
        "work rather than current findings.",
        "",
        "### Claim ledger",
        "",
        "The controlled categories are `reportable`, `supporting`, `diagnostic`, and "
        "`deferred`; no headline is promoted from a raw maximum.",
        "",
        _table(
            ["Claim", "Evidence", "Category", "Boundary"],
            [
                [
                    "Filing-origin public information ranks later public review-and-correction labels.",
                    "Generated Table 3, annual fold support, and Figure 1.",
                    _code(claim_maturity.get("public_prediction", "deferred")),
                    "Ranking evidence relative to prevalence, not calibrated deployment.",
                ],
                [
                    "Feature and training-window patterns qualify the frozen public specification.",
                    "Generated Tables 4 and 14 plus Figure 2.",
                    _code(claim_maturity.get("feature_and_window_sensitivity", "deferred")),
                    "Information-set evidence, not mechanism or XBRL dominance.",
                ],
                [
                    bridge_language["claim_text"],
                    bridge_language["claim_evidence"],
                    _code(construct_claim_maturity),
                    "Conditional on bridge tier and covered sample.",
                ],
                [
                    "Opacity/missingness has adjusted-association evidence for public labels.",
                    "DML adjusted-association rows.",
                    _code(claim_maturity.get("opacity_dml", "deferred")),
                    "Null or weak rows cannot support strategic-silence claims.",
                ],
                [
                    "Exploratory maximum lifts describe the searched alignment grid.",
                    "Separately labeled post-hoc maximum table and search-universe counts.",
                    _code("diagnostic"),
                    "Never substitutes for the declared primary alignment rows.",
                ],
                [
                    "The models identify hidden misconduct or causal regulatory effects.",
                    "No current artifact identifies either estimand.",
                    _code("deferred"),
                    "Requires a different design and evidence base.",
                ],
            ],
        ),
        "",
        "## Reproducibility and Provenance",
        "",
        *render_owner("reproducibility"),
        "### Run and package identity",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Artifact generation time", _code(manifest.get("generated_at_utc"))],
                ["Snapshot generation time", _code(generated_at)],
                ["Snapshot mode", _code("partial" if allow_partial else "full")],
                ["Study commit", _code(manifest.get("repo_commit"))],
                ["Git dirty", _code(str(manifest.get("git_dirty")))],
                ["Package schema", _code(package_manifest.get("schema_version"))],
                ["Package study commit", _code(package_manifest.get("study_commit"))],
                [
                    "Package study-manifest hash",
                    _code(package_manifest.get("study_manifest_sha256")),
                ],
                ["Config hash", _code(provenance.get("config_hash"))],
                ["Input hash", _code(provenance.get("input_hash"))],
                ["uv.lock hash", _code(provenance.get("uv_lock_hash"))],
                ["Public-data as-of date", _code(public_lake.get("as_of_date"))],
                ["Public-lake fresh build", _code(str(public_lake.get("fresh_build")))],
                ["Public-lake commit", _code(public_lake.get("commit_sha"))],
                ["Public-lake Git dirty", _code(str(public_lake.get("git_dirty")))],
                ["Public-lake config hash", _code(public_lake.get("config_hash"))],
                ["Public-lake input hash", _code(public_lake.get("input_hash"))],
                ["Public-lake uv.lock hash", _code(public_lake.get("uv_lock_hash"))],
                ["Form AP source kind", _code(form_ap.get("source_kind"))],
                ["Form AP archive hash", _code(form_ap.get("archive_sha256"))],
                ["Form AP member", _code(form_ap.get("member"))],
                ["Form AP member hash", _code(form_ap.get("member_sha256"))],
                ["WRDS source", _code(_summarize_wrds_sources(wrds.get("source_values")))],
                ["WRDS version", _code(wrds.get("source_version_values"))],
                ["WRDS extraction time", _code(wrds.get("extracted_at_values"))],
                ["WRDS hash", _code(wrds.get("sha256"))],
                ["Canonical status", _code(canonical_status)],
                [
                    "Canonical predicate failures",
                    "; ".join(canonical_failures) if canonical_failures else _code("none"),
                ],
                [
                    "Public-lake final-report schema",
                    _code(public_lake_report.get("schema_version")),
                ],
                ["Peer comparison mode", _code(peer_status)],
                ["Bridge status", _code(bridge_status)],
                ["Construct-overlap validation tier", _code(validation_tier)],
            ],
        ),
        "",
        "### Source roles and hashes",
        "",
        "Local input paths are omitted; stable roles, availability, and content hashes "
        "identify the evidence inputs.",
        "",
        _table(
            ["Source role", "Available", "SHA-256"],
            _source_role_rows(resolved_inputs),
        ),
        "",
        "### Claim maturity",
        "",
        _table(
            ["Claim", "Status"],
            _claim_maturity_rows(manifest, bridge_language),
        ),
        "",
    ]
    if rendered_tables != set(package_manifest["tables"]) or rendered_figures != set(
        package_manifest["figures"]
    ):
        raise ValueError("results snapshot did not render every package artifact exactly once")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--study-dir",
        default=ARTIFACTS_DIR / "full_with_peer",
        type=Path,
        help="Completed study artifact directory to summarize.",
    )
    parser.add_argument(
        "--docs-file",
        default=DOCS_DIR / "results_snapshot.md",
        type=Path,
        help="Markdown file to refresh.",
    )
    parser.add_argument(
        "--manuscript-package",
        default=ARTIFACTS_DIR / "manuscript_package",
        type=Path,
        help="Generated manuscript package whose tables and figures own snapshot displays.",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow a non-peer study directory and mark missing peer outputs in the docs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    study_dir = _resolve_repo_path(args.study_dir)
    docs_file = _resolve_repo_path(args.docs_file)
    manuscript_package = _resolve_repo_path(args.manuscript_package)
    missing = _missing_artifacts(study_dir, allow_partial=args.allow_partial)
    if missing:
        missing_list = "\n".join(f"- {_rel(path)}" for path in missing)
        mode = "partial" if args.allow_partial else "full peer-enabled"
        raise SystemExit(
            f"Cannot refresh {mode} results snapshot; missing required artifacts:\n"
            f"{missing_list}\n\n"
            "Run the peer-enabled study first, or pass --allow-partial for the current "
            "core study state."
        )

    docs_file.parent.mkdir(parents=True, exist_ok=True)
    docs_file.write_text(
        build_snapshot(
            study_dir,
            manuscript_package=manuscript_package,
            allow_partial=args.allow_partial,
        ),
        encoding="utf-8",
    )
    print(f"Refreshed {_rel(docs_file)} from {_rel(study_dir)}")


if __name__ == "__main__":
    main()
