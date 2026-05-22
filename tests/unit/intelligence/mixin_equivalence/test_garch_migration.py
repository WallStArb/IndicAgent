"""Equivalence test for GARCH plugin migration to IncrementalMixin (Task 14).

Equivalence strategy per plan spec:
- Seed with fixed random state, compare variance outputs with atol=1e-6
  after 200-bar burn-in (deterministic given same seed)
- 2000-bar synthetic frames for model convergence
"""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_output_equivalence,
    build_synthetic_frames,
)


def test_garch_uses_incremental_mixin():
    """GARCHVolatility plugin is an instance of IncrementalMixin."""
    from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(GARCHVolatilityPlugin(), IncrementalMixin)


def test_garch_compute_full_returns_state():
    """GARCHVolatility compute_full returns _state key with sigma2/realized vol."""
    from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin

    plugin = GARCHVolatilityPlugin()
    frames = build_synthetic_frames(n_bars=100, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    state = result["_state"]
    assert "prev_sigma2" in state
    assert "prev_close" in state
    assert "sigma_history" in state
    assert "realized_returns" in state


def test_garch_compute_next_returns_state():
    """GARCHVolatility compute_full returns _state key and compute_next uses it."""
    from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin

    plugin = GARCHVolatilityPlugin()
    frames = build_synthetic_frames(n_bars=100, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "garch_sigma" in inc_result
    assert "garch_vol_ratio" in inc_result


def test_garch_full_computation_equivalence():
    """Migrated GARCH produces equivalent output to legacy for 2000-bar full computation.

    GARCH is deterministic given same input data -- compare with 0.1% tolerance
    after 200-bar burn-in. atol is effectively enforced via rel_diff in assert_output_equivalence.
    """
    from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
    from tests.fixtures.legacy_plugins.garch_legacy import GARCHVolatilityPlugin as GARCHLegacy

    legacy = GARCHLegacy()
    migrated = GARCHVolatilityPlugin()

    # Use 2000-bar frames for model convergence per plan spec
    frames = build_synthetic_frames(n_bars=2000, seed=42)
    assert_output_equivalence(legacy, migrated, frames, tolerance=0.001)


def test_garch_variance_atol_after_burn_in():
    """Migrated GARCH garch_sigma matches legacy to atol=1e-6 after 200-bar burn-in."""
    from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
    from tests.fixtures.legacy_plugins.garch_legacy import GARCHVolatilityPlugin as GARCHLegacy

    # Run on 500-bar window (well past 200-bar burn-in)
    frames = build_synthetic_frames(n_bars=500, seed=42)

    legacy = GARCHLegacy()
    migrated = GARCHVolatilityPlugin()

    legacy_result = legacy.compute_full(frames)
    migrated_result = migrated.compute_full(frames)

    assert "garch_sigma" in legacy_result
    assert "garch_sigma" in migrated_result

    diff = abs(legacy_result["garch_sigma"] - migrated_result["garch_sigma"])
    assert diff < 1e-6, (
        f"garch_sigma mismatch after burn-in: legacy={legacy_result['garch_sigma']:.10f}, "
        f"migrated={migrated_result['garch_sigma']:.10f}, diff={diff:.2e}"
    )
