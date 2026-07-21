from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.build_manuscript_package import (
    PACKAGE_FIGURE_KEYS,
    PACKAGE_TABLE_KEYS,
    _construct_alignment,
    _public_opacity_dml_table,
    _public_sample_attrition_table,
    _public_task_metrics,
    _select_primary_public_metrics,
)
from scripts.monitor_public_lake import PUBLIC_LAKE_ROW_COUNT_KEYS
from src.provenance import (
    config_provenance,
    input_provenance,
    path_record,
    public_lake_provenance,
    sha256_path,
    uv_lock_provenance,
)


REQUIRED_DML_OUTCOMES = ["comment_thread", "amendment", "8k_402"]
ARTIFACT_OWNERSHIP = {
    "reproducibility": {"tables": ["table_01"], "figures": []},
    "experiment_1": {"tables": ["table_05", "table_06"], "figures": ["figure_03"]},
    "experiment_2": {"tables": [], "figures": []},
    "experiment_3": {"tables": ["table_12"], "figures": []},
    "experiment_4": {"tables": ["table_02", "table_18"], "figures": []},
    "experiment_5": {
        "tables": ["table_03", "table_04", "table_07", "table_13", "table_14", "table_17"],
        "figures": ["figure_01", "figure_02", "figure_04"],
    },
    "experiment_6": {
        "tables": ["table_08", "table_09", "table_15", "table_16"],
        "figures": ["figure_05"],
    },
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write(path: Path, payload: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload, encoding="utf-8")


def _artifact_record(path: Path, package_dir: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(package_dir).as_posix(),
        "sha256": str(sha256_path(path)),
    }


def _init_repo(repo: Path) -> str:
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "canonical-fixture@example.invalid")
    git(repo, "config", "user.name", "Canonical Fixture")
    files = {
        "src/__init__.py": "",
        "src/example.py": 'CONTACT = "Avery Example avery@example.invalid"\n',
        "src/report_collision.md": "# Canonical Results Snapshot\n",
        "config/study.yaml": "study: canonical\n",
        "config/benchmark.yaml": "benchmark: canonical\n",
        "config/public_cascade.yaml": "public: canonical\n",
        "config/public_lake.yaml": "lake: canonical\n",
        "tests/test_example.py": "def test_fixture():\n    assert True\n",
        "scripts/example.py": "print('fixture')\n",
        "scripts/verify_canonical_run.py": "VERIFIER_VERSION = 'fixture'\n",
        "README.md": (
            "# Fixture\n\n"
            "https://github.com/example-owner/fixture\n"
            "https://example-owner.github.io/fixture/\n"
        ),
        "LICENSE": "MIT License\n\nCopyright (c) 2026 Example Research Group\n",
        "pyproject.toml": (
            "[project]\n"
            'name = "fixture"\n'
            'version = "0.1.0"\n'
            'authors = [{name = "Avery Example", email = "avery@example.invalid"}]\n'
        ),
        "mkdocs.yml": (
            "site_name: Fixture\n"
            "site_url: https://example-owner.github.io/fixture/\n"
            "repo_url: https://github.com/example-owner/fixture\n"
        ),
        "justfile": "check:\n    python -m pytest\n",
        "uv.lock": 'version = 1\nrevision = 3\nrequires-python = ">=3.13"\n',
        ".python-version": "3.13\n",
        ".env.example": 'PROJECT_ROOT="/path/to/fixture"\n',
        ".gitignore": ".env\n.venv/\n",
        ".github/workflows/ci.yml": "name: fixture-ci\n",
    }
    for relative, content in files.items():
        _write(repo / relative, content)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "canonical study source")
    return git(repo, "rev-parse", "HEAD")


