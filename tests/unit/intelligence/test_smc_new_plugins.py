"""Tests for new SMC plugins: ICTKillzones, AMDCycle, BreakerBlocks,
MitigationBlocks, PremiumDiscount.
"""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# ICTKillzones
# ---------------------------------------------------------------------------


class TestICTKillzones:
    def test_london_killzone_at_0800_utc(self):
        from src.intelligence.smart_money.ict_killzones import ICTKillzonesPlugin

        ts = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)  # 8am UTC = 3am ET = London KZ
        df = pd.DataFrame({
            "timestamp": [ts],
            "open": [5000.0], "high": [5010.0], "low": [4990.0],
            "close": [5005.0], "volume": [1000.0],
        })
        result = ICTKillzonesPlugin().compute_full({"main": df, "features": {}})
        assert result.get("in_london_killzone") == 1.0
        assert result.get("killzone_name") == "london"
        assert result.get("in_ny_am_killzone") == 0.0

    def test_ny_am_killzone_at_1400_utc(self):
        from src.intelligence.smart_money.ict_killzones import ICTKillzonesPlugin

        ts = datetime(2026, 3, 2, 14, 0, tzinfo=UTC)  # 9am ET = NY AM KZ
        df = pd.DataFrame({
            "timestamp": [ts],
            "open": [5000.0], "high": [5010.0], "low": [4990.0],
            "close": [5005.0], "volume": [1000.0],
        })
        result = ICTKillzonesPlugin().compute_full({"main": df, "features": {}})
        assert result.get("in_ny_am_killzone") == 1.0
        assert result.get("killzone_name") == "ny_am"

    def test_outside_killzone_all_zeros(self):
        from src.intelligence.smart_money.ict_killzones import ICTKillzonesPlugin

        ts = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)  # noon UTC — between killzones
        df = pd.DataFrame({
            "timestamp": [ts],
            "open": [5000.0], "high": [5010.0], "low": [4990.0],
            "close": [5005.0], "volume": [1000.0],
        })
        result = ICTKillzonesPlugin().compute_full({"main": df, "features": {}})
        assert result.get("in_asia_killzone") == 0.0
        assert result.get("in_london_killzone") == 0.0
        assert result.get("in_ny_am_killzone") == 0.0
        assert result.get("in_ny_pm_killzone") == 0.0
        assert result.get("killzone_name") is None

    def test_minutes_until_next_positive(self):
        from src.intelligence.smart_money.ict_killzones import ICTKillzonesPlugin

        ts = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
        df = pd.DataFrame({
            "timestamp": [ts],
            "open": [5000.0], "high": [5010.0], "low": [4990.0],
            "close": [5005.0], "volume": [1000.0],
        })
        result = ICTKillzonesPlugin().compute_full({"main": df, "features": {}})
        assert result.get("minutes_until_next_killzone", 0) > 0

    def test_no_timestamp_returns_result(self):
        """Without timestamp column, falls back to current time — should not crash."""
        from src.intelligence.smart_money.ict_killzones import ICTKillzonesPlugin

        close = np.linspace(5000, 5010, 3)
        df = make_ohlcv(close)
        result = ICTKillzonesPlugin().compute_full({"main": df, "features": {}})
        assert isinstance(result, dict)
        assert "in_london_killzone" in result

    def test_empty_returns_empty(self):
        from src.intelligence.smart_money.ict_killzones import ICTKillzonesPlugin

        assert ICTKillzonesPlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# AMDCycle
# ---------------------------------------------------------------------------


