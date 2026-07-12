from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import scripts.build_manuscript_package as manuscript_module
from scripts.build_manuscript_package import (
    DML_INTERVAL_NOTE,
    MIN_VALID_FOLDS_FOR_CI,
    PUBLIC_TASK_NOTE,
    SPARSE_POSITIVE_THRESHOLD,
    _bridge_overlap_matrix,
    _bridge_sample_boundaries,
    _construct_alignment,
    _dispersion_text,
    _package_primary_identity,
    _public_fold_support,
    _public_opacity_dml_table,
    _public_sample_attrition_table,
    _public_task_metrics,
    _rel,
    _result_narrative,
    _select_primary_public_metrics,
    _task_feature_family_metrics,
)
from src.table_io import write_table


PACKAGE_TABLE_KEYS = {
    *(f"table_{index:02d}" for index in range(1, 10)),
    *(f"table_{index:02d}" for index in range(12, 19)),
}
PACKAGE_FIGURE_KEYS = {f"figure_{index:02d}" for index in range(1, 6)}
STUDY_COMMIT = "0123456789abcdef0123456789abcdef01234567"
MISSING_COMMIT = object()
EXPECTED_ARTIFACT_OWNERSHIP = {
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


def _narrative_reporting_contract(
    *,
    diagnostic: bool = True,
    constant_partner: bool = True,
) -> dict[str, object]:
    statuses = (
        {
            "comment_thread": "fit",
            "amendment": "skipped_one_class_or_too_small",
            "8k_402": "skipped_constant_treatment",
        }
        if diagnostic
        else {
            "comment_thread": "skipped_one_class_or_too_small",
            "amendment": "skipped_one_class_or_too_small",
            "8k_402": "skipped_constant_treatment",
        }
    )
    fit_outcomes = ["comment_thread"] if diagnostic else []
    maturity_by_outcome = {
        outcome: "diagnostic" if outcome in fit_outcomes else "deferred"
        for outcome in ["comment_thread", "amendment", "8k_402"]
    }
    partner = {
        "scope": "post-year-proxy uncensored public-model panel",
        "rows_evaluated": 12,
        "nonmissing_rows": 12,
        "nonzero_rows": 0 if constant_partner else 4,
        "n_distinct_nonmissing": 1 if constant_partner else 4,
        "minimum": 0,
        "maximum": 0 if constant_partner else 3,
        "is_constant_zero": constant_partner,
        "total_equals_item_402_rows": 12 if constant_partner else 7,
        "total_equals_item_402_for_all_rows": constant_partner,
    }
    return {
        "reporting_boundaries": {
            "sample_proxy": {
                "artifact_field": "is_domestic_us_gaap_proxy",
                "display_name": "10-K/10-K/A with no observed same-year FPI-form proxy",
                "validates_fpi_status": False,
                "validates_domicile": False,
                "validates_us_gaap": False,
            },
            "partner_nonadministrative_amendment": partner,
        },
        "feature_family_summary": {
            "oversight": {"display_name": "Prior-filing history (legacy artifact key: oversight)"}
        },
        "opacity_dml_evidence": {
            "required_outcomes": ["comment_thread", "amendment", "8k_402"],
            "status_by_outcome": statuses,
            "fit_outcomes": fit_outcomes,
            "maturity_by_outcome": maturity_by_outcome,
        },
        "claim_maturity": {"opacity_dml": "diagnostic" if diagnostic else "deferred"},
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sparse_fold_display_uses_diagnostic_label_without_interval() -> None:
    row = pd.Series(
        {
            "ci_low": float("nan"),
            "ci_high": float("nan"),
            "fold_min": 0.1,
            "fold_max": 0.2,
            "valid_folds": MIN_VALID_FOLDS_FOR_CI - 1,
        }
    )

    assert _dispersion_text(row) == f"diagnostic only (<{MIN_VALID_FOLDS_FOR_CI} valid folds)"


def test_dispersion_display_uses_interval_when_available() -> None:
    row = pd.Series(
        {
            "ci_low": 0.12345,
            "ci_high": 0.23456,
            "valid_folds": MIN_VALID_FOLDS_FOR_CI,
        }
    )

    assert _dispersion_text(row) == "[0.1235, 0.2346]"


def test_latex_table_uses_small_tabular_for_narrow_numeric_data() -> None:
    frame = pd.DataFrame({"Year": [2024], "Estimate": [0.1234], "N": [120]})

    tex = manuscript_module._latex_table(frame, caption="Narrow", label="tab:narrow")

    assert r"\begin{table}[!htbp]" in tex
    assert r"\small" in tex
    assert r"\begin{tabular}{lll}" in tex
    assert r"\begin{tabularx}" not in tex
    assert r"\resizebox" not in tex
    assert r"\begin{sidewaystable}" not in tex


def test_latex_table_uses_tabularx_for_long_text_without_scaling() -> None:
    frame = pd.DataFrame(
        {
            "Status": ["complete"],
            "Interpretation": [
                "This deliberately long interpretation must wrap instead of being scaled."
            ],
        }
    )

    tex = manuscript_module._latex_table(frame, caption="Long text", label="tab:long")

    assert r"\begin{table}[!htbp]" in tex
    assert r"\small" in tex
    assert r"\begin{tabularx}{\textwidth}" in tex
    assert r"\resizebox" not in tex
    assert r"\begin{sidewaystable}" not in tex


def test_latex_table_rotates_wide_display_and_scales_to_textheight() -> None:
    frame = pd.DataFrame({f"Column_{idx}": [idx] for idx in range(9)})

    tex = manuscript_module._latex_table(frame, caption="Wide", label="tab:wide")

    assert "% Requires \\usepackage{rotating}" in tex
    assert r"\begin{sidewaystable}[!htbp]" in tex
    assert r"\resizebox{\textheight}{!}{%" in tex
    assert r"\resizebox{\textwidth}{!}" not in tex
    assert r"\begin{tabularx}" not in tex


def test_construct_lift_annotation_names_precision_and_clears_interval() -> None:
    helper = getattr(manuscript_module, "_construct_lift_annotation", None)
    assert callable(helper)
    row = pd.Series(
        {
            "Top_Decile_Lift": 1.8,
            "ci_high": 2.4,
            "Top_10pct_Precision": 0.1234,
            "Top_10pct_FDR": 0.8766,
        }
    )

    annotation, x_position = helper(row)

    assert annotation == "Precision=0.123; FDR=0.877"
    assert "P=" not in annotation
    assert x_position > max(row["Top_Decile_Lift"], row["ci_high"])


def test_construct_lift_xlim_reserves_room_for_full_annotation() -> None:
    helper = getattr(manuscript_module, "_construct_lift_xlim", None)
    assert callable(helper)

    assert helper(4.3, [4.35]) >= 4.35 * 2.0


def test_public_task_metrics_include_calibration_diagnostics() -> None:
    metrics = pd.DataFrame(
        {
            "feature_set": ["all"] * MIN_VALID_FOLDS_FOR_CI,
            "train_window": ["expanding"] * MIN_VALID_FOLDS_FOR_CI,
            "task": ["comment_thread"] * MIN_VALID_FOLDS_FOR_CI,
            "test_year": [2020, 2021, 2022, 2023, 2024],
            "positive_rate_test": [0.2] * MIN_VALID_FOLDS_FOR_CI,
            "n_test": [100] * MIN_VALID_FOLDS_FOR_CI,
            "roc_auc": [0.6] * MIN_VALID_FOLDS_FOR_CI,
            "pr_auc": [0.10, 0.30, 0.30, 0.30, 0.30],
            "brier": [0.18] * MIN_VALID_FOLDS_FOR_CI,
            "brier_skill_score": [0.05] * MIN_VALID_FOLDS_FOR_CI,
            "ece": [0.04] * MIN_VALID_FOLDS_FOR_CI,
        }
    )
    task_status = pd.DataFrame(
        {
            "feature_set": ["all"] * MIN_VALID_FOLDS_FOR_CI + ["metadata"],
            "train_window": ["expanding"] * (MIN_VALID_FOLDS_FOR_CI + 1),
            "task": ["comment_thread"] * (MIN_VALID_FOLDS_FOR_CI + 1),
            "test_year": [2020, 2021, 2022, 2023, 2024, 2024],
            "status": ["fit"] * (MIN_VALID_FOLDS_FOR_CI + 1),
            "positive_test": [1, 2, 3, 4, 5, 999],
        }
    )

    table = _public_task_metrics(
        metrics,
        task_status,
        {
            "primary_specification": {
                "feature_set": "all",
                "train_window": "expanding",
            },
            "task_positive_counts": {"comment_thread": 100},
        },
    )

    assert table.loc[0, "Panel_Positives"] == "15"
    assert table.loc[0, "Mean_PR_AUC"] == "0.2600"
    assert table.loc[0, "Excluding_2020_PR_AUC"] == "0.3000"
    assert table.loc[0, "Excluding_2020_Delta"] == "0.0400"
    assert table.loc[0, "Mean_Brier_Skill"] == "0.0500"
    assert table.loc[0, "Mean_ECE"] == "0.0400"


@pytest.mark.parametrize(
    "status_rows",
    [
        [
            {
                "feature_set": "all",
                "train_window": "expanding",
                "task": "comment_thread",
                "test_year": 2024,
                "status": "fit",
                "positive_test": 2,
            },
            {
                "feature_set": "all",
                "train_window": "expanding",
                "task": "comment_thread",
                "test_year": 2024,
                "status": "fit",
                "positive_test": 2,
            },
        ],
        [],
        [
            {
                "feature_set": "all",
                "train_window": "expanding",
                "task": "comment_thread",
                "test_year": 2024,
                "status": "fit",
                "positive_test": 2,
            },
            {
                "feature_set": "all",
                "train_window": "expanding",
                "task": "comment_thread",
                "test_year": 2023,
                "status": "fit",
                "positive_test": 1,
            },
        ],
    ],
    ids=["duplicate", "missing", "extra"],
)
def test_public_task_metrics_rejects_non_bijective_fit_ownership(
    status_rows: list[dict[str, object]],
) -> None:
    metrics = pd.DataFrame(
        {
            "feature_set": ["all"],
            "train_window": ["expanding"],
            "task": ["comment_thread"],
            "test_year": [2024],
            "positive_rate_test": [0.02],
            "n_test": [100],
            "roc_auc": [0.6],
            "pr_auc": [0.2],
            "brier": [0.02],
            "brier_skill_score": [0.05],
            "ece": [0.01],
        }
    )

    with pytest.raises(ValueError, match="one-to-one fit ownership"):
        _public_task_metrics(
            metrics,
            pd.DataFrame(status_rows),
            {
                "primary_specification": {
                    "feature_set": "all",
                    "train_window": "expanding",
                }
            },
        )


def test_public_task_note_defines_excluding_2020_test_fold_sensitivity() -> None:
    assert "all + expanding" in PUBLIC_TASK_NOTE
    assert "2020 test fold" in PUBLIC_TASK_NOTE
    assert "training specifications are unchanged" in PUBLIC_TASK_NOTE
    assert "one-to-one fit-owner rows" in PUBLIC_TASK_NOTE


def test_select_primary_public_metrics_excludes_grid_distractors() -> None:
    metrics = pd.DataFrame(
        {
            "feature_set": ["all", "all", "metadata"],
            "train_window": ["expanding", "rolling_7y", "expanding"],
            "task": ["comment_thread"] * 3,
            "test_year": [2021, 2021, 2021],
            "pr_auc": [0.30, 0.90, 0.80],
        }
    )
    summary = {"primary_specification": {"feature_set": "all", "train_window": "expanding"}}

    selected = _select_primary_public_metrics(metrics, summary)

    assert selected[["feature_set", "train_window", "pr_auc"]].to_dict("records") == [
        {"feature_set": "all", "train_window": "expanding", "pr_auc": 0.30}
    ]


def test_primary_public_package_identity_records_summary_contract() -> None:
    identity = _package_primary_identity(
        {"primary_specification": {"feature_set": "all", "train_window": "expanding"}}
    )

    assert identity == {
        "primary_public_specification": {
            "feature_set": "all",
            "train_window": "expanding",
        }
    }


def test_results_narrative_renders_external_component_path_privately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    external_root = tmp_path / "private-fixture-root"
    external_output = external_root / "public_cascade"
    monkeypatch.setattr(manuscript_module, "PROJECT_ROOT", repo_root)
    public_task = pd.DataFrame(
        {
            "Task": ["comment_thread", "amendment", "8k_402"],
            "Mean_PR_AUC": ["0.3000", "0.2000", "0.1000"],
        }
    )

    narrative = _result_narrative(
        manifest={
            "generated_at_utc": "2026-07-10T00:00:00Z",
            "components": {"public_cascade": {"out_dir": str(external_output)}},
        },
        public_summary={
            "primary_specification": {"feature_set": "all", "train_window": "expanding"}
        },
        public_task=public_task,
        construct_alignment=pd.DataFrame(),
        construct_manifest={"validation_tier": "fixture"},
        reporting_contract=_narrative_reporting_contract(),
    )

    assert str(external_output) not in narrative
    assert str(external_root) not in narrative
    assert str(tmp_path) not in narrative
    assert "`<external>/public_cascade`" in narrative


def test_candidate_bridge_package_notes_and_narrative_are_nonassertive() -> None:
    bridge_language = getattr(manuscript_module, "_bridge_language", None)
    assert callable(bridge_language), "package bridge language must derive from both tiers"
    manifest = {
        "generated_at_utc": "2026-07-10T00:00:00Z",
        "components": {
            "public_cascade": {"out_dir": "artifacts/public_cascade"},
            "construct_overlap": {
                "run_status": "complete",
                "validation_tier": "candidate_external",
            },
        },
    }
    construct_manifest = {"validation_tier": "candidate_external"}
    language = bridge_language(manifest, construct_manifest)
    public_task = pd.DataFrame(
        {
            "Task": ["comment_thread", "amendment", "8k_402"],
            "Mean_PR_AUC": ["0.3000", "0.2000", "0.1000"],
        }
    )

    narrative = _result_narrative(
        manifest=manifest,
        public_summary={
            "primary_specification": {"feature_set": "all", "train_window": "expanding"}
        },
        public_task=public_task,
        construct_alignment=pd.DataFrame(),
        construct_manifest=construct_manifest,
        reporting_contract=_narrative_reporting_contract(),
    )
    normalized = " ".join(" ".join([narrative, *language.values()]).lower().split())

    assert "candidate_external" in normalized
    assert "diagnostic" in normalized
    assert "deferred" in normalized
    for forbidden in [
        "confirmed wrds",
        "wrds-validated",
        "manuscript-grade",
        "supports the integrated",
        "support the integrated",
    ]:
        assert forbidden not in normalized


@pytest.mark.parametrize("stem", ["table_04", "table_14"])
def test_feature_family_tables_preserve_raw_csv_and_use_contract_display_labels(
    tmp_path: Path,
    stem: str,
) -> None:
    contract = _narrative_reporting_contract()
    raw = pd.DataFrame({"Feature_Set": ["oversight"], "Mean_PR_AUC": ["0.1234"]})
    display = raw.copy()
    display["Feature_Set"] = display["Feature_Set"].map(
        lambda value: manuscript_module._paper_display_name(value, contract)
    )

    records = manuscript_module._write_table_bundle(
        raw,
        display_df=display,
        out_dir=tmp_path / "tables",
        stem=stem,
        caption="Feature family",
        label=f"tab:{stem}",
    )

    assert pd.read_csv(tmp_path / records["csv"]["path"]).loc[0, "Feature_Set"] == "oversight"
    for fmt in ["md", "tex"]:
        rendered = (tmp_path / records[fmt]["path"]).read_text(encoding="utf-8")
        assert "Prior-filing history (legacy artifact key: oversight)" in rendered


def test_sample_attrition_table_preserves_raw_stage_and_displays_exact_proxy_label(
    tmp_path: Path,
) -> None:
    contract = _narrative_reporting_contract()
    raw = pd.DataFrame(
        {
            "Scope": ["sequential"],
            "Stage": ["domestic_us_gaap_proxy"],
            "Task": ["all"],
            "Rows": [75],
            "Dropped_From_Parent": [5],
        }
    )
    display = raw.copy()
    display["Stage"] = display["Stage"].map(
        lambda value: manuscript_module._paper_display_name(value, contract)
    )

    records = manuscript_module._write_table_bundle(
        raw,
        display_df=display,
        out_dir=tmp_path / "tables",
        stem="table_18",
        caption="Sample attrition",
        label="tab:sample-attrition",
    )

    assert pd.read_csv(tmp_path / records["csv"]["path"]).loc[0, "Stage"] == (
        "domestic_us_gaap_proxy"
    )
    expected = "10-K/10-K/A with no observed same-year FPI-form proxy"
    for fmt in ["md", "tex"]:
        assert expected in (tmp_path / records[fmt]["path"]).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "display_name",
    [
        "Prior-filing history (legacy artifact key: oversight)",
        "Metadata",
    ],
    ids=["horizontal", "vertical"],
)
def test_figure_display_labels_preserve_raw_fold_dot_matching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    display_name: str,
) -> None:
    import matplotlib.axes

    scatter_calls: list[tuple[list[float], object]] = []
    tick_labels: list[str] = []
    original_scatter = matplotlib.axes.Axes.scatter
    original_set_yticks = matplotlib.axes.Axes.set_yticks
    original_set_xticks = matplotlib.axes.Axes.set_xticks

    def scatter_spy(self, x, y, *args, **kwargs):  # type: ignore[no-untyped-def]
        scatter_calls.append((list(x), kwargs.get("s")))
        return original_scatter(self, x, y, *args, **kwargs)

    def set_yticks_spy(self, ticks, labels=None, *args, **kwargs):  # type: ignore[no-untyped-def]
        if labels is not None:
            tick_labels.extend(str(label) for label in labels)
        return original_set_yticks(self, ticks, labels, *args, **kwargs)

    def set_xticks_spy(self, ticks, labels=None, *args, **kwargs):  # type: ignore[no-untyped-def]
        if labels is not None:
            tick_labels.extend(str(label) for label in labels)
        return original_set_xticks(self, ticks, labels, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "scatter", scatter_spy)
    monkeypatch.setattr(matplotlib.axes.Axes, "set_yticks", set_yticks_spy)
    monkeypatch.setattr(matplotlib.axes.Axes, "set_xticks", set_xticks_spy)
    summary = pd.DataFrame(
        {
            "Feature_Set": ["oversight"],
            "Display_Label": [display_name],
            "mean": [0.2],
            "ci_low": [0.1],
            "ci_high": [0.3],
        }
    )
    folds = pd.DataFrame(
        {
            "feature_set": ["oversight", "oversight"],
            "fold_value": [0.18, 0.22],
            "valid_metric": [True, True],
        }
    )

    manuscript_module._plot_metric_with_uncertainty(
        summary,
        fold_df=folds,
        summary_group_col="Feature_Set",
        summary_label_col="Display_Label",
        fold_group_col="feature_set",
        title="Feature family",
        ylabel="Mean PR-AUC",
        out_path=tmp_path / "figure_02",
    )

    assert display_name in tick_labels
    assert any(len(values) == 2 and size == 15 for values, size in scatter_calls)


