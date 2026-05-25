from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import src.public_peer_comparison as ppc
from src.public_peer_comparison import (
    PUBLIC_MAPPING_COLUMNS,
    PUBLIC_PREDICTION_COLUMNS,
    PUBLIC_STATUS_COLUMNS,
    _compact_predictions,
    run_public_peer_comparison,
)
from src.table_io import read_table, write_table


def _public_peer_config(tmp_path: Path) -> Path:
    config = tmp_path / "public_cascade.yaml"
    config.write_text(
        """
sample:
  start_year: 2018
  end_year: 2022
  domestic_only: true
analysis:
  candidate_train_windows: [null]
  min_train_years: 3
  feature_sets: ["metadata", "xbrl", "auditor", "oversight", "all"]
  parallel_jobs: 1
  top_k: [1, 2, 50, 100, 200]
model:
  seed: 42
""",
        encoding="utf-8",
    )
    return config


def _issuer_panel(tmp_path: Path, *, duplicate: bool = False) -> Path:
    rows = []
    for year in range(2018, 2023):
        for issuer_id in range(1, 13):
            rows.append(
                {
                    "issuer_cik": f"{issuer_id:010d}",
                    "accession": f"{issuer_id:010d}-{year}-000001",
                    "origin_date": f"{year + 1}-03-15",
                    "filing_date": f"{year + 1}-03-15",
                    "report_date": f"{year}-12-31",
                    "as_of_date": "2026-04-23",
                    "fiscal_year": year,
                    "form": "10-K",
                    "sic": 1200 + issuer_id,
                    "is_domestic_us_gaap_proxy": 1,
                    "label_comment_thread_365": int((issuer_id + year) % 3 == 0),
                    "label_amendment_365": int((issuer_id + year) % 4 == 0),
                    "label_8k_402_365": int((issuer_id + year) % 5 == 0),
                    "label_aaer_proxy_730": int(issuer_id == 1 and year >= 2021),
                    "censored_365": 0,
                    "censored_730": 0,
                    "k402_item_metadata_unknown_365": 0,
                    "xbrl_ratio_receivables_to_revenue": 0.05 + issuer_id / 100,
                    "xbrl_ratio_inventory_to_assets": 0.02 + (year - 2018) / 100,
                    "xbrl_ratio_profitability": 0.01 * (issuer_id % 5) - 0.02,
                    "xbrl_ratio_working_capital_to_assets": 0.1 + issuer_id / 200,
                    "xbrl_ratio_operating_cash_flow_to_assets": 0.03 + issuer_id / 300,
                    "xbrl_ratio_leverage": 0.2 + issuer_id / 100,
                    "form_ap_filing_count": issuer_id % 3,
                    "auditor_partner_prior_other_issuer_8k_402_count": issuer_id % 2,
                    "prior_comment_thread_count": (issuer_id + year) % 4,
                }
            )
    if duplicate:
        rows.append(dict(rows[0]))
    panel_path = tmp_path / "issuer_origin_panel.parquet"
    write_table(pd.DataFrame(rows), panel_path)
    return panel_path


def test_public_peer_full_mode_writes_pr2_artifacts(tmp_path: Path) -> None:
    out_dir = tmp_path / "public_peer"
    result = run_public_peer_comparison(
        config_path=_public_peer_config(tmp_path),
        issuer_origin_panel_path=_issuer_panel(tmp_path),
        out_dir=out_dir,
        mode="full",
        peer_config={"parallel_jobs": 1, "model_threads": 1},
    )

    assert result["summary_md"].exists()
    metrics = pd.read_csv(out_dir / "public_model_family_metrics.csv")
    assert not metrics.empty
    assert "ece" in metrics.columns
    assert "ece_quantile" in metrics.columns
    assert "top_50_precision" in metrics.columns
    assert "bao_top_5pct_ndcg" in metrics.columns
    assert set(metrics["input_kind"]) == {"public_issuer_origin"}
    assert "aaer_proxy" not in set(metrics["task"])
    assert "bao_inspired_tree_ensemble" in set(metrics["peer_model_id"])
    assert "bao_style_ensemble" not in set(metrics["peer_model_id"])
    assert metrics.loc[
        metrics["peer_model_id"].eq("perols_logit"), "calibration_warning"
    ].eq(True).any()

    status = pd.read_csv(out_dir / "public_model_family_task_status.csv")
    assert list(status.columns) == PUBLIC_STATUS_COLUMNS
    fixed = status.loc[status["peer_model_id"].eq("dechow_fixed_fscore_model1")]
    assert not fixed.empty
    assert fixed["reason_code"].eq("missing_required_mapping").all()

    mapping = pd.read_csv(out_dir / "public_model_family_mapping_attrition.csv")
    assert list(mapping.columns) == PUBLIC_MAPPING_COLUMNS
    soft_assets = mapping.loc[mapping["source_variable"].eq("soft_assets")]
    assert not soft_assets.empty
    assert not soft_assets["mapping_status"].eq("exact").any()
    assert "weak_proxy" in set(mapping["mapping_type"])

    predictions = read_table(out_dir / "public_model_family_predictions.parquet")
    assert list(predictions.columns) == PUBLIC_PREDICTION_COLUMNS
    assert not predictions.duplicated(
        subset=[
            "issuer_cik",
            "fiscal_year",
            "task",
            "feature_set",
            "test_year",
            "train_window",
            "peer_model_id",
        ]
    ).any()

    importance = pd.read_csv(out_dir / "public_model_family_feature_importance.csv")
    assert {
        "peer_model_id",
        "task",
        "feature_set",
        "feature_name",
        "importance_type",
    }.issubset(importance.columns)
    assert not importance["feature_name"].astype(str).str.startswith(("label_", "censored_")).any()


