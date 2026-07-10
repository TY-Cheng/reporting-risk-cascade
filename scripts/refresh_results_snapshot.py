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


CANONICAL_PUBLIC_DATA_AS_OF_DATE = "2026-07-06"
INPUT_SOURCE_ROLES = [
    "Detected-misstatement benchmark input",
    "Public issuer dimension input",
    "Public issuer-origin panel input",
    "CIK-GVKEY bridge input",
    "Public-lake run metadata input",
    "Form AP source metadata input",
]


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
    tier = str(artifact_tier or component_tier or "none")
    if not tiers_match:
        tier = f"component={component_tier or 'none'}; manifest={artifact_tier or 'none'}"
    if tiers_match and artifact_tier == WRDS_VALIDATED_TIER:
        return {
            "tier": tier,
            "status": "validated",
            "overview_data": ("a raw-only `gvkey-CIK-year` bridge for overlap validation"),
            "overview_boundary": (
                f"Construct overlap is `{tier}` using the confirmed WRDS SEC Analytics "
                "Suite CIK-GVKEY bridge."
            ),
            "headline_guidance": (
                "Headline claims should describe filing-origin measurement, prevalence-aware "
                "ranking, and construct overlap within the stated bridge tier."
            ),
            "evidence_map_label": (
                '    B["Experiment 6<br/>raw-only bridge and construct overlap"]'
            ),
            "reading_support": (
                "The WRDS-validated bridge shows related-but-non-identical overlap, "
                "especially in severe public correction states."
            ),
            "reading_boundary": (
                "Read Item 4.02 lift with absolute precision/FDR and the broader "
                "label-contingency matrix."
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
        "evidence_map_label": (
            '    B["Experiment 6<br/>candidate bridge diagnostics; claim deferred"]'
        ),
        "reading_support": (
            f"The `{tier}` crosswalk yields diagnostic overlap rows; no cross-construct claim "
            "matures from them."
        ),
        "reading_boundary": (
            "Treat all lift, precision/FDR, and contingency rows as diagnostic; the manuscript "
            "claim is deferred pending exact raw bridge validation."
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


def _component_rows(manifest: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for name, payload in manifest.get("components", {}).items():
        if not isinstance(payload, dict):
            rows.append([name, str(payload), "", "`False`"])
            continue
        status = payload.get("status") or payload.get("run_status") or ""
        tier = payload.get("validation_tier") or ""
        artifact_declared = any(
            payload.get(field)
            for field in ("out_dir", "summary_json", "manifest", "sample_attrition_csv")
        )
        rows.append([name, _code(status), _code(tier), _code(str(artifact_declared))])
    return rows


def _source_role_rows(provenance: dict[str, Any]) -> list[list[str]]:
    records = provenance.get("input_files", [])
    if not isinstance(records, list):
        records = []
    rows = []
    for index, role in enumerate(INPUT_SOURCE_ROLES):
        record = (
            records[index] if index < len(records) and isinstance(records[index], dict) else {}
        )
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


def _public_lake_rows(report: dict[str, Any]) -> list[list[str]]:
    row_counts = report.get("row_counts", {})
    if not isinstance(row_counts, dict):
        row_counts = {}
    wanted = [
        ("Silver", "filing_dim", "normalized public filing index"),
        ("Silver", "issuer_dim", "normalized issuer dimension"),
        ("Silver", "xbrl_core_fact", "controlled XBRL core facts"),
        ("Silver", "xbrl_fact_summary", "accession-level fact coverage"),
        ("Silver", "note_summary", "Notes summary mode"),
        ("Silver", "comment_thread", "SEC comment-thread signal"),
        ("Silver", "correction_event", "amended-filing/correction signal"),
        ("Gold", "issuer_origin_panel", "annual issuer-year modeling table"),
        ("Gold", "filing_origin_panel", "filing-origin provenance table"),
    ]
    rows = []
    for layer, artifact, note in wanted:
        rows.append([layer, f"`{artifact}`", _fmt(row_counts.get(artifact)), note])
    return rows


def _best_equal_task_config(metrics: pd.DataFrame) -> pd.Series | None:
    if metrics.empty:
        return None
    required = {"feature_set", "train_window", "task", "pr_auc"}
    if not required.issubset(metrics.columns):
        return None
    headline = metrics.copy()
    task_level = (
        headline.groupby(["feature_set", "train_window", "task"], dropna=False)["pr_auc"]
        .mean()
        .reset_index()
    )
    equal_task = (
        task_level.groupby(["feature_set", "train_window"], dropna=False)["pr_auc"]
        .mean()
        .reset_index(name="mean_pr_auc")
        .sort_values("mean_pr_auc", ascending=False)
    )
    if equal_task.empty:
        return None
    return equal_task.iloc[0]


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


def _public_feature_rows(metrics: pd.DataFrame, summary: dict[str, Any]) -> list[list[str]]:
    if metrics.empty or "feature_set" not in metrics.columns:
        return []
    grouped = (
        metrics.groupby("feature_set", dropna=False)
        .agg(rows=("pr_auc", "size"), mean_pr_auc=("pr_auc", "mean"), mean_roc_auc=("roc_auc", "mean"))
        .reset_index()
        .sort_values("mean_pr_auc", ascending=False)
    )
    family = summary.get("feature_family_summary", {})
    rows = []
    for _, row in grouped.iterrows():
        feature_set = str(row["feature_set"])
        meta = family.get(feature_set, {}) if isinstance(family, dict) else {}
        rows.append(
            [
                _code(feature_set),
                _fmt(meta.get("n_features")),
                _fmt(meta.get("n_xbrl_ratio_features")),
                _fmt(meta.get("n_xbrl_coverage_features")),
                _fmt(row["mean_pr_auc"]),
                _fmt(row["mean_roc_auc"]),
                _fmt(row["rows"], digits=0),
            ]
        )
    return rows


def _public_fold_support_rows(metrics: pd.DataFrame) -> list[list[str]]:
    required = {"task", "test_year", "n_test", "positive_rate_test"}
    if metrics.empty or not required.issubset(metrics.columns):
        return []
    grouped = (
        metrics.groupby(["task", "test_year"], dropna=False)
        .agg(
            configs=("pr_auc", "size"),
            test_rows=("n_test", "first"),
            prevalence=("positive_rate_test", "mean"),
        )
        .reset_index()
    )
    grouped["positives"] = (grouped["test_rows"] * grouped["prevalence"]).round().astype("Int64")
    grouped["sparse_excluded"] = grouped["positives"].lt(10)
    rows = []
    for _, row in grouped.sort_values(["task", "test_year"]).iterrows():
        rows.append(
            [
                _code(row["task"]),
                _fmt_year(row["test_year"]),
                _fmt(row["configs"], digits=0),
                _fmt(row["test_rows"]),
                _fmt(row["positives"]),
                _fmt(row["prevalence"]),
                "Yes" if bool(row["sparse_excluded"]) else "No",
            ]
        )
    return rows


def _task_feature_family_rows(metrics: pd.DataFrame) -> list[list[str]]:
    required = {
        "task",
        "feature_set",
        "test_year",
        "positive_rate_test",
        "pr_auc",
        "roc_auc",
    }
    if metrics.empty or not required.issubset(metrics.columns):
        return []
    agg_spec = {
        "metric_rows": ("pr_auc", "size"),
        "n_folds": ("test_year", "nunique"),
        "mean_prevalence": ("positive_rate_test", "mean"),
        "mean_pr_auc": ("pr_auc", "mean"),
        "mean_roc_auc": ("roc_auc", "mean"),
    }
    if "brier_skill_score" in metrics.columns:
        agg_spec["mean_brier_skill"] = ("brier_skill_score", "mean")
    if "ece" in metrics.columns:
        agg_spec["mean_ece"] = ("ece", "mean")
    grouped = (
        metrics.groupby(["task", "feature_set"], dropna=False)
        .agg(**agg_spec)
        .reset_index()
        .sort_values(["task", "mean_pr_auc"], ascending=[True, False])
    )
    rows = []
    for _, row in grouped.iterrows():
        rows.append(
            [
                _code(row["task"]),
                _code(row["feature_set"]),
                _fmt(row["mean_prevalence"]),
                _fmt(row["mean_pr_auc"]),
                _fmt(row["mean_roc_auc"]),
                _fmt(row.get("mean_brier_skill")),
                _fmt(row.get("mean_ece")),
                _fmt(row["n_folds"], digits=0),
                _fmt(row["metric_rows"], digits=0),
            ]
        )
    return rows


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


def _benchmark_timing_rows(metrics: pd.DataFrame) -> list[list[str]]:
    if metrics.empty or not {"label_mode", "window", "pr_auc"}.issubset(metrics.columns):
        return []
    grouped = (
        metrics.groupby(["label_mode", "window"], dropna=False)
        .agg(
            pr_auc=("pr_auc", "mean"),
            roc_auc=("roc_auc", "mean"),
            top_100_precision=("top_100_precision", "mean"),
            retained_positive_share=("retained_positive_train_share", "mean"),
        )
        .reset_index()
    )
    best = grouped.sort_values("pr_auc", ascending=False).groupby("label_mode", as_index=False).head(1)
    rows = []
    for _, row in best.sort_values("pr_auc", ascending=False).iterrows():
        rows.append(
            [
                _code(row["label_mode"]),
                _code(row["window"]),
                _fmt(row["pr_auc"]),
                _fmt(row["roc_auc"]),
                _fmt(row["top_100_precision"]),
                _fmt(row["retained_positive_share"]),
            ]
        )
    return rows


def _peer_model_rows(path: Path) -> list[list[str]]:
    metrics = _read_csv(path)
    if metrics.empty:
        return []
    model_col = "peer_model_id" if "peer_model_id" in metrics.columns else "model_id"
    if model_col not in metrics.columns:
        return []
    agg_spec = {
        "rows": ("pr_auc", "size"),
        "mean_pr_auc": ("pr_auc", "mean"),
        "mean_roc_auc": ("roc_auc", "mean"),
        "max_pr_auc": ("pr_auc", "max"),
    }
    if "brier" in metrics.columns:
        agg_spec["mean_brier"] = ("brier", "mean")
    grouped = metrics.groupby(model_col, dropna=False).agg(**agg_spec).reset_index()
    rows = []
    for _, row in grouped.sort_values("mean_pr_auc", ascending=False).iterrows():
        rows.append(
            [
                _code(row[model_col]),
                _fmt(row["rows"], digits=0),
                _fmt(row["mean_pr_auc"]),
                _fmt(row["mean_roc_auc"]),
                _fmt(row["max_pr_auc"]),
                _fmt(row.get("mean_brier")),
            ]
        )
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
            max_pr_auc=("pr_auc", "max"),
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
                _fmt(row["max_pr_auc"]),
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
    for _, row in grouped.sort_values(["label_mode", "pr_auc"], ascending=[True, False]).iterrows():
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
    if frame.empty or not {"window", "label_mode", "family", "break_year", "f_stat", "p_value"}.issubset(frame.columns):
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
                _fmt(row["p_value"]),
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
        rows.append([_code(row["label_mode"]), _code(row["family"]), _fmt(row["importance_share"])])
    return rows


def _opacity_rows(study_dir: Path) -> list[list[str]]:
    path = study_dir / "opacity_validation_refresh" / "opacity_diagnostics_summary.csv"
    if not path.exists():
        path = study_dir / "public_cascade" / "public_opacity_dml.csv"
    frame = _read_csv(path)
    if frame.empty:
        return []
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _code(row.get("outcome")),
                _fmt(row.get("n_obs")),
                _fmt(row.get("prevalence")),
                _fmt(row.get("mean_treatment")),
                _fmt(row.get("coef")),
                _fmt(row.get("std_err")),
                _fmt(row.get("p_value")),
                _code(row.get("status")),
            ]
        )
    return rows


def _simple_csv_rows(path: Path, columns: list[str], *, max_rows: int | None = None) -> list[list[str]]:
    frame = _read_csv(path)
    if frame.empty or not set(columns).issubset(frame.columns):
        return []
    if max_rows is not None:
        frame = frame.head(max_rows)
    rows = []
    for _, row in frame.iterrows():
        rows.append([_fmt(row.get(col)) if col not in {"public_label", "bridge_tier", "label_pattern", "metric_status"} else _code(row.get(col)) for col in columns])
    return rows


def _overlap_sample_flow_rows(study_dir: Path) -> list[list[str]]:
    return _simple_csv_rows(
        study_dir / "construct_overlap" / "overlap_sample_flow.csv",
        ["bridge_tier", "rows", "benchmark_positives"],
    )


def _label_contingency_rows(study_dir: Path) -> list[list[str]]:
    frame = _read_csv(study_dir / "construct_overlap" / "label_contingency_lift.csv")
    if frame.empty:
        return []
    columns = [
        "public_label",
        "bridge_tier",
        "n",
        "benchmark_positive_rows",
        "public_positive_rows",
        "both_positive_rows",
        "benchmark_prevalence",
        "public_prevalence",
        "public_rate_given_benchmark_pos",
        "benchmark_rate_given_public_pos",
        "lift_public_given_benchmark",
        "lift_benchmark_given_public",
    ]
    if not set(columns).issubset(frame.columns):
        return []
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _code(row["public_label"]),
                _code(row["bridge_tier"]),
                _fmt(row["n"]),
                _fmt(row["benchmark_positive_rows"]),
                _fmt(row["public_positive_rows"]),
                _fmt(row["both_positive_rows"]),
                _fmt(row["benchmark_prevalence"]),
                _fmt(row["public_prevalence"]),
                _fmt(row["public_rate_given_benchmark_pos"]),
                _fmt(row["benchmark_rate_given_public_pos"]),
                _fmt(row["lift_public_given_benchmark"]),
                _fmt(row["lift_benchmark_given_public"]),
            ]
        )
    return rows


