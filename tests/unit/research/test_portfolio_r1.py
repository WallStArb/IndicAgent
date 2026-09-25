"""R1 (prereg section 4, D-13, D-24): rank-weighted, leg-normalized, dollar-neutral
construction, and its own trailing per-name volatility. Slow-loop reference lives here, an
independent path from the vectorized implementation (pandas rank, not scipy.stats.rankdata)."""

import functools
import pickle
import time

import numpy as np
import pandas as pd
import pytest

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from src.intelligence.research.portfolio import (
    RANK_VOL_NEUTRAL_ARM,
    plan_covariance,
    rank_vol_neutral_returns,
    rank_vol_neutral_weights,
    trailing_vol,
)

CFG = HarnessConfig(warmup_sessions=20, calibration_refit_sessions=10)
MV_COND = 1000.0


def _slow_weights(alpha, vol, direction, coverage_floor):
    """Independent reference: pandas average-rank, not scipy.stats.rankdata."""
    n, m = alpha.shape
    out = np.zeros((n, m))
    has_position = np.zeros(n, dtype=bool)
    for t in range(n):
        valid = [
            i
            for i in range(m)
            if np.isfinite(alpha[t, i]) and np.isfinite(vol[t, i]) and vol[t, i] > 0
        ]
        if len(valid) < coverage_floor:
            continue
        a = {i: alpha[t, i] for i in valid}
        ranks = pd.Series(a).rank(method="average")
        nv = len(valid)
        centred = {i: (ranks[i] - 1.0) / (nv - 1) - 0.5 for i in valid}
        raw = {i: direction * centred[i] / vol[t, i] for i in valid}
        pos = {i: v for i, v in raw.items() if v > 0}
        neg = {i: v for i, v in raw.items() if v < 0}
        if not pos or not neg:
            continue
        pos_sum = sum(pos.values())
        neg_sum = sum(neg.values())
        w = np.zeros(m)
        for i, v in pos.items():
            w[i] = v / pos_sum * 0.5
        for i, v in neg.items():
            w[i] = v / -neg_sum * 0.5
        out[t] = w
        has_position[t] = True
    return out, has_position


def _panel(seed, n=30, m=6, coverage_floor=2, nan_frac=0.0):
    rng = np.random.default_rng(seed)
    alpha = rng.normal(size=(n, m))
    vol = rng.uniform(0.5, 3.0, (n, m))
    fwd = rng.normal(0, 0.01, (n, m))
    if nan_frac:
        alpha[rng.random((n, m)) < nan_frac] = np.nan
        vol[rng.random((n, m)) < nan_frac] = np.nan
    return alpha, vol, fwd


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_weights_match_slow_reference_and_are_dollar_neutral(seed):
    alpha, vol, _ = _panel(seed, coverage_floor=2)
    got_w, got_has = rank_vol_neutral_weights(alpha, vol=vol, direction=1.0, coverage_floor=2)
    want_w, want_has = _slow_weights(alpha, vol, direction=1.0, coverage_floor=2)
    np.testing.assert_array_equal(got_has, want_has)
    np.testing.assert_allclose(got_w, want_w, rtol=1e-9, atol=1e-12)
    for t in np.flatnonzero(got_has):
        row = got_w[t]
        assert row.sum() == pytest.approx(0.0, abs=1e-12)
        assert row[row > 0].sum() == pytest.approx(0.5, abs=1e-12)
        assert row[row < 0].sum() == pytest.approx(-0.5, abs=1e-12)


def test_coverage_floor_boundary():
    n, m = 2, 25
    alpha = np.full((n, m), np.nan)
    vol = np.full((n, m), np.nan)
    rng = np.random.default_rng(11)
    # Row 0: 19 valid names -> no position. Row 1: 20 valid names -> a position.
    alpha[0, :19] = rng.normal(size=19)
    vol[0, :19] = rng.uniform(0.5, 2.0, 19)
    alpha[1, :20] = rng.normal(size=20)
    vol[1, :20] = rng.uniform(0.5, 2.0, 20)
    w, has = rank_vol_neutral_weights(alpha, vol=vol, direction=1.0, coverage_floor=20)
    assert not has[0]
    assert (w[0] == 0.0).all()  # zero weights, not NaN, when no position
    assert has[1]
    assert w[1].sum() == pytest.approx(0.0, abs=1e-12)


