"""Construct-overlap validation between benchmark and public-cascade labels.

This module is intentionally a validation layer. It reuses existing study
artifacts; it does not rebuild the public lake or refit models.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from . import DATA_DIR, PROJECT_ROOT
from .linkage import DEFAULT_LINKAGE_OUT_DIR
from .ranking_metrics import matlab_round_positive
from .table_io import parquet_scan_sql, write_table


PUBLIC_LABELS = [
    "label_comment_thread_365",
    "label_amendment_365",
    "label_8k_402_365",
]
RES_AN_COLS = ["res_an0", "res_an1", "res_an2", "res_an3"]
BOOTSTRAP_REPS = 1000
BOOTSTRAP_SEED = 42
BOOTSTRAP_INTERVAL_METHOD = "row_level_percentile_bootstrap"
BOOTSTRAP_CHUNK_REPS = 100
BOOTSTRAP_INTERVAL_TOP_ROWS = 5
MIN_RANKING_POSITIVES = 10
BOOTSTRAP_POSITIVE_THRESHOLD = 30
BRIDGE_PROVENANCE_COLUMNS = ["source", "source_version", "match_method"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _scan_sql(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".parquet" or path.is_dir():
        return parquet_scan_sql(path)
    return f"read_csv_auto('{_sql_path(path)}', header=true, all_varchar=true)"


def _duckdb_connect() -> Any:
    import duckdb

    con = duckdb.connect(database=":memory:")
    con.execute("PRAGMA threads=4")
    con.execute("SET preserve_insertion_order=false")
    return con


def _norm_gvkey_expr(column: str) -> str:
    clean = f"regexp_replace(trim(CAST({column} AS VARCHAR)), '[^0-9]', '', 'g')"
    return f"""
    CASE
      WHEN {column} IS NULL THEN NULL
      WHEN TRY_CAST({clean} AS BIGINT) IS NULL THEN NULL
      ELSE CAST(TRY_CAST({clean} AS BIGINT) AS VARCHAR)
    END
    """


def _norm_cik_expr(column: str) -> str:
    clean = f"regexp_replace(trim(CAST({column} AS VARCHAR)), '[^0-9]', '', 'g')"
    return f"""
    CASE
      WHEN {column} IS NULL THEN NULL
      WHEN TRY_CAST({clean} AS BIGINT) IS NULL THEN NULL
      ELSE lpad(CAST(TRY_CAST({clean} AS BIGINT) AS VARCHAR), 10, '0')
    END
    """


def _existing_columns(con: Any, path: Path) -> set[str]:
    desc = con.execute(f"DESCRIBE SELECT * FROM {_scan_sql(path)}").fetchdf()
    return set(desc["column_name"].astype(str))


def _col_or_null(columns: set[str], name: str, cast_type: str, alias: str | None = None) -> str:
    out = alias or name
    if name in columns:
        return f'TRY_CAST("{name}" AS {cast_type}) AS "{out}"'
    return f'NULL::{cast_type} AS "{out}"'


def _label_column(columns: set[str]) -> str:
    for candidate in [
        "misstatement firm-year",
        "misstatement_firm_year",
        "misstatement",
        "fraud",
        "label",
    ]:
        if candidate in columns:
            return candidate
    raise ValueError(
        "detected-misstatement benchmark table is missing a misstatement label column"
    )


def _read_manifest(study_dir: Path) -> dict[str, Any]:
    path = study_dir / "study_run_manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(value: str | Path | None, *, default: Path) -> Path:
    if value is None or str(value) == "":
        return default
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def _write_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _bridge_evidence_from_crosswalk(crosswalk_path: Path) -> dict[str, Any]:
    """Infer bridge evidence tier from normalized crosswalk provenance columns."""
    if not crosswalk_path.exists():
        return {
            "bridge_source": "none",
            "validation_tier": "none",
            "bridge_provenance": {"source_values": [], "match_methods": []},
        }

    header = pd.read_csv(crosswalk_path, nrows=0)
    available = [col for col in BRIDGE_PROVENANCE_COLUMNS if col in header.columns]
    if not available:
        return {
            "bridge_source": "external_crosswalk_unknown_provenance",
            "validation_tier": "candidate_external",
            "bridge_provenance": {"source_values": [], "match_methods": []},
        }

    frame = pd.read_csv(crosswalk_path, usecols=available, dtype=str).fillna("")
    source_values = (
        sorted(value for value in frame["source"].str.strip().unique() if value)
        if "source" in frame
        else []
    )
    match_methods = (
        sorted(value for value in frame["match_method"].str.strip().unique() if value)
        if "match_method" in frame
        else []
    )
    evidence_text = frame.apply(lambda row: " ".join(str(value) for value in row), axis=1).str.lower()
    has_wrds = evidence_text.str.contains(r"\bwrds\b|wrds_", regex=True).any()
    has_raw = evidence_text.str.contains(
        r"raw_cik_gvkey|raw_primary|wrds_sec_analytics_cik_gvkey",
        regex=True,
    ).any()

    if has_wrds:
        all_wrds_sec_analytics = bool(source_values) and all(
            "wrds_sec_analytics_cik_gvkey" in value for value in source_values
        )
        if all_wrds_sec_analytics:
            bridge_source = "wrds_sec_analytics_cik_gvkey_link"
        else:
            bridge_source = source_values[0] if len(source_values) == 1 else "wrds_compustat_crosswalk"
        validation_tier = "wrds_validated"
    elif has_raw:
        bridge_source = "wrds_sec_analytics_cik_gvkey_link"
        validation_tier = "wrds_validated"
    else:
        bridge_source = source_values[0] if len(source_values) == 1 else "external_crosswalk"
        validation_tier = "candidate_external"

    return {
        "bridge_source": bridge_source,
        "validation_tier": validation_tier,
        "bridge_provenance": {
            "source_values": source_values,
            "match_methods": match_methods,
        },
    }


def _update_study_manifest_for_construct_overlap(
    *,
    study_dir: Path,
    out_dir: Path,
    manifest: dict[str, Any],
) -> None:
    path = study_dir / "study_run_manifest.json"
    if not path.exists():
        return
    study_manifest = _read_manifest(study_dir)
    manifest_inputs = manifest.get("inputs", {}) if isinstance(manifest.get("inputs"), dict) else {}
    if manifest_inputs:
        inputs = study_manifest.setdefault("inputs", {})
        for key in ["crosswalk", "issuer_origin_panel"]:
            if manifest_inputs.get(key):
                inputs[key] = manifest_inputs[key]
    components = study_manifest.setdefault("components", {})
    component: dict[str, Any] = {
        "run_status": manifest.get("run_status", "unknown"),
        "validation_tier": manifest.get("validation_tier", "none"),
        "out_dir": str(out_dir),
        "manifest_json": str(out_dir / "construct_overlap_manifest.json"),
    }
    summary_path = out_dir / "construct_overlap_summary.md"
    if summary_path.exists():
        component["summary_md"] = str(summary_path)
    blockers = manifest.get("blockers", [])
    if blockers:
        component["blockers"] = blockers
    components["construct_overlap"] = component
    _write_json(study_manifest, path)


def _top_precision(y: np.ndarray, score: np.ndarray, fraction: float) -> float:
    if len(y) == 0:
        return float("nan")
    k = min(max(matlab_round_positive(len(y) * fraction), 1), len(y))
    ranked = np.argsort(-np.nan_to_num(score, nan=-np.inf), kind="mergesort")[:k]
    return float(np.mean(y[ranked])) if k else float("nan")


def _top_decile_lift(y: np.ndarray, score: np.ndarray) -> float:
    prevalence = float(np.mean(y)) if len(y) else float("nan")
    precision = _top_precision(y, score, 0.10)
    if not np.isfinite(prevalence) or prevalence <= 0:
        return float("nan")
    return float(precision / prevalence)


def _bootstrap_lift_ci(
    y_true: np.ndarray,
    score: np.ndarray,
    *,
    reps: int = BOOTSTRAP_REPS,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """Row-level percentile bootstrap for top-decile lift.

    The implementation resamples rows with replacement by drawing multinomial
    row counts. Rows are sorted by score once; for each bootstrap draw, the
    top-decile set is recomputed from the resampled row counts.
    """
    y = np.asarray(y_true, dtype=int)
    s = np.asarray(score, dtype=float)
    if int(y.sum()) < BOOTSTRAP_POSITIVE_THRESHOLD or len(y) == 0:
        return (float("nan"), float("nan"))
    order = np.argsort(-np.nan_to_num(s, nan=-np.inf), kind="mergesort")
    y_sorted = y[order].astype(np.int64)
    sample_size = len(y_sorted)
    top_k = min(max(matlab_round_positive(sample_size * 0.10), 1), sample_size)
    row_prob = np.full(sample_size, 1.0 / sample_size)
    rng = np.random.default_rng(seed)
    lift_values: list[float] = []
    for start in range(0, int(reps), BOOTSTRAP_CHUNK_REPS):
        batch_reps = min(BOOTSTRAP_CHUNK_REPS, int(reps) - start)
        counts = rng.multinomial(sample_size, row_prob, size=batch_reps).astype(np.int64)
        cumulative = np.cumsum(counts, axis=1)
        top_counts = counts * (cumulative <= top_k)
        boundary = np.argmax(cumulative >= top_k, axis=1)
        previous = np.where(boundary > 0, cumulative[np.arange(batch_reps), boundary - 1], 0)
        boundary_take = np.maximum(top_k - previous, 0)
        top_counts[np.arange(batch_reps), boundary] = boundary_take

        top_positive = top_counts @ y_sorted
        total_positive = counts @ y_sorted
        with np.errstate(divide="ignore", invalid="ignore"):
            batch_lift = (top_positive / top_k) / (total_positive / sample_size)
        finite = batch_lift[np.isfinite(batch_lift)]
        lift_values.extend(float(value) for value in finite)
    if not lift_values:
        return (float("nan"), float("nan"))
    return (
        float(np.quantile(lift_values, 0.025)),
        float(np.quantile(lift_values, 0.975)),
    )


def _ranking_metrics(
    y_true: Iterable[Any],
    score: Iterable[Any],
    *,
    bootstrap_ci: bool = True,
) -> dict[str, float]:
    y = pd.to_numeric(pd.Series(list(y_true)), errors="coerce").fillna(0).astype(int).to_numpy()
    s = pd.to_numeric(pd.Series(list(score)), errors="coerce").fillna(-np.inf).to_numpy(float)
    positives = int(y.sum())
    negatives = int(len(y) - positives)
    if positives < MIN_RANKING_POSITIVES:
        return {
            "n_pos": positives,
            "n_neg": negatives,
            "roc_auc": float("nan"),
            "pr_auc": float("nan"),
            "top_1pct_precision": float("nan"),
            "top_5pct_precision": float("nan"),
            "top_10pct_precision": float("nan"),
            "top_decile_lift": float("nan"),
            "top_decile_lift_ci_low": float("nan"),
            "top_decile_lift_ci_high": float("nan"),
            "status": "blocked_sparse",
        }
    roc_auc = float(roc_auc_score(y, s)) if len(np.unique(y)) > 1 else float("nan")
    pr_auc = float(average_precision_score(y, s)) if len(np.unique(y)) > 1 else float("nan")
    if bootstrap_ci:
        ci_low, ci_high = _bootstrap_lift_ci(y, s)
    else:
        ci_low, ci_high = (float("nan"), float("nan"))
    return {
        "n_pos": positives,
        "n_neg": negatives,
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "top_1pct_precision": _top_precision(y, s, 0.01),
        "top_5pct_precision": _top_precision(y, s, 0.05),
        "top_10pct_precision": _top_precision(y, s, 0.10),
        "top_decile_lift": _top_decile_lift(y, s),
        "top_decile_lift_ci_low": ci_low,
        "top_decile_lift_ci_high": ci_high,
        "status": "fit",
    }


def _setup_base_tables(
    con: Any,
    *,
    master_panel_path: Path,
    crosswalk_path: Path,
    issuer_origin_path: Path,
) -> None:
    raw_cols = _existing_columns(con, master_panel_path)
    target_col = _label_column(raw_cols)
    res_cols = ",\n".join(_col_or_null(raw_cols, col, "INTEGER") for col in RES_AN_COLS)
    raw_select_extra = f",\n{res_cols}" if res_cols else ""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE raw_norm AS
        SELECT
          row_number() OVER () - 1 AS raw_row_id,
          {_norm_gvkey_expr('"gvkey"')} AS gvkey,
          TRY_CAST("data_year" AS INTEGER) AS data_year,
          COALESCE(TRY_CAST("{target_col}" AS INTEGER), 0) AS benchmark_label,
          {_col_or_null(raw_cols, "detection_year_proxy", "INTEGER")}
          {raw_select_extra}
        FROM {_scan_sql(master_panel_path)}
        WHERE {_norm_gvkey_expr('"gvkey"')} IS NOT NULL
          AND TRY_CAST("data_year" AS INTEGER) IS NOT NULL
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE crosswalk_norm AS
        SELECT DISTINCT
          {_norm_gvkey_expr('"gvkey"')} AS gvkey,
          TRY_CAST("data_year" AS INTEGER) AS data_year,
          {_norm_cik_expr('"issuer_cik"')} AS issuer_cik,
          COALESCE(source, 'unknown') AS bridge_source
        FROM {_scan_sql(crosswalk_path)}
        WHERE {_norm_gvkey_expr('"gvkey"')} IS NOT NULL
          AND TRY_CAST("data_year" AS INTEGER) IS NOT NULL
          AND {_norm_cik_expr('"issuer_cik"')} IS NOT NULL
        """
    )
    label_exprs = ",\n".join(
        f'COALESCE(MAX(TRY_CAST("{label}" AS INTEGER)), 0) AS "{label}"'
        for label in PUBLIC_LABELS
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE public_annual AS
        SELECT
          {_norm_cik_expr('"issuer_cik"')} AS issuer_cik,
          TRY_CAST("fiscal_year" AS INTEGER) AS data_year,
          MIN(TRY_CAST(origin_date AS TIMESTAMP)) AS origin_date_min,
          MAX(TRY_CAST(origin_date AS TIMESTAMP)) AS origin_date_max,
          COUNT(*) AS annual_public_row_count,
          {label_exprs}
        FROM {_scan_sql(issuer_origin_path)}
        WHERE {_norm_cik_expr('"issuer_cik"')} IS NOT NULL
          AND TRY_CAST("fiscal_year" AS INTEGER) IS NOT NULL
        GROUP BY 1, 2
        """
    )
    bridge_label_select = ",\n          ".join(f"p.{label}" for label in PUBLIC_LABELS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE bridge_join AS
        SELECT
          r.*,
          x.issuer_cik,
          x.bridge_source,
          p.origin_date_min,
          p.origin_date_max,
          COALESCE(p.annual_public_row_count, 0) AS annual_public_row_count,
          {bridge_label_select}
        FROM raw_norm r
        LEFT JOIN crosswalk_norm x
          ON r.gvkey = x.gvkey AND r.data_year = x.data_year
        LEFT JOIN public_annual p
          ON x.issuer_cik = p.issuer_cik AND x.data_year = p.data_year
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE bridge_tiers AS
        SELECT
          raw_row_id,
          ANY_VALUE(gvkey) AS gvkey,
          ANY_VALUE(data_year) AS data_year,
          COUNT(DISTINCT issuer_cik) FILTER (WHERE issuer_cik IS NOT NULL) AS issuer_cik_count,
          COALESCE(SUM(annual_public_row_count), 0) AS public_row_count,
          CASE
            WHEN COUNT(DISTINCT issuer_cik) FILTER (WHERE issuer_cik IS NOT NULL) = 0
              THEN 'dropped'
            WHEN COALESCE(SUM(annual_public_row_count), 0) = 0
              THEN 'dropped'
            WHEN COUNT(DISTINCT issuer_cik) FILTER (WHERE issuer_cik IS NOT NULL) = 1
             AND COALESCE(SUM(annual_public_row_count), 0) = 1
              THEN 'high_confidence'
            ELSE 'ambiguous'
          END AS bridge_tier,
          CASE
            WHEN COUNT(DISTINCT issuer_cik) FILTER (WHERE issuer_cik IS NOT NULL) = 0
              THEN 'no_bridge_match'
            WHEN COALESCE(SUM(annual_public_row_count), 0) = 0
              THEN 'no_public_match'
            WHEN COUNT(DISTINCT issuer_cik) FILTER (WHERE issuer_cik IS NOT NULL) > 1
              THEN 'multiple_ciks'
            WHEN COALESCE(SUM(annual_public_row_count), 0) > 1
              THEN 'multiple_public_rows'
            ELSE 'one_to_one'
          END AS reason_code
        FROM bridge_join
        GROUP BY raw_row_id
        """
    )
    max_labels = ",\n".join(
        f'COALESCE(MAX("{label}"), 0)::INTEGER AS "{label}"' for label in PUBLIC_LABELS
    )
    res_cols_panel = ",\n".join(f"ANY_VALUE({col}) AS {col}" for col in RES_AN_COLS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE overlap_panel AS
        SELECT
          j.raw_row_id,
          ANY_VALUE(j.gvkey) AS gvkey,
          ANY_VALUE(j.data_year) AS data_year,
          ANY_VALUE(j.benchmark_label) AS benchmark_label,
          t.bridge_tier,
          t.issuer_cik_count,
          t.public_row_count,
          STRING_AGG(DISTINCT j.issuer_cik, ';' ORDER BY j.issuer_cik)
            FILTER (WHERE j.issuer_cik IS NOT NULL) AS issuer_ciks,
          MIN(j.origin_date_min) AS origin_date_min,
          MAX(j.origin_date_max) AS origin_date_max,
          {max_labels},
          ANY_VALUE(j.detection_year_proxy) AS detection_year_proxy,
          {res_cols_panel}
        FROM bridge_join j
        JOIN bridge_tiers t USING (raw_row_id)
        GROUP BY j.raw_row_id, t.bridge_tier, t.issuer_cik_count, t.public_row_count
        """
    )


def _write_overlap_core(con: Any, out_dir: Path) -> pd.DataFrame:
    tiers = con.execute(
        """
        SELECT gvkey, data_year, issuer_cik_count, public_row_count, bridge_tier, reason_code
        FROM bridge_tiers
        ORDER BY data_year, gvkey
        """
    ).fetchdf()
    _write_csv(tiers, out_dir / "bridge_confidence_tiers.csv")

    panel = con.execute("SELECT * FROM overlap_panel ORDER BY data_year, gvkey").fetchdf()
    write_table(panel, out_dir / "overlap_panel.parquet")

    flow = (
        panel.groupby("bridge_tier", dropna=False)
        .agg(rows=("raw_row_id", "nunique"), benchmark_positives=("benchmark_label", "sum"))
        .reset_index()
    )
    extra = pd.DataFrame(
        [
            {"bridge_tier": "full_raw", "rows": len(panel), "benchmark_positives": panel["benchmark_label"].sum()},
        ]
    )
    _write_csv(pd.concat([extra, flow], ignore_index=True), out_dir / "overlap_sample_flow.csv")

    for label in PUBLIC_LABELS:
        pre = con.execute(
            f"""
            SELECT bridge_tier, AVG(COALESCE("{label}", 0)) AS pre_agg_pos_rate
            FROM bridge_join j JOIN bridge_tiers t USING (raw_row_id)
            WHERE t.bridge_tier != 'dropped'
            GROUP BY bridge_tier
            """
        ).fetchdf()
        post = (
            panel.loc[panel["bridge_tier"].ne("dropped")]
            .groupby("bridge_tier")[label]
            .mean()
            .rename("post_agg_pos_rate")
            .reset_index()
        )
        rates = pre.merge(post, on="bridge_tier", how="outer")
        rates["public_label"] = label
        rates["pos_rate_delta"] = rates["post_agg_pos_rate"] - rates["pre_agg_pos_rate"]
        rates["aggregation_sensitive"] = rates["pos_rate_delta"].abs().gt(0.005)
        rates["aggregation_rule"] = "label_max"
        if "rows" not in rates.columns:
            rates["rows"] = rates["bridge_tier"].map(panel["bridge_tier"].value_counts()).fillna(0)
        append_cols = [
            "public_label",
            "bridge_tier",
            "aggregation_rule",
            "rows",
            "pre_agg_pos_rate",
            "post_agg_pos_rate",
            "pos_rate_delta",
            "aggregation_sensitive",
        ]
        if label == PUBLIC_LABELS[0]:
            aggregation = rates[append_cols]
        else:
            aggregation = pd.concat([aggregation, rates[append_cols]], ignore_index=True)
    _write_csv(aggregation, out_dir / "aggregation_sensitivity.csv")
    _write_csv(tiers, out_dir / "bridge_multiplicity_in_overlap.csv")
    return panel


def _label_contingency(panel: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for bridge_tier in ["high_confidence", "ambiguous", "all_matched"]:
        sample = panel if bridge_tier == "all_matched" else panel.loc[panel["bridge_tier"].eq(bridge_tier)]
        sample = sample.loc[sample["bridge_tier"].ne("dropped")]
        for label in PUBLIC_LABELS:
            benchmark = sample["benchmark_label"].eq(1)
            public = sample[label].eq(1)
            n = len(sample)
            public_rate_benchmark_pos = float(public[benchmark].mean()) if benchmark.any() else np.nan
            public_rate_benchmark_neg = float(public[~benchmark].mean()) if (~benchmark).any() else np.nan
            benchmark_rate_public_pos = float(benchmark[public].mean()) if public.any() else np.nan
            benchmark_rate_public_neg = float(benchmark[~public].mean()) if (~public).any() else np.nan
            rows.append(
                {
                    "public_label": label,
                    "bridge_tier": bridge_tier,
                    "n": int(n),
                    "benchmark_positive_rows": int(benchmark.sum()),
                    "public_positive_rows": int(public.sum()),
                    "both_positive_rows": int((benchmark & public).sum()),
                    "benchmark_prevalence": float(benchmark.mean()) if n else np.nan,
                    "public_prevalence": float(public.mean()) if n else np.nan,
                    "public_rate_given_benchmark_pos": public_rate_benchmark_pos,
                    "public_rate_given_benchmark_neg": public_rate_benchmark_neg,
                    "lift_public_given_benchmark": (
                        public_rate_benchmark_pos / float(public.mean())
                        if n and float(public.mean()) > 0
                        else np.nan
                    ),
                    "benchmark_rate_given_public_pos": benchmark_rate_public_pos,
                    "benchmark_rate_given_public_neg": benchmark_rate_public_neg,
                    "lift_benchmark_given_public": (
                        benchmark_rate_public_pos / float(benchmark.mean())
                        if n and float(benchmark.mean()) > 0
                        else np.nan
                    ),
                }
            )
    out = pd.DataFrame(rows)
    _write_csv(out, out_dir / "label_contingency_lift.csv")
    return out


def _cooccurrence(panel: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    sample = panel.loc[panel["bridge_tier"].eq("high_confidence") & panel["benchmark_label"].eq(1)].copy()
    if sample.empty:
        out = pd.DataFrame(
            columns=[
                "label_pattern",
                *PUBLIC_LABELS,
                "n_benchmark_positives",
                "pct_of_benchmark_positives",
                "display_count",
            ]
        )
        _write_csv(out, out_dir / "benchmark_positive_public_label_cooccurrence.csv")
        return out
    for label in PUBLIC_LABELS:
        sample[label] = sample[label].fillna(0).astype(int)
    grouped = sample.groupby(PUBLIC_LABELS, as_index=False).size().rename(columns={"size": "n_benchmark_positives"})
    total = int(len(sample))
    grouped["pct_of_benchmark_positives"] = grouped["n_benchmark_positives"] / total
    grouped["display_count"] = grouped["n_benchmark_positives"].map(lambda value: "<5" if int(value) < 5 else str(int(value)))

    def _pattern(row: pd.Series) -> str:
        active = [label.replace("label_", "") for label in PUBLIC_LABELS if int(row[label]) == 1]
        return "+".join(active) if active else "none"

    grouped.insert(0, "label_pattern", grouped.apply(_pattern, axis=1))
    _write_csv(grouped, out_dir / "benchmark_positive_public_label_cooccurrence.csv")
    return grouped


def _score_metric_rows(
    frame: pd.DataFrame,
    *,
    group_cols: Sequence[str],
    target_col: str,
    score_col: str,
    count_prefix: str,
    bridge_source: str,
    bootstrap_top_rows: int = BOOTSTRAP_INTERVAL_TOP_ROWS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return rows
    for keys, group in frame.groupby(list(group_cols), dropna=False):
        key_values = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(group_cols, key_values))
        metrics = _ranking_metrics(group[target_col], group[score_col], bootstrap_ci=False)
        row.update(
            {
                f"n_{count_prefix}_positives_in_overlap": metrics["n_pos"],
                f"n_{count_prefix}_negatives_in_overlap": metrics["n_neg"],
                "roc_auc": metrics["roc_auc"],
                "pr_auc": metrics["pr_auc"],
                "top_1pct_precision": metrics["top_1pct_precision"],
                "top_5pct_precision": metrics["top_5pct_precision"],
                "top_10pct_precision": metrics["top_10pct_precision"],
                "top_decile_lift": metrics["top_decile_lift"],
                "top_decile_lift_ci_low": metrics["top_decile_lift_ci_low"],
                "top_decile_lift_ci_high": metrics["top_decile_lift_ci_high"],
                "metric_status": metrics["status"],
                "bridge_source": bridge_source,
            }
        )
        rows.append(row)
    _add_bootstrap_intervals_to_top_rows(
        rows,
        frame=frame,
        group_cols=group_cols,
        target_col=target_col,
        score_col=score_col,
        top_n=bootstrap_top_rows,
    )
    return rows


def _add_bootstrap_intervals_to_top_rows(
    rows: list[dict[str, Any]],
    *,
    frame: pd.DataFrame,
    group_cols: Sequence[str],
    target_col: str,
    score_col: str,
    top_n: int,
) -> None:
    if not rows or top_n <= 0:
        return
    ranked = sorted(
        (
            (idx, row)
            for idx, row in enumerate(rows)
            if row.get("metric_status") == "fit"
            and np.isfinite(row.get("top_decile_lift", np.nan))
        ),
        key=lambda item: float(item[1]["top_decile_lift"]),
        reverse=True,
    )[:top_n]
    for idx, row in ranked:
        mask = pd.Series(True, index=frame.index)
        for col in group_cols:
            value = row.get(col)
            if pd.isna(value):
                mask &= frame[col].isna()
            else:
                mask &= frame[col].eq(value)
        sample = frame.loc[mask]
        ci_low, ci_high = _bootstrap_lift_ci(sample[target_col].to_numpy(), sample[score_col].to_numpy())
        rows[idx]["top_decile_lift_ci_low"] = ci_low
        rows[idx]["top_decile_lift_ci_high"] = ci_high


def _public_score_frames(con: Any, public_predictions_path: Path) -> dict[str, pd.DataFrame]:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE public_prediction_norm AS
        SELECT
          {_norm_cik_expr('"issuer_cik"')} AS issuer_cik,
          TRY_CAST("fiscal_year" AS INTEGER) AS data_year,
          feature_set,
          train_window,
          task,
          TRY_CAST(probability AS DOUBLE) AS probability
        FROM {_scan_sql(public_predictions_path)}
        WHERE {_norm_cik_expr('"issuer_cik"')} IS NOT NULL
          AND TRY_CAST("fiscal_year" AS INTEGER) IS NOT NULL
          AND TRY_CAST(probability AS DOUBLE) IS NOT NULL
        """
    )
    base_sql = """
        SELECT
          r.raw_row_id,
          r.benchmark_label,
          t.bridge_tier,
          p.feature_set,
          p.train_window,
          p.task,
          p.probability
        FROM raw_norm r
        JOIN crosswalk_norm x ON r.gvkey = x.gvkey AND r.data_year = x.data_year
        JOIN public_prediction_norm p ON x.issuer_cik = p.issuer_cik AND r.data_year = p.data_year
        JOIN bridge_tiers t ON r.raw_row_id = t.raw_row_id
        WHERE t.bridge_tier != 'dropped'
    """
    con.execute(f"CREATE OR REPLACE TEMP TABLE public_score_long AS {base_sql}")
    outputs: dict[str, pd.DataFrame] = {}
    for aggregation, sql_agg in {
        "mean": "AVG(probability)",
        "median": "MEDIAN(probability)",
        "max": "MAX(probability)",
    }.items():
        outputs[aggregation] = con.execute(
            f"""
            SELECT
              raw_row_id,
              benchmark_label,
              bridge_tier,
              feature_set,
              train_window,
              task,
              {sql_agg} AS score
            FROM public_score_long
            GROUP BY raw_row_id, benchmark_label, bridge_tier, feature_set, train_window, task
            """
        ).fetchdf()
        outputs[aggregation]["score_aggregation"] = aggregation
    high = outputs["mean"].loc[outputs["mean"]["bridge_tier"].eq("high_confidence")].copy()
    high["score_aggregation"] = "ambiguous_excluded"
    outputs["ambiguous_excluded"] = high
    return outputs