def _selection_profile_rows(manuscript_package: Path) -> list[list[str]]:
    frame = _read_csv(manuscript_package / "tables" / "table_17_selection_profile.csv")
    required = {
        "Stratum",
        "Group",
        "Issuer_Years",
        "Comment_Rate",
        "Amendment_Rate",
        "Item_4_02_Rate",
    }
    if frame.empty or not required.issubset(frame.columns):
        return []
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                str(row["Stratum"]),
                str(row["Group"]),
                _fmt(row["Issuer_Years"]),
                _fmt(row["Comment_Rate"]),
                _fmt(row["Amendment_Rate"]),
                _fmt(row["Item_4_02_Rate"]),
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


def _manifest_inventory(root: Path) -> list[str]:
    if not root.exists():
        return [f"- `{_rel(root)}` (missing)"]
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != ".DS_Store" and "__pycache__" not in path.parts
    ]
    return [f"- `{_rel(path)}`" for path in files]


def _table_figure_rows(package_dir: Path) -> list[list[str]]:
    rows = []
    for kind, subdir in [("Table", "tables"), ("Figure", "figures")]:
        root = package_dir / subdir
        if not root.exists():
            rows.append([kind, _code(subdir), "missing"])
            continue
        files = sorted(path for path in root.iterdir() if path.is_file() and path.name != ".DS_Store")
        for path in files:
            rows.append([kind, _code(path.name), _rel(path)])
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


