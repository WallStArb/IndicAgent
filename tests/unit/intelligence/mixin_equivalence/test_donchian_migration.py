"""Equivalence test for Donchian Channels plugin migration to IncrementalMixin (Task 12)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    build_synthetic_frames,
)


def test_donchian_uses_incremental_mixin():
    """DonchianChannels plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.donchian import DonchianChannelsPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(DonchianChannelsPlugin(), IncrementalMixin)


def test_donchian_compute_next_returns_state():
    """DonchianChannels compute_full returns _state key and compute_next uses it."""
    from src.intelligence.features.i1_indicators.donchian import DonchianChannelsPlugin

    plugin = DonchianChannelsPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "donchian_upper_20" in inc_result