def _write_public_lake_inputs(root: Path, repo: Path, commit: str) -> dict[str, Path]:
    bronze = root / "bronze-arbitrary"
    payload = bronze / "form-ap" / "FirmFilings.zip"
    payload.parent.mkdir(parents=True)
    member_bytes = b"firm_id,filing_date\n1,2026-01-02\n"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("FirmFilings.csv", member_bytes)
    sidecar = payload.with_name(f"{payload.name}.meta.json")
    write_json(
        sidecar,
        {
            "source_name": "FINRA Firm Filings",
            "source_url": "https://example.invalid/FirmFilings.zip",
            "downloaded_at_utc": "2026-07-06T00:00:00+00:00",
            "sha256": sha256_path(payload),
            "size_bytes": payload.stat().st_size,
            "parser_version": "1",
            "schema_version": "1",
        },
    )
    form_ap = root / "silver" / "form_ap_source_metadata.json"
    write_json(
        form_ap,
        {
            "source_kind": "verified_zip_member",
            "archive_sha256": sha256_path(payload),
            "member": "FirmFilings.csv",
            "member_sha256": __import__("hashlib").sha256(member_bytes).hexdigest(),
        },
    )
    lake_config = repo / "config" / "public_lake.yaml"
    lake_provenance = {
        "commit_sha": commit,
        "dirty": False,
        "dirty_status": "",
        **config_provenance([lake_config]),
        **input_provenance([sidecar]),
        **uv_lock_provenance(repo),
    }
    run_metadata = root / "silver" / "public_lake_run_metadata.json"
    write_json(
        run_metadata,
        {
            "as_of_date": "2026-07-06",
            "fresh_build": True,
            "provenance": lake_provenance,
        },
    )
    panel = root / "gold" / "issuer_origin_panel.parquet"
    _write(panel, b"PAR1canonical issuer-origin panel")
    final_report = root / "silver" / "public_lake_final_report.json"
    write_json(
        final_report,
        {
            "schema_version": "public-lake-final-report-v1",
            "as_of_date": "2026-07-06",
            "public_lake_run_metadata_sha256": sha256_path(run_metadata),
            "issuer_origin_panel_sha256": sha256_path(panel),
            "row_counts": {
                key: index + 1 for index, key in enumerate(sorted(PUBLIC_LAKE_ROW_COUNT_KEYS))
            },
            "row_count_errors": {},
        },
    )
    return {
        "bronze": bronze,
        "sidecar": sidecar,
        "payload": payload,
        "form_ap": form_ap,
        "run_metadata": run_metadata,
        "panel": panel,
        "final_report": final_report,
    }


def _opacity_dml_evidence(statuses: tuple[str, str, str]) -> dict[str, Any]:
    status_by_outcome = dict(zip(REQUIRED_DML_OUTCOMES, statuses, strict=True))
    return {
        "required_outcomes": REQUIRED_DML_OUTCOMES,
        "status_by_outcome": status_by_outcome,
        "fit_outcomes": [
            outcome for outcome, status in status_by_outcome.items() if status == "fit"
        ],
        "maturity_by_outcome": {
            outcome: "diagnostic" if status == "fit" else "deferred"
            for outcome, status in status_by_outcome.items()
        },
    }


def _public_summary(statuses: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "primary_specification": {"feature_set": "all", "train_window": "expanding"},
        "primary_specification_status": "revision_frozen",
        "feature_family_summary": {
            "oversight": {
                "display_name": "Prior-filing history (legacy artifact key: oversight)",
                "model_eligible_features": ["prior_filing_count"],
                "reported_as_standalone": True,
                "n_features": 1,
                "empty": False,
                "same_as_metadata": False,
                "n_xbrl_ratio_features": 0,
                "n_xbrl_coverage_features": 0,
            },
            "visibility_history": {
                "display_name": "Visibility history",
                "model_eligible_features": ["prior_filing_count"],
                "reported_as_standalone": True,
                "n_features": 24,
                "empty": False,
                "same_as_metadata": False,
                "n_xbrl_ratio_features": 0,
                "n_xbrl_coverage_features": 0,
                "configured_features": ["prior_filing_count"],
                "available_features": ["prior_filing_count"],
                "unavailable_features": [],
            },
        },
        "reporting_boundaries": {
            "schema_version": "public-reporting-boundaries-v1",
            "sample_proxy": {
                "artifact_field": "is_domestic_us_gaap_proxy",
                "display_name": "10-K/10-K/A with no observed same-year FPI-form proxy",
                "definition": (
                    "selected 10-K or 10-K/A with no observed 20-F, 40-F, or 6-K mapped "
                    "to the same issuer fiscal year"
                ),
                "validates_fpi_status": False,
                "validates_domicile": False,
                "validates_us_gaap": False,
            },
            "pcaob_inspection_predictors": {
                "inspection_event_joined_to_gold": False,
                "model_eligible_features": [],
                "excluded_availability_markers": ["source_available_pcaob_inspections"],
            },
            "partner_nonadministrative_amendment": {
                "artifact_field": ("auditor_partner_prior_other_issuer_nonadmin_amendment_count"),
                "item_402_comparison_field": ("auditor_partner_prior_other_issuer_8k_402_count"),
                "scope": "post-year-proxy uncensored public-model panel",
                "rows_evaluated": 96733,
                "nonmissing_rows": 96000,
                "nonzero_rows": 1200,
                "n_distinct_nonmissing": 8,
                "minimum": 0,
                "maximum": 7,
                "is_constant_zero": False,
                "total_equals_item_402_rows": 95000,
                "total_equals_item_402_for_all_rows": False,
            },
        },
        "opacity_dml_evidence": _opacity_dml_evidence(statuses),
        "sample_attrition": [
            {"stage": "source_issuer_origin", "n_rows": 205652, "task": "all"},
            {"stage": "fiscal_year_2011_2024", "n_rows": 97027, "task": "all"},
            {"stage": "domestic_us_gaap_proxy", "n_rows": 96827, "task": "all"},
            {"stage": "observable_365_day_horizon", "n_rows": 96733, "task": "all"},
            {"stage": "eligible_comment_thread", "n_rows": 96000, "task": "comment_thread"},
            {"stage": "eligible_amendment", "n_rows": 95000, "task": "amendment"},
            {"stage": "eligible_8k_402", "n_rows": 94000, "task": "8k_402"},
        ],
    }


