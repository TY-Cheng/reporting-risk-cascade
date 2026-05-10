"""Ranking metrics aligned with Bao et al. (2020) fraud-detection evaluation."""

from __future__ import annotations

from typing import Dict, Iterable

import numpy as np


BAO_TOP_FRACTIONS = (0.01, 0.02, 0.03, 0.04, 0.05)


def matlab_round_positive(value: float) -> int:
    """Replicate MATLAB ``round`` for non-negative values used in top-k sizing."""
    if value < 0:
        raise ValueError("matlab_round_positive expects a non-negative value")
    return int(np.floor(float(value) + 0.5))


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return float("nan")
    return float(numerator / denominator)


def bao_top_fraction_metric(
    y_true: Iterable[float],
    score: Iterable[float],
    *,
    top_fraction: float = 0.01,
) -> Dict[str, float]:
    """Compute Bao et al.-style top-N% precision, sensitivity, specificity, BAC, NDCG.

    The public replication code computes ``k = round(n * topN)``, sorts decision
    values descending, treats the top-k observations as predicted frauds, and
    computes binary-relevance NDCG@k with the ideal ranking capped at the number
    of positives.
    """
    y = np.asarray(list(y_true), dtype=float)
    s = np.asarray(list(score), dtype=float)
    if y.shape[0] != s.shape[0]:
        raise ValueError("y_true and score must have the same length")
    if not 0 <= top_fraction <= 1:
        raise ValueError("top_fraction must be between 0 and 1")

    y_binary = np.nan_to_num(y, nan=0.0).astype(int)
    score_clean = np.nan_to_num(s, nan=-np.inf)
    n_obs = int(len(y_binary))
    k = matlab_round_positive(n_obs * float(top_fraction))
    k = min(k, n_obs)

    ranked = np.argsort(-score_clean, kind="mergesort")
    selected = ranked[:k]
    pred_topk = np.zeros(n_obs, dtype=int)
    if k > 0:
        pred_topk[selected] = 1

    positives = y_binary == 1
    negatives = ~positives
    predicted_positive = pred_topk == 1
    predicted_negative = ~predicted_positive

    tp = int(np.sum(positives & predicted_positive))
    fn = int(np.sum(positives & predicted_negative))
    tn = int(np.sum(negatives & predicted_negative))
    fp = int(np.sum(negatives & predicted_positive))

    sensitivity = _safe_divide(tp, tp + fn)
    specificity = _safe_divide(tn, tn + fp)
    precision = _safe_divide(tp, tp + fp)
    if np.isnan(sensitivity) or np.isnan(specificity):
        bac = float("nan")
    else:
        bac = float((sensitivity + specificity) / 2.0)

    hits = int(np.sum(positives))
    ideal_hits = min(k, hits)
    ideal_dcg = sum(1.0 / np.log2(1 + rank) for rank in range(1, ideal_hits + 1))
    dcg = 0.0
    for rank, idx in enumerate(ranked[:k], start=1):
        if y_binary[idx] == 1:
            dcg += 1.0 / np.log2(1 + rank)
    ndcg = float(dcg / ideal_dcg) if ideal_dcg else 0.0

    return {
        "k": int(k),
        "precision": precision,
        "sensitivity": sensitivity,
        "specificity": specificity,
        "bac": bac,
        "ndcg": ndcg,
    }


def bao_top_fraction_metrics(
    y_true: Iterable[float],
    score: Iterable[float],
    *,
    top_fractions: Iterable[float] = BAO_TOP_FRACTIONS,
    prefix: str = "bao",
) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    for fraction in top_fractions:
        pct = int(round(float(fraction) * 100))
        result = bao_top_fraction_metric(y_true, score, top_fraction=float(fraction))
        base = f"{prefix}_top_{pct}pct"
        metrics[f"{base}_k"] = result["k"]
        metrics[f"{base}_precision"] = result["precision"]
        metrics[f"{base}_sensitivity"] = result["sensitivity"]
        metrics[f"{base}_specificity"] = result["specificity"]
        metrics[f"{base}_bac"] = result["bac"]
        metrics[f"{base}_ndcg"] = result["ndcg"]
    return metrics
