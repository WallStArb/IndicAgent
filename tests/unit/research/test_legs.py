"""Session-legs transform and per-leg S1 (family 2 prereg sections 2, 4; B1)."""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.research import legs
from src.intelligence.research.factors import FactorSpec
from src.intelligence.research.panel import Panel, bar_returns
from src.intelligence.research.panel import select_symbols as panel_select_symbols


def _source(n_sessions: int = 3, bps: int = 4, m: int = 2, seed: int = 0) -> Panel:
    rng = np.random.default_rng(seed)
    n = n_sessions * bps
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, m)), axis=0))
    open_ = close * np.exp(rng.normal(0, 0.002, (n, m)))
    day = np.datetime64("2020-01-02T14:30")
    ts = np.array(
        [
            day + np.timedelta64(d, "D") + np.timedelta64(15 * b, "m")
            for d in range(n_sessions)
            for b in range(bps)
        ]
    )
    return Panel(
        tf="15m",
        symbols=tuple(f"s{j}" for j in range(m)),
        timestamps=ts,
        bars_per_session=bps,
        valid=np.ones(n, dtype=bool),
        open=open_,
        close=close,
        volume=np.full((n, m), 10.0),
    )


def test_legs_prices_and_bar_returns_match_the_prereg_table():
    src = _source()
    out = legs.session_legs(src, source_hash="abc")
    bps = src.bars_per_session
    assert out.bars_per_session == 3 and out.n_sessions == src.n_sessions
    r = bar_returns(out).reshape(out.n_sessions, 3, -1)
    for d in range(1, src.n_sessions):
        final_prev, open0 = src.close[d * bps - 1], src.open[d * bps]
        close0, final = src.close[d * bps], src.close[d * bps + bps - 1]
        np.testing.assert_allclose(r[d, 0], np.log(open0 / final_prev))
        np.testing.assert_allclose(r[d, 1], np.log(close0 / open0))
        np.testing.assert_allclose(r[d, 2], np.log(final / close0))
    assert np.isnan(r[0, 0]).all()  # no previous session
    assert out.manifest["source_snapshot_hash"] == "abc"
    assert (np.diff(out.timestamps) > np.timedelta64(0, "m")).all()


def test_target_is_bar1_open_to_final_close():
    src = _source()
    out = legs.session_legs(src)
    bps = src.bars_per_session
    t = legs.raw_target(out)
    for d in range(src.n_sessions):
        np.testing.assert_allclose(
            t[d], np.log(src.close[d * bps + bps - 1] / src.open[d * bps + 1])
        )


def test_half_day_uses_the_sessions_last_bar_with_any_close():
    src = _source()
    bps = src.bars_per_session
    src.close[bps + 2 :, :][: bps - 2] = np.nan  # session 1 ends after bar 1
    src.open[bps + 2 :, :][: bps - 2] = np.nan
    out = legs.session_legs(src)
    np.testing.assert_allclose(out.close[1 * 3 + 2], src.close[bps + 1])
    assert out.volume[1 * 3 + 2, 0] == 10.0  # bars 1 .. final (bar 1 only)


def test_a_name_missing_the_final_bar_gets_nan_not_an_earlier_close():
    src = _source()
    bps = src.bars_per_session
    src.close[bps + bps - 1, 0] = np.nan  # name 0 misses session 1's final bar
    out = legs.session_legs(src)
    assert np.isnan(out.close[3 + 2, 0])
    assert np.isfinite(out.close[3 + 2, 1])


def test_a_missing_price_removes_only_the_legs_that_read_it():
    src = _source()
    bps = src.bars_per_session
    src.close[bps - 1, 0] = np.nan  # name 0 misses session 0's final bar
    src.open[2 * bps, 1] = np.nan  # name 1 misses session 2's bar 0 open
    r = bar_returns(legs.session_legs(src)).reshape(src.n_sessions, 3, -1)
    assert np.isnan(r[1, 0, 0])  # overnight into session 1 needs that close
    np.testing.assert_allclose(r[1, 1, 0], np.log(src.close[bps, 0] / src.open[bps, 0]))
    assert np.isnan(r[2, 0, 1]) and np.isnan(r[2, 1, 1])  # both read open0
    np.testing.assert_allclose(
        r[2, 2, 1], np.log(src.close[2 * bps + bps - 1, 1] / src.close[2 * bps, 1])
    )
    # the first session's first-bar leg exists without a previous session; name 0's rest leg
    # in session 0 is NaN because its final close was removed above
    assert np.isfinite(r[0, 1]).all() and np.isnan(r[0, 2, 0]) and np.isfinite(r[0, 2, 1])


def test_missing_mid_session_bar_keeps_the_legs():
    src = _source()
    bps = src.bars_per_session
    src.close[bps + 2, 0] = src.open[bps + 2, 0] = np.nan
    out = legs.session_legs(src)
    assert np.isfinite(out.close[3:6, 0]).all()


def test_select_symbols_keeps_panel_order_and_ignores_absent_names():
    src = _source(m=3)
    sub = panel_select_symbols(src, ["s2", "s0", "zz"])
    assert sub.symbols == ("s0", "s2")
    np.testing.assert_array_equal(sub.close, src.close[:, [0, 2]])
    with pytest.raises(ValueError):
        panel_select_symbols(src, ["zz"])


def test_intraday_source_required():
    src = _source(bps=1)
    with pytest.raises(ValueError, match="intraday"):
        legs.session_legs(src)


def _spec() -> FactorSpec:
    return FactorSpec(
        window_sessions=30,
        refit_sessions=5,
        min_finite_sessions=20,
        n_components=1,
        min_group_size=2,
    )


def test_leg_residuals_equal_s1_on_each_leg_alone():
    from src.intelligence.research.factors import residual_returns

    src = _source(n_sessions=60, m=8, seed=3)
    out = legs.session_legs(src)
    spec = _spec()
    res = legs.leg_residuals(out, spec)
    r = bar_returns(out).reshape(out.n_sessions, 3, -1)
    for k in range(3):
        alone = residual_returns(r[:, k], bars_per_session=1, spec=spec).residual
        np.testing.assert_array_equal(res[k::3], alone)


def test_target_residual_sits_on_row_1_only_and_is_causal():
    src = _source(n_sessions=60, m=8, seed=4)
    out = legs.session_legs(src)
    spec = _spec()
    tgt = legs.target_residuals(out, spec)
    assert np.isnan(tgt[0::3]).all() and np.isnan(tgt[2::3]).all()
    assert np.isfinite(tgt[1::3][-5:]).any()
    # Changing only the last session's prices must not move any earlier session's target.
    src2 = _source(n_sessions=60, m=8, seed=4)
    bps = src2.bars_per_session
    src2.close[-bps:] *= 1.5
    src2.open[-bps:] *= 1.5
    tgt2 = legs.target_residuals(legs.session_legs(src2), spec)
    np.testing.assert_array_equal(tgt[:-3], tgt2[:-3])


def test_last_source_row_read():
    rows = np.array([0, 1, 2, 3, 4, 5])
    np.testing.assert_array_equal(legs.last_source_row_read(rows, 26), [0, 0, 25, 26, 26, 51])
