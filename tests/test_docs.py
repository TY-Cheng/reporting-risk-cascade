from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any

import pandas as pd
import pytest
import yaml

import scripts.refresh_results_snapshot as snapshot_module
from scripts.refresh_results_snapshot import _construct_alignment_rows


REPO_ROOT = Path(__file__).resolve().parents[1]


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
    assert "LAKE_GOLD_DIR / \"issuer_origin_panel.parquet\"" in build_linkage
    assert "PUBLIC_LAKE_SMOKE_DIR / \"gold\" / \"issuer_origin_panel.parquet\"" in build_linkage
    assert "LAKE_GOLD_DIR / \"issuer_origin_panel.parquet\"" in linkage
    assert "PUBLIC_LAKE_SMOKE_DIR / \"gold\" / \"issuer_origin_panel.parquet\"" in linkage


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
    assert 'snapshot study_dir="artifacts/full_with_peer" allow_partial="0": _check-data-env' in justfile
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
        "common metric vocabulary",
        "PR-AUC",
        "ROC-AUC",
        "Brier",
        "NDCG",
        "does not support causal claims",
        "Reproducibility Metadata",
        "Evidence Map",
        "Experiment 1: Label Observability and Detection Timing",
        "Experiment 2: Concept Drift and Model Shelf-Life",
        "Experiment 3: Opacity and Public Review/Correction Risk",
        "Experiment 4: Public Cascade Construction",
        "Experiment 5: Public Cascade Prediction",
        "Experiment 6: Detected-Misstatement Benchmark and Public Cascade Overlap",
        "Full Window Summary",
        "Strongest Structural-Break Diagnostics",
        "Public Cascade Fit and Skip Status",
        "Public Lake and Gold Panel Scale",
        "Public Cascade Readiness",
        "Public Task Metrics",
        "Detected-Misstatement Benchmark",
        "Peer-Compatible",
        "Public-Label Peer Transfer",
        "Label Contingency and Lift",
        "Event-Time Concentration",
        "Tables, Figures, and Artifact Index",
        "ARS Evidence Gallery",
        "Inline Figure Gallery",
        "Inline Table Gallery",
        "Manuscript Package Tables and Figures",
        "Full Study Artifact Inventory",
        "Selected Artifact Index",
        "artifacts/",
        "xbrl_ratio_baseline",
        "wrds_validated",
        "Key Readings",
    ]
    for phrase in required_phrases:
        assert phrase in results
    assert (
        "Generated by `just snapshot`" in results
        or "static documentation snapshot" in results
    )
    assert results.count("Key Readings") >= 1
    assert results.count("![") >= 5
    for figure in [
        "figure_01_public_task_pr_auc.png",
        "figure_02_feature_family_pr_auc.png",
        "figure_03_detected_misstatement_peer_pr_auc.png",
        "figure_04_public_peer_pr_auc.png",
        "figure_05_construct_overlap_lift.png",
    ]:
        assert f"assets/results_snapshot/{figure}" in results
    for table in [
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
    ]:
        assert f"#### `{table}`" in results
    assert "ARS claim" in results
    assert "Boundary" in results


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


