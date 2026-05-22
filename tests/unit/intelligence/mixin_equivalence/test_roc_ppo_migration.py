"""Equivalence test for ROC_PPO plugin migration to IncrementalMixin (Task 11)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    build_synthetic_frames,
)


def test_roc_ppo_uses_incremental_mixin():
    """ROC_PPO plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.roc_ppo import ROCPPOPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(ROCPPOPlugin(), IncrementalMixin)


def test_roc_ppo_compute_next_returns_state():
    """ROC_PPO compute_full returns _state and compute_next uses it."""
    from src.intelligence.features.i1_indicators.roc_ppo import ROCPPOPlugin

    plugin = ROCPPOPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "roc_14" in inc_result
