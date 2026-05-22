"""Equivalence test for MarketProfile plugin migration to IncrementalMixin (Task 12)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    build_synthetic_frames,
)


def test_market_profile_uses_incremental_mixin():
    """MarketProfile plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i3_structure.market_profile import MarketProfilePlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(MarketProfilePlugin(), IncrementalMixin)


def test_market_profile_compute_next_returns_state():
    """MarketProfile compute_full returns _state key and compute_next uses it."""
    from src.intelligence.features.i3_structure.market_profile import MarketProfilePlugin

    plugin = MarketProfilePlugin()
    frames = build_synthetic_frames(n_bars=100, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "poc_level" in inc_result
    assert "va_high" in inc_result
    assert "va_low" in inc_result
