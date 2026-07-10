from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import src.construct_overlap as construct_overlap

from src.construct_overlap import (
    BOOTSTRAP_INTERVAL_METHOD,
    BOOTSTRAP_REPS,
    BOOTSTRAP_SEED,
    _bridge_evidence_from_crosswalk,
    _finalize_alignment_rows,
    _primary_evidence,
    _ranking_metrics,
    _select_unique_row,
    run_construct_overlap,
)
from src.table_io import read_table, write_table


TEST_ALIGNMENT_CONFIG = {
    "bootstrap_seed": 42,
    "bootstrap_reps": 1000,
    "exploratory_top_n": 5,
    "public_to_benchmark_primary": {
        "model_id": "public_cascade",
        "task": "8k_402",
        "feature_set": "all",
        "train_window": "expanding",
        "label_mode": "benchmark_naive",
        "score_aggregation": "mean",
        "bridge_tier": "high_confidence",
    },
    "benchmark_to_public_primary": {
        "model_id": "benchmark_xgb",
        "target_public_label": "label_8k_402_365",
        "feature_set": "benchmark_all",
        "train_window": "expanding",
        "label_mode": "naive",
        "score_aggregation": "benchmark_score",
        "bridge_tier": "high_confidence",
    },
}


def _write_toy_study(
    tmp_path: Path,
    *,
    with_opacity: bool = True,
    crosswalk_source: str = "wrds_sec_analytics_cik_gvkey_link",
    match_method: str = "wrds_sec_analytics_cik_gvkey_intersection",
) -> tuple[Path, Path, Path]:
    study = tmp_path / "study"
    benchmark = study / "benchmark"
    cascade = study / "public_cascade"
    peer = study / "peer_comparison"
    benchmark.mkdir(parents=True)
    cascade.mkdir(parents=True)
    peer.mkdir(parents=True)
    linkage = tmp_path / "linkage"
    linkage.mkdir()
    public_panel = tmp_path / "issuer_origin_panel.parquet"
    crosswalk = linkage / "gvkey_cik_year.csv"

    raw_rows = []
    crosswalk_rows = []
    public_rows = []
    public_predictions = []
    benchmark_predictions = []
    peer_predictions = []

    for idx in range(80):
        gvkey = str(1000 + idx)
        cik = str(320000 + idx).zfill(10)
        benchmark_label_value = int(idx < 32)
        public_label = int(idx < 40)
        raw_rows.append(
            {
                "gvkey": gvkey,
                "data_year": 2018,
                "misstatement firm-year": benchmark_label_value,
                "detection_year_proxy": 2020 if benchmark_label_value and idx < 4 else pd.NA,
                "res_an0": int(benchmark_label_value and idx % 4 == 0),
                "res_an1": 0,
                "res_an2": 0,
                "res_an3": 0,
            }
        )
        crosswalk_rows.append(
            {
                "gvkey": gvkey,
                "data_year": 2018,
                "issuer_cik": cik,
                "source": crosswalk_source,
                "match_method": match_method,
            }
        )
        public_rows.append(
            {
                "issuer_cik": cik,
                "fiscal_year": 2018,
                "origin_date": "2019-05-15",
                "label_comment_thread_365": public_label,
                "label_amendment_365": int(idx < 36),
                "label_8k_402_365": int(idx < 30),
            }
        )
        public_predictions.append(
            {
                "issuer_cik": cik,
                "fiscal_year": 2018,
                "feature_set": "all",
                "train_window": "expanding",
                "task": "8k_402",
                "probability": 0.9 - idx * 0.01,
                "label": public_label,
            }
        )
        benchmark_predictions.append(
            {
                "gvkey": gvkey,
                "data_year": 2018,
                "misstatement firm-year": benchmark_label_value,
                "detection_year_proxy": 2020 if benchmark_label_value else pd.NA,
                "window": "expanding",
                "label_mode": "naive",
                "pred_prob": 0.85 - idx * 0.01,
            }
        )
        peer_predictions.append(
            {
                "gvkey": gvkey,
                "data_year": 2018,
                "label_mode": "naive",
                "test_year": 2018,
                "train_window": "expanding",
                "peer_model_id": "bertomeu_style_xgb",
                "predicted_prob": 0.8 - idx * 0.01,
                "observed_label": benchmark_label_value,
            }
        )
    # One ambiguous row: two CIKs in the same gvkey-year, one public label.
    raw_rows.append(
        {
            "gvkey": "9000",
            "data_year": 2018,
            "misstatement firm-year": 1,
            "detection_year_proxy": pd.NA,
            "res_an0": 0,
            "res_an1": 0,
            "res_an2": 0,
            "res_an3": 0,
        }
    )
    for suffix, label, prob in [("1", 0, 0.1), ("2", 1, 0.9)]:
        cik = f"00009000{suffix}"
        crosswalk_rows.append(
            {
                "gvkey": "9000",
                "data_year": 2018,
                "issuer_cik": cik,
                "source": crosswalk_source,
                "match_method": match_method,
            }
        )
        public_rows.append(
            {
                "issuer_cik": cik,
                "fiscal_year": 2018,
                "origin_date": "2019-05-20",
                "label_comment_thread_365": label,
                "label_amendment_365": label,
                "label_8k_402_365": 0,
            }
        )
        public_predictions.append(
            {
                "issuer_cik": cik,
                "fiscal_year": 2018,
                "feature_set": "all",
                "train_window": "expanding",
                "task": "8k_402",
                "probability": prob,
                "label": label,
            }
        )

    # One dropped row: bridge exists but no public issuer-year match.
    raw_rows.append(
        {
            "gvkey": "9999",
            "data_year": 2018,
            "misstatement firm-year": 0,
            "detection_year_proxy": pd.NA,
            "res_an0": 0,
            "res_an1": 0,
            "res_an2": 0,
            "res_an3": 0,
        }
    )
    crosswalk_rows.append(
        {
            "gvkey": "9999",
            "data_year": 2018,
            "issuer_cik": "0000099999",
            "source": crosswalk_source,
            "match_method": match_method,
        }
    )

    write_table(pd.DataFrame(raw_rows), benchmark / "master_panel.parquet")
    write_table(pd.DataFrame(benchmark_predictions), benchmark / "rolling_predictions.parquet")
    write_table(pd.DataFrame(public_rows), public_panel)
    write_table(pd.DataFrame(public_predictions), cascade / "public_cascade_predictions.parquet")
    write_table(pd.DataFrame(peer_predictions), peer / "detected_misstatement_model_family_predictions.parquet")
    pd.DataFrame(crosswalk_rows).to_csv(crosswalk, index=False)
    if with_opacity:
        pd.DataFrame(
            {
                "outcome": ["comment_thread", "amendment"],
                "label_col": ["label_comment_thread_365", "label_amendment_365"],
                "censor_col": ["censored_365", "censored_365"],
                "treatment": ["missingness_density_score", "missingness_density_score"],
                "n_obs": [40, 40],
                "prevalence": [0.5, 0.3],
                "mean_treatment": [0.2, 0.2],
                "n_raw_controls": [60, 60],
                "n_encoded_controls": [64, 63],
                "n_controls": [64, 63],
                "n_controls_definition": [
                    "encoded_nuisance_columns",
                    "encoded_nuisance_columns",
                ],
                "n_opacity_components": [17, 17],
                "status": ["fit", "fit"],
                "coef": [0.1, 0.2],
                "std_err": [0.2, 0.3],
                "p_value": [0.6, 0.5],
            }
        ).to_csv(cascade / "public_opacity_dml.csv", index=False)
        (cascade / "public_opacity_dml_meta.json").write_text(
            json.dumps(
                {
                    "n_raw_controls": 60,
                    "n_encoded_controls_by_outcome": {
                        "comment_thread": 64,
                        "amendment": 63,
                    },
                    "n_opacity_components": 17,
                    "n_controls_definition": "encoded_nuisance_columns",
                }
            ),
            encoding="utf-8",
        )
    (study / "study_run_manifest.json").write_text(
        json.dumps(
            {
                "inputs": {
                    "crosswalk": str(crosswalk),
                    "issuer_origin_panel": str(public_panel),
                }
            }
        ),
        encoding="utf-8",
    )
    return study, crosswalk, public_panel


