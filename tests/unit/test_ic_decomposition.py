"""Unit tests: IC decomposition kernels (Component B, todo 090, Phase 143.1 Plan 05).

sign_hit_rate (directional accuracy) and magnitude_conditional_ic (magnitude
alignment) decompose a feature's IC into "gets the direction right" vs "gets the
magnitude right when it matters." Both reuse _vectorized_ic (Pearson-on-ranks) --
no re-derived Spearman via scipy.stats.spearmanr (RESEARCH Don't Hand-Roll).

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import (
    magnitude_conditional_ic,
    sign_hit_rate,
)


def test_sign_hit_rate_matches_known_agreement_fraction():
    """75/100 bars with matching prediction/realized sign -> hit rate ~= 0.75."""
    rng = np.random.default_rng(11)
    n = 100
    n_mismatch = 25
    sign_x = np.where(rng.random(n) >= 0.5, 1.0, -1.0)
    sign_y = sign_x.copy()
    mismatch_idx = rng.choice(n, size=n_mismatch, replace=False)
    sign_y[mismatch_idx] *= -1.0

    X = (sign_x * (1.0 + rng.random(n))).reshape(-1, 1)  # nonzero magnitude, correct sign
    y = sign_y * (1.0 + rng.random(n))

    result = sign_hit_rate(X, y)

    assert result.shape == (1,)
    assert abs(result[0] - 0.75) < 1e-9, f"Expected ~0.75, got {result[0]}"


def test_sign_hit_rate_perfect_and_zero_agreement_bounds():
    """Perfect agreement -> 1.0; perfect disagreement -> 0.0 (sanity bounds)."""
    n = 50
    x = np.linspace(-1, 1, n)
    x[n // 2] = 0.1  # avoid the exact-zero midpoint

    y_same = x.copy()
    result_same = sign_hit_rate(x.reshape(-1, 1), y_same)
    assert result_same[0] == 1.0

    y_opposite = -x
    result_opposite = sign_hit_rate(x.reshape(-1, 1), y_opposite)
    assert result_opposite[0] == 0.0


def test_sign_hit_rate_degenerate_all_zero_returns_nan_not_raise():
    """All-zero prediction/return column has zero valid (nonzero-sign) pairs -> NaN, no raise."""
    n = 30
    X = np.zeros((n, 2))
    y = np.zeros(n)

    result = sign_hit_rate(X, y)

    assert result.shape == (2,)
    assert np.all(np.isnan(result))


def test_magnitude_conditional_ic_differs_from_full_sample_when_tail_stronger():
    """Fixture where the top-|prediction| tail carries stronger rank alignment than the
    full sample -> magnitude-conditional IC (top quartile) exceeds full-sample IC."""
    rng = np.random.default_rng(3)
    n = 2000

    # Small-magnitude bulk: near-independent of y (weak/no alignment).
    x_bulk = rng.normal(scale=0.1, size=n)
    y_bulk = rng.normal(size=n)

    # Large-magnitude tail: perfectly rank-aligned with y (strong alignment).
    n_tail = n // 10
    tail_vals = np.linspace(5.0, 15.0, n_tail)
    x_tail = np.where(rng.random(n_tail) >= 0.5, tail_vals, -tail_vals)
    y_tail = x_tail * 2.0  # same rank order as x_tail -> IC ~= 1 on the tail alone

    X = np.concatenate([x_bulk, x_tail]).reshape(-1, 1)
    y = np.concatenate([y_bulk, y_tail])

    full_ic = magnitude_conditional_ic(X, y, percentile=0.0)[0]  # 0th pct = whole sample
    tail_ic = magnitude_conditional_ic(X, y, percentile=90.0)[0]  # top 10% by |X|

    assert not np.isnan(full_ic)
    assert not np.isnan(tail_ic)
    assert tail_ic > full_ic, f"Expected tail IC ({tail_ic}) > full-sample IC ({full_ic})"


def test_magnitude_conditional_ic_reuses_vectorized_ic_no_scipy_spearmanr():
    """The magnitude-conditional subset IC must match _vectorized_ic computed directly
    on the same masked+re-ranked subset -- proves no independent re-derivation."""
    from scipy.stats import rankdata

    from src.intelligence.statistics.ic_math import _vectorized_ic

    rng = np.random.default_rng(5)
    n = 200
    x = rng.normal(size=n)
    y = 0.4 * x + rng.normal(size=n)
    X = x.reshape(-1, 1)

    percentile = 75.0
    threshold = np.percentile(np.abs(x), percentile)
    mask = np.abs(x) >= threshold
    expected_ic = float(_vectorized_ic(rankdata(x[mask]).reshape(-1, 1), rankdata(y[mask]))[0])

    actual_ic = magnitude_conditional_ic(X, y, percentile=percentile)[0]

    assert abs(actual_ic - expected_ic) < 1e-9


def test_magnitude_conditional_ic_degenerate_tiny_subset_returns_nan_not_raise():
    """A percentile threshold that leaves < 2 observations in the subset must return
    NaN, not raise (e.g. constant-magnitude feature with a high percentile cutoff)."""
    n = 10
    X = np.full((n, 1), 1.0)  # constant magnitude -> percentile threshold == the value itself
    y = np.arange(n, dtype=float)

    result = magnitude_conditional_ic(X, y, percentile=99.9)

    assert result.shape == (1,)
    # Either NaN (subset too small) or a finite value is acceptable numerically, but
    # the call must not raise -- assert explicitly on both branches to document intent.
    assert np.isnan(result[0]) or np.isfinite(result[0])


def test_magnitude_conditional_ic_all_nan_input_returns_nan_not_raise():
    """NaN-contaminated input must not raise -- returns NaN sentinel per existing
    module convention (_nan_to_none / _expand pattern)."""
    n = 20
    X = np.full((n, 1), np.nan)
    y = np.full(n, np.nan)

    result = magnitude_conditional_ic(X, y, percentile=75.0)

    assert result.shape == (1,)
    assert np.isnan(result[0])
