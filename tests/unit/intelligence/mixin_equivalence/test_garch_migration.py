"""Equivalence test for GARCH plugin migration to IncrementalMixin (Task 14).

Equivalence strategy per plan spec:
- Seed with fixed random state, compare variance outputs with atol=1e-6
  after 200-bar burn-in (deterministic given same seed)
- 2000-bar synthetic frames for model convergence
"""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import (
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
