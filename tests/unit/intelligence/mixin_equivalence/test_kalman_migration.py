"""Equivalence test for Kalman plugin migration to IncrementalMixin (Task 14).

Equivalence strategy per plan spec:
- Seed with fixed random state, compare covariance outputs with atol=1e-6
  after 200-bar burn-in (deterministic given same seed)
- 2000-bar synthetic frames for model convergence
"""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_kalman_uses_incremental_mixin():
    """KalmanTrend plugin is an instance of IncrementalMixin."""
    from src.intelligence.context.kalman_trend import KalmanTrendPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(KalmanTrendPlugin(), IncrementalMixin)


def test_kalman_compute_full_returns_state():
    """KalmanTrend compute_full returns _state key with x_est, P_est, trend_history."""
    from src.intelligence.context.kalman_trend import KalmanTrendPlugin

    plugin = KalmanTrendPlugin()
    frames = build_synthetic_frames(n_bars=100, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    state = result["_state"]
    assert "x_est" in state
    assert "P_est" in state
    assert "trend_history" in state
    assert "R" in state


def test_kalman_compute_next_returns_state():
    """KalmanTrend compute_full returns _state key and compute_next uses it."""
    from src.intelligence.context.kalman_trend import KalmanTrendPlugin

    plugin = KalmanTrendPlugin()
    frames = build_synthetic_frames(n_bars=100, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "kalman_trend" in inc_result
    assert "kalman_slope" in inc_result
    assert "kalman_uncertainty" in inc_result


def test_kalman_full_computation_equivalence():
    """Migrated Kalman produces equivalent output to legacy for 2000-bar full computation.

    Kalman filter is deterministic given same input -- compare with 0.1% tolerance.
    """
    from src.intelligence.context.kalman_trend import KalmanTrendPlugin
    from tests.fixtures.legacy_plugins.kalman_legacy import KalmanTrendPlugin as KalmanLegacy

    legacy = KalmanLegacy()
    migrated = KalmanTrendPlugin()

    frames = build_synthetic_frames(n_bars=2000, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


def test_kalman_covariance_atol_after_burn_in():
    """Migrated Kalman uncertainty matches legacy to atol=1e-6 after 200-bar burn-in."""
    from src.intelligence.context.kalman_trend import KalmanTrendPlugin
    from tests.fixtures.legacy_plugins.kalman_legacy import KalmanTrendPlugin as KalmanLegacy

    # Run on 500-bar window (well past 200-bar burn-in)
    frames = build_synthetic_frames(n_bars=500, seed=42)

    legacy = KalmanLegacy()
    migrated = KalmanTrendPlugin()

    legacy_result = legacy.compute_full(frames)
    migrated_result = migrated.compute_full(frames)

    assert "kalman_uncertainty" in legacy_result
    assert "kalman_uncertainty" in migrated_result

    diff = abs(legacy_result["kalman_uncertainty"] - migrated_result["kalman_uncertainty"])
    assert diff < 1e-6, (
        f"kalman_uncertainty (P_est covariance) mismatch after burn-in: "
        f"legacy={legacy_result['kalman_uncertainty']:.10f}, "
        f"migrated={migrated_result['kalman_uncertainty']:.10f}, diff={diff:.2e}"
    )
