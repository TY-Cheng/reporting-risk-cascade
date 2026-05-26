from __future__ import annotations

from pathlib import Path
import tomllib

import yaml


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
    assert (
        prompt.index("Bridge status must be read from the current")
        < prompt.index("## Review Mode: BAR Readiness Audit")
    )
    stale_bridge_sentence = "The current paper-facing bridge" + " must be"
    assert stale_bridge_sentence not in prompt

    p0_p1 = prompt.split("## P0 and P1 Checks", maxsplit=1)[1].split(
        "## Elegance and Readability", maxsplit=1
    )[0]
    p0_p1_flat = _squash(p0_p1)
    required_p0_p1 = [
        "primary-source citations",
        "point-in-time predictor discipline",
        "table and figure captions",
        "model-selection optimism check",
        "economically informative missingness",
        "parser/source unavailability",
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