def test_returns_are_nan_on_rows_without_a_position():
    n, m = 2, 25
    alpha = np.full((n, m), np.nan)
    vol = np.full((n, m), np.nan)
    fwd = np.random.default_rng(12).normal(size=(n, m))
    alpha[0, :19] = 1.0
    vol[0, :19] = 1.0
    out = rank_vol_neutral_returns(alpha, fwd, None, vol=vol, direction=1.0, coverage_floor=20)[
        RANK_VOL_NEUTRAL_ARM
    ]
    assert np.isnan(out[0])


def test_direction_negates_weights():
    alpha, vol, _ = _panel(4, coverage_floor=2)
    w_pos, has_pos = rank_vol_neutral_weights(alpha, vol=vol, direction=1.0, coverage_floor=2)
    w_neg, has_neg = rank_vol_neutral_weights(alpha, vol=vol, direction=-1.0, coverage_floor=2)
    np.testing.assert_array_equal(has_pos, has_neg)
    np.testing.assert_allclose(w_neg, -w_pos, rtol=1e-12, atol=1e-15)


def test_nan_or_nonpositive_vol_excludes_a_name():
    alpha, vol, _ = _panel(5, n=1, m=8, coverage_floor=2)
    alpha[0] = np.arange(8, dtype=float)
    vol[0] = 1.0
    vol[0, 3] = np.nan
    vol[0, 5] = 0.0
    w, has = rank_vol_neutral_weights(alpha, vol=vol, direction=1.0, coverage_floor=2)
    assert has[0]
    assert w[0, 3] == 0.0
    assert w[0, 5] == 0.0
    # The excluded names take no weight; the rest still sums dollar-neutral.
    assert w[0].sum() == pytest.approx(0.0, abs=1e-12)


def test_nan_alpha_excludes_a_name():
    alpha, vol, _ = _panel(6, n=1, m=8, coverage_floor=2)
    alpha[0, 2] = np.nan
    w, has = rank_vol_neutral_weights(alpha, vol=vol, direction=1.0, coverage_floor=2)
    assert has[0]
    assert w[0, 2] == 0.0


def test_all_tied_alpha_carries_no_position():
    n, m = 1, 10
    alpha = np.full((n, m), 3.0)
    vol = np.random.default_rng(9).uniform(0.5, 2.0, (n, m))
    w, has = rank_vol_neutral_weights(alpha, vol=vol, direction=1.0, coverage_floor=2)
    assert not has[0]
    assert (w[0] == 0.0).all()


def test_fwd_ret_nan_for_a_weighted_name_contributes_zero():
    alpha, vol, fwd = _panel(7, coverage_floor=2)
    base = rank_vol_neutral_returns(alpha, fwd, None, vol=vol, direction=1.0, coverage_floor=2)[
        RANK_VOL_NEUTRAL_ARM
    ]
    fwd_nan = fwd.copy()
    fwd_nan[:, 0] = np.nan
    moved = rank_vol_neutral_returns(
        alpha, fwd_nan, None, vol=vol, direction=1.0, coverage_floor=2
    )[RANK_VOL_NEUTRAL_ARM]
    fwd_zero = fwd.copy()
    fwd_zero[:, 0] = 0.0
    zeroed = rank_vol_neutral_returns(
        alpha, fwd_zero, None, vol=vol, direction=1.0, coverage_floor=2
    )[RANK_VOL_NEUTRAL_ARM]
    np.testing.assert_allclose(moved, zeroed, equal_nan=True)
    assert not np.allclose(np.nan_to_num(base), np.nan_to_num(moved))


def test_plan_argument_is_ignored():
    rng = np.random.default_rng(13)
    n, m = 200, 5
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, m)), axis=0))
    alpha, vol, fwd = _panel(13, n=n, m=m, coverage_floor=2)
    plan = plan_covariance(closes, CFG, MV_COND)
    a = rank_vol_neutral_returns(alpha, fwd, None, vol=vol, direction=1.0, coverage_floor=2)
    b = rank_vol_neutral_returns(alpha, fwd, plan, vol=vol, direction=1.0, coverage_floor=2)
    np.testing.assert_array_equal(a[RANK_VOL_NEUTRAL_ARM], b[RANK_VOL_NEUTRAL_ARM])