def _ars_explanation_block(explanation: dict[str, str]) -> list[str]:
    return [
        f"- **ARS claim.** {explanation['claim']}",
        f"- **Evidence.** {explanation['evidence']}",
        f"- **Boundary.** {explanation['boundary']}",
    ]


def _inline_figure_gallery(
    package_dir: Path,
    explanations: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    explanations = explanations or FIGURE_EXPLANATIONS
    figure_paths = _copy_inline_figures(package_dir)
    manifest = _read_json(package_dir / "manifest.json")
    figure_keys = sorted((manifest.get("figures") or {}).keys()) or sorted(figure_paths)
    lines = [
        "### Inline Figure Gallery",
        "",
        "The figures below are rendered directly from the current manuscript package "
        "PNG assets. The adjacent PDF files remain the LaTeX manuscript copies.",
        "",
    ]
    for key in figure_keys:
        explanation = explanations.get(
            key,
            {
                "title": key.replace("_", " ").title(),
                "claim": "This figure is part of the generated manuscript evidence package.",
                "evidence": "The figure file is read from the current manuscript package.",
                "boundary": "Interpretation should follow the surrounding results section and claim-strength ledger.",
            },
        )
        image_path = figure_paths.get(key)
        pdf_path = package_dir / "figures" / f"{key}.pdf"
        png_path = package_dir / "figures" / f"{key}.png"
        lines.extend(
            [
                f"#### {explanation['title']}",
                "",
                *(_ars_explanation_block(explanation)),
                "",
                f"- **Source PNG.** `{_rel(png_path)}`",
                f"- **Manuscript PDF.** `{_rel(pdf_path)}`",
                "",
            ]
        )
        if image_path:
            lines.extend([f"![{explanation['title']}]({image_path})", ""])
        else:
            lines.extend([f"_Missing PNG preview for `{key}`._", ""])
    return lines


def _inline_table_gallery(
    package_dir: Path,
    explanations: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    explanations = explanations or TABLE_EXPLANATIONS
    manifest = _read_json(package_dir / "manifest.json")
    table_keys = sorted((manifest.get("tables") or {}).keys())
    if not table_keys:
        table_keys = [path.stem for path in sorted((package_dir / "tables").glob("table_*.md"))]

    lines = [
        "### Inline Table Gallery",
        "",
        "The tables below are expanded directly from the current manuscript package "
        "Markdown table files. CSV and TeX copies remain listed in the provenance index.",
        "",
    ]
    for key in table_keys:
        md_path = package_dir / "tables" / f"{key}.md"
        explanation = explanations.get(
            key,
            {
                "claim": "This table is part of the generated manuscript evidence package.",
                "evidence": "The table is read from the current manuscript package Markdown output.",
                "boundary": "Interpretation should follow the surrounding results section and claim-strength ledger.",
            },
        )
        lines.extend(
            [
                f"#### `{key}`",
                "",
                *(_ars_explanation_block(explanation)),
                "",
                f"- **Source table.** `{_rel(md_path)}`",
                "",
            ]
        )
        table_md = _read_text(md_path).strip()
        if table_md:
            lines.extend([table_md, ""])
        else:
            lines.extend([f"_Missing Markdown table for `{key}`._", ""])
    return lines


def _bridge_coverage_rows(path: Path) -> list[list[str]]:
    coverage = _read_csv(path)
    if coverage.empty or not {"metric", "value"}.issubset(coverage.columns):
        return []
    wanted = [
        "raw_rows",
        "raw_firms",
        "matched_raw_rows",
        "matched_raw_firms",
        "row_coverage_rate",
        "firm_coverage_rate",
        "raw_positive_rows",
        "matched_positive_rows",
    ]
    values = dict(zip(coverage["metric"], coverage["value"], strict=False))
    return [[metric, _fmt(values.get(metric))] for metric in wanted if metric in values]


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


def _artifact_index(study_dir: Path) -> list[str]:
    wanted = [
        "study_summary.md",
        "study_run_manifest.json",
        "benchmark/benchmark_summary.md",
        "benchmark/rolling_metrics.csv",
        "public_cascade/public_cascade_summary.md",
        "public_cascade/public_cascade_metrics.csv",
        "peer_comparison/peer_comparison_summary.md",
        "peer_comparison/detected_misstatement_model_family_metrics.csv",
        "public_peer_comparison/public_model_family_summary.md",
        "public_peer_comparison/public_model_family_metrics.csv",
        "bridge_probe/bridge_probe_summary.json",
        "bridge_probe/coverage_report.csv",
        "construct_overlap/construct_overlap_summary.md",
        "construct_overlap/public_score_benchmark_ranking.csv",
        "construct_overlap/reciprocal_alignment.csv",
        "opacity_validation_refresh/opacity_diagnostics_summary.csv",
    ]
    lines = []
    for rel_path in wanted:
        path = study_dir / rel_path
        marker = "present" if path.exists() else "missing"
        lines.append(f"- `{_rel(path)}` ({marker})")
    return lines


def build_snapshot(
    study_dir: Path,
    *,
    manuscript_package: Path | None = None,
    allow_partial: bool,
) -> str:
    manuscript_package = manuscript_package or ARTIFACTS_DIR / "manuscript_package"
    manifest = _read_json(study_dir / "study_run_manifest.json")
    public_summary = _read_json(study_dir / "public_cascade" / "public_cascade_summary.json")
    bridge_summary = _read_json(study_dir / "bridge_probe" / "bridge_probe_summary.json")
    construct_manifest = _read_json(study_dir / "construct_overlap" / "construct_overlap_manifest.json")
    public_lake_report = _latest_public_lake_report()
    public_metrics = _read_csv(study_dir / "public_cascade" / "public_cascade_metrics.csv")
    benchmark_metrics = _read_csv(study_dir / "benchmark" / "rolling_metrics.csv")
    public_task_positive_counts = public_summary.get("task_positive_counts") or {}
    public_task_exclusion_counts = public_summary.get("task_exclusion_counts") or {}
    zero_positive_tasks = public_summary.get("zero_positive_tasks") or []

    best_public = _best_equal_task_config(public_metrics)
    if public_summary.get("best_feature_set") and public_summary.get("best_train_window"):
        best_public_text = (
            f"`{public_summary['best_feature_set']} + {public_summary['best_train_window']}` "
            f"with reported mean PR-AUC `{_fmt(public_summary.get('best_mean_pr_auc'))}`"
        )
    elif best_public is not None:
        best_public_text = (
            f"`{best_public['feature_set']} + {best_public['train_window']}` "
            f"with equal-task mean PR-AUC `{_fmt(best_public['mean_pr_auc'])}`"
        )
    else:
        best_public_text = "not available"

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    study_rel = _rel(study_dir)
    bridge_language = _bridge_language(manifest, construct_manifest)
    validation_tier = bridge_language["tier"]
    figure_explanations, table_explanations = _bridge_artifact_explanations(bridge_language)
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
        "prediction, and benchmark-public construct overlap. Tables and figures are "
        "rendered directly at the end and also indexed so manuscript claims can be "
        "traced to concrete files.",
        "",
        "When using this page for manuscript prose, read it as an interpretation "
        "guide rather than a model leaderboard.",
        bridge_language["headline_guidance"],
        "Single best windows, maximum PR-AUC rows, "
        "and severe-tail lifts are diagnostics unless the manuscript gives a "
        "pre-specified reason to elevate them.",
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
        "- **Highest equal-task public-cascade row.** " + best_public_text + ". "
        "Use this as a descriptive configuration diagnostic, not as a model-selection "
        "headline.",
        "",
        "- **Bridge boundary.** " + bridge_language["overview_boundary"],
        "",
        "- **Sellable claim.** The strongest current framing is a measurement-and-ranking "
        "paper on filing-origin public reporting-risk states. It does not support causal "
        "claims, hidden-misconduct occurrence claims, or same-estimand performance "
        "rankings over prior detected-misstatement papers.",
        "",
        "## Reproducibility Metadata",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Artifact generation time", _code(manifest.get("generated_at_utc"))],
                ["Snapshot generation time", _code(generated_at)],
                ["Snapshot mode", _code("partial" if allow_partial else "full")],
                ["Study commit", _code(manifest.get("repo_commit"))],
                ["Git dirty", _code(str(manifest.get("git_dirty")))],
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
                ["WRDS source", _code(wrds.get("source_values"))],
                ["WRDS version", _code(wrds.get("source_version_values"))],
                ["WRDS extraction time", _code(wrds.get("extracted_at_values"))],
                ["WRDS hash", _code(wrds.get("sha256"))],
                ["Canonical status", _code(canonical_status)],
                [
                    "Canonical predicate failures",
                    "; ".join(canonical_failures) if canonical_failures else _code("none"),
                ],
                [
                    "Public-lake report timestamp",
                    _code(public_lake_report.get("timestamp_utc")),
                ],
                ["Peer comparison mode", _code(peer_status)],
                ["Bridge status", _code(bridge_status)],
                ["Construct-overlap validation tier", _code(validation_tier)],
            ],
        ),
        "",
        "### Source roles and hashes",
        "",
        "Local input paths are intentionally omitted; stable roles, availability, and "
        "content hashes identify the evidence inputs.",
        "",
        _table(["Source role", "Available", "SHA-256"], _source_role_rows(provenance)),
        "",
        "### Component status",
        "",
        _table(
            ["Component", "Status", "Tier", "Artifact declared"],
            _component_rows(manifest),
        ),
        "",
        "### Claim maturity",
        "",
        _table(
            ["Claim", "Status"],
            _claim_maturity_rows(manifest, bridge_language),
        ),
        "",
        "### Evidence Map",
        "",
        "```mermaid",
        "flowchart LR",
        '    L["Experiment 1-2<br/>benchmark timing and drift"]',
        '    O["Experiment 3<br/>opacity and public labels"]',
        '    P["Experiment 4-5<br/>public cascade construction and prediction"]',
        bridge_language["evidence_map_label"],
        '    D["Discussion<br/>claim boundary and manuscript tables/figures"]',
        "    L --> D",
        "    O --> D",
        "    P --> D",
        "    B --> D",
        "```",
        "",
        "### Manuscript Reading Guide",
        "",
        _table(
            ["Evidence block", "What it supports", "How to bound the claim"],
            [
                [
                    "Public task metrics and Figure 1",
                    "Filing-origin public information ranks later public review-and-correction labels above task prevalence.",
                    "Annual-fold intervals describe evaluation-period dispersion; weak calibration rules out deployment-ready probability claims.",
                ],
                [
                    "Feature-family metrics and Figure 2",
                    "Feature fusion helps, while metadata remains a strong public information set.",
                    "Treat feature families as information-set evidence, not structural mechanisms or source dominance.",
                ],
                [
                    "Peer-compatible model-family tables and Figures 3-4",
                    "Detected-misstatement and public-label suites share metric language and transferable model families.",
                    "These rows are not original-study replications and do not establish same-estimand superiority.",
                ],
                [
                    "Construct-overlap tables and Figure 5",
                    bridge_language["reading_support"],
                    bridge_language["reading_boundary"],
                ],
                [
                    "Selection profile and DML opacity diagnostics",
                    "Public labels include selected public scrutiny and source-availability states.",
                    "The evidence is descriptive or adjusted-association evidence, not causal selection correction.",
                ],
            ],
        ),
        "",
        "## Results for Experiment 1: Label Observability and Detection Timing",
        "",
        "This experiment reads detected-misstatement benchmark performance as an "
        "observability diagnostic rather than a hidden-misconduct detection result.",
        "",
        "### Detected-Misstatement Benchmark Panel",
        "",
        _table(["Field", "Value"], _benchmark_panel_rows(study_dir)),
        "",
        "### Best Timing-Sensitivity Rows by Label Mode",
        "",
        _table(
            [
                "Label mode",
                "Best window",
                "Mean PR-AUC",
                "Mean ROC-AUC",
                "Top-100 precision",
                "Retained positive share",
            ],
            _benchmark_timing_rows(benchmark_metrics),
        ),
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
        _table(
            [
                "Outcome",
                "Rows",
                "Prevalence",
                "Mean treatment",
                "Coef",
                "Std err",
                "p-value",
                "Status",
            ],
            _opacity_rows(study_dir),
        ),
        "",
        "### Interpretation",
        "",
        "The DML rows report adjusted association between filing-origin opacity and "
        "later public review/correction outcomes. They distinguish source-availability "
        "and missingness diagnostics from silent-imputation claims, and they support "
        "discussion of measurement and risk ranking rather than causal claims about "
        "SEC or issuer behavior.",
        "",
        "## Results for Experiment 4: Public Cascade Construction",
        "",
        "This experiment validates whether public SEC/PCAOB data can support the "
        "filing-origin review-and-correction measurement surface.",
        "",
        "### Public Lake and Gold Panel Scale",
        "",
        _table(["Layer", "Artifact", "Rows", "Notes"], _public_lake_rows(public_lake_report)),
        "",
        "### Public Cascade Readiness",
        "",
        _table(
            ["Field", "Value"],
            [
                ["Main sample rows", _fmt(public_summary.get("n_rows"))],
                ["Fiscal-year span", "-".join(map(str, public_summary.get("sample_years", [])))],
                ["Domestic US GAAP only", _fmt(public_summary.get("domestic_only"))],
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
        "compares feature families and peer-compatible model families.",
        "",
        "### Public Task Metrics",
        "",
        _table(
            [
                "Task",
                "Positives",
                "Mean prevalence",
                "Mean PR-AUC",
                "Mean ROC-AUC",
                "Brier Skill",
                "ECE",
                "Folds",
                "Metric rows",
            ],
            _public_task_rows(manuscript_package),
        ),
        "",
        "These task rows are the main ranking evidence. Brier Skill Score and ECE "
        "are calibration diagnostics; negative skill or large ECE should push the "
        "manuscript toward a ranking/prioritization interpretation rather than a "
        "calibrated decision-rule interpretation.",
        "",
        "### Annual Fold Support",
        "",
        _table(
            ["Task", "Test year", "Configs", "Test rows", "Positives", "Prevalence", "Sparse excluded"],
            _public_fold_support_rows(public_metrics),
        ),
        "",
        "Fold support is reported to make sparse-label claims auditable. A task-year "
        "with fewer than 10 positives should not carry a formal interval claim; in "
        "the current artifact set, Item 4.02 remains rare but has at least 58 "
        "positives in every annual test fold.",
        "",
        "### Public Feature-Family Metrics",
        "",
        _table(
            [
                "Feature set",
                "Features",
                "XBRL ratios",
                "XBRL coverage",
                "Mean PR-AUC",
                "Mean ROC-AUC",
                "Metric rows",
            ],
            _public_feature_rows(public_metrics, public_summary),
        ),
        "",
        "This aggregate table averages across tasks, train windows, and annual folds. "
        "Use it for the broad information-set claim only; task-specific feature-family "
        "rows below are the safer source for label-by-label prose.",
        "",
        "### Task by Feature-Family Metrics",
        "",
        _table(
            [
                "Task",
                "Feature set",
                "Mean prevalence",
                "Mean PR-AUC",
                "Mean ROC-AUC",
                "Brier Skill",
                "ECE",
                "Folds",
                "Metric rows",
            ],
            _task_feature_family_rows(public_metrics),
        ),
        "",
        "The task-by-family matrix clarifies that feature-family rankings are not "
        "uniform across labels. It supports a measured feature-fusion claim, not a "
        "feature-importance-as-mechanism claim.",
        "",
        "### Selection-Aware Descriptive Profile",
        "",
        _table(
            [
                "Stratum",
                "Group",
                "Issuer-years",
                "Comment rate",
                "Amendment rate",
                "Item 4.02 rate",
            ],
            _selection_profile_rows(manuscript_package),
        ),
        "",
        "Selection-profile rows describe where public-label rates are concentrated "
        "across issuer visibility, filing-history, and public-scrutiny strata. They "
        "help interpret comment-thread prediction as selected public scrutiny plus "
        "issuer reporting-risk signals, but they are not a causal SEC-selection model.",
        "",
        "### Detected-Misstatement Peer-Compatible Literature Benchmarks",
        "",
        "These rows are present only when the peer-enabled study has run. They are "
        "model-family transfer and metric-language alignment, not exact replications "
        "of the original-paper samples.",
        "",
        _table(
            ["Model", "Metric rows", "Mean PR-AUC", "Mean ROC-AUC", "Max config PR-AUC", "Mean Brier"],
            _peer_model_rows(study_dir / "peer_comparison" / "detected_misstatement_model_family_metrics.csv"),
        ),
        "",
        "### Detected-Misstatement Peer Fit and Skip Status",
        "",
        _table(
            ["Status", "Reason", "Rows"],
            _status_count_rows(study_dir / "peer_comparison" / "peer_task_status.csv"),
        ),
        "",
        "### Public-Label Peer Transfer",
        "",
        _table(
            ["Model", "Metric rows", "Mean PR-AUC", "Mean ROC-AUC", "Max config PR-AUC", "Mean Brier"],
            _peer_model_rows(
                study_dir / "public_peer_comparison" / "public_model_family_metrics.csv"
            ),
        ),
        "",
        "### Public Peer Task Summary",
        "",
        _table(
            ["Task", "Metric rows", "Mean prevalence", "Mean PR-AUC", "Mean ROC-AUC", "Max config PR-AUC"],
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
        "detected-misstatement literature. `Max config PR-AUC` is retained as a "
        "diagnostic for model-selection optimism; it should not become a headline "
        "claim without a pre-specified selection rule or external validation.",
        "",
        "## Results for Experiment 6: Detected-Misstatement Benchmark and Public Cascade Overlap",
        "",
        bridge_language["experiment_intro"],
        "",
        "### Bridge Coverage",
        "",
        _table(
            ["Metric", "Value"],
            _bridge_coverage_rows(study_dir / "bridge_probe" / "coverage_report.csv"),
        ),
        "",
        "### Overlap Sample Flow",
        "",
        _table(["Bridge tier", "Rows", "Benchmark positives"], _overlap_sample_flow_rows(study_dir)),
        "",
        "### Declared primary construct-alignment rows",
        "",
        "Generated Table 9 is the sole owner of the two declared primary rows shown "
        "below; the snapshot does not reselect them from the raw alignment grids.",
        "",
        _table(
            [
                "Direction",
                "Model",
                "Target",
                "PR-AUC",
                "ROC-AUC",
                "Top-10% precision",
                "Top-10% FDR",
                "Top-decile lift",
                "Lift interval",
            ],
            _construct_alignment_rows(manuscript_package),
        ),
        "",
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
        "### Label Contingency and Lift",
        "",
        _table(
            [
                "Public label",
                "Bridge tier",
                "Rows",
                "Benchmark positives",
                "Public positives",
                "Both positive",
                "Benchmark rate",
                "Public rate",
                "Public rate if benchmark pos",
                "Benchmark rate if public pos",
                "Lift public given benchmark",
                "Lift benchmark given public",
            ],
            _label_contingency_rows(study_dir),
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
                study_dir / "construct_overlap" / "benchmark_positive_public_label_cooccurrence.csv",
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
        "## Tables, Figures, and Artifact Index",
        "",
        "This section is intentionally redundant with the prose results above: it "
        "renders every current manuscript-package figure and table in one place, "
        "then keeps the file index for provenance checks.",
        "",
        "### ARS Evidence Gallery",
        "",
        "Following the Academic Research Suite argument and visualization checks, "
        "each display is paired with a claim, the evidence it contributes, and the "
        "boundary that prevents over-interpretation.",
        "",
        *_inline_figure_gallery(manuscript_package, figure_explanations),
        "",
        *_inline_table_gallery(manuscript_package, table_explanations),
        "",
        "### Manuscript Package Tables and Figures",
        "",
        _table(["Kind", "File", "Path"], _table_figure_rows(manuscript_package)),
        "",
        "### Selected Artifact Index",
        "",
        "This index lists high-signal artifacts referenced by this generated snapshot.",
        "",
        *_artifact_index(study_dir),
        "",
        "### Full Study Artifact Inventory",
        "",
        *_manifest_inventory(study_dir),
        "",
    ]
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
