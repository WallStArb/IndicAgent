"""Family 2 members (prereg section 3): statistics, signs, placement, causality, memory."""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.research.families import overnight_intraday as f2
from src.intelligence.research.families.common import centred_rank, declared_memory_rows
from src.intelligence.research.guards import causality_probe_array, memory_check_array

S, M, FLOOR = 90, 25, 20


def _resid(seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 1, (S * 3, M))


def _expected(stat: np.ndarray, resid: np.ndarray) -> np.ndarray:
    alpha = np.full(resid.shape, np.nan)
    alpha[1::3] = stat
    alpha[~np.isfinite(resid)] = np.nan
    return centred_rank(alpha, coverage_floor=FLOOR)


def test_intraday_persistence_is_positive_prior_mean_of_rows_1_and_2():
    r = _resid()
    legs = r.reshape(S, 3, M)
    got = f2.intraday_persistence(r, bars_per_session=3, coverage_floor=FLOOR, window_sessions=5)
    stat = np.full((S, M), np.nan)
    for d in range(5, S):
        stat[d] = (legs[d - 5 : d, 1] + legs[d - 5 : d, 2]).mean(axis=0)
    # with all values finite, sessions 3 and 4 already have >= half the window
    for d in (3, 4):
        stat[d] = (legs[:d, 1] + legs[:d, 2]).mean(axis=0)
    np.testing.assert_allclose(got, _expected(stat, r))


def test_overnight_to_intraday_is_negative_prior_mean_of_row_0():
    r = _resid(1)
    legs = r.reshape(S, 3, M)
    got = f2.overnight_to_intraday(r, bars_per_session=3, coverage_floor=FLOOR, window_sessions=4)
    d = 50
    np.testing.assert_allclose(got[3 * d + 1], _expected_row(-legs[d - 4 : d, 0].mean(axis=0)))


def _expected_row(stat_row: np.ndarray) -> np.ndarray:
    return centred_rank(stat_row[None, :], coverage_floor=FLOOR)[0]


def test_gap_fade_uses_the_same_sessions_row_0_with_negative_sign():
    r = _resid(2)
    got = f2.gap_fade(r, bars_per_session=3, coverage_floor=FLOOR)
    d = 40
    np.testing.assert_allclose(got[3 * d + 1], _expected_row(-r[3 * d]))
    assert np.isnan(got[0::3]).all() and np.isnan(got[2::3]).all()


def test_gap_fade_z_scales_by_prior_sample_sd():
    r = _resid(3)
    got = f2.gap_fade_z(r, bars_per_session=3, coverage_floor=FLOOR, window_sessions=10)
    d = 60
    sd = r[3 * (d - 10) : 3 * d : 3].std(axis=0, ddof=1)
    np.testing.assert_allclose(got[3 * d + 1], _expected_row(-r[3 * d] / sd))


def test_alpha_needs_a_finite_row_1_residual():
    r = _resid(4)
    r[3 * 50 + 1, 0] = np.nan
    got = f2.gap_fade(r, bars_per_session=3, coverage_floor=FLOOR)
    assert np.isnan(got[3 * 50 + 1, 0])


def test_members_reject_a_non_legs_panel():
    with pytest.raises(ValueError, match="legs panel"):
        f2.gap_fade(np.zeros((52, 3)), bars_per_session=26, coverage_floor=2)


# Causality and the prereg's declared slot history (window + 1 for row-0 readers).
CASES = [
    (f2.intraday_persistence, {"window_sessions": 20}, 20),
    (f2.overnight_to_intraday, {"window_sessions": 20}, 21),
    (f2.gap_fade, {}, 1),
    (f2.gap_fade_z, {"window_sessions": 20}, 21),
]


@pytest.mark.parametrize(("fn", "params", "history"), CASES)
def test_causal_and_within_declared_memory(fn, params, history):
    import functools

    member = functools.partial(fn, bars_per_session=3, coverage_floor=FLOOR, **params)
    r = _resid(5)
    rows = np.array([3 * 40 + 1, 3 * 70 + 1, 3 * 70])
    causality_probe_array(member, r, rows, seed=1)
    declared = history * 3
    reach = memory_check_array(member, r, rows[rows < len(r) - declared - 1], declared=declared)
    assert reach <= declared


def test_declared_memory_formula_at_three_rows():
    assert declared_memory_rows(21, 3) == (21 + 252 + 21) * 3