@pytest.mark.parametrize("mode", ["none", "light"])
def test_public_peer_non_full_modes_skip(tmp_path: Path, mode: str) -> None:
    out_dir = tmp_path / mode
    run_public_peer_comparison(
        config_path=_public_peer_config(tmp_path),
        issuer_origin_panel_path=_issuer_panel(tmp_path),
        out_dir=out_dir,
        mode=mode,
        peer_config={"parallel_jobs": 1, "model_threads": 1},
    )

    assert pd.read_csv(out_dir / "public_model_family_metrics.csv").empty
    assert pd.read_csv(out_dir / "public_model_family_task_status.csv").empty
    assert f"public_peer_skipped_in_{mode}_mode" in (
        out_dir / "public_model_family_summary.md"
    ).read_text(encoding="utf-8")


def test_public_peer_rejects_duplicate_issuer_year_grain(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="issuer_cik x fiscal_year"):
        run_public_peer_comparison(
            config_path=_public_peer_config(tmp_path),
            issuer_origin_panel_path=_issuer_panel(tmp_path, duplicate=True),
            out_dir=tmp_path / "out",
            mode="full",
            peer_config={"parallel_jobs": 1, "model_threads": 1},
        )


def test_public_peer_compact_prediction_dtypes() -> None:
    compact = _compact_predictions(
        pd.DataFrame(
            {
                "issuer_cik": ["1"],
                "fiscal_year": [2022],
                "origin_date": ["2023-03-01"],
                "task": ["comment_thread"],
                "feature_set": ["all"],
                "test_year": [2022],
                "train_window": ["expanding"],
                "peer_model_id": ["bertomeu_style_xgb"],
                "predicted_prob": [0.123456789],
                "observed_label": [1],
            }
        )
    )
    assert str(compact["predicted_prob"].dtype) == "float32"
    assert str(compact["observed_label"].dtype) == "int8"
    assert str(compact["fiscal_year"].dtype) == "int16"


def test_public_peer_helper_branches_and_empty_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ppc._public_feature_group("note_text_count") == "text"
    assert ppc._public_feature_group("form_ap_filing_count") == "auditor"
    assert ppc._public_feature_group("prior_comment_thread_count") == "oversight"
    assert ppc._compact_predictions(pd.DataFrame()).empty
    assert "No public peer tasks" in ppc._summary_markdown(
        mode="full",
        status_df=pd.DataFrame(),
        metrics_df=pd.DataFrame(),
        mapping_df=pd.DataFrame(),
    )

    panel = read_table(_issuer_panel(tmp_path))
    mapping = pd.DataFrame(
        {"mapping_status": ["exact"], "coverage_rate": [1.0], "repo_column": ["sic"]}
    )
    mappings = {"dechow": mapping, "dechow_fixed": mapping, "bao": mapping}

    monkeypatch.setattr(
        ppc,
        "_feature_columns_for_public_spec",
        lambda *args, **kwargs: (["sic"], "bad_quality", 0.0),
    )
    with pytest.raises(ValueError, match="mapping_quality"):
        ppc._fit_public_peer_unit(
            spec={"peer_model_id": "perols_logit", "kind": "logit"},
            panel=panel,
            feature_set="metadata",
            feature_cols=["sic"],
            tasks=[(None, 2022, [2018, 2019, 2020])],
            min_train_years=1,
            top_k=[1],
            seed=42,
            mapping_by_peer=mappings,
        )
    monkeypatch.undo()

    rows, metrics, preds, _, _ = ppc._fit_public_peer_unit(
        spec={"peer_model_id": "perols_logit", "kind": "logit", "imbalance_strategy": "none"},
        panel=panel,
        feature_set="metadata",
        feature_cols=[],
        tasks=[(None, 2022, [2018, 2019, 2020])],
        min_train_years=1,
        top_k=[1],
        seed=42,
        mapping_by_peer=mappings,
    )
    assert "no_active_features" in {row["reason_code"] for row in rows}
    assert metrics == preds == []

    rows, *_ = ppc._fit_public_peer_unit(
        spec={"peer_model_id": "perols_logit", "kind": "logit", "imbalance_strategy": "none"},
        panel=panel,
        feature_set="metadata",
        feature_cols=["sic"],
        tasks=[(None, 2030, [2018])],
        min_train_years=5,
        top_k=[1],
        seed=42,
        mapping_by_peer=mappings,
    )
    assert "insufficient_train_or_test_years" in {row["reason_code"] for row in rows}

    one_class = panel.copy()
    one_class["label_comment_thread_365"] = 0
    rows, *_ = ppc._fit_public_peer_unit(
        spec={"peer_model_id": "perols_logit", "kind": "logit", "imbalance_strategy": "none"},
        panel=one_class,
        feature_set="metadata",
        feature_cols=["sic"],
        tasks=[(None, 2022, [2018, 2019, 2020])],
        min_train_years=1,
        top_k=[1],
        seed=42,
        mapping_by_peer=mappings,
    )
    assert "one_class_train_or_empty_features" in {row["reason_code"] for row in rows}

    monkeypatch.setattr(
        ppc,
        "_fit_peer_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    rows, *_ = ppc._fit_public_peer_unit(
        spec={"peer_model_id": "perols_logit", "kind": "logit", "imbalance_strategy": "none"},
        panel=panel,
        feature_set="metadata",
        feature_cols=["sic"],
        tasks=[(None, 2022, [2018, 2019, 2020])],
        min_train_years=1,
        top_k=[1],
        seed=42,
        mapping_by_peer=mappings,
    )
    assert "fit_error:RuntimeError" in {row["reason_code"] for row in rows}