def _construct_manifest() -> dict[str, Any]:
    return {
        "validation_tier": "wrds_validated",
        "interval_method": "issuer_cluster_percentile_bootstrap",
        "interval_scope": "primary_plus_top_5_per_direction",
        "interval_seed": 42,
        "interval_reps": 1000,
        "primary_alignment": {
            "public_to_benchmark": {
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "expanding",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "bridge_tier": "high_confidence",
            },
            "benchmark_to_public": {
                "model_id": "benchmark_xgb",
                "target_public_label": "label_8k_402_365",
                "feature_set": "benchmark_all",
                "train_window": "expanding",
                "label_mode": "naive",
                "score_aggregation": "benchmark_score",
                "bridge_tier": "high_confidence",
            },
            "public_to_benchmark_count": 1,
            "benchmark_to_public_count": 1,
        },
        "primary_alignment_evidence": {
            "public_to_benchmark": {
                "metric_status": "fit",
                "top_decile_lift": 2.0,
                "ci_low": 1.2,
                "ci_high": 2.8,
            },
            "benchmark_to_public": {
                "metric_status": "fit",
                "top_decile_lift": 1.8,
                "ci_low": 1.1,
                "ci_high": 2.5,
            },
        },
        "exploratory_maxima": {
            "public_to_benchmark": {
                "keys": {"train_window": "rolling_7y"},
                "top_decile_lift": 2.4,
                "primary_lift": 2.0,
                "lift_minus_primary": 0.4,
            },
            "benchmark_to_public": {
                "keys": {"train_window": "rolling_7y"},
                "top_decile_lift": 2.1,
                "primary_lift": 1.8,
                "lift_minus_primary": 0.3,
            },
        },
    }


