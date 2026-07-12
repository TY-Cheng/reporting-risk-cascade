from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
from typing import Any

import pandas as pd
import pytest
import yaml

import scripts.refresh_results_snapshot as snapshot_module
from scripts.refresh_results_snapshot import _construct_alignment_rows
from src.provenance import sha256_path


REPO_ROOT = Path(__file__).resolve().parents[1]
USER_PATH_PREFIX = "/" + "Users" + "/"
VOLUME_PATH_PREFIX = "/" + "Volumes" + "/"
CLOUD_STORAGE_MARKER = "One" + "Drive"


class _MkDocsYamlLoader(yaml.SafeLoader):
    pass


def _construct_python_name(loader: yaml.Loader, suffix: str, node: yaml.Node) -> str:
    return suffix


_MkDocsYamlLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:",
    _construct_python_name,
)


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _read_yaml(path: str) -> dict:
    return yaml.load(_read(path), Loader=_MkDocsYamlLoader)


def _read_toml(path: str) -> dict:
    return tomllib.loads(_read(path))


def _squash(text: str) -> str:
    return " ".join(text.split())


def test_mkdocs_nav_uses_paper_plan_and_future_work_pages() -> None:
    mkdocs = _read_yaml("mkdocs.yml")
    assert mkdocs["nav"] == [
        {"Home": "index.md"},
        {"Paper Plan": "paper_plan.md"},
        {"Results Snapshot": "results_snapshot.md"},
        {"FAQ": "faq.md"},
        {
            "Audit Briefs": [
                {"Development Audit": "development_audit_prompt.md"},
                {"Manuscript Audit": "manuscript_audit_prompt.md"},
            ]
        },
        {"Future Work": "future_work.md"},
    ]


def test_mkdocs_uses_material_with_light_and_dark_palettes() -> None:
    mkdocs = _read_yaml("mkdocs.yml")
    assert mkdocs["site_name"] == "Reporting Risk Cascade"
    assert mkdocs["theme"]["name"] == "material"
    schemes = {entry["scheme"] for entry in mkdocs["theme"]["palette"]}
    assert schemes == {"default", "slate"}


def test_project_identity_uses_reporting_risk_cascade_name() -> None:
    pyproject = _read_toml("pyproject.toml")
    readme = _read("README.md")
    home = _read("docs/index.md")
    env_example = _read(".env.example")

    assert pyproject["project"]["name"] == "reporting-risk-cascade"
    assert "# Reporting Risk Cascade" in readme
    assert home.strip().endswith('--8<-- "README.md:docs-home"')
    assert "hide:" in home
    assert "reproducible research workspace" in readme
    assert "reporting-risk-cascade-manuscript" in env_example
    assert 'SEC_USER_AGENT="Your Name your.email@institution.edu"' in env_example
    assert "must replace" in env_example.casefold()


def test_mkdocs_enables_richer_material_navigation_and_content_features() -> None:
    mkdocs = _read_yaml("mkdocs.yml")
    features = set(mkdocs["theme"]["features"])
    required_features = {
        "content.action.view",
        "content.code.annotate",
        "navigation.sections",
        "navigation.tabs",
        "navigation.path",
        "navigation.footer",
        "navigation.instant",
        "navigation.instant.progress",
        "navigation.top",
        "navigation.tracking",
        "content.code.copy",
        "content.tabs.link",
        "content.tooltips",
        "search.highlight",
        "search.share",
        "search.suggest",
        "toc.follow",
    }
    assert required_features.issubset(features)
    assert "content.action.edit" not in features
    assert {item["scheme"] for item in mkdocs["theme"]["palette"]} == {
        "default",
        "slate",
    }
    assert mkdocs["extra_css"] == ["assets/stylesheets/extra.css"]
    assert mkdocs["extra_javascript"] == [
        "https://unpkg.com/mermaid@11/dist/mermaid.min.js",
        "assets/javascripts/mermaid-init.js",
    ]
    assert mkdocs["repo_url"] == "https://github.com/TY-Cheng/reporting-risk-cascade"

    extensions = mkdocs["markdown_extensions"]
    extension_names = {next(iter(item)) if isinstance(item, dict) else item for item in extensions}
    required_extensions = {
        "admonition",
        "attr_list",
        "def_list",
        "footnotes",
        "md_in_html",
        "pymdownx.emoji",
        "pymdownx.tabbed",
        "pymdownx.superfences",
    }
    assert required_extensions.issubset(extension_names)

    superfences = next(
        item["pymdownx.superfences"]
        for item in extensions
        if isinstance(item, dict) and "pymdownx.superfences" in item
    )
    mermaid_fence = superfences["custom_fences"][0]
    assert mermaid_fence["name"] == "mermaid"
    assert mermaid_fence["class"] == "mermaid"
    assert mermaid_fence["format"] == "pymdownx.superfences.fence_code_format"

    mermaid_init = _read("docs/assets/javascripts/mermaid-init.js")
    assert "window.document$.subscribe(renderMermaid)" in mermaid_init
    assert 'querySelector: ".mermaid"' in mermaid_init


def test_docs_file_names_are_paper_facing_not_internal_codenames() -> None:
    doc_files = {path.name for path in (REPO_ROOT / "docs").glob("*.md")}
    assert doc_files == {
        "development_audit_prompt.md",
        "faq.md",
        "future_work.md",
        "index.md",
        "manuscript_audit_prompt.md",
        "paper_plan.md",
        "results_snapshot.md",
    }


def test_ci_workflow_is_clean_checkout_safe() -> None:
    ci = _read(".github/workflows/ci.yml")
    assert 'just check dataset="sample"' not in ci
    assert "run: just check" in ci
    assert "run: just _test" not in ci
    assert "run: just _ruff" not in ci
    assert "scripts/run_study.py" in ci
    assert "--peer-comparison-mode light" in ci
    assert "--peer-target benchmark" in ci
    assert "--parallel-jobs 1" in ci
    assert "--model-threads 1" in ci
    assert "--skip-benchmark" in ci
    assert "--skip-public-cascade" in ci
    assert "--skip-bridge-probe" in ci
    assert "artifacts/ci_peer_raw.parquet" in ci
    assert "data/raw_dataset_misstatement.parquet" not in ci


def test_just_check_is_the_single_data_free_quality_gate() -> None:
    justfile = _read("justfile")
    assert "check *args" not in justfile
    check_recipe = justfile.split("\ncheck: _check-env\n", maxsplit=1)[1].split(
        "\ndocs: _docs-build", maxsplit=1
    )[0]
    assert "run_data_prep.py" not in check_recipe
    assert "generate_sample_dataset.py" not in check_recipe
    assert "just _test" in check_recipe
    assert "just _ruff" in check_recipe
    assert "just _docs-build" in check_recipe

    docs_recipe = justfile.split("\n_docs-build: _check-env\n", maxsplit=1)[1]
    assert "mkdocs build --strict --clean" in docs_recipe
    assert "just _ruff" not in docs_recipe


def test_public_lake_defaults_follow_public_lake_dir_contract() -> None:
    justfile = _read("justfile")
    build_linkage = _read("scripts/build_linkage_bridge.py")
    linkage = _read("src/linkage.py")

    assert 'public_lake_dir="${PUBLIC_LAKE_DIR:-${DATA_DIR}/public_lake}"' in justfile
    assert 'lake_silver_dir="${LAKE_SILVER_DIR:-${public_lake_dir}/silver}"' in justfile
    assert 'lake_gold_dir="${LAKE_GOLD_DIR:-${public_lake_dir}/gold}"' in justfile
    assert (
        'public_lake_smoke_dir="${PUBLIC_LAKE_SMOKE_DIR:-${DATA_DIR}/public_lake_smoke}"'
        in justfile
    )
    assert 'silver_dir="${public_lake_smoke_dir}/silver"' in justfile
    assert 'LAKE_GOLD_DIR / "issuer_origin_panel.parquet"' in build_linkage
    assert 'PUBLIC_LAKE_SMOKE_DIR / "gold" / "issuer_origin_panel.parquet"' in build_linkage
    assert 'LAKE_GOLD_DIR / "issuer_origin_panel.parquet"' in linkage
    assert 'PUBLIC_LAKE_SMOKE_DIR / "gold" / "issuer_origin_panel.parquet"' in linkage


def test_public_lake_full_sources_env_before_cli_parse() -> None:
    script = _read("scripts/run_public_lake_full.sh")

    source_idx = script.index('source ".env"')
    default_idx = script.index('MODE="${MODE:-full}"')
    parse_idx = script.index("while [[ $# -gt 0 ]]; do")
    fetch_default_idx = script.index('FETCH_WORKERS="${FETCH_WORKERS:-2}"')
    fetch_cli_idx = script.index('FETCH_WORKERS="$2"', parse_idx)
    engine_default_idx = script.index('ENGINE="${ENGINE:-duckdb}"')
    engine_cli_idx = script.index('ENGINE="$2"', parse_idx)

    assert source_idx < default_idx < parse_idx
    assert source_idx < fetch_default_idx < parse_idx < fetch_cli_idx
    assert source_idx < engine_default_idx < parse_idx < engine_cli_idx
    assert script.count('source ".env"') == 1
    assert "physical_path()" in script
    assert 'REPO_REAL="$(physical_path "$REPO_ROOT")"' in script
    for guarded_name in [
        "DATA_DIR",
        "PUBLIC_LAKE_DIR",
        "PUBLIC_LAKE_SMOKE_DIR",
        "LAKE_BRONZE_DIR",
        "LAKE_SILVER_DIR",
        "LAKE_GOLD_DIR",
        "UV_PROJECT_ENVIRONMENT",
    ]:
        assert f'require_outside_repo "{guarded_name}"' in script


def test_public_data_vintage_is_pinned_across_entry_points_and_docs() -> None:
    paths = [
        "config/public_data.yaml",
        "justfile",
        "scripts/run_public_lake_full.sh",
        "docs/paper_plan.md",
    ]
    for path in paths:
        text = _read(path)
        assert "2026-07-06" in text, path
        assert "2026-05-26" not in text, path


def test_just_env_guards_use_physical_paths_for_external_data() -> None:
    justfile = _read("justfile")

    assert "repo_root_real=" in justfile
    assert "uv_env_real=" in justfile
    assert "data_path_real=" in justfile
    assert 'public_lake_dir="${PUBLIC_LAKE_DIR:-${DATA_DIR}/public_lake}"' in justfile
    assert (
        'public_lake_smoke_dir="${PUBLIC_LAKE_SMOKE_DIR:-${DATA_DIR}/public_lake_smoke}"'
        in justfile
    )
    assert "${LAKE_BRONZE_DIR:-${public_lake_dir}/bronze}" in justfile
    assert "${LAKE_SILVER_DIR:-${public_lake_dir}/silver}" in justfile
    assert "${LAKE_GOLD_DIR:-${public_lake_dir}/gold}" in justfile
    assert "data paths must point outside this repo" in justfile