def _write_snapshot_fixture(tmp_path: Path) -> dict[str, Any]:
    study_dir = tmp_path / "study"
    package_dir = tmp_path / "manuscript_package"
    tables_dir = package_dir / "tables"
    figures_dir = package_dir / "figures"
    tables_dir.mkdir(parents=True)
    figures_dir.mkdir(parents=True)

    commit = "a" * 40
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
                    {"path": "/Users/example/raw.csv", "exists": True, "sha256": "1" * 64},
                    {
                        "path": "/Volumes/private/issuer.parquet",
                        "exists": True,
                        "sha256": "2" * 64,
                    },
                    {
                        "path": "/Users/example/OneDrive/panel.parquet",
                        "exists": True,
                        "sha256": "3" * 64,
                    },
                    {"path": "/Volumes/private/bridge.csv", "exists": True, "sha256": "4" * 64},
                    {"path": "/Users/example/lake.json", "exists": True, "sha256": "5" * 64},
                    {"path": "/Users/example/form_ap.json", "exists": True, "sha256": "6" * 64},
                ],
                "wrds_export_metadata": {
                    "path": "/Users/example/OneDrive/bridge.csv",
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
                "benchmark": {"status": "complete", "out_dir": "/Users/example/benchmark"},
                "public_cascade": {"status": "complete", "out_dir": "/Volumes/private/public"},
                "bridge_probe": {
                    "status": "crosswalk_available",
                    "out_dir": "/Users/example/bridge",
                },
                "peer_comparison": {"status": "complete", "out_dir": "/Users/example/peer"},
                "public_peer_comparison": {
                    "status": "complete",
                    "out_dir": "/Users/example/public_peer",
                },
                "construct_overlap": {
                    "run_status": "complete",
                    "validation_tier": "wrds_validated",
                    "out_dir": "/Users/example/OneDrive/construct",
                },
            },
            "claim_maturity": {
                "public_prediction": "reportable",
                "feature_and_window_sensitivity": "supporting",
                "construct_alignment": "supporting",
                "opacity_dml": "diagnostic",
            },
            "inputs": {
                "raw_data": "/Users/example/raw.csv",
                "issuer_origin_panel": "/Volumes/private/issuer.parquet",
                "crosswalk": "/Users/example/OneDrive/bridge.csv",
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
            "feature_family_summary": {},
        },
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
    _table_09_frame().to_csv(
        tables_dir / "table_09_construct_alignment.csv",
        index=False,
    )
    for figure in CURRENT_PACKAGE_FIGURES:
        (figures_dir / f"{figure}.png").write_bytes(b"fixture-png")
        (figures_dir / f"{figure}.pdf").write_bytes(b"fixture-pdf")
    _write_json(
        package_dir / "manifest.json",
        {
            "tables": {
                table: {"csv": f"/Users/example/OneDrive/{table}.csv"}
                for table in CURRENT_PACKAGE_TABLES
            },
            "figures": {
                figure: {"png": f"/Volumes/private/{figure}.png"}
                for figure in CURRENT_PACKAGE_FIGURES
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


def test_generated_snapshot_exposes_provenance_structure_and_all_package_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)

    for phrase in [
        "Artifact generation time",
        "Study commit",
        "Git dirty",
        "Config hash",
        "Input hash",
        "uv.lock hash",
        "Public-data as-of date",
        "Form AP archive hash",
        "WRDS source",
        "WRDS version",
        "WRDS extraction time",
        "WRDS hash",
        "Component status",
        "Claim maturity",
        "Canonical status",
        "Detected-misstatement benchmark input",
        "Public issuer dimension input",
        "Public issuer-origin panel input",
        "CIK-GVKEY bridge input",
        "Public-lake run metadata input",
        "Form AP source metadata input",
        "## Results for Experiment 1: Label Observability and Detection Timing",
        "## Results for Experiment 2: Concept Drift and Model Shelf-Life",
        "## Results for Experiment 3: Opacity and Public Review/Correction Risk",
        "## Results for Experiment 4: Public Cascade Construction",
        "## Results for Experiment 5: Public Cascade Prediction",
        "## Results for Experiment 6: Detected-Misstatement Benchmark and Public Cascade Overlap",
        "### Answers to the research questions",
        "### Comparison with prior literature",
        "### Accounting and institutional interpretation",
        "### Selection and visibility",
        "### Generalizability",
        "### Limitations and future work",
        "### Claim ledger",
        "`reportable`",
        "`supporting`",
        "`diagnostic`",
        "`deferred`",
        "Note/disclosure-breadth variables enter `all` without a standalone ablation",
    ]:
        assert phrase in results
    assert "| Canonical status | `CANONICAL` |" in results
    assert "wrds_sec_analytics_cik_gvkey" in results
    assert "WRDS SEC Analytics Suite 2026-05" in results
    assert "2026-05-25T00:00:00Z" in results
    assert "7" * 64 in results
    for role_hash in ["1", "2", "3", "4", "5", "6"]:
        assert role_hash * 64 in results
    for component, status in {
        "benchmark": "complete",
        "public_cascade": "complete",
        "bridge_probe": "crosswalk_available",
        "peer_comparison": "complete",
        "public_peer_comparison": "complete",
        "construct_overlap": "complete",
    }.items():
        assert f"| {component} | `{status}` |" in results
    for claim, maturity in {
        "public_prediction": "reportable",
        "feature_and_window_sensitivity": "supporting",
        "construct_alignment": "supporting",
        "opacity_dml": "diagnostic",
    }.items():
        assert f"| {claim} | `{maturity}` |" in results
    for local_path_marker in ["/Users/", "/Volumes/", "OneDrive"]:
        assert local_path_marker not in results
    for table in fixture["tables"]:
        assert f"#### `{table}`" in results
    for figure in fixture["figures"]:
        assert f"{figure}.png" in results
    assert results.count("- **ARS claim.**") == len(fixture["tables"]) + len(fixture["figures"])


def test_generated_snapshot_keeps_raw_maxima_exploratory_and_post_hoc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_snapshot_fixture(tmp_path)

    results = _build_fixture_snapshot(fixture, tmp_path, monkeypatch)

    primary = results.split("### Declared primary construct-alignment rows", maxsplit=1)[1].split(
        "### Exploratory maxima", maxsplit=1
    )[0]
    exploratory = results.split("### Exploratory maxima", maxsplit=1)[1].split(
        "### Label Contingency and Lift", maxsplit=1
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
        line
        for line in plan.splitlines()
        if line.startswith("# ") or line.startswith("## ")
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


def test_paper_plan_is_p0_executable_spec_not_result_prompt() -> None:
    plan = _read("docs/paper_plan.md")
    required_phrases = [
        "Measurement Design",
        "Methods Including Models",
        "Evidence Gates",
        "Benchmark timing",
        "Public cascade",
        "current full-run state is `xbrl_ratio_baseline`",
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
        "xbrl_ratio_baseline",
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
        "`all + rolling_7y`",
        "feature-fusion gain, not XBRL dominance",
        "`bertomeu_style_xgb`",
        "`bao_inspired_tree_ensemble`",
        "wrds_validated",
        "The paper plan is the design contract",
        "The results snapshot is the artifact-backed current evidence report",
    ]
    for phrase in required_phrases:
        assert phrase in normalized_faq
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
    assert (
        prompt.index("Bridge status must be read from the current")
        < prompt.index("## Review Mode: BAR Readiness Audit")
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

    claim_mode = prompt.split("## Review Mode: Claim-To-Evidence Audit", maxsplit=1)[
        1
    ].split("## Review Mode: Section-Level Polish", maxsplit=1)[0]
    claim_mode_flat = _squash(claim_mode)
    for phrase in [
        "Audit every empirical claim and classify it with the Claim-strength ladder.",
        "bridge status read from the current manifest",
        "available at or before the filing-origin date",
        "model imputation",
    ]:
        assert phrase in claim_mode_flat

    polish_mode = prompt.split("## Review Mode: Section-Level Polish", maxsplit=1)[
        1
    ].split("## Review Mode: Abstract And Introduction", maxsplit=1)[0]
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
