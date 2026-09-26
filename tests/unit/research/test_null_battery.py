"""The E17 H0 battery (null_battery): its panels, and its power to catch a biased statistic."""

import dataclasses

import numpy as np

from src.intelligence.research.families.intraday_periodicity import same_slot_mean
from src.intelligence.research.null_battery import (
    MEMBER_WINDOWS,
    NullScenario,
    null_panel,
    scenarios,
    simulate,
)
from src.intelligence.research.portfolio import rank_vol_neutral_weights, trailing_vol
from src.intelligence.research.timing import timing_test
from src.intelligence.statistics.hac import hac_mean_test

SMALL = NullScenario("small", sessions=600, bars_per_session=8, names=40)


def _e16_series(w, r, has, bps, warmup):
    """E16 as built (retired): sum (w - wbar)(r - fbar), both causal expanding means."""
    n, m = w.shape
    s_n = n // bps
    w = np.where(has[:, None], w, 0.0).reshape(s_n, bps, m)
    fin = np.isfinite(r).reshape(s_n, bps, m)
    r = np.where(fin, np.nan_to_num(r).reshape(s_n, bps, m), 0.0)

    def prior(v):
        return np.concatenate([np.zeros((1, *v.shape[1:])), np.cumsum(v, axis=0)[:-1]])

    count = np.arange(s_n)[:, None, None]
    wbar = prior(w) / np.maximum(count, 1)
    rc = prior(fin.astype(float))
    with np.errstate(invalid="ignore", divide="ignore"):
        fbar = np.where(rc > 0, prior(r) / rc, 0.0)
    d = ((w - wbar) * np.where(fin, r - fbar, 0.0)).sum(axis=(1, 2))
    d[:warmup] = np.nan
    return d


def test_every_arm_is_scored():
    out = simulate(SMALL, 1)
    assert set(out) == {f"mean{w}" for w in MEMBER_WINDOWS} | {"book_equal"}
    assert all(np.isfinite(t) and 0 < p < 1 for t, p in out.values())


def test_late_name_is_missing_until_it_lists():
    sc = dataclasses.replace(SMALL, late_name=True)
    resid, target = null_panel(sc, 2)
    start = int(0.6 * sc.sessions) * sc.bars_per_session
    assert np.isnan(resid[:start, 0]).all() and np.isfinite(resid[start:, 0]).all()
    assert np.isnan(target[: start - 1, 0]).all()


def test_scenario_names_are_unique():
    names = [sc.name for sc in scenarios()]
    assert len(names) == len(set(names))


def test_battery_catches_the_retired_e16_bias():
    """The battery's panels must be able to fail a biased statistic: on late-listing nulls the
    retired E16 form scores an own-history member with a clearly negative mean t, while E17
    stays centred. Without this, a passing battery would mean nothing."""
    sc = dataclasses.replace(SMALL, sessions=1200, late_fraction=0.4)
    bps, w = sc.bars_per_session, 40
    e16, e17 = [], []
    for seed in range(20):
        resid, target = null_panel(sc, 100 + seed)
        vol = trailing_vol(resid, window_rows=20 * bps, min_finite=10 * bps)
        alpha = same_slot_mean(resid, bars_per_session=bps, coverage_floor=20, window_sessions=w)
        weights, has = rank_vol_neutral_weights(alpha, vol=vol, direction=1.0, coverage_floor=20)
        trade = np.ones(len(resid), dtype=bool)
        e16.append(hac_mean_test(_e16_series(weights, target, has, bps, 252)).t)
        e17.append(
            timing_test(
                weights,
                target,
                has,
                trade,
                bars_per_session=bps,
                warmup_sessions=252,
                memory_sessions=w,
            ).hac.t
        )
    assert np.mean(e16) < -1.0
    assert abs(np.mean(e17)) < 0.6  # measured: E16 -2.13, E17 -0.23 (sd about 1.2, n = 20)
