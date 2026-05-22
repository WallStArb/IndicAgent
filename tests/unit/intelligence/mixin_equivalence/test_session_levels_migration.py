"""Equivalence test for SessionLevels plugin migration to IncrementalMixin (Task 12)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    build_synthetic_frames,
)


def test_session_levels_uses_incremental_mixin():
    """SessionLevels plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i3_structure.session_levels import SessionLevelsPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(SessionLevelsPlugin(), IncrementalMixin)


def test_session_levels_compute_next_returns_state():
    """SessionLevels compute_full returns _state key and compute_next uses it."""
    from src.intelligence.features.i3_structure.session_levels import SessionLevelsPlugin

    plugin = SessionLevelsPlugin()
    frames = build_synthetic_frames(n_bars=500, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    # Prior session keys should be present
    assert "prior_session_high" in inc_result
    assert "weekly_pivot" in inc_result
