"""Equivalence test for HistoricalVolatility plugin migration to IncrementalMixin (Task 11)."""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_historical_volatility_full_computation_equivalence():
    """Migrated HV produces equivalent output to legacy for 500-bar full computation."""
    from src.intelligence.features.i1_indicators.historical_volatility import (
        HistoricalVolatilityPlugin,
    )
    from tests.fixtures.legacy_plugins.historical_volatility_legacy import (
        HistoricalVolatilityPlugin as HVLegacy,
    )

    legacy = HVLegacy()
    migrated = HistoricalVolatilityPlugin()

    frames = build_synthetic_frames(n_bars=500, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


def test_historical_volatility_uses_incremental_mixin():
    """HistoricalVolatility plugin is an instance of IncrementalMixin."""
    from src.intelligence.features.i1_indicators.historical_volatility import (
        HistoricalVolatilityPlugin,
    )
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(HistoricalVolatilityPlugin(), IncrementalMixin)


def test_historical_volatility_compute_next_returns_state():
    """HV compute_full returns _state and compute_next uses it."""
    from src.intelligence.features.i1_indicators.historical_volatility import (
        HistoricalVolatilityPlugin,
    )

    plugin = HistoricalVolatilityPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result
    assert result["_state"] is not None

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "hv_20" in inc_result