@pytest.mark.parametrize(
    ("diagnostic", "constant_partner", "expected"),
    [
        (
            True,
            True,
            [
                "`diagnostic`",
                "comment_thread=fit",
                "fit outcomes: comment_thread",
                "comment_thread=diagnostic",
                "12 rows evaluated",
                "12 nonmissing",
                "0 nonzero",
                "1 distinct nonmissing",
                "range [0, 0]",
                "is_constant_zero=true",
                "total_equals_item_402_rows=12",
                "total_equals_item_402_for_all_rows=true",
                "no standalone variation",
            ],
        ),
        (
            False,
            False,
            [
                "`deferred`",
                "no required outcome is currently fitted",
                "fit outcomes: none",
                "comment_thread=deferred",
                "12 nonmissing",
                "4 nonzero",
                "4 distinct nonmissing",
                "range [0, 3]",
                "is_constant_zero=false",
                "total_equals_item_402_rows=7",
                "total_equals_item_402_for_all_rows=false",
                "varies in this vintage",
            ],
        ),
    ],
    ids=["diagnostic-constant", "deferred-varied"],
)
def test_results_narrative_uses_dml_and_partner_contract_without_ranking_language(
    diagnostic: bool,
    constant_partner: bool,
    expected: list[str],
) -> None:
    narrative = _result_narrative(
        manifest={
            "generated_at_utc": "2026-07-10T00:00:00Z",
            "components": {"public_cascade": {"out_dir": "artifacts/public_cascade"}},
        },
        public_summary={
            "primary_specification": {"feature_set": "all", "train_window": "expanding"}
        },
        public_task=pd.DataFrame(
            {
                "Task": ["comment_thread", "amendment", "8k_402"],
                "Mean_PR_AUC": ["0.3000", "0.2000", "0.1000"],
            }
        ),
        construct_alignment=pd.DataFrame(),
        construct_manifest={"validation_tier": "fixture"},
        reporting_contract=_narrative_reporting_contract(
            diagnostic=diagnostic,
            constant_partner=constant_partner,
        ),
    ).lower()

    for phrase in expected:
        assert phrase in narrative
    for forbidden in ["highest mean pr-auc", "leads on mean pr-auc", "winner", "leader"]:
        assert forbidden not in narrative


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (
            (
                "reporting_boundaries",
                "partner_nonadministrative_amendment",
                "is_constant_zero",
            ),
            1,
        ),
        (("opacity_dml_evidence", "fit_outcomes"), []),
    ],
    ids=["non-boolean-partner-flag", "inconsistent-dml-fit-outcomes"],
)
def test_results_narrative_fails_closed_on_malformed_nested_contract(
    path: tuple[str, ...],
    replacement: object,
) -> None:
    contract = json.loads(json.dumps(_narrative_reporting_contract()))
    cursor = contract
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement

    with pytest.raises(ValueError, match="narrative reporting contract"):
        _result_narrative(
            manifest={
                "generated_at_utc": "2026-07-10T00:00:00Z",
                "components": {"public_cascade": {"out_dir": "artifacts/public_cascade"}},
            },
            public_summary={
                "primary_specification": {
                    "feature_set": "all",
                    "train_window": "expanding",
                }
            },
            public_task=pd.DataFrame(
                {
                    "Task": ["comment_thread", "amendment", "8k_402"],
                    "Mean_PR_AUC": ["0.3000", "0.2000", "0.1000"],
                }
            ),
            construct_alignment=pd.DataFrame(),
            construct_manifest={"validation_tier": "fixture"},
            reporting_contract=contract,
        )


