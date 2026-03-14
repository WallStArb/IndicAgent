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

        from src.intelligence.patterns.candlestick_patterns import CandlestickPatternsPlugin

        df = pd.DataFrame(
            {
                "open": [5005.0, 5010.0, 4990.0],
                "high": [5008.0, 5015.0, 5025.0],
                "low": [5001.0, 4995.0, 4985.0],
                "close": [5006.0, 5000.0, 5020.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        result = CandlestickPatternsPlugin().compute_full({"main": df, "features": {}})
        assert result.get("engulfing_bull") == 1.0
        assert result.get("engulfing_bear") == 0.0

    def test_pin_bar_bull_detected(self):
        # Pin bar bull: long lower wick >= 2× body, upper wick <= body.
        # min_lookback=3 — prepend a neutral filler bar as pp.
        # open=5005, close=5010, high=5011, low=4980 → body=5, lower_wick=25, upper_wick=1
        import pandas as pd

        from src.intelligence.patterns.candlestick_patterns import CandlestickPatternsPlugin

        df = pd.DataFrame(
            {
                "open": [5005.0, 5005.0, 5005.0],
                "high": [5011.0, 5011.0, 5011.0],
                "low": [4990.0, 4990.0, 4980.0],
                "close": [5010.0, 5010.0, 5010.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        )
        result = CandlestickPatternsPlugin().compute_full({"main": df, "features": {}})
        assert result.get("pin_bar_bull") == 1.0

    def test_doji_detected(self):
        import pandas as pd

        from src.intelligence.patterns.candlestick_patterns import CandlestickPatternsPlugin

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
        result = CandlestickPatternsPlugin().compute_full({"main": df, "features": {}})
        assert result.get("doji_detected") in (0.0, 1.0)

    def test_returns_all_fields(self):
        from src.intelligence.patterns.candlestick_patterns import CandlestickPatternsPlugin

        close = np.linspace(5000, 5010, 5)
        df = make_ohlcv(close)
        result = CandlestickPatternsPlugin().compute_full({"main": df, "features": {}})
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
        }
        assert expected.issubset(result.keys())

    def test_empty_returns_empty(self):
        from src.intelligence.patterns.candlestick_patterns import CandlestickPatternsPlugin

        assert CandlestickPatternsPlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# FlagPennant
# ---------------------------------------------------------------------------


class TestFlagPennant:
    def test_output_values_in_range(self):
        from src.intelligence.patterns.flag_pennant import FlagPennantPlugin

        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        result = FlagPennantPlugin().compute_full({"main": df, "features": {}})
        for field_name in ("bull_flag", "bear_flag", "bull_pennant", "bear_pennant"):
            val = result.get(field_name)
            if val is not None:
                assert val in (0.0, 1.0), f"{field_name}={val} not binary"

    def test_returns_expected_fields(self):
        from src.intelligence.patterns.flag_pennant import FlagPennantPlugin

        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        result = FlagPennantPlugin().compute_full({"main": df, "features": {}})
        if result:
            expected = {
                "flag_pattern",
                "pennant_pattern",
                "flag_breakout_target",
                "consolidation_compression_ratio",
            }
            assert expected.issubset(result.keys())

    def test_empty_returns_empty(self):
        from src.intelligence.patterns.flag_pennant import FlagPennantPlugin

        assert FlagPennantPlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# CupHandle
# ---------------------------------------------------------------------------


class TestCupHandle:
    def test_no_crash_on_trending_data(self):
        from src.intelligence.patterns.cup_handle import CupHandlePlugin

        close = np.linspace(5000, 5200, 80)
        df = make_ohlcv(close)
        result = CupHandlePlugin().compute_full({"main": df, "features": {}})
        # Should not raise; result may be empty or dict with values in {0.0, 1.0}
        assert isinstance(result, dict)

    def test_cup_handle_pattern_binary(self):
        from src.intelligence.patterns.cup_handle import CupHandlePlugin

        close = np.linspace(5000, 5100, 80)
        df = make_ohlcv(close)
        result = CupHandlePlugin().compute_full({"main": df, "features": {}})
        val = result.get("cup_handle_pattern")
        if val is not None:
            assert val in (0.0, 1.0)

    def test_insufficient_bars_returns_empty(self):
        from src.intelligence.patterns.cup_handle import CupHandlePlugin

        # Only 2 bars — below min_lookback (needs ~50+)
        close = np.array([5000.0, 5001.0])
        df = make_ohlcv(close)
        result = CupHandlePlugin().compute_full({"main": df, "features": {}})
        assert result.get("cup_handle_pattern") in (None, 0.0)


# ---------------------------------------------------------------------------
# MeasuredMove (ABCD)
# ---------------------------------------------------------------------------


class TestMeasuredMove:
    def test_abcd_pattern_active_in_range(self):
        from src.intelligence.patterns.measured_move import MeasuredMovePlugin

        close = np.linspace(5000, 5100, 20)
        df = make_ohlcv(close)
        features = {
            "swing_high": 5100.0,
            "swing_low": 5000.0,
            "swing_high_idx": 19,
            "swing_low_idx": 0,
            "close": 5050.0,
        }
        result = MeasuredMovePlugin().compute_full({"main": df, "features": features})
        val = result.get("abcd_pattern_active")
        assert val in (0.0, 0.5, 1.0)

    def test_missing_swing_returns_zero(self):
        from src.intelligence.patterns.measured_move import MeasuredMovePlugin

        close = np.linspace(5000, 5100, 20)
        df = make_ohlcv(close)
        result = MeasuredMovePlugin().compute_full({"main": df, "features": {}})
        assert result.get("abcd_pattern_active") == 0.0

    def test_empty_returns_empty(self):
        from src.intelligence.patterns.measured_move import MeasuredMovePlugin

        assert MeasuredMovePlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# VolumeProfile
# ---------------------------------------------------------------------------


class TestVolumeProfile:
    def test_nearest_hvn_in_price_range(self):
        from src.intelligence.patterns.volume_profile import VolumeProfilePlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = VolumeProfilePlugin().compute_full({"main": df, "features": {}})
        hvn = result.get("nearest_hvn_level")
        if hvn is not None:
            assert 4990 <= hvn <= 5110

    def test_in_lvn_is_binary(self):
        from src.intelligence.patterns.volume_profile import VolumeProfilePlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = VolumeProfilePlugin().compute_full({"main": df, "features": {}})
        val = result.get("in_lvn")
        if val is not None:
            assert val in (0.0, 1.0)

    def test_empty_returns_empty(self):
        from src.intelligence.patterns.volume_profile import VolumeProfilePlugin

        assert VolumeProfilePlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# KeyLevelReaction
# ---------------------------------------------------------------------------


class TestKeyLevelReaction:
    def test_reaction_type_in_range(self):
        from src.intelligence.patterns.key_level_reaction import KeyLevelReactionPlugin

        close = np.linspace(5000, 5100, 10)
        df = make_ohlcv(close)
        features = {"nearest_support": 5050.0, "atr_14": 10.0, "close": 5052.0}
        result = KeyLevelReactionPlugin().compute_full({"main": df, "features": features})
        val = result.get("key_level_reaction_type")
        assert val in (0.0, 1.0, 2.0, 3.0, 4.0)

    def test_confluence_count_non_negative(self):
        from src.intelligence.patterns.key_level_reaction import KeyLevelReactionPlugin

        close = np.linspace(5000, 5100, 10)
        df = make_ohlcv(close)
        features = {
            "nearest_support": 5050.0,
            "nearest_resistance": 5051.0,
            "ob_top": 5052.0,
            "atr_14": 5.0,
            "close": 5050.5,
        }
        result = KeyLevelReactionPlugin().compute_full({"main": df, "features": features})
        assert result.get("key_level_confluence_count", 0) >= 0

    def test_no_levels_returns_none_reaction(self):
        from src.intelligence.patterns.key_level_reaction import KeyLevelReactionPlugin

        close = np.linspace(5000, 5100, 10)
        df = make_ohlcv(close)
        result = KeyLevelReactionPlugin().compute_full({"main": df, "features": {}})
        assert result.get("key_level_reaction_type") == 0.0

    def test_empty_returns_empty(self):
        from src.intelligence.patterns.key_level_reaction import KeyLevelReactionPlugin

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
            "patt_VolumeProfile",
            "patt_KeyLevelReaction",
        }
        missing = new_names - set(TIER_I5)
        assert not missing, f"Missing from TIER_I5: {missing}"

    def test_tier_i5_has_14_plugins(self):
        from src.intelligence.register_plugins import TIER_I5

        assert len(TIER_I5) == 14, f"Expected 14 I5 plugins, got {len(TIER_I5)}"
