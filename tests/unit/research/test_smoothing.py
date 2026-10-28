"""The fixed smoothing menu (phase 184 B5, design D3)."""

import functools

import numpy as np
import pytest

from src.intelligence.research.guards import causality_probe_array, memory_check_array
from src.intelligence.research.smoothing import (
    SMOOTHING_HALF_LIVES,
    smooth,
    smoothing_memory_sessions,
    smoothing_weights,
)


def _x(seed=0, n=1200, m=30):
    return np.random.default_rng(seed).normal(0.0, 0.01, (n, m))


def test_menu_and_declared_memory():
    assert SMOOTHING_HALF_LIVES == (5, 21, 63)
    assert [smoothing_memory_sessions(h) for h in SMOOTHING_HALF_LIVES] == [67, 280, 838]


@pytest.mark.parametrize("bad", [0, 4, 10, 64, -5, 5.5, True])
def test_off_menu_half_life_raises(bad):
    with pytest.raises(ValueError, match="half-life"):
        smoothing_memory_sessions(bad)
    with pytest.raises(ValueError, match="half-life"):
        smooth(_x(n=100, m=2), bad)


def test_weights_are_the_truncated_exponential_with_fixed_total():
    h = 21
    a = 1 - 2 ** (-1 / h)
    k = np.arange(smoothing_memory_sessions(h) + 1)
    raw = a * (1 - a) ** k
    np.testing.assert_allclose(smoothing_weights(h), raw / raw.sum(), rtol=1e-14)
    # the cut: the last kept weight is within 1e-4 of the peak, the next one is not kept
    assert raw[-1] / raw[0] <= 1e-4 < raw[-2] / raw[0]


@pytest.mark.parametrize("h", SMOOTHING_HALF_LIVES)
def test_matches_direct_window_sum(h):
    x = _x(seed=3, n=1000, m=5)
    out = smooth(x, h)
    w = smoothing_weights(h)
    k_max = len(w) - 1
    for t in (k_max, k_max + 7, 999):
        expected = (w[:, None] * x[t - np.arange(k_max + 1)]).sum(axis=0)
        np.testing.assert_allclose(out[t], expected, rtol=1e-12, atol=1e-15)


@pytest.mark.parametrize("h", SMOOTHING_HALF_LIVES)
def test_constant_input_passes_through(h):
    x = np.full((900, 3), 2.5)
    out = smooth(x, h)
    k_max = smoothing_memory_sessions(h)
    assert np.isnan(out[:k_max]).all()
    np.testing.assert_allclose(out[k_max:], 2.5, rtol=1e-12)


def test_no_fill_single_nan_blanks_the_next_k_max_plus_one_outputs():
    h = 5
    k_max = smoothing_memory_sessions(h)
    x = _x(seed=1, n=400, m=3)
    r = 150
    x[r, 1] = np.nan
    out = smooth(x, h)
    col = out[:, 1]
    assert np.isnan(col[:k_max]).all()
    assert np.isfinite(col[k_max:r]).all()
    assert np.isnan(col[r : r + k_max + 1]).all()
    assert np.isfinite(col[r + k_max + 1 :]).all()
    # other columns are untouched by column 1's gap
    assert np.isfinite(out[k_max:, [0, 2]]).all()


def test_no_fill_leading_nan_stays_nan_until_full_history():
    h = 5
    k_max = smoothing_memory_sessions(h)
    x = _x(seed=2, n=300, m=2)
    first = 40
    x[:first, 0] = np.nan
    out = smooth(x, h)
    assert np.isnan(out[: first + k_max, 0]).all()
    assert np.isfinite(out[first + k_max :, 0]).all()
    assert np.isfinite(out[k_max:, 1]).all()


def test_short_input_is_all_nan():
    out = smooth(_x(n=60, m=2), 5)
    assert out.shape == (60, 2) and np.isnan(out).all()


def test_dtype_preserved():
    x = _x(n=200, m=2).astype(np.float32)
    assert smooth(x, 5).dtype == np.float32
    with pytest.raises(ValueError, match="floating"):
        smooth(np.ones((200, 2), dtype=np.int64), 5)


@pytest.mark.parametrize("h", SMOOTHING_HALF_LIVES)
def test_causality_probe_passes(h):
    x = _x(seed=4, n=1200, m=30)
    rows = np.array([900, 1000, 1100])
    causality_probe_array(functools.partial(smooth, half_life=h), x, rows, seed=7)


@pytest.mark.parametrize("h", SMOOTHING_HALF_LIVES)
def test_memory_check_reach_within_declared(h):
    x = _x(seed=5, n=1200, m=30)
    k_max = smoothing_memory_sessions(h)
    rows = np.array([100, 300, 340]) if h < 63 else np.array([0, 100, 300])
    reach = memory_check_array(functools.partial(smooth, half_life=h), x, rows, declared=k_max)
    assert 0 < reach <= k_max