def _write_study_raw(
    study_dir: Path,
    dml_statuses: tuple[str, str, str],
) -> dict[str, Path]:
    summary = _public_summary(dml_statuses)
    public_dir = study_dir / "public_cascade"
    construct_dir = study_dir / "construct_overlap"
    summary_path = public_dir / "public_cascade_summary.json"
    construct_path = construct_dir / "construct_overlap_manifest.json"
    write_json(summary_path, summary)
    write_json(construct_path, _construct_manifest())

    rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    for task_index, task in enumerate(("comment_thread", "amendment", "8k_402"), start=1):
        for year in range(2018, 2023):
            pr_auc = 0.10 + task_index * 0.02 + (year - 2018) * 0.005
            rows.append(
                {
                    "feature_set": "all",
                    "train_window": "expanding",
                    "test_year": year,
                    "task": task,
                    "positive_rate_test": 0.01 * task_index,
                    "pr_auc": pr_auc,
                    "roc_auc": 0.60 + task_index * 0.02,
                    "brier": 0.02 + task_index * 0.001,
                    "brier_skill_score": 0.03 + task_index * 0.01,
                    "ece": 0.01 + task_index * 0.001,
                    "n_pos_test": 20 + task_index,
                }
            )
            status_rows.append(
                {
                    "feature_set": "all",
                    "train_window": "expanding",
                    "test_year": year,
                    "task": task,
                    "status": "fit",
                    "positive_test": 20 + task_index,
                    "n_test": 1000,
                }
            )
    metrics_path = public_dir / "public_cascade_metrics.csv"
    status_path = public_dir / "public_cascade_task_status.csv"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(metrics_path, index=False)
    pd.DataFrame(status_rows).to_csv(status_path, index=False)

    dml_path = public_dir / "public_opacity_dml.csv"
    encoded_statuses = {"fit", "skipped_constant_residual_treatment"}
    encoded_outcomes = {
        outcome
        for outcome, status in zip(REQUIRED_DML_OUTCOMES, dml_statuses, strict=True)
        if status in encoded_statuses
    }
    pd.DataFrame(
        [
            {
                "outcome": outcome,
                "n_raw_controls": 60,
                "n_encoded_controls": 64 if outcome in encoded_outcomes else float("nan"),
                "n_controls": 64 if outcome in encoded_outcomes else float("nan"),
                "n_effective_nuisance_folds": (3 if outcome in encoded_outcomes else float("nan")),
                "n_controls_definition": "maximum_fold_local_encoded_nuisance_columns",
                "n_opacity_components": 17,
                "status": status,
                "coef": 0.12 if status == "fit" else float("nan"),
                "std_err": 0.03 if status == "fit" else float("nan"),
                "p_value": 0.001 if status == "fit" else float("nan"),
                "n_obs": 90000 if status == "fit" else 0,
                "prevalence": 0.02 if status == "fit" else 0.01,
            }
            for outcome, status in zip(REQUIRED_DML_OUTCOMES, dml_statuses, strict=True)
        ]
    ).to_csv(dml_path, index=False)
    dml_meta_path = public_dir / "public_opacity_dml_meta.json"
    write_json(
        dml_meta_path,
        {
            "n_raw_controls": 60,
            "n_encoded_controls_by_outcome": {outcome: 64 for outcome in encoded_outcomes},
            "n_encoded_controls_by_fold": {
                outcome: [
                    {"fold_id": 1, "n_encoded_controls": 63},
                    {"fold_id": 2, "n_encoded_controls": 64},
                    {"fold_id": 3, "n_encoded_controls": 64},
                ]
                for outcome in encoded_outcomes
            },
            "n_effective_nuisance_folds_by_outcome": {outcome: 3 for outcome in encoded_outcomes},
            "n_opacity_components": 17,
            "n_controls_definition": "maximum_fold_local_encoded_nuisance_columns",
        },
    )

    public_ranking = construct_dir / "public_score_benchmark_ranking.csv"
    reciprocal = construct_dir / "reciprocal_alignment.csv"
    construct_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "is_primary": True,
                "model_id": "public_cascade",
                "feature_set": "all",
                "train_window": "expanding",
                "n_benchmark_positives_in_overlap": 50,
                "n_benchmark_negatives_in_overlap": 950,
                "pr_auc": 0.04,
                "roc_auc": 0.70,
                "top_decile_lift": 2.0,
                "top_10pct_precision": 0.10,
                "top_decile_lift_ci_low": 1.2,
                "top_decile_lift_ci_high": 2.8,
                "n_bootstrap_clusters": 100,
                "metric_status": "fit",
                "bridge_tier": "high_confidence",
            }
        ]
    ).to_csv(public_ranking, index=False)
    pd.DataFrame(
        [
            {
                "is_primary": True,
                "model_id": "benchmark_xgb",
                "feature_set": "benchmark_all",
                "train_window": "expanding",
                "n_public_positives_in_overlap": 40,
                "n_public_negatives_in_overlap": 960,
                "pr_auc": 0.03,
                "roc_auc": 0.60,
                "top_decile_lift": 1.8,
                "top_10pct_precision": 0.072,
                "top_decile_lift_ci_low": 1.1,
                "top_decile_lift_ci_high": 2.5,
                "n_bootstrap_clusters": 100,
                "metric_status": "fit",
                "bridge_tier": "high_confidence",
            }
        ]
    ).to_csv(reciprocal, index=False)
    return {
        "public": summary_path,
        "construct": construct_path,
        "metrics": metrics_path,
        "task_status": status_path,
        "dml": dml_path,
        "dml_meta": dml_meta_path,
        "public_ranking": public_ranking,
        "reciprocal": reciprocal,
    }


