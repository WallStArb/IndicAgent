from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from scipy.stats import spearmanr

from src.intelligence.measure.ic import align_features, observation_rows, pooled_rank_ic
from src.intelligence.measure.targets import stack_targets
from tests.unit.measure.conftest import make_panel


def test_observation_rows_order():
    feats = np.arange(3 * 2 * 1, dtype=float).reshape(3, 2, 1)  # [t, j, k]
    targets = np.array([[10.0, 11.0], [20.0, 21.0], [30.0, 31.0]])
    X, y = observation_rows(feats, targets)
    assert y.tolist() == [10.0, 11.0, 20.0, 21.0, 30.0, 31.0]  # r = t * m + j
    assert X[:, 0].tolist() == [0, 1, 2, 3, 4, 5]
    mask = np.array([[True, False], [True, True], [False, True]])
    Xm, ym = observation_rows(feats, targets, mask)
    assert ym.tolist() == [10.0, 20.0, 21.0, 31.0]
    assert Xm[:, 0].tolist() == [0, 2, 3, 5]


def test_matches_spearmanr_at_stride_one(params):
    rng = np.random.default_rng(1)
    X = rng.normal(size=(400, 3))
    y = 0.3 * X[:, 0] + rng.normal(size=400)
    cell = pooled_rank_ic(X, y, stride=1, params=params)
    for j in range(3):
        assert cell.ic[j] == pytest.approx(spearmanr(X[:, j], y)[0], abs=1e-12)
    assert cell.reliable.all() and cell.n_independent.tolist() == [400] * 3
    assert (cell.ci_lower <= cell.ci_upper).all()


def test_stride_then_mask_order(params):
    rng = np.random.default_rng(2)
    X = rng.normal(size=(60, 2))
    y = rng.normal(size=60)
    y[[2, 10]] = np.nan
    cell = pooled_rank_ic(X, y, stride=2, params=dataclasses.replace(params, min_obs=5))
    rows = np.arange(0, 60, 2)
    rows = rows[np.isfinite(y[rows])]  # stride first, then the mask (ic_engine's order)
    assert cell.n_independent.tolist() == [len(rows)] * 2
    assert cell.ic[0] == pytest.approx(spearmanr(X[rows, 0], y[rows])[0], abs=1e-12)
    wrong = np.flatnonzero(np.isfinite(y))[::2]  # mask first would pick different rows
    assert not np.array_equal(rows, wrong)


def test_degenerate_feature_is_nan_and_counted(params):
    rng = np.random.default_rng(3)
    X = np.column_stack([rng.normal(size=100), np.full(100, 4.0)])
    y = rng.normal(size=100)
    cell = pooled_rank_ic(X, y, stride=1, params=params)
    assert np.isnan(cell.ic[1]) and not cell.reliable[1]
    assert np.isfinite(cell.ic[0]) and cell.n_degenerate == 1


def test_below_min_obs_is_unreliable(params):
    rng = np.random.default_rng(4)
    cell = pooled_rank_ic(rng.normal(size=(20, 2)), rng.normal(size=20), stride=1, params=params)
    assert np.isnan(cell.ic).all() and not cell.reliable.any()


def test_bootstrap_ci_is_deterministic(params):
    rng = np.random.default_rng(5)
    X = rng.normal(size=(200, 2))
    y = X[:, 0] + rng.normal(size=200)
    a = pooled_rank_ic(X, y, stride=1, params=params)
    b = pooled_rank_ic(X, y, stride=1, params=params)
    assert np.array_equal(a.ci_lower, b.ci_lower) and np.array_equal(a.ci_upper, b.ci_upper)
    c = pooled_rank_ic(X, y, stride=1, params=dataclasses.replace(params, rng_seed=99))
    assert not np.array_equal(a.ci_lower, c.ci_lower)


def test_align_features_scatters_and_counts(symbols):
    panel = make_panel(symbols[:3], 5, 1)
    stack = stack_targets([panel], 1, "2027-01-01")
    ts = np.array([panel.timestamps[1], panel.timestamps[4], np.datetime64("1999-01-01")])
    syms = np.array([symbols[2], symbols[0], symbols[0]])
    vals = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    grid, unmatched = align_features(stack, ts, syms, vals)
    assert unmatched == 1
    assert grid[1, 2].tolist() == [1.0, 2.0] and grid[4, 0].tolist() == [3.0, 4.0]
    assert np.isnan(grid[0]).all()
    with pytest.raises(ValueError, match="duplicate"):
        align_features(stack, ts[[0, 0]], syms[[0, 0]], vals[:2])
    other, missing = align_features(stack, ts[:1], np.array(["ZZZ"]), vals[:1])
    assert missing == 1 and np.isnan(other).all()