@pytest.mark.parametrize(
    ("component_tier", "artifact_tier", "paired_tier"),
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
def test_package_claim_boundary_uses_paired_bridge_tier_and_status(
    component_tier: str | None,
    artifact_tier: str | None,
    paired_tier: str,
) -> None:
    language = manuscript_module._bridge_language(
        {
            "components": {
                "construct_overlap": {"validation_tier": component_tier},
            }
        },
        {"validation_tier": artifact_tier},
    )
    boundary_builder = getattr(manuscript_module, "_bridge_claim_boundary", None)
    assert callable(boundary_builder), "package claim boundary must use paired bridge language"

    boundary = boundary_builder(language)

    assert boundary["construct_overlap_tier"] == paired_tier
    assert boundary["construct_overlap_status"] == "diagnostic"
    assert boundary["construct_overlap_component_tier"] == (component_tier or "none")
    assert boundary["construct_overlap_artifact_tier"] == (artifact_tier or "none")
    assert boundary["causal_claims_supported"] is False
    assert boundary["unobserved_true_fraud_claims_supported"] is False


def test_validated_bridge_package_retains_wrds_claim_language() -> None:
    bridge_language = getattr(manuscript_module, "_bridge_language", None)
    assert callable(bridge_language), "package bridge language must derive from both tiers"

    language = bridge_language(
        {
            "components": {
                "construct_overlap": {
                    "run_status": "complete",
                    "validation_tier": "wrds_validated",
                }
            }
        },
        {"validation_tier": "wrds_validated"},
    )

    assert "Bridge tier is wrds_validated" in language["construct_lift_note"]
    assert "WRDS-validated" in language["narrative"]
    assert "manuscript-grade" in language["narrative"]


def test_external_manifest_paths_are_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    external_root = tmp_path / "private-fixture-root"
    monkeypatch.setattr(manuscript_module, "PROJECT_ROOT", repo_root)
    package_manifest = {
        "study_dir": _rel(external_root / "study"),
        "out_dir": _rel(external_root / "manuscript_package"),
        "tables": {"table_03": {"csv": _rel(external_root / "tables" / "table_03.csv")}},
        "figures": {"figure_01": {"png": _rel(external_root / "figures" / "figure_01.png")}},
    }

    assert package_manifest["study_dir"] == "<external>/study"
    assert package_manifest["out_dir"] == "<external>/manuscript_package"
    assert package_manifest["tables"]["table_03"]["csv"] == "<external>/table_03.csv"
    assert package_manifest["figures"]["figure_01"]["png"] == "<external>/figure_01.png"
    assert str(tmp_path) not in str(package_manifest)
    assert _rel(repo_root / "artifacts" / "table.csv") == "artifacts/table.csv"


def test_public_fold_support_marks_sparse_folds() -> None:
    task_status = pd.DataFrame(
        {
            "feature_set": ["all", "metadata"],
            "train_window": ["expanding", "expanding"],
            "test_year": [2024, 2024],
            "task": ["8k_402", "8k_402"],
            "status": ["fit", "fit"],
            "n_train": [1000, 1000],
            "n_test": [100, 100],
            "excluded_train": [0, 0],
            "excluded_test": [0, 0],
            "positive_train": [20, 20],
            "positive_test": [SPARSE_POSITIVE_THRESHOLD - 1, SPARSE_POSITIVE_THRESHOLD - 1],
        }
    )

    table = _public_fold_support(task_status)

    assert table.loc[0, "Task"] == "8k_402"
    assert table.loc[0, "Test_Year"] == "2024"
    assert table.loc[0, "Sparse_Excluded"] == "Yes"


def test_task_feature_family_metrics_preserve_task_dimension() -> None:
    metrics = pd.DataFrame(
        {
            "task": ["amendment"] * MIN_VALID_FOLDS_FOR_CI,
            "feature_set": ["metadata"] * MIN_VALID_FOLDS_FOR_CI,
            "test_year": list(range(2020, 2020 + MIN_VALID_FOLDS_FOR_CI)),
            "positive_rate_test": [0.15] * MIN_VALID_FOLDS_FOR_CI,
            "n_test": [100] * MIN_VALID_FOLDS_FOR_CI,
            "roc_auc": [0.65] * MIN_VALID_FOLDS_FOR_CI,
            "pr_auc": [0.25] * MIN_VALID_FOLDS_FOR_CI,
            "brier_skill_score": [0.02] * MIN_VALID_FOLDS_FOR_CI,
            "ece": [0.05] * MIN_VALID_FOLDS_FOR_CI,
        }
    )

    table = _task_feature_family_metrics(metrics)

    assert table.loc[0, "Task"] == "amendment"
    assert table.loc[0, "Feature_Set"] == "metadata"
    assert table.loc[0, "Mean_PR_AUC"] == "0.2500"


def test_construct_alignment_reports_absolute_precision_and_fdr(tmp_path) -> None:
    overlap_dir = tmp_path / "construct_overlap"
    overlap_dir.mkdir()
    pd.DataFrame(
        {
            "model_id": ["public_cascade"],
            "task": ["8k_402"],
            "feature_set": ["all"],
            "train_window": ["rolling_7y"],
            "label_mode": ["benchmark_naive"],
            "score_aggregation": ["mean"],
            "bridge_tier": ["high_confidence"],
            "n_benchmark_positives_in_overlap": [10],
            "n_benchmark_negatives_in_overlap": [90],
            "roc_auc": [0.7],
            "pr_auc": [0.04],
            "top_1pct_precision": [0.1],
            "top_5pct_precision": [0.08],
            "top_10pct_precision": [0.06],
            "top_decile_lift": [2.0],
            "top_decile_lift_ci_low": [1.2],
            "top_decile_lift_ci_high": [2.8],
            "metric_status": ["fit"],
            "bridge_source": ["wrds"],
            "is_primary": [True],
        }
    ).to_csv(overlap_dir / "public_score_benchmark_ranking.csv", index=False)
    pd.DataFrame(
        {
            "model_id": ["bao"],
            "target_public_label": ["label_8k_402_365"],
            "feature_set": ["peer"],
            "train_window": ["expanding"],
            "label_mode": ["naive"],
            "score_aggregation": ["benchmark_score"],
            "bridge_tier": ["high_confidence"],
            "n_public_positives_in_overlap": [20],
            "n_public_negatives_in_overlap": [180],
            "roc_auc": [0.6],
            "pr_auc": [0.03],
            "top_1pct_precision": [0.09],
            "top_5pct_precision": [0.07],
            "top_10pct_precision": [0.05],
            "top_decile_lift": [1.8],
            "top_decile_lift_ci_low": [1.1],
            "top_decile_lift_ci_high": [2.5],
            "metric_status": ["fit"],
            "bridge_source": ["wrds"],
            "is_primary": [True],
        }
    ).to_csv(overlap_dir / "reciprocal_alignment.csv", index=False)

    table = _construct_alignment(tmp_path)

    assert set(table["Top_10pct_Precision"]) == {"0.0600", "0.0500"}
    assert set(table["Top_10pct_FDR"]) == {"0.9400", "0.9500"}
    assert (
        table.loc[table["Direction"].eq("Public score to benchmark positives"), "N"].item()
        == "100"
    )
    assert (
        table.loc[
            table["Direction"].eq("Public score to benchmark positives"), "Top_10pct_K"
        ].item()
        == "10"
    )
    assert (
        table.loc[
            table["Direction"].eq("Public score to benchmark positives"), "Top_10pct_Hits"
        ].item()
        == "1"
    )


def test_construct_alignment_uses_is_primary_not_maximum_lift(tmp_path: Path) -> None:
    overlap_dir = tmp_path / "construct_overlap"
    overlap_dir.mkdir()
    common = {
        "bridge_tier": "high_confidence",
        "metric_status": "fit",
        "bridge_source": "wrds",
        "roc_auc": 0.70,
        "pr_auc": 0.04,
        "top_1pct_precision": 0.10,
        "top_5pct_precision": 0.08,
        "top_10pct_precision": 0.06,
        "top_decile_lift_ci_low": 1.20,
        "top_decile_lift_ci_high": 2.80,
    }
    pd.DataFrame(
        [
            {
                **common,
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "expanding",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "n_benchmark_positives_in_overlap": 10,
                "n_benchmark_negatives_in_overlap": 90,
                "top_decile_lift": 2.0,
                "is_primary": True,
            },
            {
                **common,
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "rolling_7y",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "n_benchmark_positives_in_overlap": 10,
                "n_benchmark_negatives_in_overlap": 90,
                "top_decile_lift": 9.0,
                "is_primary": False,
            },
        ]
    ).to_csv(overlap_dir / "public_score_benchmark_ranking.csv", index=False)
    pd.DataFrame(
        [
            {
                **common,
                "model_id": "benchmark_xgb",
                "target_public_label": "label_8k_402_365",
                "feature_set": "benchmark_all",
                "train_window": "expanding",
                "label_mode": "naive",
                "score_aggregation": "benchmark_score",
                "n_public_positives_in_overlap": 20,
                "n_public_negatives_in_overlap": 180,
                "top_decile_lift": 1.8,
                "is_primary": True,
            },
            {
                **common,
                "model_id": "benchmark_xgb",
                "target_public_label": "label_8k_402_365",
                "feature_set": "benchmark_all",
                "train_window": "rolling_7y",
                "label_mode": "naive",
                "score_aggregation": "benchmark_score",
                "n_public_positives_in_overlap": 20,
                "n_public_negatives_in_overlap": 180,
                "top_decile_lift": 8.0,
                "is_primary": False,
            },
        ]
    ).to_csv(overlap_dir / "reciprocal_alignment.csv", index=False)

    table = _construct_alignment(tmp_path)

    assert set(table["Window"]) == {"expanding"}
    assert set(table["Top_Decile_Lift"]) == {"2.0000", "1.8000"}


def test_public_sample_attrition_preserves_sequence_and_task_branches() -> None:
    summary = {
        "sample_attrition": [
            {"stage": "source_issuer_origin", "n_rows": 100, "task": "all"},
            {"stage": "fiscal_year_2011_2024", "n_rows": 80, "task": "all"},
            {"stage": "domestic_us_gaap_proxy", "n_rows": 75, "task": "all"},
            {"stage": "observable_365_day_horizon", "n_rows": 70, "task": "all"},
            {"stage": "eligible_comment_thread", "n_rows": 68, "task": "comment_thread"},
            {"stage": "eligible_amendment", "n_rows": 69, "task": "amendment"},
            {"stage": "eligible_8k_402", "n_rows": 65, "task": "8k_402"},
        ]
    }

    table = _public_sample_attrition_table(summary).set_index("Stage")

    assert table.loc["source_issuer_origin", "Dropped_From_Parent"] == 0
    assert table.loc["fiscal_year_2011_2024", "Dropped_From_Parent"] == 20
    assert table.loc["observable_365_day_horizon", "Dropped_From_Parent"] == 5
    assert table.loc["eligible_comment_thread", "Dropped_From_Parent"] == 2
    assert table.loc["eligible_amendment", "Dropped_From_Parent"] == 1
    assert table.loc["eligible_8k_402", "Dropped_From_Parent"] == 5


def test_public_opacity_dml_displays_explicit_dimensions_and_nan(tmp_path: Path) -> None:
    cascade_dir = tmp_path / "public_cascade"
    cascade_dir.mkdir()
    pd.DataFrame(
        {
            "outcome": ["comment_thread", "amendment"],
            "status": ["fit", "skipped_one_class_or_too_small"],
            "n_obs": [100, 100],
            "prevalence": [0.10, 0.00],
            "coef": [0.02, float("nan")],
            "std_err": [0.01, float("nan")],
            "p_value": [0.05, float("nan")],
            "n_raw_controls": [60, 60],
            "n_encoded_controls": [64, float("nan")],
            "n_opacity_components": [17, 17],
        }
    ).to_csv(cascade_dir / "public_opacity_dml.csv", index=False)

    table = _public_opacity_dml_table(tmp_path)

    assert table[["Raw_Controls", "Encoded_Controls", "Opacity_Components"]].to_dict(
        "records"
    ) == [
        {"Raw_Controls": "60", "Encoded_Controls": "64", "Opacity_Components": "17"},
        {"Raw_Controls": "60", "Encoded_Controls": "", "Opacity_Components": "17"},
    ]
    assert DML_INTERVAL_NOTE == (
        "Raw controls are source variables before encoding; encoded controls are nuisance-model "
        "columns reported at the maximum fold-local width after training-fold categorical "
        "expansion and imputation; opacity components form the missingness-density treatment. "
        "Intervals use HC3 residual OLS after cross-fitting. The estimates are adjusted "
        "associations, not identified structural effects."
    )


def test_bridge_sample_boundaries_reports_shares_and_interpretations(tmp_path) -> None:
    overlap_dir = tmp_path / "construct_overlap"
    bridge_dir = tmp_path / "bridge_probe"
    overlap_dir.mkdir()
    bridge_dir.mkdir()
    pd.DataFrame(
        {
            "bridge_tier": ["full_raw", "ambiguous", "dropped", "high_confidence"],
            "rows": [100, 10, 40, 50],
            "benchmark_positives": [20, 2, 8, 10],
        }
    ).to_csv(overlap_dir / "overlap_sample_flow.csv", index=False)
    pd.DataFrame(
        {
            "data_year": [2020, 2021],
            "unmatched_rows": [3, 7],
            "unmatched_positive_rate": [0.1, 0.2],
        }
    ).to_csv(bridge_dir / "unmatched_raw_characteristics.csv", index=False)

    table = _bridge_sample_boundaries(tmp_path)

    high_conf = table.loc[table["Boundary"].eq("high_confidence")].iloc[0]
    assert high_conf["Row_Share"] == "0.5000"
    assert high_conf["Positive_Share"] == "0.5000"
    assert "headline bridge-gated" in high_conf["Interpretation"]
    assert "unmatched_raw" not in set(table["Boundary"])
    assert table.attrs["unmatched_raw_rows"] == 10


def test_bridge_overlap_matrix_keeps_all_public_labels(tmp_path) -> None:
    overlap_dir = tmp_path / "construct_overlap"
    overlap_dir.mkdir()
    pd.DataFrame(
        {
            "public_label": [
                "label_comment_thread_365",
                "label_amendment_365",
                "label_8k_402_365",
            ],
            "bridge_tier": ["high_confidence", "high_confidence", "high_confidence"],
            "n": [100, 100, 100],
            "benchmark_positive_rows": [10, 10, 10],
            "public_positive_rows": [30, 20, 5],
            "both_positive_rows": [4, 5, 2],
            "benchmark_prevalence": [0.1, 0.1, 0.1],
            "public_prevalence": [0.3, 0.2, 0.05],
            "public_rate_given_benchmark_pos": [0.4, 0.5, 0.2],
            "public_rate_given_benchmark_neg": [0.2889, 0.1667, 0.0333],
            "lift_public_given_benchmark": [1.3, 2.5, 4.0],
            "benchmark_rate_given_public_pos": [0.1333, 0.25, 0.4],
            "benchmark_rate_given_public_neg": [0.0857, 0.0625, 0.0842],
            "lift_benchmark_given_public": [1.3, 2.5, 4.0],
        }
    ).to_csv(overlap_dir / "label_contingency_lift.csv", index=False)

    table = _bridge_overlap_matrix(tmp_path)

    assert table["Public_Label"].tolist() == ["comment_thread", "amendment", "8k_402"]
    assert "Public_Rate_If_Benchmark_Pos" in table.columns


def _selection_panel(rows: int, *, label: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "form": ["10-K"] * rows,
            "entity_type": ["operating"] * rows,
            "size": list(range(1, rows + 1)),
            "xbrl_ratio_log_assets": list(range(1, rows + 1)),
            "days_since_previous_filing": [365] * rows,
            "prior_filing_count": [1] * rows,
            "public_history_comment_thread_3y_count": [0] * rows,
            "issuer_has_fpi_form_year": [0] * rows,
            "censored_365": [0] * rows,
            "label_comment_thread_365": [label] * rows,
            "label_amendment_365": [label] * rows,
            "label_8k_402_365": [label] * rows,
        }
    )