def _write_package(package_dir: Path, study_dir: Path, study_manifest: Path) -> dict[str, Path]:
    tables_dir = package_dir / "tables"
    figures_dir = package_dir / "figures"
    tables_dir.mkdir(parents=True)
    figures_dir.mkdir(parents=True)
    summary = json.loads(
        (study_dir / "public_cascade" / "public_cascade_summary.json").read_text()
    )
    metrics = pd.read_csv(study_dir / "public_cascade" / "public_cascade_metrics.csv")
    task_status = pd.read_csv(study_dir / "public_cascade" / "public_cascade_task_status.csv")
    frames = {
        "table_03": _public_task_metrics(
            _select_primary_public_metrics(metrics, summary), task_status, summary
        ),
        "table_09": _construct_alignment(study_dir),
        "table_12": _public_opacity_dml_table(study_dir),
        "table_18": _public_sample_attrition_table(summary),
    }
    stems = {
        "table_03": "table_03_public_task_metrics",
        "table_09": "table_09_construct_alignment",
        "table_12": "table_12_public_opacity_dml",
        "table_18": "table_18_public_sample_attrition",
    }
    table_manifest: dict[str, dict[str, dict[str, str]]] = {}
    table_paths: dict[str, Path] = {}
    for key in sorted(PACKAGE_TABLE_KEYS):
        stem = stems.get(key, key)
        csv_path = tables_dir / f"{stem}.csv"
        if key in frames:
            frames[key].to_csv(csv_path, index=False)
        else:
            pd.DataFrame({"fixture": [key]}).to_csv(csv_path, index=False)
        md_path = tables_dir / f"{stem}.md"
        tex_path = tables_dir / f"{stem}.tex"
        _write(md_path, f"# {key}\n")
        _write(tex_path, f"% {key}\n")
        table_manifest[key] = {
            "csv": _artifact_record(csv_path, package_dir),
            "md": _artifact_record(md_path, package_dir),
            "tex": _artifact_record(tex_path, package_dir),
        }
        table_paths[key] = csv_path
    figure_manifest: dict[str, dict[str, dict[str, str]]] = {}
    for key in sorted(PACKAGE_FIGURE_KEYS):
        png = figures_dir / f"{key}.png"
        pdf = figures_dir / f"{key}.pdf"
        _write(png, b"\x89PNG\r\n" + key.encode())
        _write(pdf, b"%PDF-1.4\n" + key.encode())
        figure_manifest[key] = {
            "png": _artifact_record(png, package_dir),
            "pdf": _artifact_record(pdf, package_dir),
        }
    narrative = package_dir / "results_narrative.md"
    _write(narrative, "Canonical fixture narrative.\n")
    manifest = json.loads(study_manifest.read_text())
    public_component = manifest["components"]["public_cascade"]
    write_json(
        package_dir / "manifest.json",
        {
            "schema_version": "manuscript-package-v2",
            "study_commit": manifest["repo_commit"],
            "study_manifest_sha256": sha256_path(study_manifest),
            "generated_at_utc": "2026-07-06T00:00:00+00:00",
            "primary_public_specification": {
                "feature_set": "all",
                "train_window": "expanding",
            },
            "tables": table_manifest,
            "figures": figure_manifest,
            "narrative": _artifact_record(narrative, package_dir),
            "reporting_contract": {
                "reporting_boundaries": summary["reporting_boundaries"],
                "feature_family_summary": summary["feature_family_summary"],
                "opacity_dml_evidence": public_component["opacity_dml_evidence"],
                "claim_maturity": manifest["claim_maturity"],
                "artifact_ownership": ARTIFACT_OWNERSHIP,
            },
        },
    )
    return {
        **table_paths,
        "manifest": package_dir / "manifest.json",
        "narrative": narrative,
    }