def test_construct_overlap_end_to_end_writes_validation_artifacts(
    tmp_path: Path,
) -> None:
    study, crosswalk, public_panel = _write_toy_study(tmp_path)
    result = run_construct_overlap(
        study_dir=study,
        crosswalk_path=crosswalk,
        issuer_origin_panel_path=public_panel,
        alignment_config=TEST_ALIGNMENT_CONFIG,
    )
    out = study / "construct_overlap"

    assert result["run_status"] == "complete"
    assert result["validation_tier"] == "wrds_validated"
    study_manifest = json.loads((study / "study_run_manifest.json").read_text(encoding="utf-8"))
    construct_component = study_manifest["components"]["construct_overlap"]
    assert construct_component["run_status"] == "complete"
    assert construct_component["validation_tier"] == "wrds_validated"
    assert construct_component["out_dir"] == str(out)
    assert construct_component["manifest_json"] == str(out / "construct_overlap_manifest.json")
    assert construct_component["summary_md"] == str(out / "construct_overlap_summary.md")
    construct_manifest = json.loads(
        (out / "construct_overlap_manifest.json").read_text(encoding="utf-8")
    )
    assert construct_manifest["interval_method"] == BOOTSTRAP_INTERVAL_METHOD
    assert construct_manifest["interval_seed"] == BOOTSTRAP_SEED
    assert construct_manifest["interval_reps"] == BOOTSTRAP_REPS
    assert construct_manifest["interval_scope"] == "primary_plus_top_5_per_direction"
    primary = construct_manifest["primary_alignment"]
    assert primary["public_to_benchmark_count"] == 1
    assert primary["benchmark_to_public_count"] == 1
    assert primary["public_to_benchmark"]["train_window"] == "expanding"
    assert primary["benchmark_to_public"]["model_id"] == "benchmark_xgb"
    for direction in ["public_to_benchmark", "benchmark_to_public"]:
        evidence = construct_manifest["primary_alignment_evidence"][direction]
        assert evidence["metric_status"] == "fit"
        assert np.isfinite(evidence["top_decile_lift"])
        assert np.isfinite(evidence["ci_low"])
        assert np.isfinite(evidence["ci_high"])
        assert evidence["ci_low"] <= evidence["ci_high"]
        maximum = construct_manifest["exploratory_maxima"][direction]
        assert maximum["lift_minus_primary"] == pytest.approx(
            maximum["top_decile_lift"] - maximum["primary_lift"]
        )
    expected = [
        "construct_overlap_manifest.json",
        "construct_overlap_summary.md",
        "overlap_panel.parquet",
        "bridge_confidence_tiers.csv",
        "aggregation_sensitivity.csv",
        "public_score_benchmark_ranking.csv",
        "public_score_benchmark_ranking_sensitivity.csv",
        "reciprocal_alignment.csv",
        "benchmark_positive_public_label_cooccurrence.csv",
        "event_time_concentration.csv",
        "event_time_coverage.csv",
        "res_an_proxy_coverage.csv",
    ]
    for name in expected:
        assert (out / name).exists(), name

    tiers = pd.read_csv(out / "bridge_confidence_tiers.csv")
    assert set(tiers["bridge_tier"]) == {"high_confidence", "ambiguous", "dropped"}
    assert {
        "gvkey",
        "data_year",
        "issuer_cik_count",
        "public_row_count",
        "bridge_tier",
        "reason_code",
    }.issubset(tiers.columns)

    panel = read_table(out / "overlap_panel.parquet")
    shifted = panel.loc[panel["gvkey"].eq("1000")].iloc[0]
    assert shifted["data_year"] == 2018
    assert str(shifted["origin_date_min"]).startswith("2019-05-15")

    aggregation = pd.read_csv(out / "aggregation_sensitivity.csv")
    ambiguous_comment = aggregation.loc[
        aggregation["bridge_tier"].eq("ambiguous")
        & aggregation["public_label"].eq("label_comment_thread_365")
    ].iloc[0]
    assert ambiguous_comment["pos_rate_delta"] > 0
    assert bool(ambiguous_comment["aggregation_sensitive"])

    ranking = pd.read_csv(out / "public_score_benchmark_ranking.csv")
    assert {
        "model_id",
        "task",
        "feature_set",
        "train_window",
        "label_mode",
        "score_aggregation",
        "bridge_tier",
        "n_benchmark_positives_in_overlap",
        "n_benchmark_negatives_in_overlap",
        "roc_auc",
        "pr_auc",
        "top_decile_lift_ci_low",
        "top_decile_lift_ci_high",
        "is_primary",
        "is_exploratory_top5",
        "bridge_source",
    }.issubset(ranking.columns)
    assert set(ranking["bridge_source"]) == {"wrds_sec_analytics_cik_gvkey_link"}
    assert ranking["is_primary"].sum() == 1
    sensitivity = pd.read_csv(out / "public_score_benchmark_ranking_sensitivity.csv")
    assert sensitivity["top_decile_lift_ci_low"].isna().all()
    assert sensitivity["top_decile_lift_ci_high"].isna().all()

    reciprocal = pd.read_csv(out / "reciprocal_alignment.csv")
    assert {
        "target_public_label",
        "n_public_positives_in_overlap",
        "n_public_negatives_in_overlap",
        "is_primary",
        "is_exploratory_top5",
    }.issubset(reciprocal.columns)
    assert reciprocal["is_primary"].sum() == 1

    event_time = pd.read_csv(out / "event_time_concentration.csv")
    assert "p_value" not in event_time.columns
    assert "confidence" not in " ".join(event_time.columns)
    assert 0 in set(event_time["relative_year"])

    cooccur = pd.read_csv(out / "benchmark_positive_public_label_cooccurrence.csv")
    assert {
        "label_pattern",
        "label_comment_thread_365",
        "label_amendment_365",
        "label_8k_402_365",
        "n_benchmark_positives",
        "pct_of_benchmark_positives",
        "display_count",
    }.issubset(cooccur.columns)

    summary = (out / "construct_overlap_summary.md").read_text(encoding="utf-8")
    assert "related but non-identical constructs" in summary
    assert "WRDS/Compustat provenance" in summary

    refreshed = pd.read_csv(
        study / "opacity_validation_refresh" / "opacity_diagnostics_summary.csv"
    ).set_index("outcome")
    assert set(refreshed["n_raw_controls_meta"]) == {60}
    assert refreshed["n_encoded_controls_meta"].to_dict() == {
        "comment_thread": 64,
        "amendment": 63,
    }
    assert set(refreshed["n_opacity_components_meta"]) == {17}
    assert set(refreshed["n_controls_definition_meta"]) == {
        "encoded_nuisance_columns"
    }


