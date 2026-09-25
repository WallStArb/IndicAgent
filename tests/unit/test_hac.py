"""Newey-West HAC t-test of a mean (methodology-change-ledger E16, pinned (a))."""

import numpy as np
import pytest
from scipy.stats import t as tdist

from src.intelligence.statistics.hac import hac_mean_test, newey_west_lag


def _nw_t_reference(p):
    """scripts/analysis/e16_null_size/screen_hac_tail.py::nw_t, the statistic E16's size
    simulations used, copied verbatim."""
    n = len(p)
    x = p - p.mean()
    L = int(np.floor(4 * (n / 100) ** (2 / 9)))
    v = x @ x / n
    for k in range(1, L + 1):
        v += 2 * (1 - k / (L + 1)) * (x[k:] @ x[:-k]) / n
    return p.mean() / np.sqrt(v / n)


@pytest.mark.parametrize("n,lag", [(100, 4), (190, 4), (1000, 6), (4000, 9), (3748, 8)])
def test_lag_rule(n, lag):
    assert newey_west_lag(n) == lag == int(np.floor(4 * (n / 100) ** (2 / 9)))


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_t_matches_simulated_statistic(seed):
    rng = np.random.default_rng(seed)
    x = np.convolve(rng.standard_normal(1200), np.ones(5) / 5, mode="same") + 0.01
    res = hac_mean_test(x)
    assert res.t == pytest.approx(_nw_t_reference(x), rel=1e-12)
    assert res.p == pytest.approx(tdist.sf(res.t, len(x) - 1), rel=1e-12)
    assert res.lag == newey_west_lag(len(x)) and res.n == len(x)
    assert res.se == pytest.approx(x.mean() / res.t, rel=1e-12)


def test_nan_values_are_dropped():
    x = np.array([0.1, np.nan, -0.2, 0.3, np.nan, 0.05] * 20)
    assert hac_mean_test(x).n == 80
    assert hac_mean_test(x).t == pytest.approx(_nw_t_reference(x[np.isfinite(x)]), rel=1e-12)


def test_degenerate_series_raise():
    with pytest.raises(ValueError):
        hac_mean_test(np.array([1.0]))
    with pytest.raises(ValueError):
        hac_mean_test(np.zeros(50))


def test_size_under_iid_null_is_nominal():
    rng = np.random.default_rng(7)
    p = np.array([hac_mean_test(rng.standard_normal(500)).p for _ in range(2000)])
    assert abs((p < 0.05).mean() - 0.05) < 0.015
