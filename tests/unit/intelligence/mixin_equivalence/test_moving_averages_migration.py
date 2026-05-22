"""Equivalence test for MovingAverages plugin migration to IncrementalMixin (Task 12)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    build_synthetic_frames,
)


def test_moving_averages_uses_incremental_mixin():
    """MovingAverages plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.moving_averages import MovingAveragesPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(MovingAveragesPlugin(), IncrementalMixin)


def test_moving_averages_compute_next_returns_state():
    """MovingAverages compute_full returns _state key and compute_next uses it."""
    from src.intelligence.features.i1_indicators.moving_averages import MovingAveragesPlugin

    plugin = MovingAveragesPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "sma_20" in inc_result
    assert "ema_8" in inc_result
