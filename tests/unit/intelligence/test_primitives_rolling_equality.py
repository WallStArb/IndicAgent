"""The vectorized rolling statistics (exact per-window sums) equal the per-row loops, bit for bit."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.intelligence.features.kernels._primitives import (
    STD_FLOOR,
    _rolling_mean_series,
    _rolling_std_series,
    _rolling_zscore_series,
)


def _window_sum(values, start, stop):
    """One window added left to right (the per-window sums of `_trailing_window_sums`)."""
    total = float(values[start])
    for v in values[start + 1 : stop]:
        total += float(v)
    return total


def _window_terms(cs, cs2, i, window, bad):
    """`cs`, `cs2` are the finite-zeroed values and their squares (name kept from the prefix-sum
    reference this replaced, todo 584 G4-a)."""
    eff_w = min(window, i + 1)
    start = i + 1 - eff_w
    s = _window_sum(cs, start, i + 1)
    s2 = _window_sum(cs2, start, i + 1)
    mean = s / eff_w
    if bad[start : i + 1].any():  # a window holding a non-finite value defines nothing (D1 rule 5)
        return eff_w, np.nan, np.nan
    return eff_w, mean, max(s2 / eff_w - mean * mean, 0.0)


def _ref_zscore(arr, window):
    n = len(arr)
    out = np.full(n, np.nan)
    if n < 2 or window < 2:
        return out
    bad = ~np.isfinite(arr)
    good = np.where(bad, 0.0, arr)
    cs, cs2 = good, good * good
    for i in range(1, n):
        _, mean, var = _window_terms(cs, cs2, i, window, bad)
        std = math.sqrt(var)
        out[i] = (arr[i] - mean) / std if std > STD_FLOOR else np.nan  # D1 rule 5
    return out


def _ref_std(arr, window):
    out = np.zeros(len(arr), dtype=float)
    if len(arr) == 0:
        return out
    bad = ~np.isfinite(arr)
    good = np.where(bad, 0.0, arr)
    cs, cs2 = good, good * good
    for i in range(len(arr)):
        out[i] = math.sqrt(_window_terms(cs, cs2, i, window, bad)[2])
    return out


def _ref_mean(arr, window):
    out = np.zeros(len(arr), dtype=float)
    if len(arr) == 0:
        return out
    bad = ~np.isfinite(arr)
    good = np.where(bad, 0.0, arr)
    cs = good
    for i in range(len(arr)):
        eff_w = min(window, i + 1)
        start = i + 1 - eff_w
        if bad[start : i + 1].any():
            out[i] = np.nan
        else:
            out[i] = _window_sum(cs, start, i + 1) / eff_w
    return out


def _cases():
    rng = np.random.default_rng(20260929)
    for n in (0, 1, 2, 3, 17, 300):
        base = rng.normal(0.0, 1.0, n)
        yield f"normal{n}", base
        yield f"ties{n}", np.round(base, 1)
        yield f"constant{n}", np.full(n, 3.25)
        yield f"zeros{n}", np.zeros(n)
        nan = base.copy()
        if n > 4:
            nan[rng.choice(n, max(n // 10, 1), replace=False)] = np.nan
        yield f"nan{n}", nan
        yield f"large{n}", base * 1e9 + 1e12
    yield "int", np.arange(40, dtype=np.int64) % 5


@pytest.mark.parametrize("window", [1, 2, 3, 5, 20, 400])
@pytest.mark.parametrize(
    "fast,slow", [(_rolling_zscore_series, _ref_zscore), (_rolling_std_series, _ref_std)]
)
def test_zscore_and_std_bit_identical(fast, slow, window):
    import warnings

    for name, arr in _cases():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            want = slow(arr, window)
        got = fast(arr, window)
        assert got.dtype == want.dtype and got.tobytes() == want.tobytes(), (name, window)


@pytest.mark.parametrize("window", [1, 2, 3, 5, 20, 400])
def test_mean_bit_identical(window):
    for name, arr in _cases():
        want, got = _ref_mean(arr, window), _rolling_mean_series(arr, window)
        assert got.tobytes() == want.tobytes(), (name, window)


def test_window_sums_do_not_depend_on_the_series_length_and_match_fsum():
    """The defect behind todo 584 G4-a: a difference of whole-series prefix sums loses digits to
    the running total. Exact per-window sums give the same bits for a window whether the series
    before it is long or absent, and agree with math.fsum to rounding."""
    from src.intelligence.features.kernels._primitives import _trailing_window_sums

    rng = np.random.default_rng(7)
    values = 1.0e6 + rng.normal(0.0, 1.0, 30_000)
    window = 50
    full = _trailing_window_sums(values, window)
    tail = _trailing_window_sums(values[-(window + 5) :], window)
    np.testing.assert_array_equal(full[-6:], tail[-6:])  # same bits, with or without the history
    for i in (window, 12_345, 29_999):
        exact = math.fsum(values[i - window + 1 : i + 1])
        assert abs(full[i] - exact) <= 1e-9 * abs(exact)
    float32_in = _trailing_window_sums(values[:200].astype(np.float32), window)
    assert float32_in.dtype == np.float64
    with pytest.raises(ValueError):
        _trailing_window_sums(values, 0)
