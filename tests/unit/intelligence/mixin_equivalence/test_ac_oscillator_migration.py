"""Equivalence test for ACOscillator plugin migration to IncrementalMixin (Task 11)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    build_synthetic_frames,
)


def test_ac_oscillator_uses_incremental_mixin():
    """ACOscillator plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.ac_oscillator import ACOscillatorPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(ACOscillatorPlugin(), IncrementalMixin)


def test_ac_oscillator_compute_next_returns_state():
    """ACOscillator compute_full returns _state and compute_next uses it."""
    from src.intelligence.features.i1_indicators.ac_oscillator import ACOscillatorPlugin

    plugin = ACOscillatorPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "ao" in inc_result