class TestAMDCycle:
    def _make_df(self, hour_utc: int, close: float = 5000.0) -> pd.DataFrame:
        ts = datetime(2026, 3, 2, hour_utc, 0, tzinfo=UTC)
        return pd.DataFrame({
            "timestamp": [ts, ts],
            "open": [close - 5, close - 3],
            "high": [close + 10, close + 10],
            "low": [close - 10, close - 10],
            "close": [close - 2, close],
            "volume": [1000.0, 1000.0],
        })

    def test_accumulation_phase_at_21_utc(self):
        from src.intelligence.smart_money.amd_cycle import AMDCyclePlugin

        df = self._make_df(21)
        result = AMDCyclePlugin().compute_full({"main": df, "features": {}})
        assert result.get("amd_phase") == "accumulation"

    def test_manipulation_phase_at_03_utc(self):
        from src.intelligence.smart_money.amd_cycle import AMDCyclePlugin

        df = self._make_df(3)
        result = AMDCyclePlugin().compute_full({"main": df, "features": {}})
        assert result.get("amd_phase") == "manipulation"

    def test_distribution_phase_at_14_utc(self):
        from src.intelligence.smart_money.amd_cycle import AMDCyclePlugin

        df = self._make_df(14)
        result = AMDCyclePlugin().compute_full({"main": df, "features": {}})
        assert result.get("amd_phase") == "distribution"

    def test_amd_fields_present(self):
        from src.intelligence.smart_money.amd_cycle import AMDCyclePlugin

        close = np.linspace(5000, 5010, 5)
        df = make_ohlcv(close)
        result = AMDCyclePlugin().compute_full({"main": df, "features": {}})
        assert "amd_phase" in result
        assert "amd_manipulation_detected" in result
        assert "amd_distribution_direction" in result

    def test_empty_returns_empty(self):
        from src.intelligence.smart_money.amd_cycle import AMDCyclePlugin

        assert AMDCyclePlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# BreakerBlocks
# ---------------------------------------------------------------------------


class TestBreakerBlocks:
    def test_no_ob_features_returns_null(self):
        from src.intelligence.smart_money.breaker_blocks import BreakerBlocksPlugin

        close = np.linspace(5000, 5010, 5)
        df = make_ohlcv(close)
        result = BreakerBlocksPlugin().compute_full({"main": df, "features": {}})
        assert result.get("breaker_block_active") == 0.0

    def test_mitigated_ob_stores_breaker(self):
        from src.intelligence.smart_money.breaker_blocks import BreakerBlocksPlugin

        plugin = BreakerBlocksPlugin()
        close = np.linspace(5000, 5010, 5)
        df = make_ohlcv(close)
        features = {
            "ob_type": 1.0,        # bullish OB
            "ob_top": 5020.0,
            "ob_bottom": 5010.0,
            "ob_mitigated": 1.0,   # mitigated → becomes bearish breaker
            "atr_14": 10.0,
        }
        result = plugin.compute_full({"main": df, "features": features})
        # After mitigation, breaker should be stored; active depends on close
        assert result.get("breaker_block_top") == 5020.0
        assert result.get("breaker_block_bottom") == 5010.0
        assert result.get("breaker_block_type") == -1.0  # polarity flipped

    def test_breaker_dist_atr_computed(self):
        from src.intelligence.smart_money.breaker_blocks import BreakerBlocksPlugin

        plugin = BreakerBlocksPlugin()
        close = np.linspace(5000, 5010, 5)
        df = make_ohlcv(close)
        features = {"ob_type": -1.0, "ob_top": 5005.0, "ob_bottom": 5000.0,
                    "ob_mitigated": 1.0, "atr_14": 10.0}
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("breaker_dist_atr") is not None
        assert result["breaker_dist_atr"] >= 0.0

    def test_empty_returns_empty(self):
        from src.intelligence.smart_money.breaker_blocks import BreakerBlocksPlugin

        assert BreakerBlocksPlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# MitigationBlocks
# ---------------------------------------------------------------------------


