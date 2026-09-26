import numpy as np
import pytest

from src.intelligence.research.combiner import (
    EqualWeight,
    RidgeSpec,
    refit_positions,
    walk_forward_ridge,
)

SPEC = RidgeSpec(window_rows=120, refit_rows=40, penalty=0.5, embargo=3, min_obs=30)


def _stack(seed, n=400, m=15, k=3, nan_frac=0.2):
    rng = np.random.default_rng(seed)
    stack = rng.normal(size=(n, m, k)) * np.array([1.0, 2.0, 0.5]) + np.array([0.1, -0.3, 0.2])
    target = stack @ np.array([0.3, -0.1, 0.4]) + rng.normal(size=(n, m))
    stack[rng.random((n, m, k)) < nan_frac] = np.nan
    target[rng.random((n, m)) < nan_frac] = np.nan
    return stack, target


def reference(stack, target, spec):
    """Per fold: gather complete-case pairs with plain loops, standardize, solve twice."""
    n, m, k = stack.shape
    out = np.full((n, m), np.nan)
    positions = list(refit_positions(n, spec))
    for j, p in enumerate(positions):
        q = positions[j + 1] if j + 1 < len(positions) else n
        hi = p - spec.embargo + 1
        xs, ys = [], []
        for s in range(max(0, hi - spec.window_rows), hi):
            for i in range(m):
                if np.isfinite(target[s, i]) and np.all(np.isfinite(stack[s, i])):
                    xs.append(stack[s, i].astype(float))
                    ys.append(float(target[s, i]))
        c = len(xs)
        if c < spec.min_obs:
            continue
        x = np.array(xs)
        y = np.array(ys)
        mu = x.mean(axis=0)
        sd = x.std(axis=0)
        if np.any(sd == 0):
            continue
        z = (x - mu) / sd
        b = np.linalg.solve(z.T @ z / c + spec.penalty * np.eye(k), z.T @ (y - y.mean()) / c)
        aug_x = np.vstack([z, np.sqrt(spec.penalty * c) * np.eye(k)])
        aug_y = np.concatenate([y - y.mean(), np.zeros(k)])
        b_lstsq = np.linalg.lstsq(aug_x, aug_y, rcond=None)[0]
        np.testing.assert_allclose(b, b_lstsq, rtol=1e-9, atol=1e-12)
        out[p:q] = ((stack[p:q].astype(float) - mu) / sd) @ b
    return out


def test_refit_positions():
    pos = refit_positions(400, SPEC)
    assert pos[0] == SPEC.window_rows + SPEC.embargo - 1
    assert np.all(np.diff(pos) == SPEC.refit_rows)
    assert pos[-1] < 400 <= pos[-1] + SPEC.refit_rows
    assert refit_positions(SPEC.window_rows, SPEC).size == 0


def test_matches_slow_reference():
    stack, target = _stack(0)
    got = walk_forward_ridge(stack, target, SPEC)
    want = reference(stack, target, SPEC)
    assert got.dtype == np.float64 and got.shape == target.shape
    np.testing.assert_array_equal(np.isnan(got), np.isnan(want))
    np.testing.assert_allclose(got, want, rtol=1e-8, atol=1e-8)
    assert np.isfinite(got).sum() > 1000


def test_rows_before_first_refit_are_nan():
    stack, target = _stack(1)
    got = walk_forward_ridge(stack, target, SPEC)
    p0 = refit_positions(stack.shape[0], SPEC)[0]
    assert np.all(np.isnan(got[:p0]))
    assert np.isfinite(got[p0]).any()


@pytest.mark.parametrize("t", [122, 160, 201, 290, 399])
@pytest.mark.parametrize("fill", ["nan", "random"])
def test_causal(t, fill):
    stack, target = _stack(2)
    base = walk_forward_ridge(stack, target, SPEC)
    rng = np.random.default_rng(t)
    s2, y2 = stack.copy(), target.copy()
    y_from = max(0, t - SPEC.embargo + 1)
    if fill == "nan":
        y2[y_from:] = np.nan
        s2[t + 1 :] = np.nan
    else:
        y2[y_from:] = rng.normal(size=y2[y_from:].shape) * 10
        s2[t + 1 :] = rng.normal(size=s2[t + 1 :].shape) * 10
    got = walk_forward_ridge(s2, y2, SPEC)
    np.testing.assert_array_equal(got[: t + 1], base[: t + 1])


def test_standardization_uses_training_rows_only():
    stack, target = _stack(3)
    pos = refit_positions(stack.shape[0], SPEC)
    p, q = pos[3], pos[4]
    base = walk_forward_ridge(stack, target, SPEC)
    # Offset only this fold's prediction rows, which lie outside its training window.
    shifted = stack.copy()
    offset = 5.0
    shifted[p:q, :, 1] += offset
    got = walk_forward_ridge(shifted, target, SPEC)
    np.testing.assert_array_equal(got[:p], base[:p])
    # Fold's mu/sd and b are unchanged: the prediction moves by offset / sd_1 * b_1 everywhere.
    ok = np.isfinite(base[p:q])
    delta = (got[p:q] - base[p:q])[ok]
    assert np.allclose(delta, delta[0], rtol=0, atol=1e-10)
    hi = p - SPEC.embargo + 1
    lo = max(0, hi - SPEC.window_rows)
    x = stack[lo:hi].reshape(-1, 3)
    y = target[lo:hi].reshape(-1)
    cc = np.isfinite(y) & np.isfinite(x).all(axis=1)
    x, y = x[cc], y[cc]
    mu, sd = x.mean(axis=0), x.std(axis=0)
    z = (x - mu) / sd
    b = np.linalg.solve(z.T @ z / len(y) + SPEC.penalty * np.eye(3), z.T @ (y - y.mean()) / len(y))
    assert delta[0] == pytest.approx(offset / sd[1] * b[1], rel=1e-9)


