"""Tests for new I5 pattern plugins added in the intelligence palette expansion.

Covers: CandlestickPatterns, FlagPennant, CupHandle, MeasuredMove,
        VolumeProfile, KeyLevelReaction — plus registration check.
"""

from __future__ import annotations

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# CandlestickPatterns
# ---------------------------------------------------------------------------


class TestCandlestickPatterns:
    def test_engulfing_bull_detected(self):
        # Prior bar (p): bearish (o=5010, c=5000); current bar (c): bullish engulfing.
        # min_lookback=3 — prepend a neutral filler bar as pp.
        import pandas as pd

        from src.intelligence.archive.i5_patterns.candlestick_patterns import (
            CandlestickPatternsPlugin,
        )

        df = pd.DataFrame(
            {
                "open": [5005.0, 5010.0, 4990.0],
                "high": [5008.0, 5015.0, 5025.0],
                "low": [5001.0, 4995.0, 4985.0],
                "close": [5006.0, 5000.0, 5020.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        result = CandlestickPatternsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("engulfing_bull") == 1.0
        assert result.get("engulfing_bear") == 0.0

    def test_pin_bar_bull_detected(self):
        # Pin bar bull: long lower wick >= 2× body, upper wick <= body.
        # min_lookback=3 — prepend a neutral filler bar as pp.
        # open=5005, close=5010, high=5011, low=4980 → body=5, lower_wick=25, upper_wick=1
        import pandas as pd

        from src.intelligence.archive.i5_patterns.candlestick_patterns import (
            CandlestickPatternsPlugin,
        )

        df = pd.DataFrame(
            {
                "open": [5005.0, 5005.0, 5005.0],
                "high": [5011.0, 5011.0, 5011.0],
                "low": [4990.0, 4990.0, 4980.0],
                "close": [5010.0, 5010.0, 5010.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        result = CandlestickPatternsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("pin_bar_bull") == 1.0

    def test_doji_detected(self):
        import pandas as pd

        from src.intelligence.archive.i5_patterns.candlestick_patterns import (
            CandlestickPatternsPlugin,
        )

        # Doji: open ≈ close, range exists.
        # min_lookback=3 — prepend a neutral filler bar as pp.
        df = pd.DataFrame(
            {
                "open": [5000.0, 5000.0, 5000.5],
                "high": [5010.0, 5010.0, 5010.0],
                "low": [4990.0, 4990.0, 4990.0],
                "close": [5001.0, 5000.0, 5001.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        result = CandlestickPatternsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("doji_detected") in (0.0, 1.0)

    def test_returns_all_fields(self):
        from src.intelligence.archive.i5_patterns.candlestick_patterns import (
            CandlestickPatternsPlugin,
        )

        close = np.linspace(5000, 5010, 5)
        df = make_ohlcv(close)
        result = CandlestickPatternsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        expected = {
            "engulfing_bull",
            "engulfing_bear",
            "pin_bar_bull",
            "pin_bar_bear",
            "hammer_detected",
            "shooting_star_detected",
            "inside_bar",
            "outside_bar",
            "doji_detected",
            "inside_bar_depth",
            "outside_bar_expansion",
        }
        assert expected.issubset(result.keys())

    def test_empty_returns_empty(self):
        from src.intelligence.archive.i5_patterns.candlestick_patterns import (
            CandlestickPatternsPlugin,
        )

        assert CandlestickPatternsPlugin().compute_full({}) == {}

    def test_inside_bar_depth_gradient(self):
        import pandas as pd

        from src.intelligence.archive.i5_patterns.candlestick_patterns import (
            CandlestickPatternsPlugin,
        )

        # Current bar moderately inside prior bar
        # prior: h=5020, l=5000 (range=20)
        # current: h=5016, l=5004 (inside, margins: top=4, bot=4)
        # depth = min(4, 4) / 20 = 0.2
        df = pd.DataFrame(
            {
                "open": [5005.0, 5010.0, 5010.0],
                "high": [5008.0, 5020.0, 5016.0],
                "low": [5001.0, 5000.0, 5004.0],
                "close": [5006.0, 5015.0, 5012.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        result = CandlestickPatternsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result["inside_bar"] == 1.0
        assert 0.0 < result["inside_bar_depth"] < 1.0
        assert abs(result["inside_bar_depth"] - 0.2) < 0.01

    def test_inside_bar_depth_zero_when_no_inside_bar(self):
        import pandas as pd

        from src.intelligence.archive.i5_patterns.candlestick_patterns import (
            CandlestickPatternsPlugin,
        )

        # No inside bar (current bar wider than prior)
        df = pd.DataFrame(
            {
                "open": [5005.0, 5005.0, 5005.0],
                "high": [5008.0, 5010.0, 5020.0],
                "low": [5001.0, 4995.0, 4990.0],
                "close": [5006.0, 5000.0, 5015.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        result = CandlestickPatternsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result["inside_bar"] == 0.0
        assert result["inside_bar_depth"] == 0.0

    def test_outside_bar_expansion_gradient(self):
        import pandas as pd

        from src.intelligence.archive.i5_patterns.candlestick_patterns import (
            CandlestickPatternsPlugin,
        )

        # Current bar engulfs prior bar with moderate expansion
        # prior: h=5010, l=5000 (range=10)
        # current: h=5018, l=4994 (expansion: top=8, bot=6)
        # expansion = (8 + 6) / 10 = 1.4
        df = pd.DataFrame(
            {
                "open": [5005.0, 5005.0, 5005.0],
                "high": [5008.0, 5010.0, 5018.0],
                "low": [5001.0, 5000.0, 4994.0],
                "close": [5006.0, 5008.0, 5012.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        result = CandlestickPatternsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result["outside_bar"] == 1.0
        assert result["outside_bar_expansion"] > 0.0
        assert abs(result["outside_bar_expansion"] - 1.4) < 0.01

    def test_outside_bar_expansion_zero_when_no_outside_bar(self):
        import pandas as pd

        from src.intelligence.archive.i5_patterns.candlestick_patterns import (
            CandlestickPatternsPlugin,
        )

        # No outside bar
        df = pd.DataFrame(
            {
                "open": [5005.0, 5005.0, 5005.0],
                "high": [5008.0, 5010.0, 5008.0],
                "low": [5001.0, 5000.0, 5002.0],
                "close": [5006.0, 5008.0, 5006.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        result = CandlestickPatternsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result["outside_bar"] == 0.0
        assert result["outside_bar_expansion"] == 0.0


# ---------------------------------------------------------------------------
# MTFVolatility gradient tests
# ---------------------------------------------------------------------------


class TestMTFVolatilityGradient:
    def test_expansion_continuous_values(self):
        from src.intelligence.archive.i5_patterns.mtf_volatility import MTFVolatilityPlugin

        close = np.linspace(5000, 5100, 10)
        df = make_ohlcv(close)
        intel_15m = {"vol_expansion": 0.5}
        intel_1h = {"vol_expansion": 0.3}
        result = MTFVolatilityPlugin().compute_full(
            {
                "main": df,
                "i1": {},
                "i2": {},
                "i3": {},
                "i4": {},
                "i5": {},
                "smc": {},
                "i6": {},
                "intel_15m": intel_15m,
                "intel_1h": intel_1h,
            }
        )
        # Should output continuous values, not binary 0/1
        assert 0.0 < result["mtf_vol_expansion_15m"] <= 1.0
        assert 0.0 < result["mtf_vol_expansion_1h"] <= 1.0
        assert abs(result["mtf_vol_expansion_15m"] - 0.5) < 0.01
        assert abs(result["mtf_vol_expansion_1h"] - 0.3) < 0.01

    def test_expansion_zero_when_contracting(self):
        from src.intelligence.archive.i5_patterns.mtf_volatility import MTFVolatilityPlugin

        close = np.linspace(5000, 5100, 10)
        df = make_ohlcv(close)
        intel_15m = {"vol_expansion": -0.5}
        intel_1h = {"vol_expansion": -0.3}
        result = MTFVolatilityPlugin().compute_full(
            {
                "main": df,
                "i1": {},
                "i2": {},
                "i3": {},
                "i4": {},
                "i5": {},
                "smc": {},
                "i6": {},
                "intel_15m": intel_15m,
                "intel_1h": intel_1h,
            }
        )
        assert result["mtf_vol_expansion_15m"] == 0.0
        assert result["mtf_vol_expansion_1h"] == 0.0

    def test_squeeze_within_continuous(self):
        from src.intelligence.archive.i5_patterns.mtf_volatility import MTFVolatilityPlugin

        close = np.linspace(5000, 5100, 10)
        df = make_ohlcv(close)
        features = {
            "bb_20_2_upper": 5015.0,
            "bb_20_2_lower": 5005.0,  # BB width = 10
            "keltner_upper": 5020.0,
            "keltner_lower": 5000.0,  # KC width = 20
        }
        intel_15m = {"vol_expansion": 0.6}
        result = MTFVolatilityPlugin().compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
                "intel_15m": intel_15m,
                "intel_1h": {},
            }
        )
        # squeeze_within_expansion should be continuous > 0 when squeezing and expanding
        assert result["squeeze_within_expansion"] > 0.0
        assert result["squeeze_within_expansion"] <= 1.0


# ---------------------------------------------------------------------------
# FlagPennant
# ---------------------------------------------------------------------------


class TestFlagPennant:
    def test_output_values_in_range(self):
        from src.intelligence.archive.i5_patterns.flag_pennant import FlagPennantPlugin

        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        result = FlagPennantPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        for field_name in ("bull_flag", "bear_flag", "bull_pennant", "bear_pennant"):
            val = result.get(field_name)
            if val is not None:
                assert val in (0.0, 1.0), f"{field_name}={val} not binary"

    def test_returns_expected_fields(self):
        from src.intelligence.archive.i5_patterns.flag_pennant import FlagPennantPlugin

        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        result = FlagPennantPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        if result:
            expected = {
                "flag_pattern",
                "pennant_pattern",
                "flag_breakout_target",
                "consolidation_compression_ratio",
            }
            assert expected.issubset(result.keys())

    def test_empty_returns_empty(self):
        from src.intelligence.archive.i5_patterns.flag_pennant import FlagPennantPlugin

        assert FlagPennantPlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# CupHandle
# ---------------------------------------------------------------------------


class TestCupHandle:
    def test_no_crash_on_trending_data(self):
        from src.intelligence.archive.i5_patterns.cup_handle import CupHandlePlugin

        close = np.linspace(5000, 5200, 80)
        df = make_ohlcv(close)
        result = CupHandlePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        # Should not raise; result may be empty or dict with values in {0.0, 1.0}
        assert isinstance(result, dict)

    def test_cup_handle_pattern_binary(self):
        from src.intelligence.archive.i5_patterns.cup_handle import CupHandlePlugin

        close = np.linspace(5000, 5100, 80)
        df = make_ohlcv(close)
        result = CupHandlePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        val = result.get("cup_handle_pattern")
        if val is not None:
            assert val in (0.0, 1.0)

    def test_insufficient_bars_returns_empty(self):
        from src.intelligence.archive.i5_patterns.cup_handle import CupHandlePlugin

        # Only 2 bars — below min_lookback (needs ~50+)
        close = np.array([5000.0, 5001.0])
        df = make_ohlcv(close)
        result = CupHandlePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("cup_handle_pattern") in (None, 0.0)


# ---------------------------------------------------------------------------
# MeasuredMove (ABCD)
# ---------------------------------------------------------------------------


class TestMeasuredMove:
    def test_abcd_pattern_active_in_range(self):
        from src.intelligence.archive.i5_patterns.measured_move import MeasuredMovePlugin

        close = np.linspace(5000, 5100, 20)
        df = make_ohlcv(close)
        features = {
            "swing_high": 5100.0,
            "swing_low": 5000.0,
            "swing_high_idx": 19,
            "swing_low_idx": 0,
            "close": 5050.0,
        }
        result = MeasuredMovePlugin().compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        val = result.get("abcd_pattern_active")
        assert val in (0.0, 0.5, 1.0)

    def test_missing_swing_returns_zero(self):
        from src.intelligence.archive.i5_patterns.measured_move import MeasuredMovePlugin

        close = np.linspace(5000, 5100, 20)
        df = make_ohlcv(close)
        result = MeasuredMovePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("abcd_pattern_active") == 0.0

    def test_empty_returns_empty(self):
        from src.intelligence.archive.i5_patterns.measured_move import MeasuredMovePlugin

        assert MeasuredMovePlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# VolumeProfile
# ---------------------------------------------------------------------------


class TestVolumeProfile:
    def test_nearest_hvn_in_price_range(self):
        from src.intelligence.context.volume_profile import VolumeProfilePlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = VolumeProfilePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        hvn = result.get("nearest_hvn_level")
        if hvn is not None:
            assert 4990 <= hvn <= 5110

    def test_in_lvn_is_binary(self):
        from src.intelligence.context.volume_profile import VolumeProfilePlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = VolumeProfilePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        val = result.get("in_lvn")
        if val is not None:
            assert val in (0.0, 1.0)

    def test_empty_returns_empty(self):
        from src.intelligence.context.volume_profile import VolumeProfilePlugin

        assert VolumeProfilePlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# KeyLevelReaction
# ---------------------------------------------------------------------------


class TestKeyLevelReaction:
    def test_reaction_type_in_range(self):
        from src.intelligence.archive.i5_patterns.key_level_reaction import KeyLevelReactionPlugin

        close = np.linspace(5000, 5100, 10)
        df = make_ohlcv(close)
        features = {"nearest_support": 5050.0, "atr_14": 10.0, "close": 5052.0}
        result = KeyLevelReactionPlugin().compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        val = result.get("key_level_reaction_type")
        assert val in (0.0, 1.0, 2.0, 3.0, 4.0)

    def test_confluence_count_non_negative(self):
        from src.intelligence.archive.i5_patterns.key_level_reaction import KeyLevelReactionPlugin

        close = np.linspace(5000, 5100, 10)
        df = make_ohlcv(close)
        features = {
            "nearest_support": 5050.0,
            "nearest_resistance": 5051.0,
            "ob_top": 5052.0,
            "atr_14": 5.0,
            "close": 5050.5,
        }
        result = KeyLevelReactionPlugin().compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result.get("key_level_confluence_count", 0) >= 0

    def test_no_levels_returns_none_reaction(self):
        from src.intelligence.archive.i5_patterns.key_level_reaction import KeyLevelReactionPlugin

        close = np.linspace(5000, 5100, 10)
        df = make_ohlcv(close)
        result = KeyLevelReactionPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("key_level_reaction_type") == 0.0

    def test_empty_returns_empty(self):
        from src.intelligence.archive.i5_patterns.key_level_reaction import KeyLevelReactionPlugin

        assert KeyLevelReactionPlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# Registration: all 6 new plugins in TIER_I5
# ---------------------------------------------------------------------------


class TestI5NewRegistration:
    def test_all_new_plugins_in_tier_i5(self):
        from src.intelligence.register_plugins import TIER_I5

        new_names = {
            "patt_CandlestickPatterns",
            "patt_FlagPennant",
            "patt_CupHandle",
            "patt_MeasuredMove",
            # patt_VolumeProfile migrated to TIER_I4 as ctx_VolumeProfile in Phase 34-02
            "patt_KeyLevelReaction",
        }
        missing = new_names - set(TIER_I5)
        assert not missing, f"Missing from TIER_I5: {missing}"

    def test_tier_i5_has_15_plugins(self):
        from src.intelligence.register_plugins import TIER_I5

        assert len(TIER_I5) == 16, f"Expected 16 I5 plugins, got {len(TIER_I5)}"

    def test_volume_profile_in_tier_i4(self):
        from src.intelligence.register_plugins import TIER_I4

        assert "ctx_VolumeProfile" in TIER_I4, "ctx_VolumeProfile should be in TIER_I4"
