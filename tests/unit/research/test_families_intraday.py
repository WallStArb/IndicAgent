"""Family 1 members P1-P4 (prereg section 3, D-15): slot sums, placement, half-window rule,
centred rank with the coverage floor, declared memory, causality and synthetic S3 guards."""

import functools

import numpy as np
import pytest

from src.intelligence.research.factors import FactorSpec
from src.intelligence.research.families.common import (
    centred_rank,
    declared_memory_rows,
    member_on_panel,
)
from src.intelligence.research.families.intraday_periodicity import (
    place_slot_alpha,
    same_slot_mean,
    slot_returns,
)
from src.intelligence.research.guards import integrity, run_guards
from src.intelligence.research.panel import Panel
from src.intelligence.research.signals import SignalSource

BPS = 6
WINDOWS = (1, 5, 20, 40)


def test_slot_returns_sums_bar_pairs():
    rng = np.random.default_rng(0)
    r = rng.normal(size=(2 * BPS, 2))
    r[3, 1] = np.nan
    s = slot_returns(r, bars_per_session=BPS)
    assert s.shape == (2, 3, 2)
    for d in range(2):
        for j in range(3):
            want = r[d * BPS + 2 * j] + r[d * BPS + 2 * j + 1]
            np.testing.assert_array_equal(s[d, j], want)
    assert np.isnan(s[0, 1, 1]) and np.isfinite(s[0, 1, 0])


def test_slot_returns_requires_even_bars():
    with pytest.raises(ValueError):
        slot_returns(np.zeros((5, 1)), bars_per_session=5)


def test_place_slot_alpha_rows():
    s, j_n, m = 3, 3, 1
    slot_alpha = np.arange((s + 1) * j_n * m, dtype=float).reshape(s + 1, j_n, m)
    out = place_slot_alpha(slot_alpha, bars_per_session=BPS, n_rows=s * BPS)
    expected = np.full((s * BPS, m), np.nan)
    for d in range(s + 1):
        for j in range(j_n):
            row = d * BPS + 2 * j - 1
            if 0 <= row < s * BPS:
                expected[row] = slot_alpha[d, j]
    np.testing.assert_array_equal(out, expected)
    assert np.isfinite(out[-1, 0])  # slot 0 of the session after the panel lands on its last row


def test_window_one_places_the_previous_sessions_slot():
    """Two names, so the centred rank is -0.5 / +0.5 by which name's lagged slot is larger."""
    rng = np.random.default_rng(1)
    n = 4 * BPS
    r = rng.normal(size=(n, 2))
    alpha = same_slot_mean(r, bars_per_session=BPS, coverage_floor=2, window_sessions=1)
    slots = slot_returns(r, bars_per_session=BPS)
    for d in range(1, 4):
        for j in range(3):
            row = d * BPS + 2 * j - 1
            want = np.where(slots[d - 1, j, 0] > slots[d - 1, j, 1], [0.5, -0.5], [-0.5, 0.5])
            np.testing.assert_array_equal(alpha[row], want)
    placed = {d * BPS + 2 * j - 1 for d in range(1, 5) for j in range(3)}
    other = [t for t in range(n) if t not in placed]
    assert np.isnan(alpha[other]).all()


@pytest.mark.parametrize(
    "window,finite,expect",
    [(5, 2, False), (5, 3, True), (40, 19, False), (40, 20, True), (1, 1, True)],
)
def test_half_window_rule(window, finite, expect):
    sessions = window + 1
    n = sessions * BPS
    r = np.full((n, 2), np.nan)
    rng = np.random.default_rng(2)
    # Slot 1 (bars 2, 3) finite on the last `finite` sessions before session `window`.
    for d in range(window - finite, window):
        r[d * BPS + 2 : d * BPS + 4] = rng.normal(size=(2, 2))
    r[window * BPS + 1] = 0.0  # placement row of slot 1 of the last session must be finite
    alpha = same_slot_mean(r, bars_per_session=BPS, coverage_floor=2, window_sessions=window)
    assert np.isfinite(alpha[window * BPS + 1]).all() == expect


def test_mean_uses_only_finite_days():
    window = 5
    n = (window + 1) * BPS
    r = np.full((n, 3), np.nan)
    rng = np.random.default_rng(3)
    vals = rng.normal(size=(3, 3))
    for k, d in enumerate((1, 2, 4)):
        r[d * BPS + 2] = vals[k]
        r[d * BPS + 3] = 0.0
    r[window * BPS + 1] = 0.0
    alpha = same_slot_mean(r, bars_per_session=BPS, coverage_floor=2, window_sessions=window)
    means = vals.mean(axis=0)
    np.testing.assert_array_equal(
        alpha[window * BPS + 1], centred_rank(means[None], coverage_floor=2)[0]
    )