class TestMitigationBlocks:
    def test_fresh_ob_status(self):
        from src.intelligence.smart_money.mitigation_blocks import MitigationBlocksPlugin

        plugin = MitigationBlocksPlugin()
        # Close completely outside OB zone — no overlap
        close = np.full(5, 4990.0)
        df = make_ohlcv(close)
        features = {"ob_top": 5020.0, "ob_bottom": 5010.0}
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("ob_mitigation_status") == "fresh"
        assert result.get("ob_mitigation_pct") == 0.0

    def test_void_when_ob_mitigated_flag(self):
        from src.intelligence.smart_money.mitigation_blocks import MitigationBlocksPlugin

        plugin = MitigationBlocksPlugin()
        close = np.linspace(5000, 5010, 5)
        df = make_ohlcv(close)
        features = {"ob_top": 5020.0, "ob_bottom": 5010.0, "ob_mitigated": 1.0}
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("ob_mitigation_status") == "void"
        assert result.get("ob_mitigation_pct") == 1.0

    def test_partial_when_bar_overlaps(self):
        from src.intelligence.smart_money.mitigation_blocks import MitigationBlocksPlugin

        plugin = MitigationBlocksPlugin()
        # Bar that partially overlaps OB [5010, 5020]: bar high=5015, low=5005
        import pandas as pd
        df = pd.DataFrame({
            "open": [5008.0, 5008.0], "high": [5015.0, 5015.0],
            "low": [5005.0, 5005.0], "close": [5012.0, 5012.0],
            "volume": [1000.0, 1000.0],
        })
        features = {"ob_top": 5020.0, "ob_bottom": 5010.0}
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("ob_mitigation_status") == "partial"
        assert 0.0 < result.get("ob_mitigation_pct", 0) < 1.0

    def test_no_ob_returns_null(self):
        from src.intelligence.smart_money.mitigation_blocks import MitigationBlocksPlugin

        close = np.linspace(5000, 5010, 5)
        df = make_ohlcv(close)
        result = MitigationBlocksPlugin().compute_full({"main": df, "features": {}})
        assert result.get("ob_mitigation_status") is None

    def test_empty_returns_empty(self):
        from src.intelligence.smart_money.mitigation_blocks import MitigationBlocksPlugin

        assert MitigationBlocksPlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# PremiumDiscount
# ---------------------------------------------------------------------------


class TestPremiumDiscount:
    def test_equilibrium_at_midpoint(self):
        from src.intelligence.smart_money.premium_discount import PremiumDiscountPlugin

        features = {"swing_high": 5200.0, "swing_low": 5000.0, "close": 5100.0}
        result = PremiumDiscountPlugin().compute_full({"main": None, "features": features})
        assert abs(result.get("equilibrium_level", 0) - 5100.0) < 1.0
        assert abs(result.get("premium_discount_pct", 0)) < 0.05

    def test_deep_discount_negative(self):
        from src.intelligence.smart_money.premium_discount import PremiumDiscountPlugin

        features = {"swing_high": 5200.0, "swing_low": 5000.0, "close": 5020.0}
        result = PremiumDiscountPlugin().compute_full({"main": None, "features": features})
        pct = result.get("premium_discount_pct", 0)
        assert pct < -0.5

    def test_deep_premium_positive(self):
        from src.intelligence.smart_money.premium_discount import PremiumDiscountPlugin

        features = {"swing_high": 5200.0, "swing_low": 5000.0, "close": 5180.0}
        result = PremiumDiscountPlugin().compute_full({"main": None, "features": features})
        pct = result.get("premium_discount_pct", 0)
        assert pct > 0.5

    def test_pct_clamped_to_minus_one_plus_one(self):
        from src.intelligence.smart_money.premium_discount import PremiumDiscountPlugin

        features = {"swing_high": 5200.0, "swing_low": 5000.0, "close": 5500.0}  # far above range
        result = PremiumDiscountPlugin().compute_full({"main": None, "features": features})
        assert result.get("premium_discount_pct") == 1.0

    def test_no_swing_data_returns_null(self):
        from src.intelligence.smart_money.premium_discount import PremiumDiscountPlugin

        result = PremiumDiscountPlugin().compute_full({"main": None, "features": {}})
        assert result.get("equilibrium_level") is None

    def test_close_from_df_when_no_feature(self):
        from src.intelligence.smart_money.premium_discount import PremiumDiscountPlugin

        close = np.full(5, 5100.0)
        df = make_ohlcv(close)
        features = {"swing_high": 5200.0, "swing_low": 5000.0}
        result = PremiumDiscountPlugin().compute_full({"main": df, "features": features})
        assert abs(result.get("premium_discount_pct", 99)) < 0.05


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestSMCNewRegistration:
    def test_all_new_plugins_in_tier_smc(self):
        from src.intelligence.register_plugins import TIER_SMC

        new_names = {
            "smc_ICTKillzones",
            "smc_AMDCycle",
            "smc_BreakerBlocks",
            "smc_MitigationBlocks",
            "smc_PremiumDiscount",
        }
        missing = new_names - set(TIER_SMC)
        assert not missing, f"Missing from TIER_SMC: {missing}"

    def test_tier_smc_has_13_plugins(self):
        from src.intelligence.register_plugins import TIER_SMC

        assert len(TIER_SMC) == 13, f"Expected 13 SMC plugins, got {len(TIER_SMC)}"
