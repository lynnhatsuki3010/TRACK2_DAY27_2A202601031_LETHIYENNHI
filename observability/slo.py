from __future__ import annotations

from typing import Any


def calculate_slo(target: float, bad_events: int, total_events: int) -> dict[str, Any]:
    if not 0 < target < 1:
        raise ValueError("target must be between 0 and 1 (exclusive)")
    if bad_events < 0 or total_events < 0 or bad_events > total_events:
        raise ValueError("invalid event counts")
    allowed_bad_rate = 1.0 - target
    if total_events == 0:
        return {
            "target": target,
            "actual_bad_rate": 0.0,
            "allowed_bad_rate": allowed_bad_rate,
            "burn_rate": 0.0,
            "remaining_error_budget_fraction": 1.0,
            "breached": False,
        }
    actual_bad_rate = bad_events / total_events
    burn_rate = actual_bad_rate / allowed_bad_rate
    consumed_fraction = min(1.0, actual_bad_rate / allowed_bad_rate)
    return {
        "target": target,
        "actual_bad_rate": actual_bad_rate,
        "allowed_bad_rate": allowed_bad_rate,
        "burn_rate": burn_rate,
        "remaining_error_budget_fraction": max(0.0, 1.0 - consumed_fraction),
        "breached": bool(actual_bad_rate > allowed_bad_rate),
    }


def evaluate_multiwindow_burn(
    *,
    short_window_burn: float,
    long_window_burn: float,
    policy: str = "google_sre",
) -> dict[str, Any]:
    """Multi-window burn-rate policy (Google SRE workbook style).

    Requires the short window to corroborate the long window before paging,
    so a short-lived spike that never shows up in the long window does not
    wake anyone up, while a burn that is fast *and* sustained does.

    Thresholds (approximate the SRE workbook's 2%/1h and 5%/6h alert pairs):
    - >=14.4x on both windows -> critical page (very fast burn).
    - >=6x on both windows    -> high page (sustained fast burn).
    - >=1x on both windows    -> warning page (slow sustained burn).
    - short spikes alone (long window under budget) -> no page, info only.
    """
    base = {
        "short_window_burn": short_window_burn,
        "long_window_burn": long_window_burn,
        "policy": policy,
    }
    if short_window_burn >= 14.4 and long_window_burn >= 14.4:
        return {**base, "page": True, "severity": "critical", "reason": "fast burn corroborated by both windows (>=14.4x)"}
    if short_window_burn >= 6 and long_window_burn >= 6:
        return {**base, "page": True, "severity": "high", "reason": "sustained fast burn corroborated by both windows (>=6x)"}
    if short_window_burn >= 1 and long_window_burn >= 1:
        return {**base, "page": True, "severity": "warning", "reason": "slow sustained burn corroborated by both windows (>=1x)"}
    if short_window_burn > long_window_burn:
        return {**base, "page": False, "severity": "info", "reason": "transient short-window spike not corroborated by long window"}
    if long_window_burn >= 1:
        return {**base, "page": False, "severity": "info", "reason": "long window elevated but short window not corroborating yet; monitor, do not page"}
    return {**base, "page": False, "severity": "info", "reason": "no burn-rate threshold crossed"}