def test_construct_overlap_infers_wrds_validation_tier_from_crosswalk_provenance(
    tmp_path: Path,
) -> None:
    study, crosswalk, public_panel = _write_toy_study(
        tmp_path,
        crosswalk_source="wrds_compustat_cik_gvkey_link",
        match_method="wrds_cik_gvkey_link",
    )
    result = run_construct_overlap(
        study_dir=study,
        crosswalk_path=crosswalk,
        issuer_origin_panel_path=public_panel,
        alignment_config=TEST_ALIGNMENT_CONFIG,
    )
    out = study / "construct_overlap"

    assert result["run_status"] == "complete"
    assert result["validation_tier"] == "wrds_validated"
    assert result["bridge_source"] == "wrds_compustat_cik_gvkey_link"
    assert result["bridge_provenance"]["source_values"] == ["wrds_compustat_cik_gvkey_link"]
    ranking = pd.read_csv(out / "public_score_benchmark_ranking.csv")
    assert set(ranking["bridge_source"]) == {"wrds_compustat_cik_gvkey_link"}
    summary = (out / "construct_overlap_summary.md").read_text(encoding="utf-8")
    assert "WRDS-validated bridge sample" in summary
    study_manifest = json.loads((study / "study_run_manifest.json").read_text(encoding="utf-8"))
    assert study_manifest["components"]["construct_overlap"]["validation_tier"] == "wrds_validated"


