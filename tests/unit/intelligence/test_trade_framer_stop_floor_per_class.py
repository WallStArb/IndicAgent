"""Per-class stop floor regression tests (Phase 132 A3, migration 148).

Tests _min_stop_multiplier_floor(asset_class) routing and its effect on
_resolve_stop_long / _resolve_stop_short.

Design principles:
- STRICT mock ConfigService: raises ValueError for unknown keys to catch typos.
- seed dict covers migration 148 keys + all upstream keys the router may call.
- teardown resets set_config_service(None) to prevent state leakage.
"""

from __future__ import annotations

import pytest

from src.intelligence.trading.trade_framer import (
    _min_stop_multiplier_floor,
    _resolve_stop_long,
    _resolve_stop_short,
    set_config_service,
)

# ---------------------------------------------------------------------------
# Seed values from migration 148 + upstream keys required by _cfg() calls
# ---------------------------------------------------------------------------

_MIGRATION_148_SEEDS: dict[str, float] = {
    # --- Per-class stop floor keys (migration 148) ---
    "feature.trade_framer.stop_multiplier_floor.fx": 1.0,
    "feature.trade_framer.stop_multiplier_floor.commodity_small_tick": 1.5,
    "feature.trade_framer.stop_multiplier_floor.equity_etf": 1.0,
    "feature.trade_framer.stop_multiplier_floor.futures_large_tick": 1.0,
    # --- Universal min_stop_atr (migration 146) — used as default/fallback ---
    "feature.trade_framer.min_stop_atr": 1.0,
    # --- Adaptive buffer coefficients (migration 147) — called by _adaptive_buffer ---
    "feature.trade_framer.adaptive_buffer_vol_ratio_min": 0.70,
    "feature.trade_framer.adaptive_buffer_vol_ratio_max": 1.50,
    "feature.trade_framer.adaptive_buffer_low_vol_base": 0.80,
    "feature.trade_framer.adaptive_buffer_low_vol_slope_num": 0.20,
    "feature.trade_framer.adaptive_buffer_low_vol_slope_den": 0.30,
    "feature.trade_framer.adaptive_buffer_high_vol_slope_num": 0.35,
    "feature.trade_framer.adaptive_buffer_high_vol_slope_den": 0.50,
    "feature.trade_framer.adaptive_buffer_hurst_trend_threshold": 0.55,
    "feature.trade_framer.adaptive_buffer_hurst_mr_threshold": 0.45,
    "feature.trade_framer.adaptive_buffer_hurst_tighten_rate": 0.16,
    "feature.trade_framer.adaptive_buffer_garch_shock_threshold": 3.0,
    "feature.trade_framer.adaptive_buffer_garch_shock_mult": 1.35,
    "feature.trade_framer.adaptive_buffer_hard_cap": 1.40,
    # --- Stop placement multipliers (migration 146) ---
    "feature.trade_framer.stop_demand_buffer_atr": 0.25,
    "feature.trade_framer.stop_sweep_buffer_atr": 0.30,
    "feature.trade_framer.stop_ob_buffer_atr": 0.20,
    "feature.trade_framer.stop_swing_buffer_atr": 0.25,
    "feature.trade_framer.stop_sr_buffer_atr": 0.50,
    "feature.trade_framer.stop_fallback_atr": 2.0,
}


class _StrictMockConfigService:
    """Raises ValueError for any key not in the seed dict.

    This ensures _cfg() key typos fail loudly in tests rather than silently
    using the hardcoded default in production.
    """

    def get_sync(self, key: str, default: float) -> float:  # noqa: ARG002
        if key in _MIGRATION_148_SEEDS:
            return _MIGRATION_148_SEEDS[key]
        raise ValueError(
            f"Unknown APR key in per-class stop floor test: {key!r} — "
            f"add to _MIGRATION_148_SEEDS with its seed value or fix the typo in _cfg()"
        )


ENTRY = 5000.0
ATR = 10.0  # $10 ATR — easy to reason about; all buffers scale linearly
TICK_SIZE = 0.25  # ES-like tick size for pathological tests


def _features(**kwargs) -> dict:
    return dict(kwargs)


@pytest.fixture(autouse=True)
def reset_config_service():
    """Reset module-level _config_service before and after each test."""
    set_config_service(None)
    yield
    set_config_service(None)


