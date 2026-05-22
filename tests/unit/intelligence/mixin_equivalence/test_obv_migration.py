"""Equivalence test for OBV plugin migration to IncrementalMixin (Task 12)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_obv_full_computation_equivalence():
    """Migrated OBV produces equivalent output to legacy for 500-bar full computation."""
    from src.intelligence.features.i1_indicators.obv import OBVPlugin
    from tests.fixtures.legacy_plugins.obv_legacy import OBVPlugin as OBVLegacy

    legacy = OBVLegacy()
    migrated = OBVPlugin()

    frames = build_synthetic_frames(n_bars=500, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


def test_obv_uses_incremental_mixin():
    """OBV plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.obv import OBVPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(OBVPlugin(), IncrementalMixin)


def test_obv_compute_next_returns_state():
    """OBV compute_full returns _state key and compute_next uses it."""
    from src.intelligence.features.i1_indicators.obv import OBVPlugin

    plugin = OBVPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "obv" in inc_result