def test_raw_compustat_link_provenance_is_wrds_validated(
    tmp_path: Path,
) -> None:
    crosswalk = tmp_path / "raw_crosswalk.csv"
    pd.DataFrame(
        [
            {
                "gvkey": "1000",
                "data_year": 2018,
                "issuer_cik": "0000320000",
                "source": "wrds_sec_analytics_cik_gvkey:compustat_company",
                "match_method": "wrds_sec_analytics_cik_gvkey_intersection",
            }
        ]
    ).to_csv(crosswalk, index=False)

    evidence = _bridge_evidence_from_crosswalk(crosswalk)

    assert evidence["bridge_source"] == "wrds_sec_analytics_cik_gvkey_link"
    assert evidence["validation_tier"] == "wrds_validated"


def test_external_crosswalk_without_wrds_provenance_reports_candidate_source(tmp_path: Path) -> None:
    crosswalk = tmp_path / "external_crosswalk.csv"
    pd.DataFrame(
        [
            {
                "gvkey": "1001",
                "data_year": 2018,
                "issuer_cik": "0000320001",
                "source": "external_cik_gvkey",
                "match_method": "external_date_range",
            },
        ]
    ).to_csv(crosswalk, index=False)

    evidence = _bridge_evidence_from_crosswalk(crosswalk)

    assert evidence["bridge_source"] == "external_cik_gvkey"
    assert evidence["validation_tier"] == "candidate_external"


