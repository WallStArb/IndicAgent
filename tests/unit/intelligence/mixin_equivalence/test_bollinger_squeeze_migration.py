"""Equivalence test for BollingerSqueeze plugin migration to IncrementalMixin (Task 12)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_bollinger_squeeze_full_computation_equivalence():
    """Migrated BollingerSqueeze produces equivalent output to legacy for 500-bar full computation."""
    from src.intelligence.features.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin
    from tests.fixtures.legacy_plugins.bollinger_squeeze_legacy import (
        BollingerSqueezePlugin as BollingerSqueezeLegacy,
    )

    legacy = BollingerSqueezeLegacy()
    migrated = BollingerSqueezePlugin()

    frames = build_synthetic_frames(n_bars=500, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


def test_bollinger_squeeze_uses_incremental_mixin():
    """BollingerSqueeze plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(BollingerSqueezePlugin(), IncrementalMixin)


def test_bollinger_squeeze_compute_next_returns_state():
    """BollingerSqueeze compute_full returns _state key and compute_next uses it."""
    from src.intelligence.features.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin

    plugin = BollingerSqueezePlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "squeeze_active" in inc_result
    assert "squeeze_duration" in inc_result
