"""Daily residual members against a brute-force reference (prereg 2026-10-27 section 3)."""

import numpy as np
import pytest

from src.intelligence.research.families.common import centred_rank
from src.intelligence.research.families.daily_residual import (
    residual_momentum,
    residual_momentum_z,
    residual_reversal,
)

FLOOR = 3


def _resid(seed=0, n=320, m=8):
    rng = np.random.default_rng(seed)
    e = rng.normal(0, 0.01, (n, m))
    e[rng.random((n, m)) < 0.1] = np.nan
    e[:, 0] = np.nan  # a name that never trades
    e[:150, 1] = np.nan  # a late lister
    return e


def _ref(e, lo, hi, stat):
    """Per row d, stat over sessions d-hi .. d-lo (inclusive), half-window finite rule."""
    n, m = e.shape
    out = np.full((n, m), np.nan)
    for d in range(n):
        for i in range(m):
            if not np.isfinite(e[d, i]):
                continue
            w = e[max(d - hi, 0) : d - lo + 1, i] if d - lo >= 0 else np.array([])
            out[d, i] = stat(w[np.isfinite(w)], hi - lo + 1)
    return centred_rank(out, coverage_floor=FLOOR)


def _sum(x, length):
    return x.sum() if len(x) >= (length + 1) // 2 else np.nan


def _z(x, length):
    if len(x) < max((length + 1) // 2, 2):
        return np.nan
    sd = x.std(ddof=1)
    return x.mean() / sd if sd > 0 else np.nan


def test_momentum_reads_d_minus_251_to_d_minus_21():
    e = _resid()
    got = residual_momentum(e, bars_per_session=1, coverage_floor=FLOOR)
    np.testing.assert_allclose(got, _ref(e, 21, 251, _sum), equal_nan=True, atol=1e-12)
    gz = residual_momentum_z(e, bars_per_session=1, coverage_floor=FLOOR)
    np.testing.assert_allclose(gz, _ref(e, 21, 251, _z), equal_nan=True, atol=1e-12)


@pytest.mark.parametrize("window, skip", [(5, 0), (21, 0), (5, 1)])
def test_reversal_is_minus_the_window_sum(window, skip):
    e = _resid(1)
    got = residual_reversal(
        e, bars_per_session=1, coverage_floor=FLOOR, window_sessions=window, skip_sessions=skip
    )
    want = _ref(e, skip, skip + window - 1, lambda x, n: -_sum(x, n))
    np.testing.assert_allclose(got, want, equal_nan=True, atol=1e-12)


def test_no_member_reads_a_later_row():
    e = _resid(2)
    later = e.copy()
    later[200:] = np.random.default_rng(9).normal(0, 0.05, later[200:].shape)
    for f, kw in (
        (residual_momentum, {}),
        (residual_momentum_z, {}),
        (residual_reversal, {"window_sessions": 5}),
        (residual_reversal, {"window_sessions": 5, "skip_sessions": 1}),
    ):
        a = f(e, bars_per_session=1, coverage_floor=FLOOR, **kw)
        b = f(later, bars_per_session=1, coverage_floor=FLOOR, **kw)
        np.testing.assert_array_equal(a[:200], b[:200])


def test_refuses_an_intraday_panel():
    with pytest.raises(ValueError, match="1d panel"):
        residual_momentum(_resid(), bars_per_session=26, coverage_floor=FLOOR)