def test_construct_overlap_missing_opacity_writes_blocker_without_failing(tmp_path: Path) -> None:
    study, crosswalk, public_panel = _write_toy_study(tmp_path, with_opacity=False)
    run_construct_overlap(
        study_dir=study,
        crosswalk_path=crosswalk,
        issuer_origin_panel_path=public_panel,
        alignment_config=TEST_ALIGNMENT_CONFIG,
    )
    blockers = json.loads(
        (study / "opacity_validation_refresh" / "opacity_validation_blockers.json").read_text(
            encoding="utf-8"
        )
    )
    assert blockers["blockers"][0]["code"] == "blocked_missing_opacity_artifacts"


def test_construct_overlap_blocks_cleanly_when_crosswalk_is_missing(tmp_path: Path) -> None:
    study, _, public_panel = _write_toy_study(tmp_path)
    missing = tmp_path / "missing_crosswalk.csv"
    result = run_construct_overlap(
        study_dir=study,
        crosswalk_path=missing,
        issuer_origin_panel_path=public_panel,
        alignment_config=TEST_ALIGNMENT_CONFIG,
    )
    assert result["run_status"] == "blocked_missing_crosswalk"
    assert result["validation_tier"] == "none"
    study_manifest = json.loads((study / "study_run_manifest.json").read_text(encoding="utf-8"))
    assert (
        study_manifest["components"]["construct_overlap"]["run_status"]
        == "blocked_missing_crosswalk"
    )


def test_ranking_metric_sparse_and_bootstrap_thresholds() -> None:
    sparse = _ranking_metrics([1, 0, 0, 0, 0], [0.9, 0.1, 0.2, 0.3, 0.4])
    assert sparse["status"] == "blocked_sparse"
    assert np.isnan(sparse["top_decile_lift_ci_low"])

    mid_y = np.array([1] * 12 + [0] * 28)
    mid_score = np.linspace(1, 0, len(mid_y))
    mid = _ranking_metrics(mid_y, mid_score)
    assert mid["status"] == "fit"
    assert np.isnan(mid["top_decile_lift_ci_low"])

    large_y = np.array([1] * 30 + [0] * 30)
    large_score = np.linspace(1, 0, len(large_y))
    large = _ranking_metrics(large_y, large_score)
    repeat = _ranking_metrics(large_y, large_score)
    assert large["status"] == "fit"
    assert np.isfinite(large["top_decile_lift_ci_low"])
    assert np.isfinite(large["top_decile_lift_ci_high"])
    assert large["top_decile_lift_ci_low"] == repeat["top_decile_lift_ci_low"]
    assert large["top_decile_lift_ci_high"] == repeat["top_decile_lift_ci_high"]


