from __future__ import annotations

import numpy as np

from src.intelligence.measure.ic import observation_rows, pooled_rank_ic
from src.intelligence.measure.monitoring import member_ic_over_time
from src.intelligence.measure.targets import stack_targets
from tests.unit.measure.conftest import make_panel


def _member(stack, flip_at):
    rng = np.random.default_rng(21)
    target = np.where(np.isfinite(stack.targets), stack.targets, 0.0)
    sign = np.where(stack.session < flip_at, 1.0, -1.0)[:, None]
    return sign * target + rng.normal(0, 0.005, target.shape)


def test_windows_match_pooled_ic_on_their_rows(symbols, params):
    stack = stack_targets([make_panel(symbols, 40, 1, seed=8)], 1, "2027-01-01")
    feat = _member(stack, 20)
    series = member_ic_over_time(feat, "m", stack, params)
    assert series.ic.shape == (4,) and series.n_sessions.tolist() == [10] * 4
    assert series.partial_tail_sessions == 0
    for w in range(4):
        rows = np.arange(w * 10, (w + 1) * 10)
        X, y = observation_rows(feat[rows][:, :, None], stack.targets[rows])
        assert series.ic[w] == pooled_rank_ic(X, y, stride=1, params=params).ic[0]
    assert series.window_start[1] == stack.timestamps[10]
    finite = series.ic
    assert series.mean_ic == finite.mean()
    assert np.isfinite(series.ic_sharpe) and np.isfinite(series.ic_sharpe_hac)


def test_sign_flip_shows_in_windows(symbols, params):
    stack = stack_targets([make_panel(symbols, 40, 1, seed=8)], 1, "2027-01-01")
    series = member_ic_over_time(_member(stack, 20), "m", stack, params)
    assert (series.ic[:2] > 0.5).all() and (series.ic[2:] < -0.5).all()


def test_trailing_partial_window_is_reported_not_merged(symbols, params):
    stack = stack_targets([make_panel(symbols, 45, 1, seed=8)], 1, "2027-01-01")
    series = member_ic_over_time(_member(stack, 99), "m", stack, params)
    assert series.n_sessions.tolist() == [10, 10, 10, 10, 5]
    assert series.partial_tail_sessions == 5
