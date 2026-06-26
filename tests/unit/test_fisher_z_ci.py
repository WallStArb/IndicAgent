"""Unit tests: Fisher z-transform CI statistical correctness.

Tests verify that _fisher_z_ci() from services.ic_engine:
  1. CI width shrinks as N increases (statistical consistency)
  2. Strong positive IC at large N produces ci_lower > 0 (passes_ci_gate)
  3. IC = 0 produces CI symmetric around 0 (ci_lower < 0 < ci_upper)
  4. IC = ±1 clips without raising (arctanh boundary guard)
  5. n < 4 returns NaN arrays (degenerate guard)
  6. Output shape matches input feature count

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _fisher_z_ci


def test_ci_width_shrinks_with_n():
    """CI width must decrease as N increases (asymptotic consistency)."""
    ic = np.array([0.05, 0.10, 0.15])

    lower_100, upper_100 = _fisher_z_ci(ic, n=100)
    lower_500, upper_500 = _fisher_z_ci(ic, n=500)

    width_100 = upper_100 - lower_100
    width_500 = upper_500 - lower_500

    assert np.all(
        width_500 < width_100
    ), f"CI width did not shrink with N: width_100={width_100}, width_500={width_500}"


def test_strong_positive_ic_large_n_passes_gate():
    """IC=0.10 at n=1000 must have ci_lower > 0 (passes_ci_gate expected True)."""
    ic = np.array([0.10, 0.20, 0.30])
    ci_lower, ci_upper = _fisher_z_ci(ic, n=1000)

    assert np.all(ci_lower > 0), f"Expected all ci_lower > 0 at n=1000, got {ci_lower}"
    assert np.all(ci_upper > ci_lower), "ci_upper must exceed ci_lower"


def test_zero_ic_produces_symmetric_ci():
    """IC=0 must produce CI straddling zero (ci_lower < 0 < ci_upper)."""
    ic = np.zeros(4)
    ci_lower, ci_upper = _fisher_z_ci(ic, n=200)

    assert np.all(ci_lower < 0), f"Expected ci_lower < 0 for IC=0, got {ci_lower}"
    assert np.all(ci_upper > 0), f"Expected ci_upper > 0 for IC=0, got {ci_upper}"
    np.testing.assert_allclose(
        ci_lower, -ci_upper, atol=1e-10, err_msg="CI must be symmetric around 0"
    )


def test_ic_boundary_clips_without_error():
    """IC values at ±1 must not raise (arctanh boundary guard active)."""
    ic = np.array([-1.0, -0.999, 0.999, 1.0])
    ci_lower, ci_upper = _fisher_z_ci(ic, n=100)

    assert np.all(np.isfinite(ci_lower)), f"ci_lower contains non-finite: {ci_lower}"
    assert np.all(np.isfinite(ci_upper)), f"ci_upper contains non-finite: {ci_upper}"


def test_degenerate_n_returns_nan():
    """n < 4 must return NaN arrays (arctanh SE undefined for n-3 <= 0)."""
    ic = np.array([0.1, 0.2])
    for n in [1, 2, 3]:
        ci_lower, ci_upper = _fisher_z_ci(ic, n=n)
        assert np.all(np.isnan(ci_lower)), f"Expected NaN for n={n}, got {ci_lower}"
        assert np.all(np.isnan(ci_upper)), f"Expected NaN for n={n}, got {ci_upper}"


def test_output_shape_matches_features():
    """Output arrays must have the same shape as the input ic_vector."""
    for p in [1, 5, 60]:
        ic = np.linspace(-0.2, 0.2, p)
        ci_lower, ci_upper = _fisher_z_ci(ic, n=500)
        assert ci_lower.shape == (p,), f"ci_lower shape mismatch for p={p}"
        assert ci_upper.shape == (p,), f"ci_upper shape mismatch for p={p}"


def test_ci_bounds_ordered():
    """ci_lower must always be strictly less than ci_upper for finite IC."""
    ic = np.linspace(-0.5, 0.5, 21)
    ci_lower, ci_upper = _fisher_z_ci(ic, n=300)

    assert np.all(
        ci_lower < ci_upper
    ), f"ci_lower not strictly less than ci_upper: {list(zip(ci_lower, ci_upper))}"
