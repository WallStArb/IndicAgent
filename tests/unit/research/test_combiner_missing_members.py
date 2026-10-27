"""The present-member combining rule (design 4.1, plan 187-09 Task 1)."""

import importlib.util
import pathlib
import sys
import warnings

import numpy as np
import pytest

from src.intelligence.research.combiner import EqualWeight, RidgeSpec, walk_forward_ridge

_FROZEN = pathlib.Path(__file__).with_name("_combiner_before_187_09.py")


def _frozen_ridge():
    """walk_forward_ridge as it was before plan 187-09 (a frozen copy of the module)."""
    if "combiner_before_187_09" in sys.modules:
        return sys.modules["combiner_before_187_09"]
    spec = importlib.util.spec_from_file_location("combiner_before_187_09", _FROZEN)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


def _old_equal_weight(stack, signs):
    """EqualWeight.combine as it was before plan 187-09."""
    x = stack.astype(np.float64)
    complete = np.isfinite(x).all(axis=2, keepdims=True)
    x = np.where(complete, x, np.nan)
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        sd = np.nanstd(x, axis=1, keepdims=True)
        z = (x - np.nanmean(x, axis=1, keepdims=True)) / np.where(sd > 0, sd, np.nan)
    return (z * np.asarray(signs)).mean(axis=2)


def _stack(seed=0, n=400, m=30, k=3, nan_frac=0.15):
    rng = np.random.default_rng(seed)
    stack = rng.normal(size=(n, m, k))
    stack[rng.random((n, m, k)) < nan_frac] = np.nan
    target = 0.05 * np.nansum(stack, axis=2) + rng.normal(size=(n, m))
    return stack, target


def test_unset_equal_weight_is_the_complete_case_rule():
    stack, _ = _stack()
    signs = (1.0, -1.0, 1.0)
    got = EqualWeight(signs).combine(stack, None)
    assert np.array_equal(got, _old_equal_weight(stack, signs), equal_nan=True)


def test_an_absent_member_contributes_nothing_and_keeps_the_others_weight():
    stack, _ = _stack(1)
    signs = (1.0, -1.0, 1.0)
    t, i = 7, 3
    stack[t, i] = [0.4, np.nan, -1.2]
    got = EqualWeight(signs, min_members=2).combine(stack, None)
    want = 0.0
    for k in (0, 2):
        col = stack[t, :, k]
        f = col[np.isfinite(col)]
        want += signs[k] * (col[i] - f.mean()) / f.std() / 3
    assert np.isclose(got[t, i], want)
    stack[t, i] = [0.4, np.nan, np.nan]
    assert np.isnan(EqualWeight(signs, min_members=2).combine(stack, None)[t, i])


def test_a_member_absent_for_a_whole_row_does_not_empty_it():
    stack, _ = _stack(2)
    stack[10, :, 1] = np.nan
    assert np.isfinite(EqualWeight((1.0,) * 3, min_members=2).combine(stack, None)[10]).any()
    assert np.isnan(EqualWeight((1.0,) * 3).combine(stack, None)[10]).all()


def test_min_members_out_of_range_raises():
    with pytest.raises(ValueError):
        EqualWeight((1.0, 1.0), min_members=3)
    with pytest.raises(ValueError):
        RidgeSpec(window_rows=50, refit_rows=10, penalty=1.0, embargo=2, min_obs=100, min_members=0)
    stack, target = _stack(5)
    with pytest.raises(ValueError, match="exceeds"):
        walk_forward_ridge(stack, target, RidgeSpec(**RIDGE, min_members=4))


RIDGE = dict(window_rows=120, refit_rows=20, penalty=1.0, embargo=2, min_obs=200)


def test_ridge_unset_is_bit_identical_to_before_and_complete_cells_too():
    stack, target = _stack(3)
    before = _frozen_ridge()
    old = before.walk_forward_ridge(stack, target, before.RidgeSpec(**RIDGE))
    assert np.array_equal(
        walk_forward_ridge(stack, target, RidgeSpec(**RIDGE)), old, equal_nan=True
    )
    new = walk_forward_ridge(stack, target, RidgeSpec(**RIDGE, min_members=1))
    complete = np.isfinite(stack).all(axis=2)
    assert np.array_equal(new[complete], old[complete], equal_nan=True)
    assert np.isfinite(new[~complete]).sum() > 0


def test_an_incomplete_cell_gets_the_subset_ridge_forecast():
    """b_P re-solved on the fold's standardized moments, applied to the present members."""
    stack, target = _stack(6, n=300, m=40)
    spec = RidgeSpec(**RIDGE, min_members=2)
    got = walk_forward_ridge(stack, target, spec)
    p = 121 + 20  # a row inside the second fold
    hi = p - (p - 121) % 20 - spec.embargo + 1
    lo = max(0, hi - spec.window_rows)
    x = stack[lo:hi].reshape(-1, 3)
    y = target[lo:hi].reshape(-1)
    ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
    x, y = x[ok], y[ok]
    mu, sd = x.mean(axis=0), x.std(axis=0)
    z = (x - mu) / sd
    corr = np.corrcoef(z, rowvar=False)
    c = (z * (y - y.mean())[:, None]).mean(axis=0)
    i = int(np.flatnonzero(np.isnan(stack[p, :, 1]) & np.isfinite(stack[p, :, [0, 2]]).all(0))[0])
    b = np.linalg.solve(corr[np.ix_([0, 2], [0, 2])] + np.eye(2), c[[0, 2]])
    want = ((stack[p, i, [0, 2]] - mu[[0, 2]]) / sd[[0, 2]]) @ b
    assert np.isclose(got[p, i], want, rtol=1e-6)


def test_less_information_gives_a_smaller_forecast_not_an_inflated_one():
    rng = np.random.default_rng(4)
    n, m, k = 600, 60, 3
    stack = rng.normal(size=(n, m, 1)) + 0.5 * rng.normal(size=(n, m, k))
    target = stack.sum(axis=2) * 0.1 + rng.normal(size=(n, m))
    spec = RidgeSpec(**RIDGE, min_members=1)
    full = walk_forward_ridge(stack, target, spec)
    dropped = stack.copy()
    gone = rng.random((n, m)) < 0.3
    dropped[:, :, 2][gone] = np.nan
    part = walk_forward_ridge(dropped, target, spec)
    cells = gone & np.isfinite(full) & np.isfinite(part)
    assert cells.sum() > 1000
    assert np.std(part[cells]) <= np.std(full[cells])