def test_selection_profile_names_observed_same_year_fpi_form_indicator(
    tmp_path: Path,
) -> None:
    panel = _selection_panel(2, label=0)
    panel["issuer_has_fpi_form_year"] = [0, 1]
    panel_path = tmp_path / "issuer_origin_panel.parquet"
    write_table(panel, panel_path)

    selection = manuscript_module._selection_profile_table(panel_path)
    fpi_rows = selection.loc[selection["Stratum"].eq("Observed same-year FPI-form indicator")]

    assert fpi_rows["Group"].tolist() == [
        "No observed 20-F/40-F/6-K",
        "Observed 20-F/40-F/6-K",
    ]


def _write_bound_study_fixture(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, Path]]:
    silver = tmp_path / "lake" / "silver"
    gold = tmp_path / "lake" / "gold"
    silver.mkdir(parents=True)
    gold.mkdir(parents=True)
    paths = {
        "public_lake_run_metadata": silver / "public_lake_run_metadata.json",
        "form_ap_source_metadata": silver / "form_ap_source_metadata.json",
        "public_lake_final_report": silver / "public_lake_final_report.json",
        "issuer_origin_panel": gold / "issuer_origin_panel.parquet",
    }
    paths["public_lake_run_metadata"].write_text(
        json.dumps({"as_of_date": "2026-07-06"}), encoding="utf-8"
    )
    paths["form_ap_source_metadata"].write_text(
        json.dumps(
            {
                "source_kind": "verified_zip_member",
                "archive_sha256": "a" * 64,
                "member": "FirmFilings.csv",
                "member_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    write_table(_selection_panel(1, label=0), paths["issuer_origin_panel"])
    row_counts = {
        key: 0
        for key in {
            "comment_thread",
            "correction_event",
            "filing_dim",
            "filing_origin_panel",
            "filing_xbrl_dim",
            "issuer_dim",
            "issuer_origin_panel",
            "note_summary",
            "notes_filing_dim",
            "xbrl_core_fact",
            "xbrl_fact_summary",
        }
    }
    row_counts["issuer_origin_panel"] = 1
    paths["public_lake_final_report"].write_text(
        json.dumps(
            {
                "schema_version": "public-lake-final-report-v1",
                "as_of_date": "2026-07-06",
                "public_lake_run_metadata_sha256": _sha256(paths["public_lake_run_metadata"]),
                "issuer_origin_panel_sha256": _sha256(paths["issuer_origin_panel"]),
                "row_counts": row_counts,
                "row_count_errors": {},
            }
        ),
        encoding="utf-8",
    )
    manifest: dict[str, object] = {
        "repo_commit": STUDY_COMMIT,
        "public_lake_inputs": {
            key: {
                "path": str(path),
                "exists": True,
                "kind": "file",
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for key, path in paths.items()
        },
    }
    study_manifest_path = tmp_path / "study" / "study_run_manifest.json"
    study_manifest_path.parent.mkdir()
    study_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return study_manifest_path, manifest, paths


def test_package_tables_use_only_study_bound_report_and_panel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    study_manifest_path, manifest, _ = _write_bound_study_fixture(tmp_path)
    ambient_root = tmp_path / "ambient"
    ambient_report = ambient_root / "logs" / "public_lake_full" / "new" / "run_report.json"
    ambient_report.parent.mkdir(parents=True)
    ambient_report.write_text(
        json.dumps({"row_counts": {"issuer_origin_panel": 999}}), encoding="utf-8"
    )
    ambient_panel = ambient_root / "gold" / "issuer_origin_panel.parquet"
    write_table(_selection_panel(9, label=1), ambient_panel)
    monkeypatch.setattr(manuscript_module, "ARTIFACTS_DIR", ambient_root)

    bound = manuscript_module._bound_public_lake_inputs(
        manifest,
        study_manifest_path=study_manifest_path,
    )
    scale = manuscript_module._public_lake_scale(bound["final_report"])
    selection = manuscript_module._selection_profile_table(bound["issuer_origin_panel"])

    assert scale.loc[scale["Artifact"].eq("issuer_origin_panel"), "Artifact_Rows"].item() == "1"
    assert set(selection["Issuer_Years"]) == {"1"}


@pytest.mark.parametrize("missing_key", ["public_lake_final_report", "issuer_origin_panel"])
def test_package_rejects_missing_bound_report_or_panel(
    tmp_path: Path,
    missing_key: str,
) -> None:
    study_manifest_path, manifest, paths = _write_bound_study_fixture(tmp_path)
    paths[missing_key].unlink()

    with pytest.raises(FileNotFoundError, match=paths[missing_key].name):
        manuscript_module._bound_public_lake_inputs(
            manifest,
            study_manifest_path=study_manifest_path,
        )


def test_package_rejects_malformed_bound_report(tmp_path: Path) -> None:
    study_manifest_path, manifest, paths = _write_bound_study_fixture(tmp_path)
    report_path = paths["public_lake_final_report"]
    report_path.write_text('{"schema_version":', encoding="utf-8")
    manifest["public_lake_inputs"]["public_lake_final_report"].update(  # type: ignore[index,union-attr]
        {"sha256": _sha256(report_path), "size_bytes": report_path.stat().st_size}
    )

    with pytest.raises(ValueError, match="valid JSON"):
        manuscript_module._bound_public_lake_inputs(
            manifest,
            study_manifest_path=study_manifest_path,
        )


def test_selection_profile_rejects_malformed_bound_panel(tmp_path: Path) -> None:
    panel = tmp_path / "issuer_origin_panel.parquet"
    panel.write_bytes(b"not parquet")

    with pytest.raises(ValueError, match="issuer-origin panel"):
        manuscript_module._selection_profile_table(panel)


def _write_package_manifest_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    study_manifest_path = tmp_path / "study" / "study_run_manifest.json"
    study_manifest_path.parent.mkdir()
    evidence = {
        "required_outcomes": ["comment_thread", "amendment", "8k_402"],
        "status_by_outcome": {
            "comment_thread": "fit",
            "amendment": "skipped_one_class_or_too_small",
            "8k_402": "skipped_constant_treatment",
        },
        "fit_outcomes": ["comment_thread"],
        "maturity_by_outcome": {
            "comment_thread": "diagnostic",
            "amendment": "deferred",
            "8k_402": "deferred",
        },
    }
    feature_family_summary = {
        "oversight": {
            "model_eligible_features": ["prior_filing_count"],
            "reported_as_standalone": True,
        },
        "visibility_history": {"n_features": 24},
    }
    reporting_boundaries = {
        "schema_version": "public-reporting-boundaries-v1",
        "sample_proxy": {
            "artifact_field": "is_domestic_us_gaap_proxy",
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
            "nonzero_rows": 1200,
            "n_distinct_nonmissing": 8,
            "is_constant_zero": False,
        },
    }
    public_dir = study_manifest_path.parent / "public_cascade"
    public_dir.mkdir()
    public_summary = {
        "reporting_boundaries": reporting_boundaries,
        "feature_family_summary": feature_family_summary,
        "opacity_dml_evidence": evidence,
    }
    (public_dir / "public_cascade_summary.json").write_text(
        json.dumps(public_summary, indent=2), encoding="utf-8"
    )
    claim_maturity = {
        "public_prediction": "reportable",
        "feature_and_window_sensitivity": "supporting",
        "construct_alignment": "supporting",
        "opacity_dml": "diagnostic",
    }
    study_manifest_path.write_text(
        json.dumps(
            {
                "repo_commit": STUDY_COMMIT,
                "components": {
                    "public_cascade": {
                        "status": "complete",
                        "opacity_dml_evidence": evidence,
                    }
                },
                "claim_maturity": claim_maturity,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    package_dir = tmp_path / "manuscript_package"
    (package_dir / "tables").mkdir(parents=True)
    (package_dir / "figures").mkdir()

    def record(relative_path: str, content: bytes) -> dict[str, str]:
        path = package_dir / relative_path
        path.write_bytes(content)
        return {"path": relative_path, "sha256": _sha256(path)}

    tables = {
        key: {
            fmt: record(f"tables/{key}.{fmt}", f"{key}-{fmt}".encode())
            for fmt in ("csv", "md", "tex")
        }
        for key in sorted(PACKAGE_TABLE_KEYS)
    }
    figures = {
        key: {
            fmt: record(f"figures/{key}.{fmt}", f"{key}-{fmt}".encode()) for fmt in ("png", "pdf")
        }
        for key in sorted(PACKAGE_FIGURE_KEYS)
    }
    manifest: dict[str, object] = {
        "schema_version": "manuscript-package-v2",
        "study_commit": STUDY_COMMIT,
        "study_manifest_sha256": _sha256(study_manifest_path),
        "tables": tables,
        "figures": figures,
        "narrative": record("results_narrative.md", b"narrative"),
        "reporting_contract": {
            "reporting_boundaries": reporting_boundaries,
            "feature_family_summary": feature_family_summary,
            "opacity_dml_evidence": evidence,
            "claim_maturity": claim_maturity,
            "artifact_ownership": json.loads(json.dumps(EXPECTED_ARTIFACT_OWNERSHIP)),
        },
    }
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return package_dir, study_manifest_path, manifest


def test_exact_package_manifest_and_inventory_validate(tmp_path: Path) -> None:
    package_dir, study_manifest_path, manifest = _write_package_manifest_fixture(tmp_path)

    validated = manuscript_module._validate_package_tree(package_dir, study_manifest_path)

    assert set(validated["tables"]) == PACKAGE_TABLE_KEYS
    assert set(validated["figures"]) == PACKAGE_FIGURE_KEYS
    assert validated["schema_version"] == "manuscript-package-v2"
    assert validated["reporting_contract"] == manifest["reporting_contract"]


def test_reporting_contract_rejects_summary_component_dml_evidence_divergence() -> None:
    with pytest.raises(
        ValueError,
        match="^public summary DML evidence must equal the public component copy$",
    ):
        manuscript_module._reporting_contract(
            {
                "components": {
                    "public_cascade": {
                        "opacity_dml_evidence": {"fit_outcomes": []},
                    }
                },
                "claim_maturity": {},
            },
            {
                "reporting_boundaries": {},
                "feature_family_summary": {},
                "opacity_dml_evidence": {"fit_outcomes": ["comment_thread"]},
            },
        )


def test_package_contract_owns_every_artifact_key_exactly_once(tmp_path: Path) -> None:
    package_dir, study_manifest_path, _ = _write_package_manifest_fixture(tmp_path)

    contract = manuscript_module._validate_package_tree(package_dir, study_manifest_path)[
        "reporting_contract"
    ]
    ownership = contract["artifact_ownership"]
    tables = [key for owner in ownership.values() for key in owner["tables"]]
    figures = [key for owner in ownership.values() for key in owner["figures"]]

    assert len(tables) == len(set(tables))
    assert len(figures) == len(set(figures))
    assert set(tables) == PACKAGE_TABLE_KEYS
    assert set(figures) == PACKAGE_FIGURE_KEYS


def test_package_requires_raw_reporting_contract_artifacts_early() -> None:
    assert {
        "public_cascade/public_cascade_task_status.csv",
        "public_cascade/public_opacity_dml.csv",
        "public_cascade/public_opacity_dml_meta.json",
    } <= set(manuscript_module.REQUIRED_ARTIFACTS)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("reporting_boundaries", "sample_proxy", "validates_fpi_status"), True),
        (("feature_family_summary", "oversight", "model_eligible_features"), []),
        (
            (
                "reporting_boundaries",
                "pcaob_inspection_predictors",
                "inspection_event_joined_to_gold",
            ),
            True,
        ),
        (
            (
                "reporting_boundaries",
                "partner_nonadministrative_amendment",
                "is_constant_zero",
            ),
            True,
        ),
        (("opacity_dml_evidence", "fit_outcomes"), []),
        (("claim_maturity", "opacity_dml"), "deferred"),
        (("artifact_ownership", "experiment_3", "tables"), ["table_12", "table_01"]),
    ],
    ids=[
        "proxy-flag",
        "oversight-features",
        "inspection-status",
        "partner-variation",
        "dml-evidence",
        "dml-maturity",
        "ownership",
    ],
)
def test_package_contract_rejects_mutation_against_upstream(
    tmp_path: Path,
    path: tuple[str, ...],
    replacement: object,
) -> None:
    package_dir, study_manifest_path, manifest = _write_package_manifest_fixture(tmp_path)
    cursor = manifest["reporting_contract"]
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="reporting contract|claim maturity"):
        manuscript_module._validate_package_tree(package_dir, study_manifest_path)


def test_package_manifest_accepts_case_insensitive_full_commit_match(tmp_path: Path) -> None:
    package_dir, study_manifest_path, manifest = _write_package_manifest_fixture(tmp_path)
    study_manifest = json.loads(study_manifest_path.read_text(encoding="utf-8"))
    study_manifest["repo_commit"] = STUDY_COMMIT.upper()
    study_manifest_path.write_text(json.dumps(study_manifest), encoding="utf-8")
    manifest["study_manifest_sha256"] = _sha256(study_manifest_path)
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    manuscript_module._validate_package_tree(package_dir, study_manifest_path)


@pytest.mark.parametrize(
    ("study_commit", "package_commit", "match"),
    [
        (MISSING_COMMIT, MISSING_COMMIT, "40-character hexadecimal"),
        (None, None, "40-character hexadecimal"),
        ("", "", "40-character hexadecimal"),
        ("abc123", "abc123", "40-character hexadecimal"),
        ("g" * 40, "g" * 40, "40-character hexadecimal"),
        ("+" + "1" * 39, "+" + "1" * 39, "40-character hexadecimal"),
        ("0x" + "1" * 38, "0x" + "1" * 38, "40-character hexadecimal"),
        ("1" * 40, "2" * 40, "does not match"),
    ],
    ids=["absent", "null", "empty", "short", "nonhex", "plus", "0x", "mismatch"],
)
def test_package_manifest_requires_matching_full_commit_hashes(
    tmp_path: Path,
    study_commit: object,
    package_commit: object,
    match: str,
) -> None:
    package_dir, study_manifest_path, manifest = _write_package_manifest_fixture(tmp_path)
    study_manifest = json.loads(study_manifest_path.read_text(encoding="utf-8"))
    if study_commit is MISSING_COMMIT:
        study_manifest.pop("repo_commit")
        manifest.pop("study_commit")
    else:
        study_manifest["repo_commit"] = study_commit
        manifest["study_commit"] = package_commit
    study_manifest_path.write_text(json.dumps(study_manifest), encoding="utf-8")
    manifest["study_manifest_sha256"] = _sha256(study_manifest_path)
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        manuscript_module._validate_package_tree(package_dir, study_manifest_path)


@pytest.mark.parametrize(
    "mutation",
    ["table_csv_renamed", "table_formats_swapped", "figure_formats_swapped"],
)
def test_package_manifest_rejects_artifact_suffix_mismatched_to_format_label(
    tmp_path: Path,
    mutation: str,
) -> None:
    package_dir, study_manifest_path, manifest = _write_package_manifest_fixture(tmp_path)
    tables = manifest["tables"]  # type: ignore[assignment]
    figures = manifest["figures"]  # type: ignore[assignment]
    if mutation == "table_csv_renamed":
        record = tables["table_01"]["csv"]
        old_path = package_dir / record["path"]
        new_path = old_path.with_suffix(".bin")
        old_path.rename(new_path)
        record.update(
            {
                "path": new_path.relative_to(package_dir).as_posix(),
                "sha256": _sha256(new_path),
            }
        )
    elif mutation == "table_formats_swapped":
        formats = tables["table_01"]
        formats["csv"], formats["md"] = formats["md"], formats["csv"]
    else:
        formats = figures["figure_01"]
        formats["png"], formats["pdf"] = formats["pdf"], formats["png"]
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="exact.*suffix"):
        manuscript_module._validate_package_tree(package_dir, study_manifest_path)


@pytest.mark.parametrize("mutation", ["directory", "manifest", "root"])
def test_package_tree_rejects_symlink_entries(
    tmp_path: Path,
    mutation: str,
) -> None:
    package_dir, study_manifest_path, _ = _write_package_manifest_fixture(tmp_path)
    if mutation == "directory":
        outside = tmp_path / "outside"
        outside.mkdir()
        (package_dir / "escape").symlink_to(outside, target_is_directory=True)
    elif mutation == "manifest":
        manifest_path = package_dir / "manifest.json"
        outside = tmp_path / "outside-manifest.json"
        outside.write_bytes(manifest_path.read_bytes())
        manifest_path.unlink()
        manifest_path.symlink_to(outside)
    else:
        linked_package = tmp_path / "linked-package"
        linked_package.symlink_to(package_dir, target_is_directory=True)
        package_dir = linked_package

    with pytest.raises(ValueError, match="symlink"):
        manuscript_module._validate_package_tree(package_dir, study_manifest_path)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_table", "tables"),
        ("missing_figure", "missing artifact"),
        ("missing_narrative", "missing artifact"),
        ("changed_artifact", "sha256"),
        ("absolute_path", "package-relative POSIX"),
        ("traversal_path", "package-relative POSIX"),
        ("stale_study_digest", "study_manifest_sha256"),
        ("wrong_format_set", "format set"),
        ("undeclared_extra", "undeclared"),
    ],
)
def test_package_manifest_rejects_inventory_tampering(
    tmp_path: Path,
    mutation: str,
    match: str,
) -> None:
    package_dir, study_manifest_path, manifest = _write_package_manifest_fixture(tmp_path)
    tables = manifest["tables"]  # type: ignore[assignment]
    figures = manifest["figures"]  # type: ignore[assignment]
    if mutation == "missing_table":
        del tables["table_01"]
    elif mutation == "missing_figure":
        (package_dir / figures["figure_01"]["png"]["path"]).unlink()
    elif mutation == "missing_narrative":
        (package_dir / manifest["narrative"]["path"]).unlink()  # type: ignore[index]
    elif mutation == "changed_artifact":
        (package_dir / tables["table_01"]["csv"]["path"]).write_bytes(b"changed")
    elif mutation == "absolute_path":
        tables["table_01"]["csv"]["path"] = str(
            (package_dir / "tables" / "table_01.csv").resolve()
        )
    elif mutation == "traversal_path":
        tables["table_01"]["csv"]["path"] = "../table_01.csv"
    elif mutation == "stale_study_digest":
        manifest["study_manifest_sha256"] = "0" * 64
    elif mutation == "wrong_format_set":
        del tables["table_01"]["tex"]
    else:
        (package_dir / "extra.txt").write_text("extra", encoding="utf-8")
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises((FileNotFoundError, ValueError), match=match):
        manuscript_module._validate_package_tree(package_dir, study_manifest_path)


def test_atomic_package_replace_restores_prior_tree_and_cleans_staging_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_dir = tmp_path / "manuscript_package"
    staging_dir = tmp_path / ".manuscript_package.staging"
    final_dir.mkdir()
    staging_dir.mkdir()
    (final_dir / "prior.txt").write_text("prior", encoding="utf-8")
    (staging_dir / "new.txt").write_text("new", encoding="utf-8")
    real_replace = Path.replace

    def fail_staging_replace(path: Path, target: Path) -> Path:
        if path == staging_dir and Path(target) == final_dir:
            raise OSError("simulated package swap failure")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_staging_replace)

    with pytest.raises(OSError, match="simulated package swap failure"):
        manuscript_module._replace_package_tree(staging_dir, final_dir)

    assert (final_dir / "prior.txt").read_text(encoding="utf-8") == "prior"
    assert not staging_dir.exists()
    assert not list(tmp_path.glob(".manuscript_package.backup-*"))
