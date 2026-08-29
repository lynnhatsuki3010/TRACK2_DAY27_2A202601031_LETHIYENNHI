"""Anomaly detection starter.

Z-score is deliberately the default baseline. Students should improve `auto`
mode for seasonality/outliers rather than deleting the simple implementation.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def zscore_detector(current: float, history: Iterable[float], threshold: float = 3.0) -> dict[str, Any]:
    values = np.asarray(list(history), dtype=float)
    values = values[~np.isnan(values)]
    if values.size < 3:
        return {"is_anomaly": False, "score": 0.0, "method": "zscore", "reason": "insufficient_history"}
    mean = float(np.mean(values))
    std = float(np.std(values))
    if std == 0:
        score = float("inf") if float(current) != mean else 0.0
    else:
        score = abs(float(current) - mean) / std
    return {
        "is_anomaly": bool(score > threshold),
        "score": float(score),
        "method": "zscore",
        "reason": f"mean={mean:.3f}, std={std:.3f}, threshold={threshold}",
    }


def mad_detector(current: float, history: Iterable[float], threshold: float = 3.5) -> dict[str, Any]:
    """Robust example, intentionally incomplete around zero-MAD edge cases.

    Students may improve this function and/or use it from auto mode.
    """
    values = np.asarray(list(history), dtype=float)
    values = values[~np.isnan(values)]
    if values.size < 5:
        return {"is_anomaly": False, "score": 0.0, "method": "mad", "reason": "insufficient_history"}
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    if mad == 0:
        # History is a constant run (e.g. same value repeated). Fall back to
        # mean absolute deviation so a real jump still scores instead of
        # silently reporting "not anomalous" whenever MAD collapses to zero.
        fallback = float(np.mean(np.abs(values - median)))
        if fallback == 0:
            score = float("inf") if float(current) != median else 0.0
            return {
                "is_anomaly": bool(score > 0),
                "score": score,
                "method": "mad",
                "reason": f"median={median:.3f}, mad=0, fallback=mean_abs_dev=0",
            }
        modified_z = abs(float(current) - median) / fallback
        return {
            "is_anomaly": bool(modified_z > threshold),
            "score": float(modified_z),
            "method": "mad",
            "reason": f"median={median:.3f}, mad=0, fallback_mean_abs_dev={fallback:.3f}, threshold={threshold}",
        }
    modified_z = 0.6745 * abs(float(current) - median) / mad
    return {
        "is_anomaly": bool(modified_z > threshold),
        "score": float(modified_z),
        "method": "mad",
        "reason": f"median={median:.3f}, mad={mad:.3f}, threshold={threshold}",
    }


def detect_anomaly(
    current: float,
    history: Iterable[float],
    *,
    method: str = "auto",
    threshold: float = 3.0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stable lab API.

    - `zscore`: basic z-score (unchanged, used directly by public tests).
    - `mad`: MAD example (zero-MAD edge case now falls back to mean-abs-dev).
    - `auto`: context-aware baseline selection:
        1. `known_event` in context suppresses the alert (planned traffic
           change, e.g. a flash sale) instead of flagging it as anomalous.
        2. `same_segment_history` (e.g. same-weekday history precomputed by
           the caller) is preferred over the raw `history` so a legitimate
           Saturday dip is compared against other Saturdays, not the whole
           week.
        3. Once a history is chosen, MAD is used when there is enough
           history to compute a stable median (n >= 5) since it is robust to
           the outliers that would otherwise inflate a z-score baseline;
           z-score is the fallback for short histories.
    """
    if method == "mad":
        return mad_detector(current, history)
    if method == "zscore":
        return zscore_detector(current, history, threshold=threshold)
    if method != "auto":
        raise ValueError(f"Unsupported method: {method}")

    context = context or {}

    if context.get("known_event"):
        return {
            "is_anomaly": False,
            "score": 0.0,
            "method": "auto:suppressed_known_event",
            "reason": f"known_event={context['known_event']!r} suppresses alert",
        }

    same_segment = context.get("same_segment_history")
    if same_segment:
        chosen_history = list(same_segment)
        segment_label = f"day_of_week={context.get('day_of_week')}" if context.get("day_of_week") is not None else "same_segment"
    else:
        chosen_history = list(history)
        segment_label = "full_history"

    values = np.asarray(chosen_history, dtype=float)
    values = values[~np.isnan(values)]
    if values.size >= 5:
        result = mad_detector(current, chosen_history)
        result["method"] = "auto:mad"
    else:
        result = zscore_detector(current, chosen_history, threshold=threshold)
        result["method"] = "auto:zscore"
    result["reason"] += f"; segment={segment_label}, n={values.size}"
    return result