def test_just_snapshot_refreshes_results_snapshot_then_checks() -> None:
    justfile = _read("justfile")
    assert (
        'snapshot study_dir="artifacts/full_with_peer" allow_partial="0": _check-data-env'
        in justfile
    )
    snapshot_recipe = justfile.split(
        '\nsnapshot study_dir="artifacts/full_with_peer" allow_partial="0": _check-data-env\n',
        maxsplit=1,
    )[1].split("\n_docs-build: _check-env", maxsplit=1)[0]
    assert "scripts/refresh_results_snapshot.py" in snapshot_recipe
    assert "--allow-partial" in snapshot_recipe
    assert "study_dir must be relative or under ARTIFACTS_DIR" in snapshot_recipe
    assert "artifacts/full_with_peer" in snapshot_recipe
    assert '--manuscript-package "artifacts/manuscript_package"' in snapshot_recipe
    manuscript_index = snapshot_recipe.index("just manuscript")
    snapshot_index = snapshot_recipe.index("scripts/refresh_results_snapshot.py")
    assert manuscript_index < snapshot_index
    assert "just check" in snapshot_recipe


def test_just_manuscript_builds_paper_facing_package() -> None:
    justfile = _read("justfile")
    assert (
        'manuscript study_dir="artifacts/full_with_peer" '
        'out_dir="artifacts/manuscript_package": _check-data-env'
    ) in justfile
    manuscript_recipe = justfile.split(
        '\nmanuscript study_dir="artifacts/full_with_peer" '
        'out_dir="artifacts/manuscript_package": _check-data-env\n',
        maxsplit=1,
    )[1].split("\n_docs-build: _check-env", maxsplit=1)[0]
    assert "scripts/build_manuscript_package.py" in manuscript_recipe
    assert "artifacts/full_with_peer" in manuscript_recipe
    assert "artifacts/manuscript_package" in manuscript_recipe
    assert "manuscript paths must be relative or under ARTIFACTS_DIR" in manuscript_recipe


def test_readme_points_to_current_docs_pages() -> None:
    readme = _read("README.md")
    docs_url = "https://ty-cheng.github.io/reporting-risk-cascade/"
    assert f"[Reporting Risk Cascade]({docs_url})" in readme
    assert f"[Paper Plan]({docs_url}paper_plan/)" in readme
    assert f"[Results Snapshot]({docs_url}results_snapshot/)" in readme
    assert f"[FAQ]({docs_url}faq/)" in readme
    assert f"[Future Work]({docs_url}future_work/)" in readme
    assert "[Paper Plan](paper_plan.md)" not in readme
    assert "[Results Snapshot](results_snapshot.md)" not in readme
    assert "[FAQ](faq.md)" not in readme
    assert "[Future Work](future_work.md)" not in readme


def test_docs_home_is_the_readme_snippet_only() -> None:
    home = _read("docs/index.md")
    assert home.strip().endswith('--8<-- "README.md:docs-home"')
    assert "hide:" in home


def test_results_snapshot_exposes_current_main_artifact_results() -> None:
    results = _read("docs/results_snapshot.md")
    required_phrases = [
        "Results and Discussion",
        "Connection to Paper Plan",
        "Results Overview",
        "SEC/PCAOB",
        "gvkey x data_year",
        "detected-misstatement benchmark",
        "issuer_origin_panel",
        "filing_origin_panel",
        "gvkey-CIK-year",
        "PR-AUC",
        "Experiment 1: Label Observability and Detection Timing",
        "Experiment 2: Concept Drift and Model Shelf-Life",
        "Experiment 3: Opacity and Public Review/Correction Risk",
        "Experiment 4: Public Cascade Construction",
        "Experiment 5: Public Cascade Prediction",
        "Experiment 6: Detected-Misstatement Benchmark and Public Cascade Overlap",
    ]
    for phrase in required_phrases:
        assert phrase in results
    assert "Generated by `just snapshot`" in results or "static documentation snapshot" in results
    assert "ARS" not in results
    assert "Academic Research Suite" not in results


def test_wrds_source_summary_counts_observed_combinations_and_families() -> None:
    summarize = getattr(snapshot_module, "_summarize_wrds_sources", None)
    assert callable(summarize)
    families = ["capital_iq", "compustat_company", "compustat_security", "crsp_ccm"]
    source_values = [
        ";".join(
            f"wrds_bridge:{family}" for idx, family in enumerate(families) if mask & (1 << idx)
        )
        for mask in range(1, 1 << len(families))
    ]

    assert summarize(source_values) == (
        "15 observed combinations across 4 WRDS source families in the current run; "
        "full values remain hash-bound in the study manifest"
    )


def test_structural_break_pvalue_formatter_uses_threshold_not_zero() -> None:
    formatter = getattr(snapshot_module, "_fmt_p_value", None)
    assert callable(formatter)
    assert formatter(0.00001) == "<0.001"
    assert formatter(0.0009) == "<0.001"
    assert formatter(0.001) == "0.0010"
    assert formatter(float("nan")) == ""


CURRENT_PACKAGE_TABLES = [
    "table_01_component_status",
    "table_02_public_lake_scale",
    "table_03_public_task_metrics",
    "table_04_feature_family_metrics",
    "table_05_benchmark_timing_metrics",
    "table_06_detected_misstatement_peer_metrics",
    "table_07_public_peer_metrics",
    "table_08_bridge_coverage",
    "table_09_construct_alignment",
    "table_12_public_opacity_dml",
    "table_13_public_fold_support",
    "table_14_task_feature_family_metrics",
    "table_15_bridge_overlap_matrix",
    "table_16_bridge_sample_boundaries",
    "table_17_selection_profile",
    "table_18_public_sample_attrition",
]
CURRENT_PACKAGE_FIGURES = [
    "figure_01_public_task_pr_auc",
    "figure_02_feature_family_pr_auc",
    "figure_03_detected_misstatement_peer_pr_auc",
    "figure_04_public_peer_pr_auc",
    "figure_05_construct_overlap_lift",
]
PACKAGE_TABLE_STEMS = {
    f"table_{index:02d}": stem
    for index, stem in zip(
        [*range(1, 10), *range(12, 19)],
        CURRENT_PACKAGE_TABLES,
        strict=True,
    )
}
PACKAGE_FIGURE_STEMS = {
    f"figure_{index:02d}": stem for index, stem in enumerate(CURRENT_PACKAGE_FIGURES, start=1)
}
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _table_03_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Task": "comment_thread",
                "Panel_Positives": "321",
                "Mean_Prevalence": "0.1234",
                "Mean_PR_AUC": "0.3000",
                "Mean_ROC_AUC": "0.7000",
                "Mean_Brier_Skill": "0.0500",
                "Mean_ECE": "0.0400",
                "n_folds": "1",
                "metric_rows": "1",
            }
        ]
    )


def _table_09_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Direction": "Public score to benchmark positives",
                "Model": "public_cascade",
                "Target": "8k_402",
                "PR_AUC": "0.0400",
                "ROC_AUC": "0.7000",
                "Top_10pct_Precision": "0.0600",
                "Top_10pct_FDR": "0.9400",
                "Top_Decile_Lift": "2.0000",
                "Lift_Bootstrap_Interval": "[1.2000, 2.8000]",
            },
            {
                "Direction": "Benchmark score to public positives",
                "Model": "benchmark_xgb",
                "Target": "label_8k_402_365",
                "PR_AUC": "0.0300",
                "ROC_AUC": "0.6000",
                "Top_10pct_Precision": "0.0500",
                "Top_10pct_FDR": "0.9500",
                "Top_Decile_Lift": "1.8000",
                "Lift_Bootstrap_Interval": "[1.1000, 2.5000]",
            },
        ]
    )


def _bridge_claim_boundary(
    component_tier: str | None,
    artifact_tier: str | None,
) -> dict[str, str]:
    component_label = component_tier or "none"
    artifact_label = artifact_tier or "none"
    paired_tier = artifact_label
    if component_tier != artifact_tier:
        paired_tier = f"component={component_label}; manifest={artifact_label}"
    status = "validated" if component_tier == artifact_tier == "wrds_validated" else "diagnostic"
    return {
        "construct_overlap_tier": paired_tier,
        "construct_overlap_status": status,
        "construct_overlap_component_tier": component_label,
        "construct_overlap_artifact_tier": artifact_label,
    }


