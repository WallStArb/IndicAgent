"""Equivalence test for StochRSI plugin migration to IncrementalMixin (Task 11)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_stoch_rsi_full_computation_equivalence():
    """Migrated StochRSI produces equivalent output to legacy for 500-bar full computation."""
    from src.intelligence.features.i1_indicators.stochastic_rsi import StochRSIPlugin
    from tests.fixtures.legacy_plugins.stochastic_rsi_legacy import StochRSIPlugin as StochRSILegacy

    legacy = StochRSILegacy()
    migrated = StochRSIPlugin()

    frames = build_synthetic_frames(n_bars=500, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


def test_stoch_rsi_uses_incremental_mixin():
    """StochRSI plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.stochastic_rsi import StochRSIPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(StochRSIPlugin(), IncrementalMixin)


def test_stoch_rsi_compute_next_returns_state():
    """StochRSI compute_full returns _state and compute_next uses it."""
    from src.intelligence.features.i1_indicators.stochastic_rsi import StochRSIPlugin

    plugin = StochRSIPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "stoch_rsi_k_14" in inc_result