def test_partial_binding_is_picklable():
    alpha, vol, fwd = _panel(14, coverage_floor=2)
    bound = functools.partial(rank_vol_neutral_returns, vol=vol, direction=1.0, coverage_floor=2)
    restored = pickle.loads(pickle.dumps(bound))
    want = bound(alpha, fwd, None)
    got = restored(alpha, fwd, None)
    np.testing.assert_array_equal(got[RANK_VOL_NEUTRAL_ARM], want[RANK_VOL_NEUTRAL_ARM])


def test_direction_validation():
    alpha, vol, fwd = _panel(15, coverage_floor=2)
    with pytest.raises(ValueError, match="direction"):
        rank_vol_neutral_returns(alpha, fwd, None, vol=vol, direction=0.5, coverage_floor=2)


def test_coverage_floor_validation():
    alpha, vol, fwd = _panel(16, coverage_floor=2)
    with pytest.raises(ValueError, match="coverage_floor"):
        rank_vol_neutral_returns(alpha, fwd, None, vol=vol, direction=1.0, coverage_floor=1)


# --- trailing_vol -----------------------------------------------------------------------------


def _slow_trailing_vol(returns, window_rows, min_finite):
    n, m = returns.shape
    out = np.full((n, m), np.nan)
    for t in range(n):
        lo = max(0, t - window_rows + 1)
        window = returns[lo : t + 1]
        for i in range(m):
            col = window[:, i]
            finite = col[np.isfinite(col)]
            if len(finite) < min_finite:
                continue
            sd = np.std(finite, ddof=1)
            if sd > 0:
                out[t, i] = sd
    return out


def test_trailing_vol_matches_slow_loop():
    rng = np.random.default_rng(20)
    n, m = 40, 4
    returns = rng.normal(0, 0.01, (n, m))
    returns[rng.random((n, m)) < 0.1] = np.nan
    got = trailing_vol(returns, window_rows=10, min_finite=3)
    want = _slow_trailing_vol(returns, window_rows=10, min_finite=3)
    np.testing.assert_allclose(got, want, rtol=1e-10, atol=1e-14, equal_nan=True)


def test_trailing_vol_nan_below_min_finite():
    returns = np.array([[1.0], [np.nan], [np.nan], [2.0]])
    got = trailing_vol(returns, window_rows=4, min_finite=3)
    assert np.isnan(got[:3]).all()


def test_trailing_vol_is_causal():
    rng = np.random.default_rng(21)
    n, m = 20, 3
    returns = rng.normal(0, 0.01, (n, m))
    base = trailing_vol(returns, window_rows=5, min_finite=2)
    changed = returns.copy()
    changed[15:] = rng.normal(1.0, 5.0, (n - 15, m))  # rewrite everything after row 14
    changed_vol = trailing_vol(changed, window_rows=5, min_finite=2)
    np.testing.assert_allclose(base[:15], changed_vol[:15], equal_nan=True)


@pytest.mark.slow
def test_rank_vol_neutral_returns_is_vectorized():
    """Order-of-magnitude guard against a per-row Python loop (about 1.7 s idle at full size).
    Not a benchmark: a wall-clock bound near the idle time fails whenever the box is loaded."""
    rng = np.random.default_rng(22)
    n, m = 127_400, 233
    alpha = rng.normal(size=(n, m)).astype(np.float32)
    alpha[1::2] = np.nan
    vol = rng.uniform(0.5, 3.0, (n, m)).astype(np.float32)
    fwd = rng.normal(0, 0.01, (n, m)).astype(np.float32)
    start = time.monotonic()
    rank_vol_neutral_returns(alpha, fwd, None, vol=vol, direction=1.0, coverage_floor=20)
    elapsed = time.monotonic() - start
    assert elapsed < 20.0, f"rank_vol_neutral_returns took {elapsed:.2f}s; is it looping per row?"
