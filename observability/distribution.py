from __future__ import annotations

from typing import Any, Iterable

import numpy as np

# Two-sided KS critical coefficient at alpha = 0.01.
_KS_ALPHA_COEFF = 1.6276


def _mean_ratio_score(cur_mean: float, base_mean: float) -> float:
    if base_mean == 0:
        return float("inf") if cur_mean != 0 else 1.0
    return max(abs(cur_mean / base_mean), abs(base_mean / cur_mean)) if cur_mean != 0 else float("inf")


def _welch_z_score(cur: np.ndarray, base: np.ndarray) -> float:
    """Two-sample mean-shift z-score (Welch-style standard error).

    Catches shifts that a ratio can miss when both means are moderate but the
    baseline is tight (a small absolute move is still statistically large).
    """
    if cur.size < 2 or base.size < 2:
        return 0.0
    cur_var = float(np.var(cur, ddof=1))
    base_var = float(np.var(base, ddof=1))
    se = ((cur_var / cur.size) + (base_var / base.size)) ** 0.5
    if se == 0:
        return float("inf") if float(np.mean(cur)) != float(np.mean(base)) else 0.0
    return abs(float(np.mean(cur)) - float(np.mean(base))) / se


def _ks_statistic(cur: np.ndarray, base: np.ndarray) -> float:
    """Two-sample Kolmogorov-Smirnov D: max gap between the two empirical CDFs."""
    cur_sorted = np.sort(cur)
    base_sorted = np.sort(base)
    grid = np.concatenate([cur_sorted, base_sorted])
    cur_cdf = np.searchsorted(cur_sorted, grid, side="right") / cur.size
    base_cdf = np.searchsorted(base_sorted, grid, side="right") / base.size
    return float(np.max(np.abs(cur_cdf - base_cdf)))


def _ks_score(cur: np.ndarray, base: np.ndarray) -> float:
    """KS statistic normalized so that 1.0 == the alpha=0.01 critical value.

    Sample-size aware: the critical value shrinks as both samples grow, so this
    stays comparable across a 20-point batch and a 20k-point batch.
    """
    if cur.size < 2 or base.size < 2:
        return 0.0
    critical = _KS_ALPHA_COEFF * ((cur.size + base.size) / (cur.size * base.size)) ** 0.5
    if critical == 0:
        return 0.0
    return _ks_statistic(cur, base) / critical


def _robust_point_score(cur: np.ndarray, base: np.ndarray) -> float:
    """Robust z of a single current observation against the baseline.

    KS and Welch both need >=2 points per side, so a one-value current batch
    would otherwise be invisible no matter how far it sits from the baseline.
    """
    if cur.size != 1 or base.size < 2:
        return 0.0
    median = float(np.median(base))
    mad = float(np.median(np.abs(base - median)))
    scale = 1.4826 * mad
    if scale == 0:
        scale = float(np.std(base, ddof=1))
    if scale == 0:
        return float("inf") if float(cur[0]) != median else 0.0
    return abs(float(cur[0]) - median) / scale


def detect_distribution_shift(
    current_values: Iterable[float],
    baseline_values: Iterable[float],
    *,
    ratio_threshold: float = 3.0,
    z_threshold: float = 3.0,
) -> dict[str, Any]:
    """Distribution-shift detector: mean ratio + mean-shift z + KS shape test.

    Mean-based signals only see the first moment, so a batch that keeps the
    baseline mean but blows up its variance, splits bimodally, or changes shape
    entirely slips past both of them. The two-sample KS statistic compares the
    full empirical CDFs and catches those. Every sub-score is normalized so that
    the same threshold (default 3.0) applies to all of them, and any one signal
    tripping flags the batch.
    """
    cur = np.asarray(list(current_values), dtype=float)
    base = np.asarray(list(baseline_values), dtype=float)
    cur = cur[~np.isnan(cur)]
    base = base[~np.isnan(base)]
    method = "mean_ratio+meanshift_z+ks"
    if cur.size == 0 or base.size == 0:
        return {"is_anomaly": False, "score": 0.0, "method": method, "reason": "empty_input"}

    cur_mean = float(np.mean(cur))
    base_mean = float(np.mean(base))
    ratio_score = _mean_ratio_score(cur_mean, base_mean)
    z_score = _welch_z_score(cur, base)
    # Rescale KS and the single-point fallback onto the shared threshold scale.
    ks_score = _ks_score(cur, base) * z_threshold
    point_score = _robust_point_score(cur, base)

    score = max(ratio_score, z_score, ks_score, point_score)
    is_anomaly = bool(
        ratio_score >= ratio_threshold
        or z_score >= z_threshold
        or ks_score >= z_threshold
        or point_score >= z_threshold
    )
    return {
        "is_anomaly": is_anomaly,
        "score": float(score),
        "method": method,
        "ratio_score": float(ratio_score),
        "meanshift_z": float(z_score),
        "ks_score": float(ks_score),
        "reason": (
            f"baseline_mean={base_mean:.3f}, current_mean={cur_mean:.3f}, "
            f"ratio_score={ratio_score:.3f}, meanshift_z={z_score:.3f}, "
            f"ks_score={ks_score:.3f}, point_score={point_score:.3f}"
        ),
    }