@pytest.mark.parametrize("window", WINDOWS)
def test_no_lookahead(window):
    rng = np.random.default_rng(4)
    sessions = window + 6
    n = sessions * BPS
    r = rng.normal(size=(n, 5))
    base = same_slot_mean(r, bars_per_session=BPS, coverage_floor=2, window_sessions=window)
    for _ in range(10):
        d = int(rng.integers(window, sessions))
        j = int(rng.integers(0, 3))
        row = d * BPS + 2 * j - 1
        if row < 0:
            continue
        changed = r.copy()
        changed[row + 1 :] = rng.normal(5.0, 3.0, changed[row + 1 :].shape)
        out = same_slot_mean(
            changed, bars_per_session=BPS, coverage_floor=2, window_sessions=window
        )
        np.testing.assert_array_equal(out[: row + 1], base[: row + 1])


def test_nan_placement_residual_gives_no_position():
    rng = np.random.default_rng(5)
    r = rng.normal(size=(4 * BPS, 3))
    row = 2 * BPS + 1
    r[row, 0] = np.nan
    alpha = same_slot_mean(r, bars_per_session=BPS, coverage_floor=2, window_sessions=1)
    assert np.isnan(alpha[row, 0]) and np.isfinite(alpha[row, 1:]).all()


def test_centred_rank_ties_and_floor():
    got = centred_rank(np.array([[3.0, 1.0, 2.0, 2.0, 5.0]]), coverage_floor=5)
    # 0-based average ranks: 1 -> 0, 2 -> 1.5, 2 -> 1.5, 3 -> 3, 5 -> 4; divided by n - 1 = 4.
    np.testing.assert_allclose(got[0], np.array([3.0, 0.0, 1.5, 1.5, 4.0]) / 4 - 0.5)
    row = np.full((1, 25), np.nan)
    row[0, :19] = np.arange(19)
    assert np.isnan(centred_rank(row, coverage_floor=20)).all()
    row[0, 19] = 19.0
    assert np.isfinite(centred_rank(row, coverage_floor=20)[0, :20]).all()


def test_declared_memory_rows_match_prereg():
    assert [declared_memory_rows(w, 26) for w in WINDOWS] == [7124, 7228, 7618, 8138]


@pytest.mark.parametrize("window", WINDOWS)
def test_measured_reach_within_window(window):
    rng = np.random.default_rng(6)
    sessions = window + 8
    n = sessions * BPS
    r = rng.normal(size=(n, 6))
    base = same_slot_mean(r, bars_per_session=BPS, coverage_floor=2, window_sessions=window)
    for t in rng.integers(0, 3 * BPS, 5):
        shocked = r.copy()
        shocked[t] += 10.0
        out = same_slot_mean(
            shocked, bars_per_session=BPS, coverage_floor=2, window_sessions=window
        )
        moved = np.flatnonzero(~((out == base) | (np.isnan(out) & np.isnan(base))).all(axis=1))
        if moved.size:
            assert moved[0] >= t
            assert moved[-1] - t <= window * BPS


SMALL = FactorSpec(
    window_sessions=20, refit_sessions=5, n_components=2, min_finite_sessions=10, min_group_size=5
)


def _synthetic_panel(seed=7, sessions=100, m=24, bps=26):
    rng = np.random.default_rng(seed)
    n = sessions * bps
    groups = np.arange(m) % 5
    market = rng.normal(0, 0.002, n)
    sector = rng.normal(0, 0.0015, (n, 5))[:, groups]
    idio = rng.normal(0, 0.001, (n, m))
    r = market[:, None] * rng.uniform(0.5, 1.5, m) + sector + idio
    close = 100 * np.exp(np.cumsum(r, axis=0))
    opens = close * np.exp(-r)
    missing = rng.random((n, m)) < 0.05
    close[missing] = np.nan
    opens[missing] = np.nan
    days = np.datetime64("2012-01-03T14:30") + np.repeat(np.arange(sessions), bps) * np.timedelta64(
        1, "D"
    )
    ts = days + np.tile(np.arange(bps), sessions) * np.timedelta64(15, "m")
    return Panel(
        tf="15m",
        symbols=tuple(f"S{i}" for i in range(m)),
        timestamps=ts,
        bars_per_session=bps,
        valid=np.ones(n, dtype=bool),
        open=opens,
        close=close,
        volume=np.where(missing, np.nan, 1e5),
    )


def _source(window):
    compute = functools.partial(
        member_on_panel,
        member=same_slot_mean,
        factor_spec=SMALL,
        coverage_floor=20,
        params={"window_sessions": window},
    )
    return SignalSource(
        compute=compute,
        memory=declared_memory_rows(window, 26, SMALL),
        direction=1.0,
        n_tested=1,
        horizon=2,
    )


def test_integrity_on_synthetic_panel():
    panel = _synthetic_panel()
    alpha = _source(5).compute(panel)
    report = integrity(panel, alpha)
    assert np.isfinite(alpha).any()
    assert report.coverage.shape == (len(panel.timestamps),)


@pytest.mark.slow
@pytest.mark.parametrize("window", WINDOWS)
def test_synthetic_guards_pass(window):
    panel = _synthetic_panel()
    report = run_guards(_source(window), panel, seed=11, n_random=1, max_rows=5)
    assert report.memory_reach <= _source(window).memory