def _write_snapshot_fixture(
    tmp_path: Path,
    *,
    diagnostic_dml: bool = True,
) -> dict[str, Any]:
    study_dir = tmp_path / "study"
    package_dir = tmp_path / "manuscript_package"
    tables_dir = package_dir / "tables"
    figures_dir = package_dir / "figures"
    tables_dir.mkdir(parents=True)
    figures_dir.mkdir(parents=True)

    commit = "a" * 40
    dml_statuses = {
        "comment_thread": "fit" if diagnostic_dml else "skipped_one_class_or_too_small",
        "amendment": "skipped_one_class_or_too_small",
        "8k_402": "skipped_constant_treatment",
    }
    fit_outcomes = ["comment_thread"] if diagnostic_dml else []
    dml_evidence = {
        "required_outcomes": ["comment_thread", "amendment", "8k_402"],
        "status_by_outcome": dml_statuses,
        "fit_outcomes": fit_outcomes,
        "maturity_by_outcome": {
            outcome: "diagnostic" if outcome in fit_outcomes else "deferred"
            for outcome in dml_statuses
        },
    }
    dml_maturity = "diagnostic" if diagnostic_dml else "deferred"
    reporting_boundaries = {
        "schema_version": "public-reporting-boundaries-v1",
        "sample_proxy": {
            "artifact_field": "is_domestic_us_gaap_proxy",
            "display_name": "10-K/10-K/A with no observed same-year FPI-form proxy",
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
            "scope": "post-year-proxy uncensored public-model panel",
            "rows_evaluated": 12,
            "nonmissing_rows": 12,
            "nonzero_rows": 4,
            "n_distinct_nonmissing": 4,
            "minimum": 0,
            "maximum": 3,
            "is_constant_zero": False,
            "total_equals_item_402_rows": 7,
            "total_equals_item_402_for_all_rows": False,
        },
    }
    feature_family_summary = {
        "oversight": {
            "display_name": "Prior-filing history (legacy artifact key: oversight)",
            "model_eligible_features": ["prior_filing_count"],
            "reported_as_standalone": True,
        }
    }
    _write_json(
        study_dir / "study_run_manifest.json",
        {
            "generated_at_utc": "2026-07-10T00:00:00+00:00",
            "repo_commit": commit,
            "git_dirty": False,
            "provenance": {
                "commit_sha": commit,
                "dirty": False,
                "config_hash": "b" * 64,
                "input_hash": "c" * 64,
                "uv_lock_hash": "d" * 64,
                "input_files": [
                    {
                        "path": USER_PATH_PREFIX + "example/raw.csv",
                        "exists": True,
                        "sha256": "1" * 64,
                    },
                    {
                        "path": VOLUME_PATH_PREFIX + "private/issuer_dim.parquet",
                        "exists": True,
                        "sha256": "2" * 64,
                    },
                    {
                        "path": USER_PATH_PREFIX
                        + "example/"
                        + CLOUD_STORAGE_MARKER
                        + "/panel.parquet",
                        "exists": True,
                        "sha256": "3" * 64,
                    },
                    {
                        "path": VOLUME_PATH_PREFIX + "private/public_lake_final_report.json",
                        "exists": True,
                        "sha256": "4" * 64,
                    },
                    {
                        "path": VOLUME_PATH_PREFIX + "private/bridge.csv",
                        "exists": True,
                        "sha256": "5" * 64,
                    },
                    {
                        "path": USER_PATH_PREFIX + "example/lake.json",
                        "exists": True,
                        "sha256": "6" * 64,
                    },
                    {
                        "path": USER_PATH_PREFIX + "example/form_ap.json",
                        "exists": True,
                        "sha256": "7" * 64,
                    },
                ],
                "wrds_export_metadata": {
                    "path": USER_PATH_PREFIX + "example/" + CLOUD_STORAGE_MARKER + "/bridge.csv",
                    "exists": True,
                    "sha256": "7" * 64,
                    "source_values": ["wrds_sec_analytics_cik_gvkey"],
                    "source_version_values": ["WRDS SEC Analytics Suite 2026-05"],
                    "extracted_at_values": ["2026-05-25T00:00:00Z"],
                },
            },
            "public_lake_provenance": {
                "as_of_date": "2026-07-06",
                "fresh_build": True,
                "commit_sha": commit,
                "git_dirty": False,
                "config_hash": "8" * 64,
                "input_hash": "9" * 64,
                "uv_lock_hash": "0" * 64,
                "source_metadata_inventory": [
                    {
                        "metadata_file": "form-ap/FirmFilings.zip.meta.json",
                        "metadata_sha256": "e" * 64,
                        "source_name": "form-ap",
                        "payload_sha256": "f" * 64,
                    }
                ],
                "form_ap": {
                    "source_kind": "verified_zip_member",
                    "archive_sha256": "e" * 64,
                    "member": "FirmFilings.csv",
                    "member_sha256": "f" * 64,
                },
            },
            "components": {
                "benchmark": {
                    "status": "complete",
                    "out_dir": USER_PATH_PREFIX + "example/benchmark",
                },
                "public_cascade": {
                    "status": "complete",
                    "out_dir": VOLUME_PATH_PREFIX + "private/public",
                    "opacity_dml_evidence": dml_evidence,
                },
                "bridge_probe": {
                    "status": "crosswalk_available",
                    "out_dir": USER_PATH_PREFIX + "example/bridge",
                },
                "peer_comparison": {
                    "status": "complete",
                    "out_dir": USER_PATH_PREFIX + "example/peer",
                },
                "public_peer_comparison": {
                    "status": "complete",
                    "out_dir": USER_PATH_PREFIX + "example/public_peer",
                },
                "construct_overlap": {
                    "run_status": "complete",
                    "validation_tier": "wrds_validated",
                    "out_dir": USER_PATH_PREFIX + "example/" + CLOUD_STORAGE_MARKER + "/construct",
                },
            },
            "claim_maturity": {
                "public_prediction": "reportable",
                "feature_and_window_sensitivity": "supporting",
                "construct_alignment": "supporting",
                "opacity_dml": dml_maturity,
            },
            "inputs": {
                "raw_data": USER_PATH_PREFIX + "example/raw.csv",
                "issuer_dim": VOLUME_PATH_PREFIX + "private/issuer_dim.parquet",
                "issuer_origin_panel": USER_PATH_PREFIX
                + "example/"
                + CLOUD_STORAGE_MARKER
                + "/panel.parquet",
                "public_lake_final_report": VOLUME_PATH_PREFIX
                + "private/public_lake_final_report.json",
                "crosswalk": VOLUME_PATH_PREFIX + "private/bridge.csv",
                "public_lake_run_metadata": USER_PATH_PREFIX + "example/lake.json",
                "form_ap_source_metadata": USER_PATH_PREFIX + "example/form_ap.json",
            },
            "runtime": {"peer_comparison_mode": "full"},
        },
    )
    _write_json(
        study_dir / "public_cascade" / "public_cascade_summary.json",
        {
            "sample_years": [2011, 2024],
            "primary_specification": {"feature_set": "all", "train_window": "expanding"},
            "task_positive_counts": {},
            "task_exclusion_counts": {},
            "feature_family_summary": feature_family_summary,
            "reporting_boundaries": reporting_boundaries,
            "opacity_dml_evidence": dml_evidence,
        },
    )
    pd.DataFrame(
        [
            {
                "task": "comment_thread",
                "feature_set": "all",
                "train_window": "expanding",
                "test_year": 2023,
                "n_test": 1000,
                "positive_rate_test": 0.10,
                "pr_auc": 0.30,
                "roc_auc": 0.70,
                "brier_skill_score": 0.05,
                "ece": 0.04,
            },
            {
                "task": "comment_thread",
                "feature_set": "all",
                "train_window": "rolling_7y",
                "test_year": 2024,
                "n_test": 1000,
                "positive_rate_test": 0.20,
                "pr_auc": 0.90,
                "roc_auc": 0.99,
                "brier_skill_score": 0.80,
                "ece": 0.90,
            },
        ]
    ).to_csv(
        study_dir / "public_cascade" / "public_cascade_metrics.csv",
        index=False,
    )
    _write_json(
        study_dir / "bridge_probe" / "bridge_probe_summary.json",
        {"status": "crosswalk_available"},
    )
    _write_json(
        study_dir / "construct_overlap" / "construct_overlap_manifest.json",
        {
            "validation_tier": "wrds_validated",
            "search_universe_rows": {
                "public_to_benchmark": 17,
                "benchmark_to_public": 23,
            },
            "exploratory_maxima": {
                "public_to_benchmark": {
                    "keys": {"model_id": "public_decoy", "train_window": "rolling_7y"}
                },
                "benchmark_to_public": {
                    "keys": {"model_id": "benchmark_decoy", "train_window": "rolling_7y"}
                },
            },
        },
    )
    pd.DataFrame(
        [
            {
                "model_id": "public_cascade",
                "task": "8k_402",
                "train_window": "expanding",
                "pr_auc": 0.04,
                "roc_auc": 0.70,
                "top_10pct_precision": 0.06,
                "top_decile_lift": 2.0,
            },
            {
                "model_id": "public_decoy",
                "task": "8k_402",
                "train_window": "rolling_7y",
                "pr_auc": 0.09,
                "roc_auc": 0.80,
                "top_10pct_precision": 0.10,
                "top_decile_lift": 9.0,
            },
        ]
    ).to_csv(
        study_dir / "construct_overlap" / "public_score_benchmark_ranking.csv",
        index=False,
    )
    pd.DataFrame(
        [
            {
                "model_id": "benchmark_xgb",
                "target_public_label": "label_8k_402_365",
                "train_window": "expanding",
                "pr_auc": 0.03,
                "roc_auc": 0.60,
                "top_10pct_precision": 0.05,
                "top_decile_lift": 1.8,
            },
            {
                "model_id": "benchmark_decoy",
                "target_public_label": "label_8k_402_365",
                "train_window": "rolling_7y",
                "pr_auc": 0.08,
                "roc_auc": 0.75,
                "top_10pct_precision": 0.09,
                "top_decile_lift": 8.0,
            },
        ]
    ).to_csv(
        study_dir / "construct_overlap" / "reciprocal_alignment.csv",
        index=False,
    )

    for table in CURRENT_PACKAGE_TABLES:
        (tables_dir / f"{table}.md").write_text(
            "| Fixture | Value |\n| --- | --- |\n| row | 1 |\n",
            encoding="utf-8",
        )
        (tables_dir / f"{table}.csv").write_text("Fixture,Value\nrow,1\n", encoding="utf-8")
        (tables_dir / f"{table}.tex").write_text("fixture table\n", encoding="utf-8")
    _table_03_frame().to_csv(
        tables_dir / "table_03_public_task_metrics.csv",
        index=False,
    )
    (tables_dir / "table_03_public_task_metrics.md").write_text(
        "| Task | Panel_Positives | Mean_Prevalence | Mean_PR_AUC | Mean_ROC_AUC | "
        "Mean_Brier_Skill | Mean_ECE | n_folds | metric_rows |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| `comment_thread` | 321 | 0.1234 | 0.3000 | 0.7000 | 0.0500 | 0.0400 | 1 | 1 |\n",
        encoding="utf-8",
    )
    _table_09_frame().to_csv(
        tables_dir / "table_09_construct_alignment.csv",
        index=False,
    )
    (tables_dir / "table_09_construct_alignment.md").write_text(
        "| Direction | Model | Top_Decile_Lift |\n"
        "| --- | --- | --- |\n"
        "| Public score to benchmark positives | `public_cascade` | 2.0000 |\n"
        "| Benchmark score to public positives | `benchmark_xgb` | 1.8000 |\n",
        encoding="utf-8",
    )
    for figure in CURRENT_PACKAGE_FIGURES:
        (figures_dir / f"{figure}.png").write_bytes(b"fixture-png")
        (figures_dir / f"{figure}.pdf").write_bytes(b"fixture-pdf")
    table_manifest = {
        key: {
            fmt: {
                "path": f"tables/{stem}.{fmt}",
                "sha256": sha256_path(tables_dir / f"{stem}.{fmt}"),
            }
            for fmt in ("csv", "md", "tex")
        }
        for key, stem in PACKAGE_TABLE_STEMS.items()
    }
    figure_manifest = {
        key: {
            fmt: {
                "path": f"figures/{stem}.{fmt}",
                "sha256": sha256_path(figures_dir / f"{stem}.{fmt}"),
            }
            for fmt in ("png", "pdf")
        }
        for key, stem in PACKAGE_FIGURE_STEMS.items()
    }
    _write_json(
        package_dir / "manifest.json",
        {
            "schema_version": "manuscript-package-v2",
            "study_commit": commit,
            "study_manifest_sha256": sha256_path(study_dir / "study_run_manifest.json"),
            "claim_boundary": _bridge_claim_boundary(
                "wrds_validated",
                "wrds_validated",
            ),
            "tables": table_manifest,
            "figures": figure_manifest,
            "reporting_contract": {
                "reporting_boundaries": reporting_boundaries,
                "feature_family_summary": feature_family_summary,
                "opacity_dml_evidence": dml_evidence,
                "claim_maturity": {
                    "public_prediction": "reportable",
                    "feature_and_window_sensitivity": "supporting",
                    "construct_alignment": "supporting",
                    "opacity_dml": dml_maturity,
                },
                "artifact_ownership": ARTIFACT_OWNERSHIP,
            },
        },
    )
    return {
        "study_dir": study_dir,
        "package_dir": package_dir,
        "tables": CURRENT_PACKAGE_TABLES,
        "figures": CURRENT_PACKAGE_FIGURES,
    }


