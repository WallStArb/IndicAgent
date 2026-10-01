"""_zscore_from_deque delegates to _zscore_last and equals its former inline body, bit for bit."""

from __future__ import annotations

from collections import deque

import numpy as np
import pytest

from src.intelligence.features.kernels._cache_state import _zscore_from_deque


def _former_body(history: deque, window: int) -> float:
    if len(history) < window:
        return 0.0
    arr = np.array(list(history)[-window:])
    std = float(arr.std())
    if std < 1e-8:
        return 0.0
    return float((float(history[-1]) - float(arr.mean())) / std)


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
def test_matches_former_body(window):
    for name, values in _histories():
        history = deque(values, maxlen=400)
        if not values:
            continue
        with np.errstate(all="ignore"):
            want = _former_body(history, window)
            got = _zscore_from_deque(history, window)
        assert np.float64(got).tobytes() == np.float64(want).tobytes(), (name, window)