def test_complete_cases_only():
    stack, target = _stack(4, nan_frac=0.0)
    t, i = 300, 7
    stack[t, i, 2] = np.nan
    got = walk_forward_ridge(stack, target, SPEC)
    assert np.isnan(got[t, i])
    assert np.isfinite(got[t, np.arange(15) != i]).all()
    # The incomplete pair is out of training: changing its other members or target is inert.
    s2, y2 = stack.copy(), target.copy()
    s2[t, i, :2] = 1e6
    y2[t, i] = -1e6
    np.testing.assert_array_equal(walk_forward_ridge(s2, y2, SPEC), got)
    # A NaN target makes the pair incomplete for training but not for prediction.
    y3 = target.copy()
    y3[t, i] = np.nan
    assert np.isfinite(walk_forward_ridge(stack, y3, SPEC)[t, np.arange(15) != i]).all()


def test_recovers_planted_coefficients():
    rng = np.random.default_rng(5)
    n, m = 600, 40
    stack = rng.normal(size=(n, m, 3))
    target = 0.3 * stack[..., 0] - 0.2 * stack[..., 1] + 0.1 * rng.normal(size=(n, m))
    spec = RidgeSpec(window_rows=300, refit_rows=100, penalty=1e-6, embargo=1, min_obs=10)
    got = walk_forward_ridge(stack, target, spec)
    p = refit_positions(n, spec)[0]
    rows = slice(p, p + spec.refit_rows)
    x = stack[rows].reshape(-1, 3)
    b, *_ = np.linalg.lstsq(np.c_[x, np.ones(len(x))], got[rows].reshape(-1), rcond=None)
    # Members are standardized with sd about 1, so the fitted slopes are b on the raw scale.
    np.testing.assert_allclose(b[:3], [0.3, -0.2, 0.0], atol=0.02)


def test_min_obs_fold_predicts_nan():
    stack, target = _stack(6)
    spec = RidgeSpec(window_rows=120, refit_rows=40, penalty=0.5, embargo=3, min_obs=10**6)
    assert np.all(np.isnan(walk_forward_ridge(stack, target, spec)))
    # One sparse fold: blank every target in the second fold's training window.
    pos = refit_positions(stack.shape[0], SPEC)
    hi = pos[1] - SPEC.embargo + 1
    y2 = target.copy()
    y2[max(0, hi - SPEC.window_rows) : hi] = np.nan
    got = walk_forward_ridge(stack, y2, SPEC)
    assert np.all(np.isnan(got[pos[1] : pos[2]]))
    assert np.isfinite(got[pos[0] : pos[1]]).any()


def test_zero_sd_fold_predicts_nan():
    stack, target = _stack(7, nan_frac=0.0)
    stack[..., 1] = 2.0
    assert np.all(np.isnan(walk_forward_ridge(stack, target, SPEC)))


def test_float32_matches_float64():
    stack, target = _stack(8)
    got64 = walk_forward_ridge(stack, target, SPEC)
    s32 = stack.astype(np.float32)
    got32 = walk_forward_ridge(s32, target.astype(np.float32), SPEC)
    want = walk_forward_ridge(s32.astype(np.float64), target.astype(np.float32).astype(float), SPEC)
    assert got32.dtype == np.float64
    np.testing.assert_allclose(got32, want, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(got32, got64, rtol=1e-4, atol=1e-5)


def test_equal_weight_is_the_signed_mean_of_per_row_z_scores():
    rng = np.random.default_rng(9)
    n, m = 30, 12
    stack = rng.normal(size=(n, m, 3))
    stack[4, 2, 1] = np.nan  # name 2 drops out of row 4 entirely (complete cases)
    got = EqualWeight(signs=(1.0, -1.0, 1.0)).combine(stack, np.zeros((n, m)))
    for t in (0, 4):
        ok = np.isfinite(stack[t]).all(axis=1)
        x = stack[t][ok]
        z = (x - x.mean(axis=0)) / x.std(axis=0)
        np.testing.assert_allclose(got[t][ok], (z * [1, -1, 1]).mean(axis=1), rtol=1e-12)
    assert np.isnan(got[4, 2]) and np.isfinite(got[4][np.arange(m) != 2]).all()


def test_equal_weight_reads_no_target_and_rejects_bad_signs():
    stack = np.random.default_rng(1).normal(size=(10, 8, 2))
    ew = EqualWeight(signs=(1.0, 1.0))
    a = ew.combine(stack, np.zeros((10, 8)))
    b = ew.combine(stack, np.full((10, 8), 7.0))
    np.testing.assert_array_equal(a, b)
    assert ew.training_rows == 0 and SPEC.training_rows == SPEC.window_rows + SPEC.embargo
    for bad in ((), (1.0, 0.5)):
        with pytest.raises(ValueError, match="signs"):
            EqualWeight(signs=bad)
    with pytest.raises(ValueError, match="does not match"):
        EqualWeight(signs=(1.0,)).combine(stack, np.zeros((10, 8)))