@pytest.fixture
def strict_cfg():
    """Inject strict mock ConfigService."""
    mock = _StrictMockConfigService()
    set_config_service(mock)
    return mock


# ---------------------------------------------------------------------------
# Unit tests for _min_stop_multiplier_floor
# ---------------------------------------------------------------------------


class TestMinStopMultiplierFloor:
    """Direct unit tests for the router function."""

    def test_commodity_small_tick_returns_1_5(self, strict_cfg):
        result = _min_stop_multiplier_floor("commodity_small_tick")
        assert result == pytest.approx(1.5)

    def test_equity_etf_returns_1_0(self, strict_cfg):
        result = _min_stop_multiplier_floor("equity_etf")
        assert result == pytest.approx(1.0)

    def test_fx_returns_1_0(self, strict_cfg):
        result = _min_stop_multiplier_floor("fx")
        assert result == pytest.approx(1.0)

    def test_futures_large_tick_returns_1_0(self, strict_cfg):
        result = _min_stop_multiplier_floor("futures_large_tick")
        assert result == pytest.approx(1.0)

    def test_none_returns_universal_min_stop_atr(self, strict_cfg):
        """No asset_class → universal min_stop_atr (1.0) as fallback."""
        result = _min_stop_multiplier_floor(None)
        assert result == pytest.approx(1.0)

    def test_unknown_class_returns_universal_fallback(self, strict_cfg):
        """Unknown asset class key absent in APR → falls back to min_stop_atr default.

        When _cfg("feature.trade_framer.stop_multiplier_floor.unknown_class", default)
        is called and the key is not in config_state, ConfigService returns the default
        (i.e., min_stop_atr=1.0). In our strict mock this key is absent, so we need
        to verify the fallback chain: the strict mock raises for the per-class key,
        but _min_stop_multiplier_floor must pass `default` to _cfg() so the mock
        returns the default.

        Actually: the strict mock raises for unknown keys. _min_stop_multiplier_floor
        calls _cfg(f"...{asset_class}", default) and the mock would raise. We need
        to test with a permissive mock for the fallback path, or simply test without
        config service (None path).
        """
        # Test with no config service — should return min_stop_atr seed (1.0)
        set_config_service(None)
        result = _min_stop_multiplier_floor("unknown_class")
        # Without config service, returns _cfg("feature.trade_framer.min_stop_atr", 1.0)
        # which uses the hardcoded default 1.0 since _config_service is None
        assert result == pytest.approx(1.0)

    def test_none_no_config_service_returns_1_0(self):
        """Without ConfigService, universal default (1.0) is returned."""
        set_config_service(None)
        result = _min_stop_multiplier_floor(None)
        assert result == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Integration tests: per-class floor applied in _resolve_stop_long
# ---------------------------------------------------------------------------


class TestPerClassFloorAppliedInLongStop:
    """Verify _min_stop_multiplier_floor is the effective min for long stops."""

    def test_commodity_floor_1_5_atr_minimum(self, strict_cfg):
        """Commodity min_stop must be >= 1.5 * ATR from entry at vol_ratio=1.0.

        At vol_ratio=1.0: garch_mult = low_vol_base + (1.0 - vol_ratio_min) * slope
                        = 0.80 + (1.0 - 0.70) * (0.20/0.30) = 0.80 + 0.20 = 1.00
        So _adaptive_buffer(base_mult=1.5, vol_ratio=1.0) = 1.5 * 1.0 = 1.5
        min_stop for long = entry - atr * 1.5 = 5000 - 10 * 1.5 = 4985.0
        """
        f = _features(asset_class="commodity_small_tick", garch_vol_ratio=1.0)
        stop, _ = _resolve_stop_long(ENTRY, ATR, f)
        expected_min_stop = ENTRY - ATR * 1.5
        assert (
            stop <= expected_min_stop + 1e-9
        ), f"stop {stop:.4f} must be <= min_stop {expected_min_stop:.4f} for commodity_small_tick"

    def test_equity_etf_floor_1_0_atr_minimum(self, strict_cfg):
        """Equity ETF min_stop floor is 1.0 ATR (same as universal)."""
        f = _features(asset_class="equity_etf", garch_vol_ratio=1.0)
        stop, _ = _resolve_stop_long(ENTRY, ATR, f)
        expected_min_stop = ENTRY - ATR * 1.0
        assert (
            stop <= expected_min_stop + 1e-9
        ), f"stop {stop:.4f} must be <= min_stop {expected_min_stop:.4f} for equity_etf"

    def test_commodity_stop_below_fx_stop_at_same_features(self, strict_cfg):
        """commodity_small_tick floor (1.5) produces a lower stop than fx floor (1.0)
        when the fallback ATR path is taken (no structural levels).
        """
        f_commodity = _features(asset_class="commodity_small_tick", garch_vol_ratio=1.0)
        f_fx = _features(asset_class="fx", garch_vol_ratio=1.0)
        stop_commodity, _ = _resolve_stop_long(ENTRY, ATR, f_commodity)
        stop_fx, _ = _resolve_stop_long(ENTRY, ATR, f_fx)
        # commodity must have a wider (lower) min_stop boundary
        assert (
            stop_commodity <= stop_fx + 1e-9
        ), f"commodity stop {stop_commodity:.4f} should be <= fx stop {stop_fx:.4f}"


