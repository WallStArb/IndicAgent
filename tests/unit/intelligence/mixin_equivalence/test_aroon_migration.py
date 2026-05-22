"""Equivalence test for Aroon plugin migration to IncrementalMixin (Task 10)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    build_synthetic_frames,
)


def test_aroon_uses_incremental_mixin():
    """Aroon plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.aroon import AroonPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(AroonPlugin(), IncrementalMixin)


def test_aroon_compute_next_returns_state():
    """Aroon compute_full returns _state and compute_next uses it."""
    from src.intelligence.features.i1_indicators.aroon import AroonPlugin

    plugin = AroonPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "aroon_up_25" in inc_result
