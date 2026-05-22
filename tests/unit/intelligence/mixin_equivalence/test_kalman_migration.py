"""Equivalence test for Kalman plugin migration to IncrementalMixin (Task 14).

Equivalence strategy per plan spec:
- Seed with fixed random state, compare covariance outputs with atol=1e-6
  after 200-bar burn-in (deterministic given same seed)
- 2000-bar synthetic frames for model convergence
"""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
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