def canonical_fixture(
    tmp_path: Path,
    *,
    dml_statuses: tuple[str, str, str] = (
        "fit",
        "skipped_one_class_or_too_small",
        "skipped_constant_treatment",
    ),
) -> dict[str, Any]:
    repo = tmp_path / "repo"
    commit = _init_repo(repo)
    evidence_root = tmp_path / "evidence"
    lake = _write_public_lake_inputs(evidence_root, repo, commit)
    study_dir = evidence_root / "study"
    package_dir = evidence_root / "package"
    raw = _write_study_raw(study_dir, dml_statuses)

    raw_data = evidence_root / "inputs" / "raw.csv"
    issuer_dim = evidence_root / "inputs" / "issuer_dim.parquet"
    crosswalk = evidence_root / "inputs" / "crosswalk.csv"
    for path, content in (
        (raw_data, "raw\n1\n"),
        (issuer_dim, "issuer\n1\n"),
        (crosswalk, "gvkey,cik\n1,1\n"),
    ):
        _write(path, content)
    config_paths = [
        repo / "config" / "study.yaml",
        repo / "config" / "benchmark.yaml",
        repo / "config" / "public_cascade.yaml",
    ]
    input_paths = [
        raw_data,
        issuer_dim,
        lake["panel"],
        lake["final_report"],
        crosswalk,
        lake["run_metadata"],
        lake["form_ap"],
    ]
    provenance = {
        "commit_sha": commit,
        "dirty": False,
        "dirty_status": "",
        **config_provenance(config_paths),
        **input_provenance(input_paths),
        **uv_lock_provenance(repo),
    }
    manifest_path = study_dir / "study_run_manifest.json"
    opacity_dml_evidence = _opacity_dml_evidence(dml_statuses)
    write_json(
        manifest_path,
        {
            "repo_commit": commit,
            "git_dirty": False,
            "runtime": {
                "parallel_jobs": 4,
                "model_threads": 2,
                "seed_policy": "task-isolated",
                "peer_comparison_mode": "full",
                "peer_target": "both",
                "peer_parallel_jobs": 4,
                "peer_model_threads": 2,
            },
            "provenance": provenance,
            "public_lake_inputs": {
                "public_lake_final_report": path_record(lake["final_report"]),
                "public_lake_run_metadata": path_record(lake["run_metadata"]),
                "form_ap_source_metadata": path_record(lake["form_ap"]),
                "issuer_origin_panel": path_record(lake["panel"]),
            },
            "public_lake_provenance": public_lake_provenance(
                lake["run_metadata"], lake["form_ap"], bronze_root=lake["bronze"]
            ),
            "components": {
                "benchmark": {"status": "complete"},
                "public_cascade": {
                    "status": "complete",
                    "opacity_dml_evidence": opacity_dml_evidence,
                },
                "bridge_probe": {"status": "crosswalk_available"},
                "peer_comparison": {"status": "complete"},
                "public_peer_comparison": {"status": "complete"},
                "construct_overlap": {
                    "run_status": "complete",
                    "validation_tier": "wrds_validated",
                },
            },
            "claim_maturity": {
                "public_prediction": "reportable",
                "feature_and_window_sensitivity": "supporting",
                "construct_alignment": "supporting",
                "opacity_dml": (
                    "diagnostic" if opacity_dml_evidence["fit_outcomes"] else "deferred"
                ),
            },
        },
    )
    package = _write_package(package_dir, study_dir, manifest_path)

    report_paths = [repo / "docs" / "results_snapshot.md"]
    _write(report_paths[0], "# Canonical Results Snapshot\n")
    package_manifest = json.loads(package["manifest"].read_text())
    for key in sorted(PACKAGE_FIGURE_KEYS):
        package_png = package_dir / package_manifest["figures"][key]["png"]["path"]
        report_path = repo / "docs" / "assets" / "results_snapshot" / package_png.name
        _write(report_path, package_png.read_bytes())
        report_paths.append(report_path)

    return {
        "repo": repo,
        "commit": commit,
        "study_dir": study_dir,
        "package_dir": package_dir,
        "manifest": manifest_path,
        "public": raw["public"],
        "construct": raw["construct"],
        "table_03": package["table_03"],
        "table_09": package["table_09"],
        "table_12": package["table_12"],
        "table_18": package["table_18"],
        "package_manifest": package["manifest"],
        "bronze": lake["bronze"],
        "sidecar": lake["sidecar"],
        "payload": lake["payload"],
        "run_metadata": lake["run_metadata"],
        "form_ap": lake["form_ap"],
        "panel": lake["panel"],
        "final_report": lake["final_report"],
        "config": repo / "config" / "study.yaml",
        "lake_config": repo / "config" / "public_lake.yaml",
        "input": raw_data,
        "lock": repo / "uv.lock",
        "raw": raw,
        "report_paths": report_paths,
        "attestation": evidence_root / "canonical_attestation.json",
    }
