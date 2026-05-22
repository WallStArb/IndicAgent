"""Equivalence test for RSI plugin migration to IncrementalMixin (Task 9)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_rsi_full_computation_equivalence():
    """Migrated RSI produces equivalent output to legacy for 500-bar full computation."""
    from src.intelligence.features.i1_indicators.rsi import RSIPlugin
    from tests.fixtures.legacy_plugins.rsi_legacy import RSIPlugin as RSILegacy

    legacy = RSILegacy()
    migrated = RSIPlugin()

    frames = build_synthetic_frames(n_bars=500, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


def test_rsi_uses_incremental_mixin():
    """RSI plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.rsi import RSIPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(RSIPlugin(), IncrementalMixin)


def test_rsi_compute_next_returns_state():
    """RSI compute_full returns _state key and compute_next uses it."""
    from src.intelligence.features.i1_indicators.rsi import RSIPlugin

    plugin = RSIPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    assert result["_state"] is not None

    # Run incremental step
    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "rsi_14" in inc_result
