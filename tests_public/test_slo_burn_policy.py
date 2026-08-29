"""Multi-window burn-rate policy regression tests (Google SRE workbook table 5-3)."""
import pytest
from student_api import multiwindow_burn, slo_status


def test_fast_burn_on_both_windows_pages_critical():
    result = multiwindow_burn(short_window_burn=20.0, long_window_burn=18.0)
    assert result["page"] is True
    assert result["severity"] == "critical"


def test_sustained_six_x_burn_pages_high():
    result = multiwindow_burn(short_window_burn=8.0, long_window_burn=7.0)
    assert result["page"] is True
    assert result["severity"] == "high"


def test_transient_short_spike_does_not_page():
    assert multiwindow_burn(short_window_burn=20.0, long_window_burn=0.2)["page"] is False


def test_slow_sustained_burn_is_a_ticket_not_a_page():
    """1x burn is the rate the budget is meant to be spent at -> ticket, no page."""
    result = multiwindow_burn(short_window_burn=1.5, long_window_burn=1.2)
    assert result["page"] is False
    assert result["severity"] == "warning"


def test_short_spike_over_a_mildly_elevated_long_window_does_not_page():
    assert multiwindow_burn(short_window_burn=20.0, long_window_burn=1.5)["page"] is False


def test_recovering_short_window_does_not_page():
    """Long window still hot but the burn has stopped: alert must not fire."""
    assert multiwindow_burn(short_window_burn=2.0, long_window_burn=10.0)["page"] is False


def test_no_burn_does_not_page():
    assert multiwindow_burn(short_window_burn=0.0, long_window_burn=0.0)["page"] is False


@pytest.mark.parametrize(
    "target,bad,total,allowed,burn",
    [
        (0.995, 2, 100, 0.005, 4.0),
        (0.999, 5, 1000, 0.001, 5.0),
        (0.99, 1, 100, 0.01, 1.0),
    ],
)
def test_budget_math_is_exact_not_float_noise(target, bad, total, allowed, burn):
    result = slo_status(target, bad_events=bad, total_events=total)
    assert result["allowed_bad_rate"] == allowed
    assert result["burn_rate"] == burn


def test_exactly_at_budget_is_not_breached():
    result = slo_status(0.99, bad_events=1, total_events=100)
    assert result["breached"] is False
    assert result["remaining_error_budget_fraction"] == 0.0
