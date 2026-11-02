"""_z_or_nan over a deque: the cache histories feed it directly, so its semantics are pinned
here on deque inputs (short history and zero-spread windows are NaN, D1 rules 1 and 5)."""

from __future__ import annotations

import math
from collections import deque

import numpy as np
import pytest

from src.intelligence.features.kernels._primitives import _z_or_nan


def _histories():
    rng = np.random.default_rng(11)
    for n in (0, 1, 2, 5, 30, 260):
        base = rng.normal(0.0, 1.0, n).tolist()
        yield f"normal{n}", base
        yield f"constant{n}", [2.5] * n
        yield f"tiny_std{n}", [1.0 + 1e-10 * v for v in base]
        yield f"ints{n}", [int(v * 5) for v in base]
        nan = list(base)
        if n:
            nan[rng.integers(0, n)] = float("nan")
        yield f"nan{n}", nan
        yield f"np_scalars{n}", [np.float64(v) for v in base]


@pytest.mark.parametrize("window", [1, 2, 3, 10, 30, 252, 400])
def test_short_history_and_zero_spread_are_nan(window):
    assert math.isnan(_z_or_nan(deque([], maxlen=400), window))
    assert math.isnan(_z_or_nan(deque([1.5] * max(window - 1, 1), maxlen=400), window))
    assert math.isnan(_z_or_nan(deque([2.5] * window, maxlen=400), window))  # zero spread


@pytest.mark.parametrize("window", [1, 2, 3, 10, 30, 252, 400])
def test_equals_the_plain_array_zscore(window):
    for name, values in _histories():
        history = deque(values, maxlen=400)
        arr = np.asarray(history, dtype=float)[-window:]
        if len(arr) < window or float(arr.std()) < 1e-8:
            expected = float("nan")
        else:
            expected = float((float(arr[-1]) - float(arr.mean())) / float(arr.std()))
        got = _z_or_nan(history, window)
        assert np.float64(got).tobytes() == np.float64(expected).tobytes(), (name, window)
