from __future__ import annotations

from typing import Any


def calculate_slo(target: float, bad_events: int, total_events: int) -> dict[str, Any]:
    if not 0 < target < 1:
        raise ValueError("target must be between 0 and 1 (exclusive)")
    if bad_events < 0 or total_events < 0 or bad_events > total_events:
        raise ValueError("invalid event counts")
    # 1.0 - 0.995 is 0.005000000000000004 in binary float; rounding keeps the
    # budget, burn rate and boundary comparisons exact for realistic targets.
    allowed_bad_rate = round(1.0 - target, 12)
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
    consumed_fraction = min(1.0, burn_rate)
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
    """Multi-window, multi-burn-rate policy (Google SRE workbook, table 5-3).

    The long window decides whether the burn is real; the short window has to
    corroborate it, so an alert both needs a sustained problem and resets fast
    once the burn stops.

    | burn rate | long / short window | consumes budget in | action        |
    |-----------|---------------------|--------------------|---------------|
    | >= 14.4x  | 1h / 5m             | ~2% per hour       | page critical |
    | >= 6x     | 6h / 30m            | ~5% per 6h         | page high     |
    | >= 1x     | 3d / 6h             | ~10% per 3 days    | ticket, no page |

    Only the two fast-burn rows page. A 1x-ish burn is by definition the rate
    the error budget is *meant* to be spent at, so it opens a ticket instead of
    waking someone up, and a short-window spike the long window never confirms
    stays informational.
    """
    base = {
        "short_window_burn": short_window_burn,
        "long_window_burn": long_window_burn,
        "policy": policy,
    }
    if short_window_burn >= 14.4 and long_window_burn >= 14.4:
        return {
            **base,
            "page": True,
            "severity": "critical",
            "action": "page",
            "reason": "fast burn (>=14.4x) corroborated by both windows: ~2% of budget per hour",
        }
    if short_window_burn >= 6 and long_window_burn >= 6:
        return {
            **base,
            "page": True,
            "severity": "high",
            "action": "page",
            "reason": "sustained fast burn (>=6x) corroborated by both windows: ~5% of budget per 6h",
        }
    if short_window_burn >= 1 and long_window_burn >= 1:
        return {
            **base,
            "page": False,
            "severity": "warning",
            "action": "ticket",
            "reason": "slow sustained burn (>=1x) but below the fast-burn page thresholds; open a ticket, do not page",
        }
    if short_window_burn > long_window_burn:
        return {
            **base,
            "page": False,
            "severity": "info",
            "action": "none",
            "reason": "transient short-window spike not corroborated by the long window",
        }
    if long_window_burn >= 1:
        return {
            **base,
            "page": False,
            "severity": "info",
            "action": "none",
            "reason": "long window elevated but short window not corroborating; monitor, do not page",
        }
    return {
        **base,
        "page": False,
        "severity": "info",
        "action": "none",
        "reason": "no burn-rate threshold crossed",
    }
