"""Equivalence test for MovingAverages plugin migration to IncrementalMixin (Task 12)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_moving_averages_full_computation_equivalence():
    """Migrated MovingAverages produces equivalent output to legacy for 500-bar full computation."""
    from src.intelligence.features.i1_indicators.moving_averages import MovingAveragesPlugin
    from tests.fixtures.legacy_plugins.moving_averages_legacy import (
        MovingAveragesPlugin as MovingAveragesLegacy,
    )

    legacy = MovingAveragesLegacy()
    migrated = MovingAveragesPlugin()

    frames = build_synthetic_frames(n_bars=500, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


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