def test_select_unique_row_ignores_higher_lift_distractor() -> None:
    frame = pd.DataFrame(
        [
            {
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "expanding",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "bridge_tier": "high_confidence",
                "top_decile_lift": 2.0,
            },
            {
                "model_id": "public_cascade",
                "task": "8k_402",
                "feature_set": "all",
                "train_window": "rolling_7y",
                "label_mode": "benchmark_naive",
                "score_aggregation": "mean",
                "bridge_tier": "high_confidence",
                "top_decile_lift": 9.0,
            },
        ]
    )
    keys = {
        "model_id": "public_cascade",
        "task": "8k_402",
        "feature_set": "all",
        "train_window": "expanding",
        "label_mode": "benchmark_naive",
        "score_aggregation": "mean",
        "bridge_tier": "high_confidence",
    }

    selected = _select_unique_row(frame, keys=keys, direction="public_to_benchmark")

    assert selected["train_window"] == "expanding"
    assert selected["top_decile_lift"] == 2.0


def test_bootstrap_union_includes_primary_outside_top_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "model_id": "m",
            "task": f"task_{idx}",
            "metric_status": "fit",
            "top_decile_lift": float(10 - idx),
        }
        for idx in range(7)
    ]
    frame = pd.DataFrame(
        {
            "model_id": ["m"] * 14,
            "task": [f"task_{idx}" for idx in range(7) for _ in range(2)],
            "target": [0, 1] * 7,
            "score": [0.1, 0.9] * 7,
        }
    )
    monkeypatch.setattr(
        construct_overlap,
        "_bootstrap_lift_ci",
        lambda y, score, *, reps, seed: (1.0, 2.0),
    )

    finalized = _finalize_alignment_rows(
        rows,
        frame=frame,
        group_cols=["model_id", "task"],
        target_col="target",
        score_col="score",
        primary_keys={"model_id": "m", "task": "task_6"},
        exploratory_top_n=5,
        direction="public_to_benchmark",
        bootstrap_seed=42,
        bootstrap_reps=1000,
    )

    assert all(
        pd.notna(finalized[idx]["top_decile_lift_ci_low"])
        for idx in [0, 1, 2, 3, 4, 6]
    )
    assert pd.isna(finalized[5].get("top_decile_lift_ci_low", np.nan))


def test_select_unique_row_rejects_missing_primary() -> None:
    frame = pd.DataFrame({"model_id": ["other"], "task": ["8k_402"]})
    with pytest.raises(ValueError, match="matched 0"):
        _select_unique_row(
            frame,
            keys={"model_id": "public_cascade", "task": "8k_402"},
            direction="public_to_benchmark",
        )


def test_select_unique_row_rejects_duplicate_primary() -> None:
    frame = pd.DataFrame(
        {"model_id": ["public_cascade", "public_cascade"], "task": ["8k_402"] * 2}
    )
    with pytest.raises(ValueError, match="matched 2"):
        _select_unique_row(
            frame,
            keys={"model_id": "public_cascade", "task": "8k_402"},
            direction="public_to_benchmark",
        )


def test_select_unique_row_matches_nan_key() -> None:
    frame = pd.DataFrame(
        {"model_id": ["public_cascade", "public_cascade"], "bridge_tier": [np.nan, "high"]}
    )

    selected = _select_unique_row(
        frame,
        keys={"model_id": "public_cascade", "bridge_tier": np.nan},
        direction="public_to_benchmark",
    )

    assert pd.isna(selected["bridge_tier"])


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"metric_status": "blocked_sparse"}, "not fitted"),
        (
            {
                "metric_status": "fit",
                "top_decile_lift": 1.0,
                "top_decile_lift_ci_low": np.nan,
                "top_decile_lift_ci_high": 2.0,
            },
            "lacks a finite interval",
        ),
        (
            {
                "metric_status": "fit",
                "top_decile_lift": 1.0,
                "top_decile_lift_ci_low": 3.0,
                "top_decile_lift_ci_high": 2.0,
            },
            "interval is reversed",
        ),
    ],
)
def test_primary_alignment_evidence_rejects_invalid_rows(
    row: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _primary_evidence(pd.Series(row), direction="public_to_benchmark")
