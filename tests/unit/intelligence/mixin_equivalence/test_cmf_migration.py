"""Equivalence test for CMF plugin migration to IncrementalMixin (Task 10)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    build_synthetic_frames,
)


def test_cmf_uses_incremental_mixin():
    """CMF plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.cmf import CMFPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(CMFPlugin(), IncrementalMixin)


def test_cmf_compute_next_returns_state():
    """CMF compute_full returns _state and compute_next uses it."""
    from src.intelligence.features.i1_indicators.cmf import CMFPlugin

    plugin = CMFPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "cmf_20" in inc_result
