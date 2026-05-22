"""Equivalence test for ChandelierExit plugin migration to IncrementalMixin (Task 10)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    build_synthetic_frames,
)


def test_chandelier_uses_incremental_mixin():
    """ChandelierExit plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.chandelier import ChandelierPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(ChandelierPlugin(), IncrementalMixin)


def test_chandelier_compute_next_returns_state():
    """Chandelier compute_full returns _state and compute_next uses it."""
    from src.intelligence.features.i1_indicators.chandelier import ChandelierPlugin

    plugin = ChandelierPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "chandelier_long_22" in inc_result
