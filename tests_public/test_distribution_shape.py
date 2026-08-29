"""Shape-drift regression tests: cases a mean-only detector cannot see."""
import numpy as np
import pytest
from student_api import detect_distribution


def _rng():
    return np.random.default_rng(1234)


def test_variance_blowup_with_unchanged_mean_detected():
    rng = _rng()
    baseline = list(rng.normal(100, 2, 200))
    current = list(rng.normal(100, 30, 200))
    result = detect_distribution(current, baseline)
    assert result["is_anomaly"] is True


def test_bimodal_split_with_unchanged_mean_detected():
    rng = _rng()
    baseline = list(rng.normal(100, 5, 200))
    current = [50.0] * 100 + [150.0] * 100
    assert detect_distribution(current, baseline)["is_anomaly"] is True


def test_shape_change_with_unchanged_mean_detected():
    rng = _rng()
    baseline = list(rng.uniform(0, 20, 300))
    current = list(rng.exponential(10, 300))
    assert detect_distribution(current, baseline)["is_anomaly"] is True


def test_single_current_value_far_from_baseline_detected():
    assert detect_distribution([25], [10, 10, 11, 9, 10, 10])["is_anomaly"] is True


@pytest.mark.parametrize("n", [10, 100, 1000])
def test_same_distribution_is_not_flagged(n):
    rng = _rng()
    baseline = list(rng.normal(100, 10, n))
    current = list(rng.normal(100, 10, n))
    assert detect_distribution(current, baseline)["is_anomaly"] is False


def test_empty_input_is_safe():
    result = detect_distribution([], [1, 2, 3])
    assert result["is_anomaly"] is False
    assert result["score"] == 0.0
