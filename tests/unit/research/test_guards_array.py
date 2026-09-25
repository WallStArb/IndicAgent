"""Array-input guard probes (D-25)."""

import functools

import numpy as np
import pytest

from src.intelligence.research.families.intraday_periodicity import same_slot_mean
from src.intelligence.research.guards import (
    GuardFailure,
    causality_probe_array,
    memory_check_array,
)


def _rolling_mean(x, window=5):
    out = np.full(x.shape, np.nan)
    for t in range(window - 1, len(x)):
        out[t] = np.nanmean(x[t - window + 1 : t + 1], axis=0)
    return out


def _rolling_sum(x, window=10):
    c = np.cumsum(np.nan_to_num(x), axis=0)
    out = c.copy()
    out[window:] -= c[:-window]
    return out


def _ahead(x, k=1):
    out = np.full(x.shape, np.nan)
    out[:-k] = x[k:]
    return out


def _x(seed=0, n=120, m=4):
    return np.random.default_rng(seed).normal(0, 0.01, (n, m))


ROWS = np.array([10, 40, 70, 95])


def test_causality_array_passes_causal_and_catches_lookahead():
    x = _x()
    causality_probe_array(_rolling_mean, x, ROWS, seed=1)
    with pytest.raises(GuardFailure, match="lookahead"):
        causality_probe_array(_ahead, x, ROWS, seed=1)


def test_causality_array_reach():
    x = _x()
    three = functools.partial(_ahead, k=3)
    causality_probe_array(three, x, ROWS, seed=1, reach=3)
    with pytest.raises(GuardFailure, match="lookahead"):
        causality_probe_array(three, x, ROWS, seed=1, reach=2)


def test_memory_array():
    x = _x()
    rows = np.array([10, 40, 70])
    assert memory_check_array(_rolling_sum, x, rows, declared=10) <= 10
    with pytest.raises(GuardFailure, match="memory"):
        memory_check_array(_rolling_sum, x, rows, declared=5)
    with pytest.raises(GuardFailure, match="lookahead"):
        memory_check_array(_ahead, x, rows, declared=10)


def test_array_probes_never_mutate_input():
    x = _x()
    saved = x.copy()
    causality_probe_array(_rolling_mean, x, ROWS, seed=1)
    memory_check_array(_rolling_sum, x, np.array([10, 40]), declared=10)
    np.testing.assert_array_equal(x, saved)


def test_memory_array_shock_is_additive_and_restored():
    x = _x()
    seen = []

    def spy(arr):
        seen.append(arr.copy())
        return _rolling_sum(arr)

    memory_check_array(spy, x, np.array([20, 50]), declared=10)
    sd = np.nanstd(x, axis=0)
    np.testing.assert_allclose(seen[1][20] - x[20], 5.0 * sd)
    np.testing.assert_array_equal(seen[2][20], x[20])  # restored before the next shock
    np.testing.assert_allclose(seen[2][50] - x[50], 5.0 * sd)


@pytest.mark.parametrize("window", [1, 5, 20, 40])
def test_family_members_pass_array_probes(window):
    bps = 26
    x = np.random.default_rng(3).normal(0, 0.001, (60 * bps, 30))
    fn = functools.partial(
        same_slot_mean, bars_per_session=bps, coverage_floor=20, window_sessions=window
    )
    rows = np.array([5 * bps + 3, 10 * bps - 1, 13 * bps + 7])
    causality_probe_array(fn, x, rows, seed=2)
    assert memory_check_array(fn, x, rows, declared=window * bps) <= window * bps
