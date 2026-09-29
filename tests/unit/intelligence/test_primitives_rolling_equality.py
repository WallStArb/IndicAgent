"""The vectorized cumsum rolling statistics equal the per-row loops they replaced, bit for bit."""

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


def _window_terms(cs, cs2, i, window):
    eff_w = min(window, i + 1)
    start = i + 1 - eff_w
    s = cs[i] - (cs[start - 1] if start > 0 else 0.0)
    s2 = cs2[i] - (cs2[start - 1] if start > 0 else 0.0)
    mean = s / eff_w
    return eff_w, mean, max(s2 / eff_w - mean * mean, 0.0)


def _ref_zscore(arr, window):
    n = len(arr)
    out = np.zeros(n, dtype=float)
    if n < 2 or window < 2:
        return out
    cs, cs2 = np.cumsum(arr), np.cumsum(arr * arr)
    for i in range(1, n):
        _, mean, var = _window_terms(cs, cs2, i, window)
        std = math.sqrt(var)
        out[i] = (arr[i] - mean) / std if std > STD_FLOOR else 0.0
    return out


def _ref_std(arr, window):
    out = np.zeros(len(arr), dtype=float)
    if len(arr) == 0:
        return out
    cs, cs2 = np.cumsum(arr), np.cumsum(arr * arr)
    for i in range(len(arr)):
        out[i] = math.sqrt(_window_terms(cs, cs2, i, window)[2])
    return out


def _ref_mean(arr, window):
    out = np.zeros(len(arr), dtype=float)
    if len(arr) == 0:
        return out
    cs = np.cumsum(arr)
    for i in range(len(arr)):
        eff_w = min(window, i + 1)
        start = i + 1 - eff_w
        out[i] = (cs[i] - (cs[start - 1] if start > 0 else 0.0)) / eff_w
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