def _public_ranking(
    con: Any,
    public_predictions_path: Path,
    out_dir: Path,
    bridge_source: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = _public_score_frames(con, public_predictions_path)
    main = frames["mean"].loc[frames["mean"]["bridge_tier"].eq("high_confidence")].copy()
    main["model_id"] = "public_cascade"
    main["label_mode"] = "benchmark_naive"
    main_rows = _score_metric_rows(
        main,
        group_cols=[
            "model_id",
            "task",
            "feature_set",
            "train_window",
            "label_mode",
            "score_aggregation",
            "bridge_tier",
        ],
        target_col="benchmark_label",
        score_col="score",
        count_prefix="benchmark",
        bridge_source=bridge_source,
    )
    main_out = pd.DataFrame(main_rows)
    _write_csv(main_out, out_dir / "public_score_benchmark_ranking.csv")

    sens = pd.concat(frames.values(), ignore_index=True)
    sens["model_id"] = "public_cascade"
    sens["label_mode"] = "benchmark_naive"
    sens_rows = _score_metric_rows(
        sens,
        group_cols=[
            "model_id",
            "task",
            "feature_set",
            "train_window",
            "label_mode",
            "score_aggregation",
            "bridge_tier",
        ],
        target_col="benchmark_label",
        score_col="score",
        count_prefix="benchmark",
        bridge_source=bridge_source,
    )
    sens_out = pd.DataFrame(sens_rows)
    _write_csv(sens_out, out_dir / "public_score_benchmark_ranking_sensitivity.csv")
    top = main_out[
        [
            "model_id",
            "task",
            "feature_set",
            "train_window",
            "label_mode",
            "score_aggregation",
            "bridge_tier",
            "top_decile_lift",
            "top_decile_lift_ci_low",
            "top_decile_lift_ci_high",
            "bridge_source",
        ]
    ].copy()
    _write_csv(top, out_dir / "top_decile_lift.csv")
    return main_out, sens_out


def _reciprocal_alignment(
    con: Any,
    *,
    benchmark_predictions_path: Path,
    peer_predictions_path: Path | None,
    out_dir: Path,
    bridge_source: str,
) -> pd.DataFrame:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE benchmark_score_norm AS
        SELECT
          {_norm_gvkey_expr('"gvkey"')} AS gvkey,
          TRY_CAST("data_year" AS INTEGER) AS data_year,
          'benchmark_xgb' AS model_id,
          'benchmark_all' AS feature_set,
          "window" AS train_window,
          label_mode,
          TRY_CAST(pred_prob AS DOUBLE) AS score
        FROM {_scan_sql(benchmark_predictions_path)}
        WHERE {_norm_gvkey_expr('"gvkey"')} IS NOT NULL
          AND TRY_CAST("data_year" AS INTEGER) IS NOT NULL
          AND TRY_CAST(pred_prob AS DOUBLE) IS NOT NULL
        """
    )
    score_sources = ["SELECT * FROM benchmark_score_norm"]
    if peer_predictions_path is not None and peer_predictions_path.exists():
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE peer_score_norm AS
            SELECT
              {_norm_gvkey_expr('"gvkey"')} AS gvkey,
              TRY_CAST("data_year" AS INTEGER) AS data_year,
              peer_model_id AS model_id,
              'peer_compatible' AS feature_set,
              train_window,
              label_mode,
              TRY_CAST(predicted_prob AS DOUBLE) AS score
            FROM {_scan_sql(peer_predictions_path)}
            WHERE {_norm_gvkey_expr('"gvkey"')} IS NOT NULL
              AND TRY_CAST("data_year" AS INTEGER) IS NOT NULL
              AND TRY_CAST(predicted_prob AS DOUBLE) IS NOT NULL
            """
        )
        score_sources.append("SELECT * FROM peer_score_norm")
    union_sql = " UNION ALL ".join(score_sources)
    label_select = ", ".join(PUBLIC_LABELS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE reciprocal_base AS
        SELECT
          s.model_id,
          s.feature_set,
          s.train_window,
          s.label_mode,
          'benchmark_score' AS score_aggregation,
          p.bridge_tier,
          s.score,
          {label_select}
        FROM ({union_sql}) s
        JOIN overlap_panel p ON s.gvkey = p.gvkey AND s.data_year = p.data_year
        WHERE p.bridge_tier = 'high_confidence'
        """
    )
    frames = []
    for label in PUBLIC_LABELS:
        df = con.execute(
            f"""
            SELECT
              model_id,
              '{label}' AS target_public_label,
              feature_set,
              train_window,
              label_mode,
              score_aggregation,
              bridge_tier,
              "{label}" AS target_label,
              score
            FROM reciprocal_base
            """
        ).fetchdf()
        frames.append(df)
    base = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    rows = _score_metric_rows(
        base,
        group_cols=[
            "model_id",
            "target_public_label",
            "feature_set",
            "train_window",
            "label_mode",
            "score_aggregation",
            "bridge_tier",
        ],
        target_col="target_label",
        score_col="score",
        count_prefix="public",
        bridge_source=bridge_source,
    )
    out = pd.DataFrame(rows)
    _write_csv(out, out_dir / "reciprocal_alignment.csv")
    return out


def _event_time(con: Any, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    rel_frames: dict[int, pd.DataFrame] = {}
    for rel in range(-3, 4):
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE event_rel AS
            SELECT
              p.raw_row_id,
              p.gvkey,
              p.data_year,
              p.benchmark_label,
              p.bridge_tier,
              p.issuer_ciks,
              p.data_year + {rel} AS public_year,
              a.label_comment_thread_365,
              a.label_amendment_365,
              a.label_8k_402_365,
              a.origin_date_min
            FROM overlap_panel p
            LEFT JOIN public_annual a
              ON p.issuer_ciks = a.issuer_cik AND p.data_year + {rel} = a.data_year
            WHERE p.bridge_tier = 'high_confidence'
            """
        )
        rel_df = con.execute("SELECT * FROM event_rel").fetchdf()
        rel_frames[rel] = rel_df
        has_public = rel_df["origin_date_min"].notna()
        coverage_rows.append(
            {
                "relative_year": rel,
                "rows": int(len(rel_df)),
                "covered_rows": int(has_public.sum()),
                "coverage_rate": float(has_public.mean()) if len(rel_df) else np.nan,
            }
        )

    covered_sets = [
        set(frame.loc[frame["origin_date_min"].notna(), "raw_row_id"].astype(int))
        for frame in rel_frames.values()
    ]
    balanced_ids = set.intersection(*covered_sets) if covered_sets else set()
    for item in coverage_rows:
        item["balanced_rows"] = int(len(balanced_ids))
        item["rows_dropped_for_balanced_window"] = int(item["rows"] - len(balanced_ids))

    for rel, rel_df in rel_frames.items():
        balanced_mask = rel_df["raw_row_id"].astype(int).isin(balanced_ids)
        balanced = rel_df.loc[balanced_mask].copy()
        for label in PUBLIC_LABELS:
            benchmark_pos = balanced["benchmark_label"].eq(1)
            rows.append(
                {
                    "relative_year": rel,
                    "public_label": label,
                    "n_benchmark_positive": int(benchmark_pos.sum()),
                    "n_benchmark_negative": int((~benchmark_pos).sum()),
                    "covered_rows": int(len(balanced)),
                    "public_label_rate_benchmark_positive": (
                        float(balanced.loc[benchmark_pos, label].mean()) if benchmark_pos.any() else np.nan
                    ),
                    "public_label_rate_benchmark_negative": (
                        float(balanced.loc[~benchmark_pos, label].mean()) if (~benchmark_pos).any() else np.nan
                    ),
                    "raw_difference": (
                        float(balanced.loc[benchmark_pos, label].mean())
                        - float(balanced.loc[~benchmark_pos, label].mean())
                        if benchmark_pos.any() and (~benchmark_pos).any()
                        else np.nan
                    ),
                    "balanced_window": True,
                }
            )
    concentration = pd.DataFrame(rows)
    coverage = pd.DataFrame(coverage_rows)
    _write_csv(concentration, out_dir / "event_time_concentration.csv")
    _write_csv(coverage, out_dir / "event_time_coverage.csv")
    return concentration, coverage


