"""Equivalence test for MACD plugin migration to IncrementalMixin (Task 9)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_macd_full_computation_equivalence():
    """Migrated MACD produces equivalent output to legacy for 500-bar full computation."""
    from src.intelligence.features.i1_indicators.macd import MACDPlugin
    from tests.fixtures.legacy_plugins.macd_legacy import MACDPlugin as MACDLegacy

    legacy = MACDLegacy()
    migrated = MACDPlugin()

    frames = build_synthetic_frames(n_bars=500, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


def test_macd_uses_incremental_mixin():
    """MACD plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.macd import MACDPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(MACDPlugin(), IncrementalMixin)


def test_macd_compute_next_returns_state():
    """MACD compute_full returns _state and compute_next uses it."""
    from src.intelligence.features.i1_indicators.macd import MACDPlugin

    plugin = MACDPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "macd_12_26_9" in inc_result