def _build_fixture_snapshot(
    fixture: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    monkeypatch.setattr(snapshot_module, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(snapshot_module, "DOCS_DIR", tmp_path / "docs")
    monkeypatch.setattr(
        snapshot_module,
        "_latest_public_lake_report",
        lambda: {"timestamp_utc": "2026-07-10T00:00:00Z", "row_counts": {}},
    )
    return snapshot_module.build_snapshot(
        fixture["study_dir"],
        manuscript_package=fixture["package_dir"],
        allow_partial=False,
    )


def _rebind_package_fixture(fixture: dict[str, Any]) -> None:
    study_manifest_path = fixture["study_dir"] / "study_run_manifest.json"
    public_summary_path = fixture["study_dir"] / "public_cascade" / "public_cascade_summary.json"
    package_manifest_path = fixture["package_dir"] / "manifest.json"
    study_manifest = json.loads(study_manifest_path.read_text(encoding="utf-8"))
    public_summary = json.loads(public_summary_path.read_text(encoding="utf-8"))
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    package_manifest["study_commit"] = study_manifest["repo_commit"]
    package_manifest["study_manifest_sha256"] = sha256_path(study_manifest_path)
    package_manifest["reporting_contract"] = snapshot_module._reporting_contract(
        study_manifest,
        public_summary,
    )
    _write_json(package_manifest_path, package_manifest)


def _attach_modern_public_lake_fixture(
    fixture: dict[str, Any],
    tmp_path: Path,
) -> dict[str, Any]:
    run_metadata_path = tmp_path / "public_lake_run_metadata.json"
    issuer_origin_panel_path = tmp_path / "issuer_origin_panel.parquet"
    form_ap_source_metadata_path = tmp_path / "form_ap_source_metadata.json"
    report_path = tmp_path / "public_lake_final_report.json"
    _write_json(run_metadata_path, {"as_of_date": "2026-07-06"})
    issuer_origin_panel_path.write_bytes(b"fixture issuer-origin panel")
    _write_json(form_ap_source_metadata_path, {"source_kind": "verified_zip_member"})
    row_counts = {
        "issuer_dim": 102,
        "filing_dim": 101,
        "filing_xbrl_dim": 110,
        "xbrl_fact_summary": 104,
        "xbrl_core_fact": 103,
        "notes_filing_dim": 111,
        "note_summary": 105,
        "comment_thread": 106,
        "correction_event": 107,
        "issuer_origin_panel": 108,
        "filing_origin_panel": 109,
    }
    _write_json(
        report_path,
        {
            "schema_version": "public-lake-final-report-v1",
            "as_of_date": "2026-07-06",
            "public_lake_run_metadata_sha256": sha256_path(run_metadata_path),
            "issuer_origin_panel_sha256": sha256_path(issuer_origin_panel_path),
            "row_counts": row_counts,
            "row_count_errors": {},
        },
    )
    paths = {
        "public_lake_final_report": report_path,
        "public_lake_run_metadata": run_metadata_path,
        "issuer_origin_panel": issuer_origin_panel_path,
        "form_ap_source_metadata": form_ap_source_metadata_path,
    }
    records = {
        key: {
            "path": str(path),
            "exists": True,
            "sha256": sha256_path(path),
        }
        for key, path in paths.items()
    }
    manifest_path = fixture["study_dir"] / "study_run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_paths = {manifest["inputs"].get(key) for key in paths}
    manifest["inputs"].update({key: str(path) for key, path in paths.items()})
    manifest["provenance"]["input_files"] = [
        record
        for record in manifest["provenance"]["input_files"]
        if record.get("path") not in old_paths
    ] + list(records.values())
    manifest["public_lake_inputs"] = records
    _write_json(manifest_path, manifest)
    _rebind_package_fixture(fixture)
    return {
        "manifest_path": manifest_path,
        "paths": paths,
        "records": records,
        "row_counts": row_counts,
    }


def test_snapshot_source_roles_follow_semantic_inputs_when_records_are_shuffled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    modern = _attach_modern_public_lake_fixture(fixture, tmp_path)
    manifest_path = modern["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest["provenance"]["input_files"]
    manifest["provenance"]["input_files"] = [
        records[6],
        records[4],
        records[0],
        records[3],
        records[2],
        records[5],
        records[1],
    ]
    _write_json(manifest_path, manifest)
    _rebind_package_fixture(fixture)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)

    expected = [
        ("Detected-misstatement benchmark input", "1"),
        ("Public issuer dimension input", "2"),
        ("Public issuer-origin panel input", modern["records"]["issuer_origin_panel"]["sha256"]),
        (
            "Public-lake final report input",
            modern["records"]["public_lake_final_report"]["sha256"],
        ),
        ("CIK-GVKEY bridge input", "5"),
        (
            "Public-lake run metadata input",
            modern["records"]["public_lake_run_metadata"]["sha256"],
        ),
        (
            "Form AP source metadata input",
            modern["records"]["form_ap_source_metadata"]["sha256"],
        ),
    ]
    for role, digest in expected:
        expected_hash = digest * 64 if len(digest) == 1 else digest
        assert f"| {role} | `True` | `{expected_hash}` |" in results


def test_snapshot_uses_pinned_public_lake_report_counts_and_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    _attach_modern_public_lake_fixture(fixture, tmp_path)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)

    assert "| Public-lake final-report schema | `public-lake-final-report-v1` |" in results
    assert results.count("#### `table_02_public_lake_scale`") == 1
    assert "### Public Lake and Gold Panel Scale" not in results


@pytest.mark.parametrize(
    "missing_key",
    [
        "public_lake_final_report",
        "public_lake_run_metadata",
        "issuer_origin_panel",
        "form_ap_source_metadata",
    ],
)
def test_snapshot_rejects_incomplete_modern_public_lake_input_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_key: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    modern = _attach_modern_public_lake_fixture(fixture, tmp_path)
    manifest_path = modern["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["public_lake_inputs"].pop(missing_key)
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match=f"pinned public-lake inputs missing {missing_key}"):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    ("record_key", "message"),
    [
        ("public_lake_run_metadata", "pinned public-lake run metadata hash mismatch"),
        ("issuer_origin_panel", "pinned issuer-origin panel hash mismatch"),
    ],
)
def test_snapshot_rejects_hash_mismatch_in_bound_public_lake_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_key: str,
    message: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    modern = _attach_modern_public_lake_fixture(fixture, tmp_path)
    manifest_path = modern["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["public_lake_inputs"][record_key]["sha256"] = "0" * 64
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match=message):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


