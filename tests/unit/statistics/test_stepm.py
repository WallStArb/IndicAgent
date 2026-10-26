"""Romano-Wolf StepM (phase 187 plan 04, design 7.3.2)."""

import numpy as np
import pytest

from src.intelligence.statistics.stepm import stepm

KW = dict(block_mean=10, max_horizon_sessions=2, reps=400, fwer=0.05, seed=7)


def _nulls(rng, s, k):
    return rng.normal(0, 1, (s, k))


def test_one_strong_series_among_nulls_is_the_selection():
    rng = np.random.default_rng(0)
    x = _nulls(rng, 1000, 30)
    x[:, 4] += 0.25  # t about 8
    out = stepm(x, **KW)
    assert out.selected.tolist() == [k == 4 for k in range(30)]


def test_global_null_family_wise_error_is_controlled():
    hits = 0
    trials = 120
    for seed in range(trials):
        rng = np.random.default_rng(1000 + seed)
        hits += stepm(_nulls(rng, 400, 20), **{**KW, "reps": 200, "seed": seed}).selected.any()
    rate = hits / trials
    assert rate <= 0.05 + 2 * np.sqrt(0.05 * 0.95 / trials)


def test_correlated_tweaks_cost_about_one_trial():
    rng = np.random.default_rng(3)
    z = rng.normal(0, 1, 1000)
    base = (z - z.mean()) / z.std() + 0.08  # t about 2.5
    tweaks = base[:, None] + rng.normal(0, 0.05, (1000, 10))
    unrelated = np.column_stack([base, rng.normal(0, 1, (1000, 9))])
    together = stepm(tweaks, **KW)
    apart = stepm(unrelated, **KW)
    assert together.selected.all() or not together.selected.any()
    # The same series priced among ten near-copies pays far less than among ten unrelated tries.
    assert together.adjusted_p.max() < apart.adjusted_p[0]


def test_deterministic_under_seed_and_monotone_p():
    rng = np.random.default_rng(5)
    x = _nulls(rng, 600, 8) + np.linspace(0, 0.2, 8)
    a, b = stepm(x, **KW), stepm(x, **KW)
    assert np.array_equal(a.adjusted_p, b.adjusted_p)
    order = np.argsort(-a.t)
    assert np.all(np.diff(a.adjusted_p[order]) >= 0)


def test_differing_spans_are_not_filled():
    rng = np.random.default_rng(9)
    x = _nulls(rng, 800, 3)
    x[:, 0] += 0.3
    x[:300, 0] = np.nan  # a late-starting attempt
    x[500:, 2] = np.nan  # an early-ending one
    out = stepm(x, **KW)
    assert out.selected[0] and not out.selected[1:].any()
    assert np.isfinite(out.t).all()


def test_block_must_exceed_the_longest_horizon():
    with pytest.raises(ValueError, match="horizon"):
        stepm(np.zeros((10, 2)) + 1, **{**KW, "block_mean": 2, "max_horizon_sessions": 2})
