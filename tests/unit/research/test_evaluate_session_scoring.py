"""R2 (family 1 prereg section 4, D-14): session-aggregated scoring in evaluate(), observed and
null alike, plus the bootstrap standard error (D-09)."""

import dataclasses
import functools
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from src.intelligence.research import evaluate as ev
from src.intelligence.research.evaluate import (
    SESSIONS_PER_YEAR,
    aggregate_sessions,
    annualized_sharpe,
    evaluate,
    scored_sharpe,
    trade_mask,
)
from src.intelligence.research.portfolio import (
    FIXED_SIGN_ARM,
    fixed_sign_returns,
    plan_covariance,
)
from src.intelligence.statistics.panel_null import shift_panel

BPS = 4
CFG = HarnessConfig(
    warmup_sessions=20,
    calibration_refit_sessions=10,
    min_shift=10,
    trading_start="2000-01-01",
    sub_periods=(("2000-01-01", "2000-02-15"), ("2000-02-16", "2000-12-31")),
    bootstrap_reps=50,
)
KW = {"mv_condition_max": 1000.0, "ic_shrinkage_k": 100.0}


def _panel(seed, n_sessions=120, m=6, bps=BPS):
    rng = np.random.default_rng(seed)
    n = n_sessions * bps
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, (n, m)), axis=0))
    fwd = rng.normal(0, 0.003, (n, m))
    alpha = rng.normal(size=(n, m))
    start = np.datetime64("2000-01-03T14:30")
    step = np.timedelta64(60, "m") if bps > 1 else np.timedelta64(1, "D")
    dates = start + np.arange(n) * step
    if bps > 1:
        # Each session on its own calendar day: row k of session d at 14:30 + k hours.
        d = np.arange(n) // bps
        dates = (
            np.datetime64("2000-01-03T14:30")
            + d * np.timedelta64(1, "D")
            + (np.arange(n) % bps) * np.timedelta64(60, "m")
        )
    return alpha, fwd, closes, dates


def _fixed():
    return functools.partial(fixed_sign_returns, direction=1.0)


def _slow_sessions(r, trade, bps):
    s = len(r) // bps
    sums = np.full(s, np.nan)
    st = np.zeros(s, dtype=bool)
    for k in range(s):
        rows = range(k * bps, (k + 1) * bps)
        vals = [r[i] for i in rows if trade[i] and np.isfinite(r[i])]
        st[k] = any(trade[i] for i in rows)
        if vals:
            sums[k] = sum(vals)
    return sums, st


def test_aggregate_sessions_matches_slow_loop():
    rng = np.random.default_rng(0)
    r = rng.normal(size=12)
    r[[1, 8, 9, 10, 11]] = np.nan
    trade = np.ones(12, dtype=bool)
    trade[4:6] = False
    got = aggregate_sessions(r, trade, 4)
    want = _slow_sessions(r, trade, 4)
    np.testing.assert_allclose(got[0], want[0], equal_nan=True)
    np.testing.assert_array_equal(got[1], want[1])
    assert np.isnan(got[0][2])  # session with no finite traded row


def test_scored_sharpe_off_is_annualized_sharpe():
    rng = np.random.default_rng(1)
    r = rng.normal(size=40)
    trade = np.ones(40, dtype=bool)
    assert scored_sharpe(
        r, trade, periods_per_year=1008, bars_per_session=4, session_scoring=False
    ) == annualized_sharpe(r, trade, 1008)


def test_one_bar_panel_session_scoring_is_identical():
    alpha, fwd, closes, dates = _panel(2, n_sessions=300, bps=1)
    off = evaluate(alpha, fwd, closes, dates, CFG, construction=_fixed(), **KW)
    on = evaluate(alpha, fwd, closes, dates, CFG, construction=_fixed(), session_scoring=True, **KW)
    for f in dataclasses.fields(off):
        a, b = getattr(off, f.name), getattr(on, f.name)
        if isinstance(a, np.ndarray):
            np.testing.assert_array_equal(a, b, err_msg=f.name)
        else:
            assert a == b, f.name


def _intraday_run(**extra):
    alpha, fwd, closes, dates = _panel(3)
    res = evaluate(
        alpha,
        fwd,
        closes,
        dates,
        CFG,
        construction=_fixed(),
        bars_per_session=BPS,
        session_scoring=True,
        **KW,
        **extra,
    )
    return res, alpha, fwd, closes, dates


def test_intraday_observed_and_null_sharpes_are_per_session():
    res, alpha, fwd, closes, dates = _intraday_run()
    trade = trade_mask(dates, CFG)
    rcfg = ev.rows_config(CFG, BPS)
    plan = plan_covariance(closes, rcfg, 1000.0, ev.DAILY_EMBARGO)
    obs = fixed_sign_returns(alpha, fwd, plan, direction=1.0)[FIXED_SIGN_ARM]
    sums, st = _slow_sessions(obs, trade, BPS)
    assert res.sharpe_obs[0] == pytest.approx(annualized_sharpe(sums, st, SESSIONS_PER_YEAR))
    for k in (0, len(res.shifts) // 2, len(res.shifts) - 1):
        shifted = fixed_sign_returns(
            shift_panel(alpha, int(res.shifts[k])), fwd, plan, direction=1.0
        )[FIXED_SIGN_ARM]
        s2, st2 = _slow_sessions(shifted, trade, BPS)
        assert res.sharpe_null[k, 0] == pytest.approx(annualized_sharpe(s2, st2, SESSIONS_PER_YEAR))
    n_sessions = alpha.shape[0] // BPS
    assert res.observed_daily.shape == (1, n_sessions)
    assert res.null_median_daily.shape == (1, n_sessions)


def test_intraday_bootstrap_and_sub_periods_use_sessions():
    res, alpha, fwd, closes, dates = _intraday_run()
    trade = trade_mask(dates, CFG)
    _, st = aggregate_sessions(res.observed_daily[0].repeat(BPS), trade, BPS)
    excess = res.observed_daily[0] - res.null_median_daily[0]
    x = excess[st]
    ci = np.percentile(
        ev._bootstrap_sharpe_draws(
            x, CFG.bootstrap_mean_block, CFG.bootstrap_reps, CFG.seed, SESSIONS_PER_YEAR
        ),
        [2.5, 97.5],
    )
    np.testing.assert_allclose(res.excess_ci[0], ci)
    session_days = dates[::BPS].astype("datetime64[D]")
    for j, (a, b) in enumerate(CFG.sub_periods):
        m = (session_days >= np.datetime64(a)) & (session_days <= np.datetime64(b)) & st
        assert res.sub_period_excess[0, j] == pytest.approx(np.nanmean(excess[m]))


def test_excess_se_is_std_of_bootstrap_draws():
    rng = np.random.default_rng(5)
    x = rng.normal(0.001, 0.01, 300)
    draws = ev._bootstrap_sharpe_draws(x, 5, 200, 7, SESSIONS_PER_YEAR)
    res, *_ = _intraday_run()
    assert res.excess_se is not None and res.excess_se.shape == (1,)
    assert res.excess_se[0] > 0


def test_worker_pool_matches_serial_under_session_scoring():
    serial, *_ = _intraday_run()
    pooled, *_ = _intraday_run(workers=2, pool_factory=lambda w: ThreadPoolExecutor(w))
    np.testing.assert_array_equal(serial.sharpe_null, pooled.sharpe_null)
    np.testing.assert_array_equal(serial.null_median_daily, pooled.null_median_daily)