def test_snapshot_rejects_modern_input_path_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    modern = _attach_modern_public_lake_fixture(fixture, tmp_path)
    manifest_path = modern["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["inputs"]["public_lake_final_report"] = str(tmp_path / "different.json")
    _write_json(manifest_path, manifest)

    with pytest.raises(
        ValueError,
        match="pinned public-lake final report path does not match manifest.inputs",
    ):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


def test_snapshot_rejects_modern_provenance_sha_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    modern = _attach_modern_public_lake_fixture(fixture, tmp_path)
    manifest_path = modern["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_metadata_path = str(modern["paths"]["public_lake_run_metadata"])
    for record in manifest["provenance"]["input_files"]:
        if record.get("path") == run_metadata_path:
            record["sha256"] = "0" * 64
    _write_json(manifest_path, manifest)

    with pytest.raises(
        ValueError,
        match="pinned public-lake run metadata SHA does not match provenance",
    ):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("remove", "pinned Form AP source metadata provenance record is missing"),
        ("duplicate", "pinned Form AP source metadata provenance record is ambiguous"),
    ],
)
def test_snapshot_rejects_invalid_form_ap_provenance_cardinality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    modern = _attach_modern_public_lake_fixture(fixture, tmp_path)
    manifest_path = modern["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    form_ap_path = str(modern["paths"]["form_ap_source_metadata"])
    matching = [
        record
        for record in manifest["provenance"]["input_files"]
        if record.get("path") == form_ap_path
    ]
    if mutation == "remove":
        manifest["provenance"]["input_files"] = [
            record
            for record in manifest["provenance"]["input_files"]
            if record.get("path") != form_ap_path
        ]
    else:
        manifest["provenance"]["input_files"].append(dict(matching[0]))
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match=message):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("report_field", "public lake final report fields must be exactly"),
        ("row_count", "public lake final report.row_counts keys must be exactly"),
    ],
)
def test_snapshot_reuses_exact_public_lake_final_report_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
    message: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    modern = _attach_modern_public_lake_fixture(fixture, tmp_path)
    report_path = modern["paths"]["public_lake_final_report"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if missing == "report_field":
        report.pop("as_of_date")
    else:
        report["row_counts"].pop("filing_xbrl_dim")
    _write_json(report_path, report)
    digest = sha256_path(report_path)
    manifest_path = modern["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["public_lake_inputs"]["public_lake_final_report"]["sha256"] = digest
    for record in manifest["provenance"]["input_files"]:
        if record.get("path") == str(report_path):
            record["sha256"] = digest
    _write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match=message):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    ("record", "error", "message"),
    [
        ("malformed", ValueError, "pinned public-lake final report record is malformed"),
        ("missing", FileNotFoundError, "pinned public-lake final report is missing"),
        ("hash_mismatch", ValueError, "pinned public-lake final report hash mismatch"),
    ],
)
def test_snapshot_rejects_invalid_pinned_public_lake_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record: str,
    error: type[Exception],
    message: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    modern = _attach_modern_public_lake_fixture(fixture, tmp_path)
    report_path = modern["paths"]["public_lake_final_report"]
    manifest_path = modern["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if record == "malformed":
        pinned: object = "not-a-record"
    else:
        path = tmp_path / "missing.json" if record == "missing" else report_path
        digest = "0" * 64 if record == "hash_mismatch" else sha256_path(report_path)
        pinned = {
            "path": str(path),
            "exists": True,
            "sha256": digest,
        }
        manifest["inputs"]["public_lake_final_report"] = str(path)
        for provenance_record in manifest["provenance"]["input_files"]:
            if provenance_record.get("path") == str(report_path):
                provenance_record.update(pinned)
    manifest["public_lake_inputs"]["public_lake_final_report"] = pinned
    _write_json(manifest_path, manifest)

    with pytest.raises(error, match=message):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


@pytest.mark.parametrize("path_kind", ["absolute", "traversal"])
def test_manifest_format_path_rejects_escaping_canonical_record(
    tmp_path: Path,
    path_kind: str,
) -> None:
    package_dir = tmp_path / "manuscript_package"
    fallback = package_dir / "tables" / "table_01.md"
    fallback.parent.mkdir(parents=True)
    fallback.write_text("legacy fallback", encoding="utf-8")
    declared = str(tmp_path / "outside.md") if path_kind == "absolute" else "../outside.md"

    with pytest.raises(ValueError, match="canonical manifest path escapes manuscript package"):
        snapshot_module._manifest_format_path(
            package_dir,
            {"md": {"path": declared, "sha256": "a" * 64}},
            "md",
            fallback,
        )


def test_manifest_format_path_rejects_canonical_symlink_escape(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "manuscript_package"
    tables_dir = package_dir / "tables"
    outside_dir = tmp_path / "outside"
    tables_dir.mkdir(parents=True)
    outside_dir.mkdir()
    fallback = tables_dir / "table_01.md"
    fallback.write_text("legacy fallback", encoding="utf-8")
    (outside_dir / "declared.md").write_text("outside", encoding="utf-8")
    (tables_dir / "escape").symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="canonical manifest path escapes manuscript package"):
        snapshot_module._manifest_format_path(
            package_dir,
            {
                "md": {
                    "path": "tables/escape/declared.md",
                    "sha256": "a" * 64,
                }
            },
            "md",
            fallback,
        )


def test_snapshot_construct_rows_read_generated_table_only(tmp_path: Path) -> None:
    package_dir = tmp_path / "manuscript_package"
    tables_dir = package_dir / "tables"
    tables_dir.mkdir(parents=True)
    _table_09_frame().to_csv(
        tables_dir / "table_09_construct_alignment.csv",
        index=False,
    )

    rows = _construct_alignment_rows(package_dir)

    assert len(rows) == 2
    assert {row[1] for row in rows} == {"`public_cascade`", "`benchmark_xgb`"}
    assert {row[7] for row in rows} == {"2.0000", "1.8000"}


@pytest.mark.parametrize("row_count", [1, 3])
def test_snapshot_construct_rows_require_exactly_two_primary_rows(
    tmp_path: Path,
    row_count: int,
) -> None:
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    frame = pd.concat([_table_09_frame(), _table_09_frame().iloc[[0]]], ignore_index=True)
    frame.iloc[:row_count].to_csv(tables_dir / "table_09_construct_alignment.csv", index=False)

    with pytest.raises(
        ValueError, match="generated Table 9 must contain exactly two primary rows"
    ):
        _construct_alignment_rows(tmp_path)


def test_snapshot_construct_rows_require_generated_table_schema(tmp_path: Path) -> None:
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    _table_09_frame().drop(columns="Lift_Bootstrap_Interval").to_csv(
        tables_dir / "table_09_construct_alignment.csv",
        index=False,
    )

    with pytest.raises(
        ValueError, match="generated Table 9 must contain exactly two primary rows"
    ):
        _construct_alignment_rows(tmp_path)


@pytest.mark.parametrize(
    ("diagnostic_dml", "expected_maturity"),
    [(True, "diagnostic"), (False, "deferred")],
)
def test_generated_snapshot_is_owner_directed_results_and_discussion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    diagnostic_dml: bool,
    expected_maturity: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path, diagnostic_dml=diagnostic_dml)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)

    copied_asset_dir = tmp_path / "docs" / "assets" / "results_snapshot"
    for figure in CURRENT_PACKAGE_FIGURES:
        assert (copied_asset_dir / f"{figure}.png").read_bytes() == b"fixture-png"

    experiment_headings = [
        "## Results for Experiment 1: Label Observability and Detection Timing",
        "## Results for Experiment 2: Concept Drift and Model Shelf-Life",
        "## Results for Experiment 3: Opacity and Public Review/Correction Risk",
        "## Results for Experiment 4: Public Cascade Construction",
        "## Results for Experiment 5: Public Cascade Prediction",
        "## Results for Experiment 6: Detected-Misstatement Benchmark and Public Cascade Overlap",
    ]
    discussion_headings = [
        "### Answers to the research questions",
        "### Comparison with prior literature",
        "### Accounting and institutional interpretation",
        "### Selection and visibility",
        "### Generalizability",
        "### Limitations and future work",
        "### Claim ledger",
    ]
    top_level = [
        "# Results and Discussion",
        "## Connection to Paper Plan",
        "## Results Overview",
        *experiment_headings,
        "## Discussion",
        "## Reproducibility and Provenance",
    ]
    positions = [results.index(heading) for heading in top_level]
    assert positions == sorted(positions)
    assert results.count("## Results for Experiment ") == 6
    assert [line for line in results.splitlines() if line.startswith("## ")][-1] == (
        "## Reproducibility and Provenance"
    )

    experiment_blocks: dict[str, str] = {}
    for index, heading in enumerate(experiment_headings):
        end_heading = (
            experiment_headings[index + 1]
            if index + 1 < len(experiment_headings)
            else "## Discussion"
        )
        block = results[results.index(heading) : results.index(end_heading)]
        assert block.count("### Interpretation") == 1
        experiment_blocks[f"experiment_{index + 1}"] = block
    discussion = results[results.index("## Discussion") :]
    discussion_positions = [discussion.index(heading) for heading in discussion_headings]
    assert discussion_positions == sorted(discussion_positions)

    owner_blocks = {
        **experiment_blocks,
        "reproducibility": results[results.index("## Reproducibility and Provenance") :],
    }
    for owner, owned in ARTIFACT_OWNERSHIP.items():
        for table_key in owned["tables"]:
            marker = f"#### `{PACKAGE_TABLE_STEMS[table_key]}`"
            assert results.count(marker) == 1
            assert marker in owner_blocks[owner]
        for figure_key in owned["figures"]:
            stem = PACKAGE_FIGURE_STEMS[figure_key]
            embeds = re.findall(rf"!\[[^\]]+\]\([^)]*{re.escape(stem)}\.png\)", results)
            assert len(embeds) == 1
            assert embeds[0] in owner_blocks[owner]
    assert sum(results.count(f"#### `{stem}`") for stem in CURRENT_PACKAGE_TABLES) == 16
    assert results.count("![") == 5

    dynamic_surfaces = {
        "experiment_1": ["Detected-Misstatement Benchmark Panel", "Full Window Summary"],
        "experiment_2": [
            "Strongest Structural-Break Diagnostics",
            "Mean Feature-Family Importance",
        ],
        "experiment_4": ["Public Cascade Readiness", "Public Cascade Fit and Skip Status"],
        "experiment_5": ["Public Peer Task Summary"],
        "experiment_6": [
            "Exploratory maxima (post-hoc)",
            "Aggregation Sensitivity",
            "Benchmark-Positive Public-Label Co-occurrence",
            "Event-Time Concentration",
        ],
    }
    for owner, headings in dynamic_surfaces.items():
        for heading in headings:
            assert heading in owner_blocks[owner]

    for phrase in [
        "Prior-filing history (legacy artifact key: oversight)",
        "`prior_filing_count`",
        "not PCAOB inspection",
        "`is_domestic_us_gaap_proxy`",
        "10-K/10-K/A with no observed same-year FPI-form proxy",
        "validates neither FPI status, domicile, nor US GAAP",
        "PCAOB inspection archives are provenance inputs",
        "events are not joined to Gold",
        "no model-eligible inspection features",
        "adjusted-association diagnostic",
        f"aggregate maturity is `{expected_maturity}`",
        "post-year-proxy uncensored public-model panel",
        "is_constant_zero=false",
        "all + expanding",
    ]:
        assert phrase in results
    for local_path_marker in [USER_PATH_PREFIX, VOLUME_PATH_PREFIX, CLOUD_STORAGE_MARKER]:
        assert local_path_marker not in results
    for forbidden in [
        "Evidence Gallery",
        "Inline Figure Gallery",
        "Inline Table Gallery",
        "Manuscript Package Tables and Figures",
        "Selected Artifact Index",
        "Full Study Artifact Inventory",
        "Highest equal-task",
        "Sellable claim",
        "Max config PR-AUC",
        "Domestic US GAAP only",
    ]:
        assert forbidden not in results


@pytest.mark.parametrize(
    ("component_tier", "artifact_tier", "expected_tier"),
    [
        ("candidate_external", "candidate_external", "candidate_external"),
        (None, None, "none"),
        (
            "wrds_validated",
            "candidate_external",
            "component=wrds_validated; manifest=candidate_external",
        ),
        (
            "candidate_external",
            "wrds_validated",
            "component=candidate_external; manifest=wrds_validated",
        ),
    ],
    ids=["candidate", "missing", "validated-component-only", "validated-artifact-only"],
)
def test_candidate_bridge_snapshot_is_noncanonical_and_nonassertive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    component_tier: str | None,
    artifact_tier: str | None,
    expected_tier: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    study_manifest_path = fixture["study_dir"] / "study_run_manifest.json"
    study_manifest = json.loads(study_manifest_path.read_text(encoding="utf-8"))
    study_manifest["components"]["construct_overlap"]["validation_tier"] = component_tier
    study_manifest["claim_maturity"]["construct_alignment"] = "supporting"
    _write_json(study_manifest_path, study_manifest)
    _rebind_package_fixture(fixture)
    construct_manifest_path = (
        fixture["study_dir"] / "construct_overlap" / "construct_overlap_manifest.json"
    )
    construct_manifest = json.loads(construct_manifest_path.read_text(encoding="utf-8"))
    construct_manifest["validation_tier"] = artifact_tier
    _write_json(construct_manifest_path, construct_manifest)
    package_manifest_path = fixture["package_dir"] / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    package_manifest["claim_boundary"] = _bridge_claim_boundary(
        component_tier,
        artifact_tier,
    )
    _write_json(package_manifest_path, package_manifest)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)
    normalized = " ".join(results.lower().split())

    assert "| Canonical status | `NON-CANONICAL` |" in results
    if component_tier != "wrds_validated":
        assert "construct component validation tier is not `wrds_validated`" in results
    if artifact_tier != "wrds_validated":
        assert "construct manifest validation tier is not `wrds_validated`" in results
    assert expected_tier in results
    assert "diagnostic" in normalized
    assert "deferred" in normalized
    assert "construct-overlap headline claims are deferred" in normalized
    assert "lift above one is a numeric pattern in the diagnostic rows" in normalized
    assert "cross-construct claim is deferred" in normalized
    assert "lift above one shows enrichment" not in normalized
    assert (
        "headline claims should describe filing-origin measurement, prevalence-aware ranking, "
        "and construct overlap" not in normalized
    )
    for forbidden in [
        "confirmed wrds",
        "wrds-validated",
        "manuscript-grade",
        "supports the integrated",
        "support the integrated",
        "integrated construct argument",
    ]:
        assert forbidden not in normalized


@pytest.mark.parametrize(
    ("component_tier", "artifact_tier", "package_component", "package_artifact"),
    [
        (
            "candidate_external",
            "candidate_external",
            "wrds_validated",
            "wrds_validated",
        ),
        (
            "wrds_validated",
            "wrds_validated",
            "candidate_external",
            "candidate_external",
        ),
    ],
    ids=["live-candidate-stale-validated-package", "live-validated-stale-candidate-package"],
)
def test_snapshot_rejects_stale_package_bridge_boundary_before_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    component_tier: str,
    artifact_tier: str,
    package_component: str,
    package_artifact: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    study_manifest_path = fixture["study_dir"] / "study_run_manifest.json"
    study_manifest = json.loads(study_manifest_path.read_text(encoding="utf-8"))
    study_manifest["components"]["construct_overlap"]["validation_tier"] = component_tier
    _write_json(study_manifest_path, study_manifest)
    _rebind_package_fixture(fixture)
    construct_manifest_path = (
        fixture["study_dir"] / "construct_overlap" / "construct_overlap_manifest.json"
    )
    construct_manifest = json.loads(construct_manifest_path.read_text(encoding="utf-8"))
    construct_manifest["validation_tier"] = artifact_tier
    _write_json(construct_manifest_path, construct_manifest)
    package_manifest_path = fixture["package_dir"] / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    package_manifest["claim_boundary"] = _bridge_claim_boundary(
        package_component,
        package_artifact,
    )
    _write_json(package_manifest_path, package_manifest)
    stale_marker = "WRDS-validated stale package claim"
    (fixture["package_dir"] / "tables" / "table_09_construct_alignment.md").write_text(
        stale_marker,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="package claim boundary"):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


