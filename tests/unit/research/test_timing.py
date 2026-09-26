"""E17 tested series: book session P&L against returns net of the memory-lagged cell mean."""

import numpy as np
import pytest

from src.intelligence.research.timing import MIN_HISTORY_SESSIONS, timing_series, timing_test


def _slow(weights, fwd, has, trade, bps, warmup, memory, floor):
    """Literal reading of the E17 formula, one cell at a time."""
    n, m = weights.shape
    s_n = n // bps
    w = np.where(has[:, None], weights, 0.0)
    scored = [s for s in range(s_n) if trade[s * bps : (s + 1) * bps].any()]
    out = np.full(s_n, np.nan)
    for k, s in enumerate(scored):
        old = [p for p in scored if p < s - memory]
        if k < max(warmup, 1) or len(old) < floor:
            continue
        total = 0.0
        for pos in range(bps):
            row = s * bps + pos
            if not trade[row]:
                continue
            for j in range(m):
                if not np.isfinite(fwd[row, j]):
                    continue
                past = [
                    fwd[p * bps + pos, j]
                    for p in old
                    if trade[p * bps + pos] and np.isfinite(fwd[p * bps + pos, j])
                ]
                if len(past) < floor:
                    continue
                total += w[row, j] * (fwd[row, j] - np.mean(past))
        out[s] = total
    return out


@pytest.mark.parametrize("bps", [1, 4])
def test_timing_series_matches_slow_reference(bps):
    rng = np.random.default_rng(bps)
    s_n, m = 80, 7
    n = s_n * bps
    weights = rng.normal(size=(n, m))
    fwd = rng.normal(0, 0.01, (n, m))
    fwd[rng.random((n, m)) < 0.1] = np.nan
    fwd[: 40 * bps, 0] = np.nan  # a name that lists late
    has = rng.random(n) > 0.2
    trade = np.ones(n, dtype=bool)
    trade[: 5 * bps] = False
    trade[20 * bps + 1] = False
    trade[30 * bps : 31 * bps] = False  # an unscored session
    kw = dict(bars_per_session=bps, warmup_sessions=10, memory_sessions=7, min_history_sessions=12)
    got = timing_series(weights, fwd, has, trade, **kw)
    want = _slow(weights, fwd, has, trade, bps, 10, 7, 12)
    assert np.isfinite(want).sum() > 30
    np.testing.assert_allclose(got, want, rtol=1e-12, atol=1e-15, equal_nan=True)


def test_series_is_causal():
    rng = np.random.default_rng(4)
    n, m, bps = 240, 6, 4
    weights = rng.normal(size=(n, m))
    fwd = rng.normal(0, 0.01, (n, m))
    ones = np.ones(n, bool)
    kw = dict(bars_per_session=bps, warmup_sessions=5, memory_sessions=3, min_history_sessions=4)
    base = timing_series(weights, fwd, ones, ones, **kw)
    changed_w, changed_f = weights.copy(), fwd.copy()
    changed_w[31 * bps :] = rng.normal(size=changed_w[31 * bps :].shape)
    changed_f[31 * bps :] = rng.normal(size=changed_f[31 * bps :].shape)
    out = timing_series(changed_w, changed_f, ones, ones, **kw)
    np.testing.assert_array_equal(out[:31], base[:31])


def test_cell_mean_ignores_the_signals_memory():
    """Returns inside the last L sessions never reach fbar_L: changing them moves only the
    sessions where they are scored, not the mean that session s subtracts."""
    rng = np.random.default_rng(8)
    s_n, m, memory = 200, 5, 10
    weights = rng.normal(size=(s_n, m))
    fwd = rng.normal(size=(s_n, m))
    ones = np.ones(s_n, bool)
    kw = dict(
        bars_per_session=1, warmup_sessions=20, memory_sessions=memory, min_history_sessions=20
    )
    s = 150
    base = timing_series(weights, fwd, ones, ones, **kw)[s]
    changed = fwd.copy()
    changed[s - memory : s] += 5.0  # the window a memory-10 signal at s reads
    assert timing_series(weights, changed, ones, ones, **kw)[s] == pytest.approx(base, abs=1e-12)


def test_static_cell_means_do_not_enter_even_for_late_names():
    """A book whose weights load on large static cell means, with a third of the names listing
    late: fbar_L removes each mean, and the history floor keeps a late name out until its
    fbar_L is defined, so the series has zero mean."""
    rng = np.random.default_rng(6)
    s_n, m = 3000, 30
    means = rng.normal(0, 1.0, m)
    fwd = means + rng.normal(0, 1, (s_n, m))
    late = rng.random(m) < 1 / 3
    start = rng.integers(300, 2000, m)
    for j in np.flatnonzero(late):
        fwd[: start[j], j] = np.nan
    weights = np.sign(means) + 0.5 * rng.normal(size=(s_n, m))  # a static tilt on the means
    ones = np.ones(s_n, bool)
    d = timing_series(
        weights, fwd, ones, ones, bars_per_session=1, warmup_sessions=252, memory_sessions=40
    )
    x = d[np.isfinite(d)]
    assert abs(x.mean()) < 4 * x.std() / np.sqrt(len(x))


def test_untested_sessions():
    n, m = 200, 3
    got = timing_series(
        np.ones((n, m)),
        np.ones((n, m)),
        np.ones(n, bool),
        np.ones(n, bool),
        bars_per_session=1,
        warmup_sessions=12,
        memory_sessions=5,
        min_history_sessions=30,
    )
    # Session s needs 12 scored sessions before it and 30 below s - 5 (s - 5 of them): s >= 35.
    assert np.isnan(got[:35]).all() and np.isfinite(got[35:]).all()


@pytest.mark.parametrize("memory, floor", [(0, 60), (5, 0)])
def test_nonpositive_memory_or_floor_is_refused(memory, floor):
    one = np.ones((10, 2))
    with pytest.raises(ValueError, match="must be positive"):
        timing_series(
            one,
            one,
            np.ones(10, bool),
            np.ones(10, bool),
            bars_per_session=1,
            warmup_sessions=1,
            memory_sessions=memory,
            min_history_sessions=floor,
        )


def test_timing_test_record():
    rng = np.random.default_rng(5)
    n, m = 800, 10
    signal = rng.normal(size=(n, m))
    fwd = 0.1 * signal + rng.normal(0, 1, (n, m))  # the book times returns (t about 8)
    rec = timing_test(
        signal,
        fwd,
        np.ones(n, bool),
        np.ones(n, bool),
        bars_per_session=1,
        warmup_sessions=50,
        memory_sessions=3,
    )
    # Tested from session 63: 50 warmup, and sessions 0 .. s - 4 number at least 60.
    assert rec.hac.n == n - 63 and rec.hac.t > 3 and rec.hac.p < 0.01
    assert rec.annualized_sharpe > 0
    assert (rec.memory_sessions, rec.min_history_sessions) == (3, MIN_HISTORY_SESSIONS)
