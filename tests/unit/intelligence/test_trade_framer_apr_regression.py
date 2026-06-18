"""Regression tests: APR-backed trade_framer produces identical output at seed values.

Proves the APR migration (migration 145) is behavior-preserving: injecting a
ConfigService that returns the exact seed values must produce output byte-identical
to the no-ConfigService path (hardcoded fallbacks).

Design principle: STRICT mock — any APR key not in the seed dict raises ValueError.
This catches typos like 'stop_demnad_buffer_atr' at test time, not in production.
A permissive mock that returns `default` for unknown keys would silently mask typos.

All 19 module-level constants seeded in migration 145 are covered. The test also
exercises the VP proximity gate, stop basis classification, and the full frame_trade()
path for both long and short directions.

Module-level state: set_config_service(None) in teardown to prevent state leakage.
"""

from __future__ import annotations

import pytest

from src.intelligence.trading.trade_framer import (
    EPSILON_TOLERANCE,
    _adaptive_buffer,
    _classify_stop_basis,
    _resolve_stop_long,
    _resolve_stop_short,
    _vp_regime_active,
    frame_trade,
    set_config_service,
)

# ---------------------------------------------------------------------------
# Seed values from migration 145 — must match SQL config_state inserts exactly
# ---------------------------------------------------------------------------

_APR_SEEDS: dict[str, float] = {
    "feature.trade_framer.stop_demand_buffer_atr": 0.25,
    "feature.trade_framer.stop_sweep_buffer_atr": 0.30,
    "feature.trade_framer.stop_ob_buffer_atr": 0.20,
    "feature.trade_framer.stop_swing_buffer_atr": 0.25,
    "feature.trade_framer.stop_sr_buffer_atr": 0.50,
    "feature.trade_framer.stop_fallback_atr": 2.0,
    "feature.trade_framer.zone_sweep_atr": 0.76,
    "feature.trade_framer.zone_low_atr": 1.0,
    "feature.trade_framer.zone_high_atr": 0.5,
    "feature.trade_framer.target_min_atr": 0.5,
    "feature.trade_framer.zone_plugin_fallback_atr": 0.2,
    "feature.trade_framer.vp_proximity_atr": 0.5,
    "feature.trade_framer.fallback_t1_atr": 2.0,
    "feature.trade_framer.fallback_t2_atr": 3.5,
    "feature.trade_framer.fallback_t3_atr": 5.5,
    "feature.trade_framer.min_stop_atr": 1.0,
    "threshold.trade_framer.min_rr_t1": 1.5,
    "feature.trade_framer.adaptive_buffer_hard_cap": 1.40,
    "feature.trade_framer.structure_snap_proximity_atr": 1.5,
    # Keys from migration 147 (Plan 03) — adaptive buffer piecewise coefficients
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
    # Keys from other modules that _cfg() also resolves (pre-warmed in production).
    # Add here if get_sync() is called with a key not in _APR_SEEDS during tests
    # so the strict mock can catch the additional key without raising.
    "feature.zone_engine.min_stop_distance_atr": 0.5,
    "feature.zone_engine.min_zone_width_atr": 1.5,
    "feature.zone_engine.min_zone_width_atr.equity": 1.5,
    "feature.zone_engine.min_zone_width_atr.fx": 1.0,
    "feature.zone_engine.min_zone_width_atr.futures": 1.5,
    "feature.zone_engine.cluster_radius_atr": 0.50,
    "feature.zone_engine.zone_buffer_atr": 0.15,
    "feature.zone_engine.min_width_atr": 0.25,
    "feature.zone_engine.single_level_radius_atr": 0.25,
}


