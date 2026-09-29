"""gap_z and overnight_gap_z rebuilt from an aligned previous-close array (186 debt pass B3).

The `_reference` functions below are the earlier index-shifting implementations, kept verbatim
as slow references: the aligned kernels must match them bit for bit on every input.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.features.kernels._primitives import (
    _fixed_window_zscore_series,
    _rolling_zscore_series,
)
from src.intelligence.features.kernels.price import (
    _gap_z_series_full,
    _overnight_gap_series_full,
    _overnight_gap_z_series_full,
)

EPS = 1e-10


def _gap_z_reference(opens, closes, atr_raw, atr_valid, zscore_window):
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    atr_core = atr_raw
    atr_for_gap = atr_core[:-1] if len(atr_core) >= 2 else atr_core
    if len(atr_for_gap) > 0 and len(opens) >= 2 and len(closes) >= 2:
        gap_high = min(len(opens) - 2, len(atr_for_gap))
        gap_atr_valid = atr_valid[1 : 1 + gap_high]
        gap_raw = (opens[2 : 2 + gap_high] - closes[1 : 1 + gap_high]) / np.where(
            gap_atr_valid, atr_for_gap[:gap_high], 1.0
        )
        gap_z_core = _rolling_zscore_series(np.concatenate([[0.0], gap_raw]), zscore_window)
        result = np.zeros(n, dtype=float)
        if len(gap_z_core) >= 2:
            result[2:] = gap_z_core[1:]
    return result


def _overnight_gap_series_reference(opens, closes, eps=EPS):
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    prev_closes = closes[:-1]
    raw_gaps = np.where(prev_closes > eps, (opens[1:] - prev_closes) / prev_closes, 0.0)
    return np.concatenate([[0.0], raw_gaps])


def _overnight_gap_z_reference(opens, closes, window):
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    raw_gaps = _overnight_gap_series_reference(opens, closes)[1:]
    z = _fixed_window_zscore_series(raw_gaps, window)
    return np.concatenate([[0.0], z])


def _case(n, seed):
    rng = np.random.default_rng(seed)
    closes = np.cumprod(1.0 + rng.normal(0, 0.02, n)) * 100.0
    if n > 5:
        closes[n // 2] = 0.0  # a zero previous close: the eps guard and the divide path
    opens = closes * (1.0 + rng.normal(0, 0.01, n))
    atr_padded = np.concatenate([[0.0], np.abs(rng.normal(1.0, 0.5, max(n - 1, 0)))])[:n]
    atr_valid = rng.random(n) > 0.2
    atr_valid[:1] = False
    if n > 8:
        atr_padded[5] = np.nan  # a NaN behind a False mask must not leak
        atr_valid[5] = False
    return opens, closes, atr_padded, atr_valid


SIZES = [0, 1, 2, 3, 4, 5, 6, 9, 30, 101, 800]


@pytest.mark.parametrize("n", SIZES)
@pytest.mark.parametrize("window", [2, 3, 20, 500])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_gap_z_equals_the_shifted_reference(n, window, seed):
    opens, closes, atr_padded, atr_valid = _case(n, seed)
    with np.errstate(all="ignore"):
        got = _gap_z_series_full(opens, closes, atr_padded, atr_valid, window)
        want = _gap_z_reference(opens, closes, atr_padded[1:], atr_valid, window)
    np.testing.assert_array_equal(got, want)


@pytest.mark.parametrize("n", SIZES)
@pytest.mark.parametrize("window", [2, 3, 20])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_overnight_gap_z_equals_the_shifted_reference(n, window, seed):
    opens, closes, _, _ = _case(n, seed)
    with np.errstate(all="ignore"):
        np.testing.assert_array_equal(
            _overnight_gap_series_full(opens, closes),
            _overnight_gap_series_reference(opens, closes),
        )
        np.testing.assert_array_equal(
            _overnight_gap_z_series_full(opens, closes, window),
            _overnight_gap_z_reference(opens, closes, window),
        )
