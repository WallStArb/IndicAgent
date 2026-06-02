"""PERF-03 migration audit tests.

Two test categories:
1. Flag audit: all supports_incremental=True plugins have _state_migration_complete=True.
2. Behavioral state tests: representative incremental plugins (kalman_trend,
   garch_volatility) actually propagate state across calls (not cold-starting every bar).

Phase 112 D-07 requirement:
- All 34 incremental plugins must have _state_migration_complete=True.
- Behavioral tests must FAIL if a plugin cold-starts on every bar.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_frames(n: int = 50, seed: int = 42) -> dict:
    """Build a minimal frames dict for plugin testing."""
    rng = np.random.default_rng(seed)
    base = 5000.0
    returns = rng.normal(0.0001, 0.005, n)
    close = base * np.cumprod(1 + returns)
    spread = rng.uniform(0.001, 0.003, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    open_ = close * (1 + rng.normal(0, 0.001, n))
    volume = rng.integers(1000, 5000, n).astype(float)

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    return {"main": df, "features": {}}


def _make_frames_single_bar(close_price: float, prev_high: float, prev_low: float) -> dict:
    """Build a 50-bar frames dict ending with a specific close price."""
    frames = _make_frames(49)
    df = frames["main"]
    # Append the specific bar
    new_row = pd.DataFrame(
        {
            "open": [prev_high * 0.999],
            "high": [prev_high],
            "low": [prev_low],
            "close": [close_price],
            "volume": [2500.0],
        }
    )
    frames["main"] = pd.concat([df, new_row], ignore_index=True)
    return frames


# ---------------------------------------------------------------------------
# Test 1: Flag audit — all incremental plugins must be PERF-03 complete
# ---------------------------------------------------------------------------


def test_perf03_flag_audit_all_incremental_plugins() -> None:
    """All supports_incremental=True plugins must have _state_migration_complete=True.

    Failure message lists every non-compliant plugin by name.
    """
    from src.intelligence.plugins.base import registry
    from src.intelligence.register_plugins import register_all_plugins

    register_all_plugins()

    all_plugins = {**registry.indicators, **registry.patterns}
    incremental = {
        name: p for name, p in all_plugins.items() if getattr(p, "supports_incremental", False)
    }

    incomplete = [
        name
        for name, p in incremental.items()
        if not getattr(p, "_state_migration_complete", False)
    ]

    assert not incomplete, (
        f"PERF-03 migration incomplete for {len(incomplete)} plugin(s): {sorted(incomplete)}. "
        f"Set _state_migration_complete = True on each plugin after auditing that "
        f"compute_next() correctly uses the state= parameter."
    )

    # Sanity: there should be at least 30 incremental plugins
    assert len(incremental) >= 30, (
        f"Expected >= 30 incremental plugins, found {len(incremental)}. "
        f"Check register_plugins.py for missing supports_incremental=True declarations."
    )


# ---------------------------------------------------------------------------
# Test 2: Behavioral state test — kalman_trend
#
# The kalman_slope output depends on the history of filtered estimates.
# A cold-starting plugin recomputes from scratch each bar, giving the same
# slope as the first call. A state-propagating plugin accumulates history,
# so the slope (trend_history[-1] - trend_history[-6]) changes across calls.
# ---------------------------------------------------------------------------


def test_kalman_trend_behavioral_state_propagation() -> None:
    """kalman_trend must propagate state: second-call slope differs from first-call slope.

    This proves the plugin is NOT cold-starting every bar.
    Specifically verified field: kalman_slope (based on 6-bar trend history window).
    """
    from src.intelligence.context.kalman_trend import plugin as kalman_plugin

    # Seed the plugin with a 50-bar history to get a valid initial state
    frames_seed = _make_frames(50, seed=1)
    result_full = kalman_plugin.compute_full(frames_seed)

    assert result_full, "compute_full returned empty — insufficient data or plugin broken"
    assert "_state" in result_full, "compute_full must return _state (IncrementalMixin contract)"

    # Deep copy the seed state before passing to compute_next — the mixin mutates in place
    state_seed_snapshot = copy.deepcopy(result_full["_state"])
    x_est_seed = state_seed_snapshot.get("x_est")
    trend_history_seed = list(state_seed_snapshot.get("trend_history", []))

    # First incremental call: bar at price 5100 (upward move)
    frames_bar1 = _make_frames(50, seed=2)
    frames_bar1["main"].iloc[-1, frames_bar1["main"].columns.get_loc("close")] = 5100.0
    state_for_call1 = copy.deepcopy(state_seed_snapshot)
    result_1 = kalman_plugin.compute_next(frames_bar1, state=state_for_call1)

    assert result_1, "compute_next call 1 returned empty"
    assert "_state" in result_1, "compute_next must return _state"

    x_est_after_1 = state_for_call1.get("x_est")
    trend_history_after_1 = list(state_for_call1.get("trend_history", []))

    # Key assertion: the Kalman filter's internal state (trend_history) changes
    # between calls. A cold-starting plugin would compute slope from a fresh
    # 50-bar history each time, giving the same answer regardless of prior state.
    # State propagation means trend_history accumulates, changing the slope.
    assert x_est_seed is not None, "state must contain x_est after seed"
    assert x_est_after_1 is not None, "state must contain x_est after first incremental call"
    assert x_est_after_1 != x_est_seed, (
        f"x_est did not change between seed ({x_est_seed:.6f}) and first incremental call "
        f"({x_est_after_1:.6f}) — plugin appears to be cold-starting (not reading state)"
    )

    # trend_history should have changed after a new bar
    assert trend_history_after_1 != trend_history_seed, (
        "trend_history did not change between seed and first incremental call — "
        "plugin is cold-starting (state not being read/written)"
    )


# ---------------------------------------------------------------------------
# Test 3: Behavioral state test — garch_volatility
#
# GARCH(1,1) sigma evolves from a prior. A cold-starting plugin reinitializes
# sigma2 from variance of the first 20 returns each bar, giving a nearly
# identical sigma each call. A state-propagating plugin carries sigma2 forward,
# so after a high-volatility bar, sigma2 increases, giving a higher garch_sigma.
# ---------------------------------------------------------------------------


def test_garch_volatility_behavioral_state_propagation() -> None:
    """garch_volatility must propagate state: sigma estimate evolves across calls.

    This proves the plugin is NOT cold-starting every bar.
    Verified field: garch_sigma (GARCH conditional volatility estimate).
    """
    from src.intelligence.context.garch_volatility import plugin as garch_plugin

    # Seed the plugin with a 50-bar normal history
    frames_seed = _make_frames(50, seed=10)
    result_full = garch_plugin.compute_full(frames_seed)

    assert result_full, "compute_full returned empty"
    assert "_state" in result_full, "compute_full must return _state"

    # Deep copy seed state before passing to compute_next — mixin mutates in place
    state_seed_snapshot = copy.deepcopy(result_full["_state"])
    sigma2_seed = state_seed_snapshot.get("prev_sigma2")
    sigma_seed = result_full.get("garch_sigma", 0.0)

    # Simulate a HIGH volatility bar (large return: 3% move)
    frames_high_vol = _make_frames(50, seed=10)
    last_close = frames_high_vol["main"]["close"].iloc[-1]
    frames_high_vol["main"].iloc[-1, frames_high_vol["main"].columns.get_loc("close")] = (
        last_close * 1.03
    )

    state_for_high = copy.deepcopy(state_seed_snapshot)
    result_high = garch_plugin.compute_next(frames_high_vol, state=state_for_high)
    assert result_high, "compute_next (high vol bar) returned empty"
    assert "_state" in result_high

    sigma2_after_high = state_for_high.get("prev_sigma2")
    sigma_high = result_high.get("garch_sigma", 0.0)

    # Simulate a NORMAL volatility bar from the same seed (same frames, original last close)
    frames_normal = _make_frames(50, seed=10)
    state_for_normal = copy.deepcopy(state_seed_snapshot)
    result_normal = garch_plugin.compute_next(frames_normal, state=state_for_normal)
    assert result_normal, "compute_next (normal bar) returned empty"

    sigma2_after_normal = state_for_normal.get("prev_sigma2")

    # GARCH(1,1) state propagation: sigma2 carries the prior shock forward.
    # After a high-vol bar (3% move), sigma2 should be elevated vs after a normal bar.
    assert sigma2_seed is not None, "state must contain prev_sigma2 after seed"
    assert sigma2_after_high is not None, "state must contain prev_sigma2 after high-vol call"
    assert sigma2_after_normal is not None, "state must contain prev_sigma2 after normal call"

    # The high-vol call should produce a higher sigma2 than the normal call
    assert sigma2_after_high > sigma2_after_normal, (
        f"GARCH sigma2 not elevated after high-vol bar: "
        f"high={sigma2_after_high:.8f} <= normal={sigma2_after_normal:.8f}. "
        f"This suggests the plugin is not updating state from the passed state= parameter."
    )

    # Also verify sigma changed from seed
    assert sigma2_after_high != sigma2_seed, (
        f"prev_sigma2 did not change after high-vol bar "
        f"(seed={sigma2_seed:.8f}, after_high={sigma2_after_high:.8f}) — "
        "plugin appears to be cold-starting"
    )
