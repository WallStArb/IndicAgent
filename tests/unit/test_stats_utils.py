"""Unit tests for src/core/stats_utils.bootstrap_ci_lower."""

from __future__ import annotations

import math

from src.core.stats_utils import bootstrap_ci_lower


def test_empty_list_returns_neg_inf():
    assert bootstrap_ci_lower([]) == float("-inf")


def test_fewer_than_10_samples_returns_neg_inf():
    assert bootstrap_ci_lower([0.1] * 9) == float("-inf")


def test_exactly_10_samples_returns_finite():
    result = bootstrap_ci_lower([0.1] * 10)
    assert math.isfinite(result)


def test_positive_pnl_returns_positive_ci():
    result = bootstrap_ci_lower([1.0] * 100)
    assert result > 0.0


def test_negative_pnl_returns_negative_ci():
    result = bootstrap_ci_lower([-1.0] * 100)
    assert result < 0.0


def test_ci_lower_le_mean():
    values = [0.5] * 100
    result = bootstrap_ci_lower(values)
    assert result <= 0.5


def test_custom_alpha():
    values = list(range(1, 101))
    ci_95 = bootstrap_ci_lower(values, alpha=0.05)
    ci_99 = bootstrap_ci_lower(values, alpha=0.01)
    assert ci_99 <= ci_95


def test_custom_n_boot():
    result = bootstrap_ci_lower([0.1] * 50, n_boot=500)
    assert math.isfinite(result)


def test_reproducible_with_seed():
    values = [float(i) for i in range(20)]
    r1 = bootstrap_ci_lower(values)
    r2 = bootstrap_ci_lower(values)
    assert r1 == r2
