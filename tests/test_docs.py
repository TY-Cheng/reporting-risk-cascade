from __future__ import annotations

from pathlib import Path
import tomllib

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _read_yaml(path: str) -> dict:
    return yaml.load(_read(path), Loader=yaml.Loader)


def _read_toml(path: str) -> dict:
    return tomllib.loads(_read(path))


def test_mkdocs_nav_uses_paper_plan_and_future_work_pages() -> None:
    mkdocs = _read_yaml("mkdocs.yml")
    assert mkdocs["nav"] == [
        {"Home": "index.md"},
        {"Paper Plan": "paper_plan.md"},
        {
            "Audit Prompts": [
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
    assert "# Reporting Risk Cascade Docs" in home
    assert "reporting-risk-cascade-manuscript" in env_example


def test_mkdocs_enables_richer_material_navigation_and_content_features() -> None:
    mkdocs = _read_yaml("mkdocs.yml")
    features = set(mkdocs["theme"]["features"])
    required_features = {
        "navigation.sections",
        "navigation.top",
        "navigation.tracking",
        "content.code.copy",
        "content.tabs.link",
        "search.highlight",
        "search.suggest",
    }
    assert required_features.issubset(features)

    extensions = mkdocs["markdown_extensions"]
    extension_names = {
        next(iter(item)) if isinstance(item, dict) else item for item in extensions
    }
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


def test_docs_file_names_are_paper_facing_not_internal_codenames() -> None:
    doc_files = {path.name for path in (REPO_ROOT / "docs").glob("*.md")}
    assert doc_files == {
        "development_audit_prompt.md",
        "future_work.md",
        "index.md",
        "manuscript_audit_prompt.md",
        "paper_plan.md",
    }


def test_readme_points_to_current_docs_pages() -> None:
    readme = _read("README.md")
    assert "docs/paper_plan.md" in readme
    assert "docs/future_work.md" in readme


def test_docs_home_keeps_readme_as_source_but_adds_material_landing_shell() -> None:
    home = _read("docs/index.md")
    assert '--8<-- "README.md:docs-home"' in home
    assert "grid cards" in home
    assert ".md-button" in home
    assert "Run Surface" in home
    assert "Readiness Snapshot" in home
    assert "development_audit_prompt.md" in home
    assert "manuscript_audit_prompt.md" in home


def test_readme_home_explains_project_and_workflow() -> None:
    home = _read("README.md")
    required_phrases = [
        "What This Repo Does",
        "Research Spine",
        "Layout",
        "5-Minute Workflow",
        "Public Lake Run",
        "Main Outputs",
        "Current Priorities",
        "pre-disclosure reporting-risk state",
        "just analysis study raw",
    ]
    for phrase in required_phrases:
        assert phrase in home


def test_paper_plan_documents_required_research_spine() -> None:
    plan = _read("docs/paper_plan.md")
    required_phrases = [
        "pre-disclosure reporting-risk state",
        "gvkey-CIK-year",
        "Naive Versus Timing-Sensitivity Restatement Evaluation",
        "Concept Drift And Model Shelf-Life",
        "Strategic Silence And MNAR Missingness",
        "Public Cascade Prediction",
        "Old Benchmark And Public Cascade Overlap",
        "comment_thread_365",
        "label_8k_402_365",
        "label_aaer_proxy_730",
        "just analysis study raw artifacts/study",
    ]
    for phrase in required_phrases:
        assert phrase in plan


def test_paper_plan_is_p0_executable_spec_not_result_prompt() -> None:
    plan = _read("docs/paper_plan.md")
    required_phrases = [
        "Execution Invariants",
        "Evidence State And Decision Gate",
        "benchmark evidence available",
        "public cascade evidence under construction",
        "integration evidence pending gate",
        "Benchmark Timing-Sensitivity Algorithm",
        "timing_coverage.csv",
        "timing_claim_status",
        "train_origin_year = test_year - 1",
        "Diagnostic interpretation",
        "D = missingness_density_score",
        "Partially linear regression",
        "Public Cascade Feature Contract",
        "xbrl_ratio_*",
        "XBRL ratio baseline",
        "Outcome Semantics",
        "Bridge Plan",
        "bridge_probe_summary.json",
        "coverage_report.csv",
        "raw_identifier_blocker",
        "Readiness Matrix",
        "10 requests/second",
        "zero-positive task labels",
    ]
    for phrase in required_phrases:
        assert phrase in plan
    assert "Expected result" not in plan
    assert "data/public_lake_smoke" not in plan


def test_paper_plan_documents_prior_literature_and_intended_contribution() -> None:
    plan = _read("docs/paper_plan.md")
    required_phrases = [
        "Prior Literature And Intended Contribution",
        "Dechow, Ge, Larson, and Sloan",
        "Perols",
        "Bao, Ke, Yu, and Zhang",
        "Bertomeu, Cheynel, Floyd, and Pan",
        "Barton, Burnett, Gunny, and Miller",
        "Using Machine Learning to Detect Misstatements",
        "The intended contribution is not another horse race",
        "Potential findings and selling points",
    ]
    for phrase in required_phrases:
        assert phrase in plan


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
        "deliberately deferred",
        "Multimodal Cascade Model",
        "long-context finance embeddings",
        "No runtime code is retained",
        "Public Security And Attention Layers",
        "Auditor And Oversight Network",
        "Restatement Severity And Detector Labels",
        "do not put bivariate-probit",
    ]
    for phrase in required_phrases:
        assert phrase in future


def test_development_audit_prompt_targets_code_against_paper_plan() -> None:
    prompt = _read("docs/development_audit_prompt.md")
    required_phrases = [
        "Development Audit Prompt",
        "reporting-risk-cascade paper",
        "pre-disclosure reporting-risk state",
        "docs/paper_plan.md as the binding research and implementation contract",
        "src/benchmark.py",
        "src/public_lake.py",
        "src/public_cascade.py",
        "src/bridge.py",
        "res_an0",
        "proxy_sensitivity",
        "raw_identifier_blocker",
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
        "Do not treat absence of WRDS or Audit Analytics as a code bug",
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
        "AAER / accounting-enforcement severity proxy",
        "DML-style high-dimensional adjustment",
        "AI flavor",
        "terminology ledger",
        "claim-to-evidence ledger",
        "citation audit",
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
        "Do not make absence of WRDS/Audit Analytics sound like a fatal manuscript flaw",
        "Do not recommend paid data as required for the current v1 paper",
        "benchmark layer",
        "public cascade layer",
        "bridge gate",
        "public-data-only design",
        "public-data support ledger",
        "bridge-gate assessment",
        "comment_thread_365",
        "amendment_365",
        "8k_402_365",
        "aaer_proxy_730",
        "Do not browse for live pricing",
    ]
    for phrase in required_phrases:
        assert phrase in prompt