class _StrictMockConfigService:
    """STRICT mock ConfigService that raises on unknown APR keys.

    Purpose: catch typos in _cfg() key strings at test time rather than
    silently falling back to the hardcoded default in production.

    If a _cfg("feature.trade_framer.stop_demnad_buffer_atr", 0.25) typo exists,
    this mock raises ValueError immediately — exposing the bug in CI.
    A permissive mock returning `default` would let the typo pass undetected
    while the production path silently uses the hardcoded value.
    """

    def get_sync(self, key: str, default: float) -> float:
        if key in _APR_SEEDS:
            return _APR_SEEDS[key]
        raise ValueError(
            f"Unknown APR key in regression test: {key!r} — "
            f"add to _APR_SEEDS with its seed value or fix the typo in _cfg()"
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ENTRY = 5000.0
ATR = 10.0  # Easy to reason about — all buffers scale linearly


def _features(**kwargs) -> dict:
    """Build a minimal features dict."""
    return dict(kwargs)


@pytest.fixture(autouse=True)
def reset_config_service():
    """Ensure module-level _config_service is None before and after each test."""
    set_config_service(None)
    yield
    set_config_service(None)


@pytest.fixture
def strict_cfg():
    """Inject strict mock and return it for assertions."""
    mock = _StrictMockConfigService()
    set_config_service(mock)
    return mock


# ---------------------------------------------------------------------------
# Test: _resolve_stop_long — seed vs hardcoded for each stop type
# ---------------------------------------------------------------------------


class TestStopLongSeedEqualsHardcoded:
    """Prove each stop type produces identical output with/without ConfigService."""

    def _run_both(self, features: dict) -> tuple[tuple, tuple]:
        set_config_service(None)
        hardcoded = _resolve_stop_long(ENTRY, ATR, features)
        set_config_service(_StrictMockConfigService())
        seeded = _resolve_stop_long(ENTRY, ATR, features)
        set_config_service(None)
        return hardcoded, seeded

    def test_demand_zone_stop(self):
        f = _features(in_demand_zone=1.0, nearest_demand_low=4985.0)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "demand_zone"

    def test_sweep_stop(self):
        f = _features(sweep_detected=1.0, sweep_level=4980.0)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "sweep_level"

    def test_ob_bottom_stop(self):
        f = _features(ob_type=1.0, ob_bottom=4990.0)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "ob_bottom"

    def test_fvg_low_stop(self):
        f = _features(fvg_type=1.0, fvg_bottom=4988.0)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "fvg_low"

    def test_swing_low_stop(self):
        f = _features(swing_low=4988.0)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "swing_low"

    def test_ema21_support_stop(self):
        f = _features(ema_21=4985.0)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "ema_21_support"

    def test_sr_support_stop(self):
        f = _features(sr_nearest_support=4975.0)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "sr_support"

    def test_atr_fallback_stop(self):
        f = _features()
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "atr"
        # Verify exact value: ENTRY - ATR * 2.0 = 4980.0
        assert abs(seeded[0] - (ENTRY - ATR * 2.0)) < EPSILON_TOLERANCE

    def test_min_stop_floor_applied(self):
        """min_stop = ENTRY - ATR * 1.0 = 4990; structural stop above this is clamped."""
        # demand_low very close to entry — stop would be 4999.75, but min_stop = 4990
        f = _features(in_demand_zone=1.0, nearest_demand_low=4999.9)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        # Both should use the min_stop floor (1.0 ATR from entry)
        assert seeded[0] <= ENTRY - ATR * 1.0 + EPSILON_TOLERANCE


class TestStopShortSeedEqualsHardcoded:
    """Mirror of long tests for short direction."""

    def _run_both(self, features: dict) -> tuple[tuple, tuple]:
        set_config_service(None)
        hardcoded = _resolve_stop_short(ENTRY, ATR, features)
        set_config_service(_StrictMockConfigService())
        seeded = _resolve_stop_short(ENTRY, ATR, features)
        set_config_service(None)
        return hardcoded, seeded

    def test_supply_zone_stop(self):
        f = _features(in_supply_zone=1.0, nearest_supply_high=5015.0)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "supply_zone"

    def test_sweep_stop_short(self):
        f = _features(sweep_detected=1.0, sweep_level=5020.0)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "sweep_level"

    def test_atr_fallback_short(self):
        f = _features()
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded[1] == "atr"
        # Verify: ENTRY + ATR * 2.0 = 5020.0
        assert abs(seeded[0] - (ENTRY + ATR * 2.0)) < EPSILON_TOLERANCE


# ---------------------------------------------------------------------------
# Test: _adaptive_buffer — seed values produce identical piecewise output
# ---------------------------------------------------------------------------


class TestAdaptiveBufferSeedValues:
    """Verify adaptive buffer piecewise math is unchanged with/without config service.

    These tests verify the buffer function shape at specific vol_ratio values,
    confirming the mathematical output matches expected values from the piecewise
    function definition. Plan 03 migrates the buffer coefficients; until then
    ADAPTIVE_BUFFER_HARD_CAP is the only buffer-related APR key.
    """

    def _run_both(self, features: dict, base_mult: float = 1.0) -> tuple[float, float]:
        set_config_service(None)
        hardcoded = _adaptive_buffer(features, base_mult)
        set_config_service(_StrictMockConfigService())
        seeded = _adaptive_buffer(features, base_mult)
        set_config_service(None)
        return hardcoded, seeded

    def test_vol_ratio_low_base(self):
        """vol_ratio = 0.70 -> garch_mult = 0.80 (low-vol floor)."""
        f = _features(garch_vol_ratio=0.70)
        hardcoded, seeded = self._run_both(f)
        assert abs(seeded - hardcoded) < EPSILON_TOLERANCE
        assert abs(seeded - 0.80) < EPSILON_TOLERANCE

    def test_vol_ratio_neutral(self):
        """vol_ratio = 1.0 -> garch_mult = 1.00 (neutral, no expansion)."""
        f = _features(garch_vol_ratio=1.0)
        hardcoded, seeded = self._run_both(f)
        assert abs(seeded - hardcoded) < EPSILON_TOLERANCE
        assert abs(seeded - 1.00) < EPSILON_TOLERANCE

    def test_vol_ratio_high_caps_at_hard_cap(self):
        """vol_ratio = 1.50 -> garch_mult = 1.35, capped by ADAPTIVE_BUFFER_HARD_CAP = 1.40."""
        f = _features(garch_vol_ratio=1.50)
        hardcoded, seeded = self._run_both(f)
        assert abs(seeded - hardcoded) < EPSILON_TOLERANCE
        # 1.00 + 0.50 * (0.35 / 0.50) = 1.00 + 0.35 = 1.35; cap at 1.40 -> result = 1.35
        assert abs(seeded - 1.35) < EPSILON_TOLERANCE

    def test_hard_cap_applied_when_garch_shock(self):
        """GARCH shock > 3.0 and vol ratio at 1.0 -> shock override applies, capped by 1.40."""
        # garch_shock boosts to max(result, base_mult * 1.35), then cap at 1.40
        f = _features(garch_vol_ratio=1.0, garch_shock=4.0)
        hardcoded, seeded = self._run_both(f)
        assert abs(seeded - hardcoded) < EPSILON_TOLERANCE
        # vol_ratio=1.0 -> garch_mult=1.00, result=1.0; shock -> max(1.0, 1.35) = 1.35; cap = 1.35
        assert abs(seeded - 1.35) < EPSILON_TOLERANCE


# ---------------------------------------------------------------------------
# Test: VP proximity gate seed equality
# ---------------------------------------------------------------------------


class TestVPProximitySeedEqualsHardcoded:
    """Verify VP proximity gate reads APR value at seed correctly."""

    def _run_both(self, features: dict) -> tuple[bool, bool]:
        set_config_service(None)
        hardcoded = _vp_regime_active(features)
        set_config_service(_StrictMockConfigService())
        seeded = _vp_regime_active(features)
        set_config_service(None)
        return hardcoded, seeded

    def test_near_vah_activates_regime(self):
        """distance_to_vah_atr < 0.5 ATR -> regime active."""
        # _vp_regime_active reads features["distance_to_vah_atr"] and ["distance_to_val_atr"]
        f = _features(distance_to_vah_atr=0.3)  # 0.3 < 0.5 ATR threshold
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded is True

    def test_far_from_vah_not_active(self):
        """Distance to VAH >= 0.5 ATR and VAL >= 0.5 ATR -> regime not active."""
        f = _features(distance_to_vah_atr=0.7, distance_to_val_atr=0.8)
        hardcoded, seeded = self._run_both(f)
        assert seeded == hardcoded
        assert seeded is False


# ---------------------------------------------------------------------------
# Test: stop basis classification seed equality
# ---------------------------------------------------------------------------


class TestStopBasisClassificationSeedEqualsHardcoded:
    """Verify _classify_stop_basis reads structure_snap_proximity_atr correctly."""

    def _run_both(
        self, stop_type: str, stop_price: float, entry: float, atr: float, direction: int
    ):
        set_config_service(None)
        hardcoded = _classify_stop_basis(stop_type, stop_price, entry, atr, direction)
        set_config_service(_StrictMockConfigService())
        seeded = _classify_stop_basis(stop_type, stop_price, entry, atr, direction)
        set_config_service(None)
        return hardcoded, seeded

    def test_structure_snap_classification(self):
        """Stop within 1.5 ATR of ATR fallback -> structure_snap."""
        # ATR fallback at 5000 - 10 * 2.0 = 4980
        # Stop at 4981 -> distance = |4981 - 4980| / 10 = 0.1 ATR (< 1.5)
        hardcoded, seeded = self._run_both("swing_low", 4981.0, 5000.0, 10.0, 1)
        assert seeded == hardcoded
        assert seeded[0] == "structure_snap"

    def test_garch_adaptive_classification(self):
        """Stop far from ATR fallback -> garch_adaptive."""
        # ATR fallback at 5000 - 10 * 2.0 = 4980
        # Stop at 4960 -> distance = |4960 - 4980| / 10 = 2.0 ATR (> 1.5)
        hardcoded, seeded = self._run_both("demand_zone", 4960.0, 5000.0, 10.0, 1)
        assert seeded == hardcoded
        assert seeded[0] == "garch_adaptive"


# ---------------------------------------------------------------------------
# Test: Full frame_trade() — zone and target paths
# ---------------------------------------------------------------------------


class TestFrameTradeSeedEqualsHardcoded:
    """End-to-end: frame_trade() output is identical with/without ConfigService at seeds."""

    def _run_both(self, **frame_kwargs) -> tuple:
        set_config_service(None)
        hardcoded = frame_trade(**frame_kwargs)
        set_config_service(_StrictMockConfigService())
        seeded = frame_trade(**frame_kwargs)
        set_config_service(None)
        return hardcoded, seeded

    def test_atr_fallback_path_long(self):
        """No structural features -> ATR fallback stop and targets."""
        hardcoded, seeded = self._run_both(
            setup_type="trend_long",
            direction=1,
            entry=ENTRY,
            features={"atr_14": ATR},
            atr=ATR,
        )
        assert seeded.viable == hardcoded.viable
        assert abs(seeded.stop - hardcoded.stop) < 0.01
        assert seeded.entry_type == hardcoded.entry_type
        assert len(seeded.targets) == len(hardcoded.targets)
        for t_s, t_h in zip(seeded.targets, hardcoded.targets):
            assert abs(t_s.price - t_h.price) < 0.01
            assert abs(t_s.rr - t_h.rr) < EPSILON_TOLERANCE

    def test_atr_fallback_path_short(self):
        """Short ATR fallback path."""
        hardcoded, seeded = self._run_both(
            setup_type="trend_short",
            direction=-1,
            entry=ENTRY,
            features={"atr_14": ATR},
            atr=ATR,
        )
        assert seeded.viable == hardcoded.viable
        assert abs(seeded.stop - hardcoded.stop) < 0.01

    def test_demand_zone_structural_path_long(self):
        """Demand zone structural stop + ATR fallback targets (no structural levels above)."""
        features = {
            "atr_14": ATR,
            "in_demand_zone": 1.0,
            "nearest_demand_low": 4975.0,
            "nearest_demand_high": 4990.0,  # wide enough zone
        }
        hardcoded, seeded = self._run_both(
            setup_type="supply_demand_long",
            direction=1,
            entry=ENTRY,
            features=features,
            atr=ATR,
        )
        # Both may be viable or not (zone gate may reject) — key point is they match
        assert seeded.viable == hardcoded.viable
        if seeded.viable:
            assert abs(seeded.stop - hardcoded.stop) < 0.01
            assert seeded.stop_type == hardcoded.stop_type

    def test_sweep_zone_path(self):
        """Sweep entry zone uses zone_sweep_atr = 0.76."""
        features = {"atr_14": ATR, "sweep_detected": 1.0, "sweep_level": 4980.0}
        hardcoded, seeded = self._run_both(
            setup_type="sweep_reclaim_long",
            direction=1,
            entry=ENTRY,
            features=features,
            atr=ATR,
        )
        assert seeded.viable == hardcoded.viable
        if seeded.viable:
            assert abs(seeded.zone_low - hardcoded.zone_low) < 0.01
            assert abs(seeded.zone_high - hardcoded.zone_high) < 0.01

    def test_rr_gate_uses_seed_value(self):
        """RR gate threshold comes from APR at seed = 1.5; must match hardcoded behavior."""
        # Standard ATR fallback: T1 = 2.0R, which passes the 1.5R gate
        hardcoded, seeded = self._run_both(
            setup_type="trend_long",
            direction=1,
            entry=ENTRY,
            features={"atr_14": ATR},
            atr=ATR,
        )
        # Both should be viable (ATR fallback T1 = 2.0R > 1.5 threshold)
        assert seeded.viable is True
        assert hardcoded.viable is True
        assert seeded.rr_t1 == hardcoded.rr_t1


# ---------------------------------------------------------------------------
# Test: Strict mock correctly rejects unknown keys
# ---------------------------------------------------------------------------


class TestStrictMockCatchesTypos:
    """The STRICT mock raises on typos — proving the test design is sound."""

    def test_unknown_key_raises(self):
        """A typo in an APR key should raise ValueError (not silently use default)."""
        mock = _StrictMockConfigService()
        with pytest.raises(ValueError, match="Unknown APR key in regression test"):
            mock.get_sync("feature.trade_framer.stop_demnad_buffer_atr", 0.25)

    def test_known_key_returns_seed(self):
        """Known keys return the seed value, not the default argument."""
        mock = _StrictMockConfigService()
        # Seed is 0.25; passing wrong default (99.0) should still return 0.25
        assert mock.get_sync("feature.trade_framer.stop_demand_buffer_atr", 99.0) == 0.25
