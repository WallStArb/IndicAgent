"""E16 tested series: book session P&L minus its causal static-tilt P&L."""

import numpy as np
import pytest

from src.intelligence.research.timing import timing_series, timing_test


def _slow(weights, fwd, has, trade, bps, warmup):
    n, m = weights.shape
    s_n = n // bps
    w = np.where(has[:, None], weights, 0.0)
    scored = [s for s in range(s_n) if trade[s * bps : (s + 1) * bps].any()]
    out = np.full(s_n, np.nan)
    for k, s in enumerate(scored):
        if k < max(warmup, 1):
            continue
        prior = scored[:k]
        total = 0.0
        for pos in range(bps):
            row = s * bps + pos
            if not trade[row]:
                continue
            tilt = np.mean([w[p * bps + pos] for p in prior], axis=0)
            for j in range(m):
                if not np.isfinite(fwd[row, j]):
                    continue
                past = [
                    fwd[p * bps + pos, j]
                    for p in prior
                    if trade[p * bps + pos] and np.isfinite(fwd[p * bps + pos, j])
                ]
                fbar = np.mean(past) if past else 0.0
                total += (w[row, j] - tilt[j]) * (fwd[row, j] - fbar)
        out[s] = total
    return out


@pytest.mark.parametrize("bps", [1, 4])
def test_timing_series_matches_slow_reference(bps):
    rng = np.random.default_rng(bps)
    s_n, m = 60, 7
    n = s_n * bps
    weights = rng.normal(size=(n, m))
    fwd = rng.normal(0, 0.01, (n, m))
    fwd[rng.random((n, m)) < 0.1] = np.nan
    has = rng.random(n) > 0.2
    trade = np.ones(n, dtype=bool)
    trade[: 5 * bps] = False
    trade[20 * bps + 1] = False
    got = timing_series(weights, fwd, has, trade, bars_per_session=bps, warmup_sessions=10)
    np.testing.assert_allclose(
        got, _slow(weights, fwd, has, trade, bps, 10), rtol=1e-12, atol=1e-15, equal_nan=True
    )


def test_constant_book_has_zero_timing_pnl():
    rng = np.random.default_rng(3)
    n, m, bps = 200, 5, 4
    weights = np.tile(rng.normal(size=(bps, m)), (n // bps, 1))  # same per-slot book every day
    fwd = rng.normal(0, 0.01, (n, m))
    got = timing_series(
        weights, fwd, np.ones(n, bool), np.ones(n, bool), bars_per_session=bps, warmup_sessions=5
    )
    np.testing.assert_allclose(got[5:], 0.0, atol=1e-15)


def test_tilt_is_causal():
    rng = np.random.default_rng(4)
    n, m, bps = 240, 6, 4
    weights = rng.normal(size=(n, m))
    fwd = rng.normal(0, 0.01, (n, m))
    ones = np.ones(n, bool)
    base = timing_series(weights, fwd, ones, ones, bars_per_session=bps, warmup_sessions=5)
    changed_w, changed_f = weights.copy(), fwd.copy()
    changed_w[31 * bps :] = rng.normal(size=changed_w[31 * bps :].shape)
    changed_f[31 * bps :] = rng.normal(size=changed_f[31 * bps :].shape)
    out = timing_series(changed_w, changed_f, ones, ones, bars_per_session=bps, warmup_sessions=5)
    np.testing.assert_array_equal(out[:31], base[:31])


def test_static_return_means_do_not_enter():
    """A persistent book on returns with large static means but no timing: the tested series
    carries no (w - wbar) * mean-return term, so its mean stays near zero."""
    rng = np.random.default_rng(6)
    s_n, m = 3000, 20
    means = rng.normal(0, 1.0, m)  # large static means
    fwd = means + rng.normal(0, 1, (s_n, m))
    ar = np.zeros((s_n, m))
    for t in range(1, s_n):
        ar[t] = 0.98 * ar[t - 1] + rng.normal(size=m)  # persistent, unrelated to returns
    ones = np.ones(s_n, bool)
    d = timing_series(ar, fwd, ones, ones, bars_per_session=1, warmup_sessions=252)
    x = d[np.isfinite(d)]
    assert abs(x.mean()) < 4 * x.std() / np.sqrt(len(x) / 50)


def test_warmup_sessions_are_not_tested():
    n, m = 40, 3
    got = timing_series(
        np.ones((n, m)),
        np.ones((n, m)),
        np.ones(n, bool),
        np.ones(n, bool),
        bars_per_session=1,
        warmup_sessions=12,
    )
    assert np.isnan(got[:12]).all() and np.isfinite(got[12:]).all()


def test_timing_test_record():
    rng = np.random.default_rng(5)
    n, m = 800, 10
    signal = rng.normal(size=(n, m))
    fwd = 0.1 * signal + rng.normal(0, 1, (n, m))  # the book times returns (t about 8)
    rec = timing_test(
        signal, fwd, np.ones(n, bool), np.ones(n, bool), bars_per_session=1, warmup_sessions=50
    )
    assert rec.hac.n == n - 50 and rec.hac.t > 3 and rec.hac.p < 0.01
    assert rec.annualized_sharpe > 0
