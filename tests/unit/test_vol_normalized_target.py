"""Unit tests: epsilon-guarded vol-normalized return target (Component F, todo 097,
Phase 143.1-03).

Tests verify that `vol_normalized_return()` from src.intelligence.statistics.ic_math:
  1. Returns a finite value (0.0, not inf/nan) when true_range_pct is ~0 -- matches
     the epsilon-guard convention in src/intelligence/feature_factory.py's
     _ret_vol_ratio().
  2. For non-zero true_range_pct, output equals return_x / true_range_pct exactly.
  3. Operates on arrays already available in the cross-sectional load (no new
     query/join needed -- it is a pure function of two already-fetched columns).

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import vol_normalized_return


def test_epsilon_guard_near_zero_true_range_pct_returns_zero_not_inf_or_nan() -> None:
    return_x = np.array([0.01, -0.02, 0.5, -0.5], dtype=np.float64)
    true_range_pct = np.array([0.0, 1e-12, -1e-11, 5e-11], dtype=np.float64)

    result = vol_normalized_return(return_x, true_range_pct)

    assert np.all(np.isfinite(result))
    assert np.allclose(result, 0.0)


def test_epsilon_guard_matches_ret_vol_ratio_default_threshold() -> None:
    # _ret_vol_ratio's default eps is 1e-10 -- confirm vol_normalized_return's
    # default guard threshold matches (a value just inside eps must guard to 0.0,
    # a value just outside must divide normally).
    return_x = np.array([1.0, 1.0], dtype=np.float64)
    true_range_pct = np.array([9e-11, 2e-10], dtype=np.float64)  # inside / outside 1e-10

    result = vol_normalized_return(return_x, true_range_pct)

    assert result[0] == 0.0
    assert np.isclose(result[1], 1.0 / 2e-10)


def test_non_zero_true_range_pct_returns_exact_ratio() -> None:
    return_x = np.array([0.02, -0.015, 0.0, 0.1], dtype=np.float64)
    true_range_pct = np.array([0.01, 0.005, 0.02, 0.05], dtype=np.float64)

    result = vol_normalized_return(return_x, true_range_pct)

    expected = return_x / true_range_pct
    assert np.allclose(result, expected)


def test_output_shape_matches_input_shape() -> None:
    n = 500
    rng = np.random.default_rng(42)
    return_x = rng.normal(0, 0.02, size=n)
    true_range_pct = rng.uniform(0.001, 0.05, size=n)

    result = vol_normalized_return(return_x, true_range_pct)

    assert result.shape == (n,)


def test_custom_eps_overrides_default_guard_threshold() -> None:
    return_x = np.array([1.0], dtype=np.float64)
    true_range_pct = np.array([0.05], dtype=np.float64)

    # With a large custom eps, even a moderate true_range_pct gets guarded to 0.0.
    result = vol_normalized_return(return_x, true_range_pct, eps=0.1)

    assert result[0] == 0.0


def test_operates_on_arrays_shaped_like_ic_engine_cross_sectional_load() -> None:
    # Mirrors _compute_cross_sectional_tf's shapes: return_x is returns_scale
    # (shape [n_valid]), true_range_pct is a single column sliced from X_raw/X_sub
    # at _FEATURE_NAMES.index("true_range_pct") (also shape [n_valid] after the
    # same valid_mask is applied) -- no new SQL, purely a derived array from data
    # already fetched by the existing chunk_sql query.
    n_valid = 1000
    rng = np.random.default_rng(7)
    returns_scale = rng.normal(0, 0.015, size=n_valid).astype(np.float32)
    true_range_pct_col = rng.uniform(0.0005, 0.03, size=n_valid).astype(np.float32)

    result = vol_normalized_return(returns_scale, true_range_pct_col)

    assert result.shape == (n_valid,)
    assert np.all(np.isfinite(result))