def test_snapshot_rejects_missing_package_claim_boundary(tmp_path: Path) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    package_manifest_path = fixture["package_dir"] / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    package_manifest.pop("claim_boundary")
    _write_json(package_manifest_path, package_manifest)

    with pytest.raises(ValueError, match="package claim boundary"):
        snapshot_module.build_snapshot(
            fixture["study_dir"],
            manuscript_package=fixture["package_dir"],
            allow_partial=False,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("study_commit", "b" * 40),
        ("study_manifest_sha256", "0" * 64),
    ],
)
def test_snapshot_rejects_package_study_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    package_manifest_path = fixture["package_dir"] / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    package_manifest[field] = value
    _write_json(package_manifest_path, package_manifest)

    with pytest.raises(ValueError, match=field):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


@pytest.mark.parametrize("mutation", ["dml", "partner"])
def test_snapshot_rejects_package_reporting_contract_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    package_manifest_path = fixture["package_dir"] / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    contract = package_manifest["reporting_contract"]
    if mutation == "dml":
        contract["opacity_dml_evidence"]["status_by_outcome"]["comment_thread"] = (
            "skipped_constant_treatment"
        )
    else:
        contract["reporting_boundaries"]["partner_nonadministrative_amendment"]["maximum"] = 999
    _write_json(package_manifest_path, package_manifest)

    with pytest.raises(ValueError, match="reporting contract"):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


@pytest.mark.parametrize("malformation", ["owner", "tables", "figures"])
def test_snapshot_rejects_malformed_artifact_ownership_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    package_manifest_path = fixture["package_dir"] / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text(encoding="utf-8"))
    ownership = package_manifest["reporting_contract"]["artifact_ownership"]
    if malformation == "owner":
        ownership["experiment_1"] = []
    else:
        ownership["experiment_1"][malformation] = None
    _write_json(package_manifest_path, package_manifest)

    with pytest.raises(ValueError, match="artifact_ownership"):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


def test_generated_snapshot_sanitizes_external_fixture_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)

    assert "`<external>/study`" in results
    for local_path_marker in [
        str(tmp_path),
        USER_PATH_PREFIX,
        VOLUME_PATH_PREFIX,
        CLOUD_STORAGE_MARKER,
    ]:
        assert local_path_marker not in results


def test_generated_snapshot_uses_generated_table_3_for_main_ranking_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)

    main_ranking = results.split("#### `table_03_public_task_metrics`", maxsplit=1)[1].split(
        "#### `table_04_feature_family_metrics`", maxsplit=1
    )[0]
    assert (
        "| `comment_thread` | 321 | 0.1234 | 0.3000 | 0.7000 | 0.0500 | 0.0400 | 1 | 1 |"
        in main_ranking
    )
    assert "0.6000" not in main_ranking
    assert "0.9000" not in main_ranking


@pytest.mark.parametrize("invalid_case", ["empty", "duplicate_task", "missing_column"])
def test_generated_snapshot_requires_valid_generated_table_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_case: str,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    table_3 = _table_03_frame()
    if invalid_case == "empty":
        table_3 = table_3.iloc[0:0]
    elif invalid_case == "duplicate_task":
        table_3 = pd.concat([table_3, table_3], ignore_index=True)
    else:
        table_3 = table_3.drop(columns="Mean_ECE")
    table_3.to_csv(
        fixture["package_dir"] / "tables" / "table_03_public_task_metrics.csv",
        index=False,
    )

    with pytest.raises(
        ValueError,
        match="generated Table 3 must contain nonempty unique task rows with display columns",
    ):
        _build_fixture_snapshot(fixture, tmp_path, monkeypatch)


def test_generated_snapshot_keeps_raw_maxima_exploratory_and_post_hoc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)

    primary = results.split("#### `table_09_construct_alignment`", maxsplit=1)[1].split(
        "#### `table_15_bridge_overlap_matrix`", maxsplit=1
    )[0]
    exploratory = results.split("### Exploratory maxima", maxsplit=1)[1].split(
        "### Aggregation Sensitivity", maxsplit=1
    )[0]
    assert "`public_cascade`" in primary
    assert "`benchmark_xgb`" in primary
    assert "public_decoy" not in primary
    assert "benchmark_decoy" not in primary
    assert "post-hoc" in exploratory
    assert "public_decoy" in exploratory
    assert "benchmark_decoy" in exploratory
    assert "17" in exploratory
    assert "23" in exploratory
    assert "9.0000" in exploratory
    assert "8.0000" in exploratory
    assert "2.0000" in exploratory
    assert "1.8000" in exploratory
    assert "7.0000" in exploratory
    assert "6.2000" in exploratory


def test_generated_snapshot_lists_every_failed_canonical_predicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)
    manifest_path = fixture["study_dir"] / "study_run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["git_dirty"] = True
    manifest["provenance"]["commit_sha"] = "b" * 40
    manifest["public_lake_provenance"].update(
        {
            "git_dirty": True,
            "fresh_build": False,
            "as_of_date": "2026-07-05",
            "commit_sha": "c" * 40,
        }
    )
    _write_json(manifest_path, manifest)
    _rebind_package_fixture(fixture)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)

    assert "| Canonical status | `NON-CANONICAL` |" in results
    for reason in [
        "dirty-state: study git_dirty is not false",
        "dirty-state: public-lake git_dirty is not false",
        "freshness: public-lake fresh_build is not true",
        "date: public-data as-of date is not 2026-07-06",
        "identity: study and provenance commits differ",
        "identity: study and public-lake commits differ",
    ]:
        assert reason in results


def test_readme_home_explains_project_and_workflow() -> None:
    home = _read("README.md")
    required_phrases = [
        "Research Object",
        "Public Review-and-Correction Labels",
        "Repository Layout",
        "Execution Contract",
        "Public Lake",
        "Primary Artifacts",
        "Bridge Inputs",
        "Current Artifact Boundary",
        "public observability states",
        "SEC filing review process",
        "SEC EDGAR filing access",
        "SEC Form 8-K",
        "just full mode=full dataset=raw",
        "just task study raw",
        "--peer-target public",
    ]
    for phrase in required_phrases:
        assert phrase in home


def test_paper_plan_documents_required_research_spine() -> None:
    plan = _read("docs/paper_plan.md")
    headings = [
        line for line in plan.splitlines() if line.startswith("# ") or line.startswith("## ")
    ]
    assert headings == [
        "# Paper Plan",
        "## Introduction",
        "## Materials and Methods",
        "## Expected Experiments",
        "## Reproducibility and Execution Contract",
    ]
    required_phrases = [
        "Overview and Why This Work",
        "Literature Review and Existing Results",
        "Positioning Against Existing Results",
        "Research Question and Contribution",
        "Research Gap",
        "Our Contribution and Claim Boundary",
        "**Core question.**",
        "**Timing contamination.**",
        "**Main contribution.**",
        "**Construct claim.**",
        "**Evidence requirement.**",
        "filing-origin public reporting-risk estimand",
        "not same-estimand performance rankings",
        "metric-compatible ranking evidence",
        "Peer models and metrics",
        "bridge-based overlap validation",
        "detected-misstatement benchmark labels",
        "ex post detected misconduct",
        "review-and-correction risk rather than unobserved fraud occurrence",
        "does not by itself identify unobserved fraud occurrence, causal effects",
        "positive-class rate",
        "random-ranking baseline for PR-AUC",
        "annual out-of-time evaluation",
        "Cross-fitting appears separately",
        "Double / Debiased Machine Learning (DML)",
        "not alternative names for fraud",
        "Materials and Methods",
        "Data and Market/Institutional Setting",
        "Reproduction Inputs",
        "Source-to-table mapping",
        "Data Engineering and Preprocessing Overview",
        "Public Review-and-Correction Labels",
        "label_comment_thread_365 = 1",
        "Horizon-specific censoring",
        "Leakage exclusions",
        "Fold-local transformations",
        "Public peer mapping",
        "Methods Including Models",
        "Model Families",
        "Performance Metrics and Selection Criteria",
        "Metric Selection Criteria",
        "Public filing-origin cascade",
        "Bridge and interpretation layer",
        "external benchmark, not SEC/PCAOB public lake",
        "detected-misstatement peer suite",
        "public-label peer suite",
        "same metric vocabulary as benchmark",
        "Construct-overlap checks",
        "```mermaid",
        "flowchart LR",
        "pre-disclosure public reporting-risk state",
        "gvkey-CIK-year",
        "Label Observability and Detection Timing",
        "Concept Drift and Model Shelf-Life",
        "Opacity and Public Review/Correction Risk",
        "Public Cascade Prediction",
        "Detected-Misstatement Benchmark and Public Cascade Overlap",
        "[SEC Inline eXtensible Business Reporting Language (XBRL)](https://www.sec.gov/data-research/structured-data/inline-xbrl)",
        "label_comment_thread_365",
        "label_8k_402_365",
        "broad amendment/friction signal",
        "Brier Skill Score",
        "native missing-value handling",
        "Bao-style top-fraction balanced accuracy",
        "SEC filing review process",
        "SEC EDGAR filing access",
        "SEC Form 8-K",
        "operational command surface",
        "Expected Evidence Pattern",
        "Connection to Results Snapshot",
        "Artifact Map",
        "Reproducibility and Execution Contract",
        "just full mode=full dataset=raw",
        "artifacts/full_with_peer",
        "--peer-comparison-mode full",
        "--peer-target both",
        "repository home page",
    ]
    for phrase in required_phrases:
        assert phrase in plan
    for experiment in range(1, 7):
        block = plan.split(f"### Experiment {experiment}:", maxsplit=1)[1].split(
            "### Experiment " if experiment < 6 else "### Expected Evidence Pattern",
            maxsplit=1,
        )[0]
        for anchor in ["**Purpose.**", "**Design.**", "**Outputs.**", "**Interpretation.**"]:
            assert anchor in block
    assert "grid cards" not in plan
    assert "How to use this page" not in plan
    assert "This paper is" not in plan


def test_paper_plan_assigns_results_owners_and_exact_claim_boundaries() -> None:
    plan = _read("docs/paper_plan.md")
    experiment_2 = plan.split("### Experiment 2:", maxsplit=1)[1].split(
        "### Experiment 3:", maxsplit=1
    )[0]
    experiment_5 = plan.split("### Experiment 5:", maxsplit=1)[1].split(
        "### Experiment 6:", maxsplit=1
    )[0]

    assert "Table 4" not in experiment_2
    assert "Table 14" not in experiment_2
    assert "dynamic-only" in experiment_2
    for artifact in ["Table 3", "Table 4", "Table 7", "Table 13", "Table 14", "Table 17"]:
        assert artifact in experiment_5
    for phrase in [
        "Prior-filing history (legacy artifact key: oversight)",
        "`prior_filing_count`",
        "not PCAOB inspection",
        "`is_domestic_us_gaap_proxy`",
        "selected 10-K/10-K/A issuer-years with no observed same-year 20-F/40-F/6-K proxy",
        "validates neither FPI status, domicile, nor US GAAP",
        "PCAOB inspection archives are provenance/Bronze inputs only",
        "events are not joined to Gold",
        "no inspection model features",
        "PCAOB Form AP may supply auditor and engagement-partner features",
        "at least one required outcome is fitted",
        "all-skipped or disabled",
        "post-year-proxy uncensored public-model panel",
        "counts, range, constant-zero status, and equality to Item 4.02",
        "source and feature readiness",
        "revision-frozen `all + expanding`",
    ]:
        assert phrase in plan


