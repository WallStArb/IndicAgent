"""Unit tests: circular block bootstrap statistical correctness.

Tests verify that _circular_block_bootstrap_ic() from services.ic_engine:
  1. CI width shrinks as N increases (statistical consistency)
  2. CI is wider with larger block_size on autocorrelated data (captures autocorr)
  3. Circular wrap handles edge indices correctly (start near n wraps without error)
  4. Determinism: two calls with same seed produce identical outputs

The circular block bootstrap is the most novel statistical component in the IC
engine substrate. These tests anchor its correctness before corpus runs.

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scipy.stats import rankdata

from services.ic_engine import _circular_block_bootstrap_ic


def _make_ar1_series(n: int, phi: float, seed: int) -> np.ndarray:
    """Generate AR(1) series: x[t] = phi * x[t-1] + epsilon[t]."""
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    x[0] = rng.standard_normal()
    noise = rng.standard_normal(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + noise[t]
    return x


def _make_ranked_inputs(
    n: int, n_features: int, phi: float, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Build pre-ranked (X, Y) matrices as expected by _circular_block_bootstrap_ic."""
    rng_x = np.random.default_rng(seed)
    rng_y = np.random.default_rng(seed + 1)

    # AR(1) features
    X = np.column_stack([_make_ar1_series(n, phi, seed=seed + j) for j in range(n_features)])
    Y = _make_ar1_series(n, phi, seed=seed + 1000)

    ranks_X = rankdata(X, axis=0).astype(float)
    ranks_Y = rankdata(Y).astype(float)
    return ranks_X, ranks_Y


def test_ci_width_shrinks_with_n():
    """CI width (upper - lower) must decrease as N increases.

    Uses AR(1) with phi=0.3. At n=500 the CI should be narrower than at n=100
    for all features, demonstrating statistical consistency.
    """
    phi = 0.3
    n_features = 3
    n_boot = 500
    block_size = 10

    # n=100 (subset)
    rX_100, rY_100 = _make_ranked_inputs(100, n_features, phi, seed=7)
    rng_100 = np.random.default_rng(99)
    ci_lower_100, ci_upper_100 = _circular_block_bootstrap_ic(
        rX_100, rY_100, block_size, n_boot, rng_100
    )
    ci_width_100 = ci_upper_100 - ci_lower_100

    # n=500 (full)
    rX_500, rY_500 = _make_ranked_inputs(500, n_features, phi, seed=7)
    rng_500 = np.random.default_rng(99)
    ci_lower_500, ci_upper_500 = _circular_block_bootstrap_ic(
        rX_500, rY_500, block_size, n_boot, rng_500
    )
    ci_width_500 = ci_upper_500 - ci_lower_500

    assert np.all(ci_width_500 < ci_width_100), (
        f"CI width did not shrink with N: "
        f"ci_width_100={ci_width_100}, ci_width_500={ci_width_500}"
    )


def test_ci_wider_with_larger_block_size_on_correlated_data():
    """CI must be wider with block_size=50 vs block_size=5 on AR(1) phi=0.7 data.

    High autocorrelation (phi=0.7) means large blocks capture more correlation
    structure. A larger block size produces a wider CI because each bootstrap
    replicate preserves more of the autocorrelation in the original series.
    """
    phi = 0.7
    n = 300
    n_features = 3
    n_boot = 500

    rX, rY = _make_ranked_inputs(n, n_features, phi, seed=42)

    rng_small = np.random.default_rng(0)
    ci_lower_small, ci_upper_small = _circular_block_bootstrap_ic(
        rX, rY, block_size=5, n_boot=n_boot, rng=rng_small
    )
    ci_width_small = ci_upper_small - ci_lower_small

    rng_large = np.random.default_rng(0)
    ci_lower_large, ci_upper_large = _circular_block_bootstrap_ic(
        rX, rY, block_size=50, n_boot=n_boot, rng=rng_large
    )
    ci_width_large = ci_upper_large - ci_lower_large

    mean_width_small = float(np.mean(ci_width_small))
    mean_width_large = float(np.mean(ci_width_large))

    assert mean_width_large > mean_width_small, (
        f"Expected larger block_size to produce wider CI on AR(1) phi={phi} data: "
        f"mean CI width at block_size=5: {mean_width_small:.6f}, "
        f"mean CI width at block_size=50: {mean_width_large:.6f}"
    )


def test_circular_wrap_no_index_error():
    """block_size=7 with n=20 forces circular wrap (7 blocks of 7 = 49 > 20).

    This verifies no IndexError is raised and output shape/finiteness is correct.
    """
    n = 20
    n_features = 3
    block_size = 7  # 7*3=21 > 20 -- forces wrap
    n_boot = 50

    rX, rY = _make_ranked_inputs(n, n_features, phi=0.3, seed=13)

    rng = np.random.default_rng(77)
    # Must not raise IndexError
    ci_lower, ci_upper = _circular_block_bootstrap_ic(rX, rY, block_size, n_boot, rng)

    assert ci_lower.shape == (
        n_features,
    ), f"Expected ci_lower shape ({n_features},), got {ci_lower.shape}"
    assert ci_upper.shape == (
        n_features,
    ), f"Expected ci_upper shape ({n_features},), got {ci_upper.shape}"
    assert np.all(np.isfinite(ci_lower)), f"ci_lower contains non-finite: {ci_lower}"
    assert np.all(np.isfinite(ci_upper)), f"ci_upper contains non-finite: {ci_upper}"


def test_determinism_same_seed():
    """Two calls with identical rng seed produce identical ci_lower, ci_upper."""
    n = 100
    n_features = 4
    block_size = 10
    n_boot = 200

    rX, rY = _make_ranked_inputs(n, n_features, phi=0.3, seed=42)

    rng_1 = np.random.default_rng(42)
    ci_lower_1, ci_upper_1 = _circular_block_bootstrap_ic(rX, rY, block_size, n_boot, rng_1)

    rng_2 = np.random.default_rng(42)
    ci_lower_2, ci_upper_2 = _circular_block_bootstrap_ic(rX, rY, block_size, n_boot, rng_2)

    np.testing.assert_array_equal(
        ci_lower_1,
        ci_lower_2,
        err_msg="ci_lower differs between two identical-seed runs (not deterministic)",
    )
    np.testing.assert_array_equal(
        ci_upper_1,
        ci_upper_2,
        err_msg="ci_upper differs between two identical-seed runs (not deterministic)",
    )
