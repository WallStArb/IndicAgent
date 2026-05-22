"""Equivalence test for ParabolicSAR plugin migration to IncrementalMixin (Task 11)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_parabolic_sar_full_computation_equivalence():
    """Migrated PSAR produces equivalent output to legacy for 500-bar full computation."""
    from src.intelligence.features.i1_indicators.parabolic_sar import PSARPlugin
    from tests.fixtures.legacy_plugins.parabolic_sar_legacy import PSARPlugin as PSARLegacy

    legacy = PSARLegacy()
    migrated = PSARPlugin()

    frames = build_synthetic_frames(n_bars=500, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


def test_parabolic_sar_uses_incremental_mixin():
    """ParabolicSAR plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.parabolic_sar import PSARPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(PSARPlugin(), IncrementalMixin)


def test_parabolic_sar_compute_next_returns_state():
    """PSAR compute_full returns _state and compute_next uses it."""
    from src.intelligence.features.i1_indicators.parabolic_sar import PSARPlugin

    plugin = PSARPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "psar_value" in inc_result