def test_paper_plan_states_public_sample_and_inspection_boundaries() -> None:
    plan = _read("docs/paper_plan.md")

    for phrase in [
        "selected 10-K/10-K/A issuer-years with no observed same-year 20-F/40-F/6-K proxy",
        "validates neither FPI status, domicile, nor US GAAP",
        "PCAOB inspection archives are provenance/Bronze inputs only",
        "inspection events are not joined to Gold",
        "no inspection model features",
        "PCAOB Form AP may supply auditor and engagement-partner features",
    ]:
        assert phrase in plan

    for stale_claim in [
        "Domestic U.S. GAAP issuer-years",
        "domestic U.S. GAAP proxy",
        "PCAOB inspection tables",
        "PCAOB Form AP and inspection sources produce auditor and oversight features",
    ]:
        assert stale_claim not in plan


def test_paper_plan_displays_prior_filing_history_on_paper_facing_surfaces() -> None:
    plan = _read("docs/paper_plan.md")
    legacy_display = "Prior-filing history (legacy artifact key: oversight)"
    blocks = [
        plan.split('subgraph PUBLIC["', maxsplit=1)[1].split("    end", maxsplit=1)[0],
        plan.split("### Preprocessing and Feature Construction", maxsplit=1)[1].split(
            "#### Visibility/History Baseline", maxsplit=1
        )[0],
        plan.split("#### Model Families", maxsplit=1)[1].split(
            "#### Model Selection and Skip Rules", maxsplit=1
        )[0],
        plan.split("### Experiment 3:", maxsplit=1)[1].split("### Experiment 4:", maxsplit=1)[0],
        plan.split("### Experiment 5:", maxsplit=1)[1].split("### Experiment 6:", maxsplit=1)[0],
        plan.split("#### Expected Evidence Pattern", maxsplit=1)[1].split(
            "#### Connection to Results Snapshot", maxsplit=1
        )[0],
    ]

    for block in blocks:
        assert "prior-filing history" in block.lower()
        assert re.search(r"\boversight\b", block.replace(legacy_display, "")) is None


def test_paper_plan_is_p0_executable_spec_not_result_prompt() -> None:
    plan = _read("docs/paper_plan.md")
    required_phrases = [
        "Measurement Design",
        "Methods Including Models",
        "Evidence Gates",
        "Benchmark timing",
        "Public cascade",
        "revision-frozen primary specification",
        "Bridge overlap",
        "Detected-Misstatement Benchmark Labels",
        "timing_coverage.csv",
        "timing_claim_status",
        "proxy_drop_observed",
        "proxy_imputed_lag",
        "flowchart LR",
        "Public-label opacity DML",
        "not proof of look-ahead bias by itself",
        "public-label PLR spec",
        "D = missingness_density_score",
        "Data integrity gates",
        "xbrl_ratio_*",
        "visibility/history information set",
        "Claim Boundaries",
        "Bridge Validation Inputs",
        "bridge_probe_summary.json",
        "coverage_report.csv",
        "construct_overlap/public_score_benchmark_ranking.csv",
        "construct_overlap/reciprocal_alignment.csv",
        "validation_tier = wrds_validated",
        "validation_tier = wrds_validated",
        "raw_identifier_blocker",
        "Evidence Gates",
        "External gvkey-CIK bridge rows are no longer used",
        "just check",
        "just full mode=full dataset=raw",
        "--peer-comparison-mode full",
        "--peer-target public",
        "repository home page",
    ]
    for phrase in required_phrases:
        assert phrase in plan
    assert "Expected result" not in plan
    assert "data/public_lake_smoke" not in plan


def test_paper_plan_stabilizes_revision_frozen_methods_and_reporting_contract() -> None:
    plan = _read("docs/paper_plan.md")
    normalized_plan = " ".join(plan.split())
    public_config = _read_yaml("config/public_cascade.yaml")

    configured_families = public_config["analysis"]["feature_sets"]
    assert configured_families == [
        "metadata",
        "xbrl",
        "auditor",
        "oversight",
        "visibility_history",
        "all",
    ]
    display_names = {
        "metadata": "metadata",
        "xbrl": "XBRL",
        "auditor": "auditor",
        "oversight": "Prior-filing history (legacy artifact key: oversight)",
        "visibility_history": "visibility/history",
        "all": "all",
    }
    displayed_families = [display_names[family] for family in configured_families]
    family_contract = ", ".join(displayed_families[:-1]) + ", and " + displayed_families[-1]
    model_family_block = plan.split("#### Model Families", maxsplit=1)[1].split(
        "#### Model Selection and Skip Rules", maxsplit=1
    )[0]
    expectation_block = plan.split("#### Expected Evidence Pattern", maxsplit=1)[1].split(
        "#### Connection to Results Snapshot", maxsplit=1
    )[0]
    for block in [model_family_block, expectation_block]:
        assert family_contract in block
        assert "notes/disclosure-breadth variables enter `all` only" in block
        for stale_family in ["text/notes", "note-opacity"]:
            assert stale_family not in block

    required_phrases = [
        "as_of_date=2026-07-06",
        "fiscal years 2011-2024",
        "archive-first Form AP source contract",
        "verified metadata sidecar",
        "atomically replaces",
        "must not fall back to an older CSV",
        "Sequential attrition",
        "source issuer-origin rows",
        "observable 365-day horizon",
        "task-specific exclusions",
        "revision-frozen `all + expanding`",
        "Table 3 and Figure 1",
        "visibility/history information set",
        "information-set comparison, not a causal selection correction",
        "notes/disclosure-breadth variables enter `all`",
        "no standalone text-family ablation",
        "objective=binary:logistic",
        "eval_metric=logloss",
        "n_estimators=250",
        "max_depth=4",
        "learning_rate=0.05",
        "subsample=0.8",
        "colsample_bytree=0.8",
        "min_child_weight=5.0",
        "reg_lambda=1.0",
        "tree_method=hist",
        "base seed=42 with task-isolated deterministic seeds",
        "configuration default `n_jobs=4`",
        "canonical paper command overrides realized model threads to `2`",
        "run manifest must record `2`",
        "scale_pos_weight=max(1, training negatives/training positives)",
        "numeric columns are cast to float and retain NaN",
        "categoricals are fitted on training years only",
        "constant-imputed to `__MISSING__`",
        "unknown test categories ignored",
        "one-class train or test task/folds are skipped and reported",
        "expanding and rolling 5-, 7-, and 10-year windows",
        "excluding-2020 PR-AUC sensitivity",
        "Brier score",
        "Brier Skill Score",
        "expected calibration error",
        "seed 42 and 1,000 bootstrap draws",
        "primary plus the top five exploratory rows in each direction",
        "Tables 4 and 14 belong to Experiment 5",
        "Table 18",
        "reviewer archive",
        "canonical manifest gate",
        "just data full fresh",
        "just task study raw artifacts/full_with_peer",
        "--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated",
        "`just full mode=full dataset=raw` remains a convenience workflow",
        "not the canonical paper run",
    ]
    for phrase in required_phrases:
        assert phrase in normalized_plan

    public_to_benchmark = """model_id: public_cascade
task: 8k_402
feature_set: all
train_window: expanding
label_mode: benchmark_naive
score_aggregation: mean
bridge_tier: high_confidence"""
    benchmark_to_public = """model_id: benchmark_xgb
target_public_label: label_8k_402_365
feature_set: benchmark_all
train_window: expanding
label_mode: naive
score_aggregation: benchmark_score
bridge_tier: high_confidence"""
    assert plan.count(public_to_benchmark) == 1
    assert plan.count(benchmark_to_public) == 1

    for realized in [
        "205,652",
        "97,027",
        "96,827",
        "96,733",
        "0.3679",
        "0.2557",
        "0.0508",
        "current full-run state is",
    ]:
        assert realized not in plan


def test_paper_plan_documents_prior_literature_and_intended_contribution() -> None:
    plan = _read("docs/paper_plan.md")
    required_phrases = [
        "Literature Review and Existing Results",
        "Positioning Against Existing Results",
        "Dechow, Ge, Larson, and Sloan",
        "Perols",
        "Bao, Ke, Li, Yu, and Zhang",
        "Bertomeu, Cheynel, Floyd, and Pan",
        "Barton, Burnett, Gunny, and Miller",
        "Dyck, Morse, and Zingales",
        "Cassell, Cunningham, and Myers",
        "Bozanic, Dietrich, and Johnson",
        "Brown, Tian, and Tucker",
        "not same-estimand performance rankings",
        "does not mechanically force an earlier-stage label",
        "Dechow-style scores",
        "benchmark model zoo",
        "Bao-style top-fraction balanced accuracy",
        "Metric-compatible",
        "not PR-AUC comparators",
        "regression-style evidence",
        "Using Machine Learning to Detect Misstatements",
        "The intended contribution is a measurement redesign",
        "Peer models and metrics are used for compatibility checks",
    ]
    for phrase in required_phrases:
        assert phrase in plan


def test_faq_explains_cross_audience_design_and_current_boundaries() -> None:
    faq = _read("docs/faq.md")
    normalized_faq = " ".join(faq.split())
    required_phrases = [
        "# FAQ",
        "filing-origin public SEC/PCAOB information",
        "public review-and-correction cascade",
        "public observability states",
        "not interchangeable with fraud",
        "detected-misstatement benchmark",
        "raw `CIK-GVKEY Link Table.csv`",
        "Do not supplement missing raw `gvkey x year` rows with external gvkey-CIK rows",
        "Disjoint raw/external conflict `gvkey x year` cells",
        "Raw benchmark rows affected by those conflicts",
        "372",
        "24",
        "public_lake_smoke",
        "linkage/raw_only",
        "The public-cascade model does not need the benchmark-to-public bridge",
        "No. The detected-misstatement benchmark uses a `gvkey x data_year` feature table",
        "PR-AUC is the primary headline ranking metric",
        "Comparisons are valid within the same task, split, feature family, and label definition",
        "wrds_validated",
        "The paper plan is the design contract",
        "The results snapshot is the artifact-backed current evidence report",
        "revision-frozen `all + expanding`",
        "visibility/history information set",
        "notes/disclosure-breadth variables enter `all`",
        "no standalone text-family ablation",
        "historical conflict counts",
        "[generated results snapshot](results_snapshot.md)",
        "as_of_date=2026-07-06",
        "fiscal years 2011-2024",
        "just data full fresh",
        "just task study raw artifacts/full_with_peer",
        "--peer-comparison-mode full --peer-target both --parallel-jobs 4 --model-threads 2 --seed-policy task-isolated",
        "`just full mode=full dataset=raw` is a convenience workflow",
    ]
    for phrase in required_phrases:
        assert phrase in normalized_faq
    for stale in ["0.3679", "0.2557", "0.0508", "`all + rolling_7y`"]:
        assert stale not in faq
    for stale_structure in [
        "Current paper-facing counts:",
        "Current public task metrics:",
        "Which peer models perform best?",
        "| Object | Current count |",
        "| Bridge diagnostic | Current count |",
    ]:
        assert stale_structure not in faq

    historical_heading = "## Historical conflict counts"
    assert faq.count(historical_heading) == 1
    prefix, historical_tail = faq.split(historical_heading, maxsplit=1)
    historical_body, _, suffix = historical_tail.partition("\n## ")
    for count in ["372", "24"]:
        token = rf"(?<!\d){count}(?!\d)"
        assert re.search(token, historical_body)
        assert not re.search(token, prefix)
        assert not re.search(token, suffix)

    assert "WRDS-validated" in normalized_faq
    assert "unobserved true-fraud occurrence claims" in normalized_faq


