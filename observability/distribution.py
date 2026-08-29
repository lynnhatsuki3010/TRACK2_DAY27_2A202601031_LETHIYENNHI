from __future__ import annotations

from typing import Any, Iterable

import numpy as np


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


def detect_distribution_shift(
    current_values: Iterable[float],
    baseline_values: Iterable[float],
    *,
    ratio_threshold: float = 3.0,
    z_threshold: float = 3.0,
) -> dict[str, Any]:
    """Distribution-shift detector combining mean-ratio and mean-shift z-score.

    Mean ratio alone misses shifts where the baseline is tight and the move
    is modest in absolute-ratio terms; the Welch-style z-score catches those.
    Either signal tripping flags the batch as anomalous.
    """
    cur = np.asarray(list(current_values), dtype=float)
    base = np.asarray(list(baseline_values), dtype=float)
    cur = cur[~np.isnan(cur)]
    base = base[~np.isnan(base)]
    if cur.size == 0 or base.size == 0:
        return {"is_anomaly": False, "score": 0.0, "method": "mean_ratio+meanshift_z", "reason": "empty_input"}
    cur_mean = float(np.mean(cur))
    base_mean = float(np.mean(base))
    ratio_score = _mean_ratio_score(cur_mean, base_mean)
    z_score = _welch_z_score(cur, base)
    is_anomaly = bool(ratio_score >= ratio_threshold or z_score >= z_threshold)
    return {
        "is_anomaly": is_anomaly,
        "score": float(max(ratio_score, z_score)),
        "method": "mean_ratio+meanshift_z",
        "reason": (
            f"baseline_mean={base_mean:.3f}, current_mean={cur_mean:.3f}, "
            f"ratio_score={ratio_score:.3f}, meanshift_z={z_score:.3f}"
        ),
    }