def _res_an_proxy_coverage(panel: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows = []
    any_res = panel[RES_AN_COLS].fillna(0).astype(int).sum(axis=1).gt(0)
    for scope, mask in {
        "all_rows": pd.Series(True, index=panel.index),
        "benchmark_positive_rows": panel["benchmark_label"].eq(1),
    }.items():
        sample = panel.loc[mask]
        sample_any = any_res.loc[mask]
        rows.append(
            {
                "scope": scope,
                "rows": int(len(sample)),
                "with_any_res_an": int(sample_any.sum()),
                "without_any_res_an": int((~sample_any).sum()),
                "proxy_coverage_rate": float(sample_any.mean()) if len(sample_any) else np.nan,
            }
        )
    out = pd.DataFrame(rows)
    _write_csv(out, out_dir / "res_an_proxy_coverage.csv")
    return out


def _opacity_refresh(study_dir: Path, out_dir: Path) -> dict[str, Any]:
    opacity_dir = out_dir
    opacity_dir.mkdir(parents=True, exist_ok=True)
    dml_path = study_dir / "public_cascade" / "public_opacity_dml.csv"
    meta_path = study_dir / "public_cascade" / "public_opacity_dml_meta.json"
    blockers: list[dict[str, str]] = []
    if not dml_path.exists() or not meta_path.exists():
        blockers.append(
            {
                "code": "blocked_missing_opacity_artifacts",
                "detail": "public_opacity_dml.csv or public_opacity_dml_meta.json is missing",
            }
        )
        _write_json({"blockers": blockers}, opacity_dir / "opacity_validation_blockers.json")
        _write_csv(pd.DataFrame(), opacity_dir / "opacity_diagnostics_summary.csv")
        (opacity_dir / "opacity_validation_refresh_summary.md").write_text(
            "# Opacity Validation Refresh\n\nMissing public opacity DML artifacts.\n",
            encoding="utf-8",
        )
        return {"run_status": "blocked_missing_artifacts", "blockers": blockers}
    dml = pd.read_csv(dml_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    dml["n_opacity_components_meta"] = int(meta.get("n_opacity_components", 0))
    dml["n_controls_meta"] = int(meta.get("n_controls", 0))
    dml["interpretation"] = "adjusted_association_not_causal"
    _write_csv(dml, opacity_dir / "opacity_diagnostics_summary.csv")
    _write_json({"blockers": []}, opacity_dir / "opacity_validation_blockers.json")
    lines = [
        "# Opacity Validation Refresh",
        "",
        "This summary reuses existing public-label DML artifacts. It does not refit DML.",
        "",
        "| Outcome | Coef. | p-value | Interpretation |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in dml.itertuples(index=False):
        lines.append(
            f"| `{row.outcome}` | {float(row.coef):.4f} | {float(row.p_value):.4f} | adjusted association, not causal |"
        )
    (opacity_dir / "opacity_validation_refresh_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return {"run_status": "complete", "blockers": []}


def _write_summary(
    *,
    out_dir: Path,
    manifest: dict[str, Any],
    label_lift: pd.DataFrame,
    public_ranking: pd.DataFrame,
    reciprocal: pd.DataFrame,
    cooccurrence: pd.DataFrame,
    aggregation: pd.DataFrame,
) -> None:
    bridge_source = manifest["bridge_source"]
    validation_tier = manifest["validation_tier"]
    matched_sample_label = (
        "WRDS-validated bridge sample"
        if validation_tier == "wrds_validated"
        else "matched candidate-bridge sample"
    )
    best = (
        public_ranking.sort_values("top_decile_lift", ascending=False).head(1)
        if not public_ranking.empty
        else pd.DataFrame()
    )
    aggregation_sensitive = bool(
        not aggregation.empty and aggregation["aggregation_sensitive"].fillna(False).any()
    )
    lines = [
        "# Construct-Overlap Summary",
        "",
        "## Reader Guide",
        "",
        "| Question | Artifact |",
        "| --- | --- |",
        "| How many benchmark rows enter the overlap? | `overlap_sample_flow.csv` |",
        "| Does bridge aggregation affect public-label rates? | `aggregation_sensitivity.csv` |",
        "| Do public labels overlap detected-misstatement benchmark labels? | "
        "`label_contingency_lift.csv` |",
        "| Do public scores rank benchmark positives? | `public_score_benchmark_ranking.csv` |",
        "| Do benchmark scores rank public labels? | `reciprocal_alignment.csv` |",
        "| Which public labels co-occur among benchmark positives? | "
        "`benchmark_positive_public_label_cooccurrence.csv` |",
        "| When do public labels concentrate around benchmark years? | `event_time_concentration.csv` |",
        "",
        "## Evidence Tier",
        "",
        f"- Run status: `{manifest['run_status']}`",
        f"- Validation tier: `{validation_tier}`",
        f"- Bridge source: `{bridge_source}`",
        f"- Aggregation-sensitive public-label rates: `{aggregation_sensitive}`",
        "",
        "## Claim Template",
        "",
    ]
    if best.empty:
        lines.append(
            "The matched candidate-bridge sample is available, but ranking metrics did not meet reporting thresholds."
        )
    else:
        row = best.iloc[0]
        lines.append(
            f"In the {matched_sample_label}, detected-misstatement benchmark "
            "firm-years are "
            f"enriched in the top decile of public review-and-correction risk scores "
            f"(best top-decile lift = {row['top_decile_lift']:.2f}), but most high-risk "
            "public-cascade firm-years do not correspond to detected-misstatement "
            "benchmark positives. Among benchmark-positive firm-years, a measurable "
            "share exhibits at "
            "least one public review-and-correction label within the event-time window. "
            "This pattern is consistent with related but non-identical constructs: the "
            "public cascade captures a broader set of review-and-correction events "
            "than detected-misstatement benchmark positives."
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Public-label event-time rows are descriptive rates only; no significance tests are reported.",
        ]
    )
    if validation_tier == "wrds_validated":
        lines.append("- Bridge tier is inferred from WRDS/Compustat provenance in the normalized crosswalk.")
    else:
        lines.append("- Bridge tier is inferred from crosswalk provenance; non-WRDS tiers remain candidate evidence.")
    (out_dir / "construct_overlap_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _missing_required(paths: dict[str, Path]) -> list[dict[str, str]]:
    return [
        {"code": "blocked_missing_artifacts", "path": str(path)}
        for path in paths.values()
        if not path.exists()
    ]


def run_construct_overlap(
    *,
    study_dir: Path,
    out_dir: Path | None = None,
    opacity_out_dir: Path | None = None,
    crosswalk_path: Path | None = None,
    issuer_origin_panel_path: Path | None = None,
) -> dict[str, Any]:
    study_dir = Path(study_dir)
    out_dir = Path(out_dir or study_dir / "construct_overlap")
    opacity_out_dir = Path(opacity_out_dir or study_dir / "opacity_validation_refresh")
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_in = _read_manifest(study_dir)
    inputs = manifest_in.get("inputs", {}) if isinstance(manifest_in, dict) else {}
    crosswalk = _resolve_path(
        crosswalk_path or inputs.get("crosswalk"),
        default=DEFAULT_LINKAGE_OUT_DIR / "gvkey_cik_year.csv",
    )
    issuer_origin = _resolve_path(
        issuer_origin_panel_path or inputs.get("issuer_origin_panel"),
        default=DATA_DIR / "public_lake" / "gold" / "issuer_origin_panel.parquet",
    )
    required = {
        "master_panel": study_dir / "benchmark" / "master_panel.parquet",
        "benchmark_predictions": study_dir / "benchmark" / "rolling_predictions.parquet",
        "public_predictions": study_dir / "public_cascade" / "public_cascade_predictions.parquet",
        "crosswalk": crosswalk,
        "issuer_origin_panel": issuer_origin,
    }
    blockers = _missing_required(required)
    if not crosswalk.exists():
        blockers.append({"code": "blocked_missing_crosswalk", "path": str(crosswalk)})
    if blockers:
        manifest = {
            "created_at": _utc_now(),
            "run_status": "blocked_missing_crosswalk"
            if any(item["code"] == "blocked_missing_crosswalk" for item in blockers)
            else "blocked_missing_artifacts",
            "validation_tier": "none",
            "blockers": blockers,
            "inputs": {key: str(value) for key, value in required.items()},
        }
        _write_json(manifest, out_dir / "construct_overlap_manifest.json")
        _write_json({"blockers": blockers}, out_dir / "construct_overlap_blockers.json")
        _update_study_manifest_for_construct_overlap(
            study_dir=study_dir,
            out_dir=out_dir,
            manifest=manifest,
        )
        return manifest

    bridge_evidence = _bridge_evidence_from_crosswalk(crosswalk)
    bridge_source = str(bridge_evidence["bridge_source"])
    validation_tier = str(bridge_evidence["validation_tier"])

    con = _duckdb_connect()
    try:
        _setup_base_tables(
            con,
            master_panel_path=required["master_panel"],
            crosswalk_path=crosswalk,
            issuer_origin_path=issuer_origin,
        )
        panel = _write_overlap_core(con, out_dir)
        label_lift = _label_contingency(panel, out_dir)
        cooccurrence = _cooccurrence(panel, out_dir)
        public_ranking, _ = _public_ranking(
            con,
            required["public_predictions"],
            out_dir,
            bridge_source,
        )
        reciprocal = _reciprocal_alignment(
            con,
            benchmark_predictions_path=required["benchmark_predictions"],
            peer_predictions_path=study_dir / "peer_comparison" / "detected_misstatement_model_family_predictions.parquet",
            out_dir=out_dir,
            bridge_source=bridge_source,
        )
        _event_time(con, out_dir)
        _res_an_proxy_coverage(panel, out_dir)
        aggregation = pd.read_csv(out_dir / "aggregation_sensitivity.csv")
    finally:
        con.close()

    opacity_status = _opacity_refresh(study_dir, opacity_out_dir)
    blockers: list[dict[str, str]] = []
    sparse_files: list[str] = []
    manifest = {
        "created_at": _utc_now(),
        "run_status": "complete",
        "validation_tier": validation_tier,
        "bridge_source": bridge_source,
        "bridge_provenance": bridge_evidence["bridge_provenance"],
        "interval_method": BOOTSTRAP_INTERVAL_METHOD,
        "interval_seed": BOOTSTRAP_SEED,
        "interval_reps": BOOTSTRAP_REPS,
        "interval_scope": "top_lift_rows_per_construct_overlap_artifact",
        "interval_top_rows_per_artifact": BOOTSTRAP_INTERVAL_TOP_ROWS,
        "study_dir": str(study_dir),
        "out_dir": str(out_dir),
        "opacity_refresh": opacity_status,
        "blockers": blockers,
        "sparse_outputs": sparse_files,
        "inputs": {
            "crosswalk": str(crosswalk),
            "issuer_origin_panel": str(issuer_origin),
        },
    }
    _write_json(manifest, out_dir / "construct_overlap_manifest.json")
    _write_json({"blockers": blockers}, out_dir / "construct_overlap_blockers.json")
    _write_summary(
        out_dir=out_dir,
        manifest=manifest,
        label_lift=label_lift,
        public_ranking=public_ranking,
        reciprocal=reciprocal,
        cooccurrence=cooccurrence,
        aggregation=aggregation,
    )
    _update_study_manifest_for_construct_overlap(
        study_dir=study_dir,
        out_dir=out_dir,
        manifest=manifest,
    )
    return manifest