def test_gitignore_covers_local_manuscript_exports_and_mac_junk() -> None:
    gitignore = _read(".gitignore")
    required_lines = [
        ".DS_Store",
        "/reporting-risk-cascade-manuscript/",
        "**/reporting-risk-cascade-manuscript/",
    ]
    for line in required_lines:
        assert line in gitignore


def test_future_work_documents_deferred_scope_and_guardrails() -> None:
    future = _read("docs/future_work.md")
    required_phrases = [
        "They are deferred",
        "Multimodal Cascade Model",
        "long-context finance embeddings",
        "No runtime code is retained",
        "Public Security and Attention Layers",
        "Auditor and Oversight Network",
        "Restatement Severity And Detector Labels",
        "do not put bivariate-probit",
    ]
    for phrase in required_phrases:
        assert phrase in future


def test_development_audit_prompt_targets_code_against_paper_plan() -> None:
    prompt = _read("docs/development_audit_prompt.md")
    required_phrases = [
        "Development Audit Brief",
        "reporting-risk-cascade paper",
        "pre-disclosure reporting-risk state",
        "docs/paper_plan.md as the binding research and implementation contract",
        "Discover the current file inventory",
        "Source code, wrappers, and tests live under src/, scripts/, and tests/",
        "artifact indexes",
        "res_an0",
        "label-observability sensitivity",
        "raw_identifier_blocker",
        "task dispatcher",
        "conventional output directory name",
        "--peer-comparison-mode",
        "--peer-target",
        "validation_tier = wrds_validated",
        "mapping_attrition_rate",
        "origin_date is the focal public filing date",
        "event_date < origin_date",
        "amendment_annotation",
        "bounded explanatory-note scan",
        "exhaustive artifact list",
        "task-status tables",
        "manifests",
        "blockers",
        "retired enforcement-tail outputs absent from paper-facing labels",
        "model-selection optimism",
        "xbrl_coverage_* by fiscal year",
        "uv.lock",
        "development audit, not a manuscript review",
        "not_auditable_from_checkout",
        "artifact_unavailable",
        "claim-support matrix",
        "stale_snapshot",
        "acceptance_datetime",
        "item_metadata_missing",
        "source_available_form_ap",
        "feature-selection code path",
        "training fold",
        "as-first-reported",
        "overlap sample flow",
        "bridge confidence tiers",
        "sensitivity output",
        "label co-occurrence",
        "public-opacity DML artifacts",
        "data-prep and table-I/O tests",
        "Design Overview",
        "Evidence Map",
        "current evidence state",
        "Selected Artifact Index",
        "DuckDB memory",
        "xbrl_ratio_*",
        "P0: critical violations",
    ]
    for phrase in required_phrases:
        assert phrase in prompt
    assert "corporate misstatement prediction paper" not in prompt


def test_development_audit_prompt_is_public_data_first() -> None:
    prompt = _read("docs/development_audit_prompt.md")
    required_phrases = [
        "public-data-first",
        "Do not treat absence of Audit Analytics or other unprovided paid databases",
        "raw-only WRDS SEC Analytics Suite bridge",
        "validation_tier = wrds_validated",
        "Fallback hierarchy",
        "Public Data Utilization Audit",
        "Blocker Resolution Matrix",
        "OpenFIGI",
        "gvkey is not supported",
        "sec-api.io",
        "Financial Modeling Prep",
        "EODHD",
        "institutional only",
        "optional accelerator",
        "Do not recommend LLM/GNN",
    ]
    for phrase in required_phrases:
        assert phrase in prompt


def test_manuscript_audit_prompt_targets_manuscript_quality_and_terms() -> None:
    prompt = _read("docs/manuscript_audit_prompt.md")
    required_phrases = [
        "reporting-risk-cascade paper",
        "reporting-risk-cascade-manuscript",
        "pre-disclosure reporting-risk state",
        "public comment-letter scrutiny",
        "public Item 4.02 material-correction proxy",
        "DML-style high-dimensional adjustment",
        "formulaic prose",
        "Claim-strength ladder",
        "reportable finding",
        "candidate evidence",
        "diagnostic only",
        "not supported",
        "artifacts/full_with_peer",
        "terminology ledger",
        "claim-to-evidence + claim-strength",
        "citation audit",
        "Referee robustness check",
        "comment-letter prediction literature",
        "predictor text",
        "outcome text",
        "unpriced market risk",
        "prevalence/base-rate",
        "screening evidence",
        "asymmetric costs",
        "false negatives",
        "endogenous scrutiny",
        "predictive association",
        "triage audit",
        "full audit",
        "likely rejection path",
        "fold dispersion",
        "annual fold dispersion",
        "uncertainty caveat",
        "limited screening interpretation",
        "Cross-Discipline Terminology Bridge",
        "AI-flavored prose patterns",
        "Audit Workflow",
        "scale_pos_weight",
        "Do not invent empirical findings",
    ]
    for phrase in required_phrases:
        assert phrase in prompt
    assert "corporate misstatement prediction paper" not in prompt


def test_manuscript_audit_prompt_enforces_public_data_first_claim_discipline() -> None:
    prompt = _read("docs/manuscript_audit_prompt.md")
    required_phrases = [
        "public-data-first",
        "artifact-backed",
        "Do not make absence of Audit Analytics or other unprovided commercial datasets",
        "Do not recommend paid data as required for the current v1 paper",
        "benchmark layer",
        "public cascade layer",
        "bridge gate",
        "public-data-only design",
        "public-data support ledger",
        "bridge-gate assessment",
        "WRDS-validated construct-overlap",
        "feature fusion, not XBRL dominance",
        "retired enforcement-tail outputs as outside the current paper-facing",
        "headline public tasks are comment_thread, amendment, and 8k_402",
        "feature fusion helps, metadata remains strong",
        "rare but rankable",
        "common-sample / coverage caveat",
        "WRDS-validated construct-overlap",
        "reciprocal risk-score alignment",
        "event-time concentration",
        "single-fold 2020 8k_402",
        "strong strategic-silence claim",
        "valid folds >= 5",
        "fewer than 10 positives",
        "population confidence interval",
        "out-of-time evaluation dispersion",
        "public review-and-correction risk",
        "comment_thread_365",
        "amendment_365",
        "8k_402_365",
        "Do not browse for live pricing",
    ]
    for phrase in required_phrases:
        assert phrase in prompt


def test_manuscript_audit_prompt_has_structural_hardening_rules() -> None:
    prompt = _read("docs/manuscript_audit_prompt.md")

    assert prompt.count("## Mode Invocation Rule") == 1
    assert prompt.count("run exactly one Review Mode per invocation") == 1
    assert prompt.index("Bridge status must be read from the current") < prompt.index(
        "## Review Mode: BAR Readiness Audit"
    )
    stale_bridge_sentence = "The current paper-facing bridge" + " must be"
    assert stale_bridge_sentence not in prompt
    stale_wrds_sentence = "current paper-facing bridge " + "must be `wrds_validated`"
    assert stale_wrds_sentence not in prompt

    p0_p1 = prompt.split("## P0 and P1 Checks", maxsplit=1)[1].split(
        "## Elegance and Readability", maxsplit=1
    )[0]
    p0_p1_flat = _squash(p0_p1)
    required_p0_p1 = [
        "Bridge freshness check.",
        "Primary-source citation check.",
        "Point-in-time predictor check.",
        "Table/figure interpretation check.",
        "Model-selection optimism check.",
        "Missingness and opacity check.",
        "Article-prose contamination check.",
        "Table-unit clarity check.",
        "primary-source citations",
        "point-in-time predictor discipline",
        "table and figure captions",
        "economically informative missingness",
        "parser/source unavailability",
        "model imputation",
        "weaken strategic-silence language",
        'column named "Rows"',
        "response memo or design memo",
    ]
    for phrase in required_p0_p1:
        assert phrase in p0_p1_flat

    claim_mode = prompt.split("## Review Mode: Claim-To-Evidence Audit", maxsplit=1)[1].split(
        "## Review Mode: Section-Level Polish", maxsplit=1
    )[0]
    claim_mode_flat = _squash(claim_mode)
    for phrase in [
        "Audit every empirical claim and classify it with the Claim-strength ladder.",
        "bridge status read from the current manifest",
        "available at or before the filing-origin date",
        "model imputation",
    ]:
        assert phrase in claim_mode_flat

    polish_mode = prompt.split("## Review Mode: Section-Level Polish", maxsplit=1)[1].split(
        "## Review Mode: Abstract And Introduction", maxsplit=1
    )[0]
    polish_mode_flat = _squash(polish_mode)
    for phrase in [
        "performance captions state evaluation unit",
        "base-rate context",
        "bounded measurement interpretation",
        "practical screening economics",
        "max-PR-AUC language",
    ]:
        assert phrase in polish_mode_flat


def test_manuscript_audit_prompt_primary_source_and_ai_policy_guardrails() -> None:
    prompt = _read("docs/manuscript_audit_prompt.md")
    mechanics = prompt.split("## BAR Mechanics and Citation Discipline", maxsplit=1)[1].split(
        "## Table And Figure Architecture", maxsplit=1
    )[0]
    mechanics_flat = _squash(mechanics)

    required_phrases = [
        "Verify mechanics against primary sources",
        "SEC/PCAOB/BAR/Elsevier rules",
        "double-anonymized",
        "no more than 6 keywords",
        "current Elsevier length rule",
        "data availability",
        "CRediT",
        "Author-side AI tools",
        "human oversight, disclosure, and author responsibility",
        "Reviewers and editors should not upload submitted manuscripts",
        "author-side QC",
    ]
    for phrase in required_phrases:
        assert phrase in mechanics_flat


def test_manuscript_package_generator_uses_dispersion_and_bootstrap_language() -> None:
    script = _read("scripts/build_manuscript_package.py")
    assert "PR_AUC_Dispersion" in script
    assert "Lift_Bootstrap_Interval" in script
    assert "row-level percentile bootstrap intervals" in script
    assert "descriptive fold-dispersion intervals" in script
    assert "PR_AUC_95CI" not in script
    assert "Lift_95CI" not in script
    benchmark_peer_block = script.split('"table_06_detected_misstatement_peer_metrics"')[1].split(
        '"table_07_public_peer_metrics"'
    )[0]
    public_peer_block = script.split('"table_07_public_peer_metrics"')[1].split(
        '"table_08_bridge_coverage"'
    )[0]
    assert '"Mean_Brier"' not in benchmark_peer_block
    assert '"Mean_Brier"' not in public_peer_block