# ---------------------------------------------------------------------------
# Integration tests: per-class floor applied in _resolve_stop_short
# ---------------------------------------------------------------------------


class TestPerClassFloorAppliedInShortStop:
    """Verify _min_stop_multiplier_floor is the effective min for short stops."""

    def test_commodity_floor_1_5_atr_minimum_short(self, strict_cfg):
        """Commodity max_stop must be >= 1.5 * ATR above entry at vol_ratio=1.0."""
        f = _features(asset_class="commodity_small_tick", garch_vol_ratio=1.0)
        stop, _ = _resolve_stop_short(ENTRY, ATR, f)
        expected_max_stop = ENTRY + ATR * 1.5
        assert (
            stop >= expected_max_stop - 1e-9
        ), f"stop {stop:.4f} must be >= max_stop {expected_max_stop:.4f} for commodity_small_tick short"

    def test_futures_floor_1_0_atr_minimum_short(self, strict_cfg):
        """Futures max_stop floor is 1.0 ATR above entry."""
        f = _features(asset_class="futures_large_tick", garch_vol_ratio=1.0)
        stop, _ = _resolve_stop_short(ENTRY, ATR, f)
        expected_max_stop = ENTRY + ATR * 1.0
        assert (
            stop >= expected_max_stop - 1e-9
        ), f"stop {stop:.4f} must be >= max_stop {expected_max_stop:.4f} for futures_large_tick short"


# ---------------------------------------------------------------------------
# Pathological tiny-ATR case: stop_distance floor gate (Phase 126 invariant)
# ---------------------------------------------------------------------------


class TestPhase126StopDistanceGatePreserved:
    """The Phase 126 stop_too_close gate still applies independently.

    This test does NOT call frame_trade() — that would require the full
    features dict including zone bounds. Instead, we verify that the
    min_stop floor computed by _resolve_stop_long always maintains a
    stop at least ATR * per_class_floor from entry for any asset class,
    confirming the floor is applied correctly even with a tiny ATR.

    The stop_distance floor gate (feature.zone_engine.min_stop_distance_atr)
    is inside frame_trade() after zone resolution — it's a frame-level gate,
    not a stop-resolution gate. We test it separately here by confirming
    that _min_stop_multiplier_floor returns appropriate values that would
    produce a valid distance.
    """

    def test_tiny_atr_commodity_still_applies_1_5_floor(self, strict_cfg):
        """With a tiny ATR (e.g., 0.001), commodity floor is still 1.5x that ATR."""
        tiny_atr = 0.001
        f = _features(asset_class="commodity_small_tick", garch_vol_ratio=1.0)
        stop, _ = _resolve_stop_long(ENTRY, tiny_atr, f)
        # min_stop = entry - tiny_atr * 1.5 (at vol_ratio=1.0, garch_mult=1.0)
        expected_floor = ENTRY - tiny_atr * 1.5
        assert stop <= expected_floor + 1e-12

    def test_zero_class_config_service_uses_universal_fallback(self):
        """Without ConfigService, the universal 1.0 ATR floor applies for any class."""
        set_config_service(None)
        f = _features(asset_class="commodity_small_tick", garch_vol_ratio=1.0)
        stop, _ = _resolve_stop_long(ENTRY, ATR, f)
        # Without config, min_stop_multiplier_floor returns 1.0 (universal fallback)
        expected_floor = ENTRY - ATR * 1.0
        assert stop <= expected_floor + 1e-9
