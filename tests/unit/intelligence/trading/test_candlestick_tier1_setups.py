"""Tests for CandlestickPatternSetup I7 plugin - Tier 1 patterns."""

import pandas as pd


class TestCandlestickTier1Patterns:
    """Tests for 9 new Tier 1 candlestick patterns in CandlestickPatternSetupPlugin.

    Each pattern is already computed in I5 (CandlestickPatternsPlugin) and written
    to intelligence_features.i5. This suite verifies the I7 read/promotion wiring.

    S/R confirmation path used throughout (nearest_support/resistance within 0.3*ATR).
    """

    def _make_df(self, n: int = 25, close: float = 5000.0):
        return pd.DataFrame(
            {
                "open": [close - 5.0] * n,
                "high": [close + 10.0] * n,
                "low": [close - 10.0] * n,
                "close": [close] * n,
                "volume": [1200.0] * n,
            }
        )

    def _bull_features(self, pattern_field: str) -> dict:
        """Features dict with bullish pattern flag, S/R near close, bullish trend."""
        return {
            pattern_field: 1.0,
            "trend_regime": 0.7,
            "atr_14": 10.0,
            # nearest_support within 0.3*ATR=3 of close=5000 → S/R confirms
            "nearest_support": 4998.0,
            "volume_sma_20": 1000.0,  # vol 1200 < 1.3*1000=1300 → volume does NOT confirm
            # Phase 119: gate-passing values for dual gate
            "ctf_score": 0.5,
            "hmm_prob_trending_up": 0.6,
            "hmm_prob_trending_down": 0.3,
        }

    def _bear_features(self, pattern_field: str) -> dict:
        """Features dict with bearish pattern flag, S/R near close, bearish trend."""
        return {
            pattern_field: 1.0,
            "trend_regime": -0.7,
            "atr_14": 10.0,
            # nearest_resistance within 0.3*ATR=3 of close=5000 → S/R confirms
            "nearest_resistance": 5002.0,
            "volume_sma_20": 1000.0,
            # Phase 119: gate-passing values for dual gate
            "ctf_score": 0.5,
            "hmm_prob_trending_up": 0.3,
            "hmm_prob_trending_down": 0.6,
        }

    def _frames(self, f: dict) -> dict:
        """Spread flat feature dict across all tier keys (plugins no longer read frames['features'])."""
        return {"i1": f, "i2": f, "i3": f, "i4": f, "i5": f, "smc": f, "i6": f}

    def test_three_white_soldiers_bullish(self):
        from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
            CandlestickPatternSetupPlugin,
        )

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, **self._frames(self._bull_features("three_white_soldiers"))}
        )
        assert result.get("direction") == 1
        assert "three_white_soldiers" in result.get("signal_type", "")

    def test_three_black_crows_bearish(self):
        from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
            CandlestickPatternSetupPlugin,
        )

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, **self._frames(self._bear_features("three_black_crows"))}
        )
        assert result.get("direction") == -1
        assert "three_black_crows" in result.get("signal_type", "")

    def test_morning_star_bullish(self):
        from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
            CandlestickPatternSetupPlugin,
        )

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, **self._frames(self._bull_features("morning_star"))}
        )
        assert result.get("direction") == 1
        assert "morning_star" in result.get("signal_type", "")

    def test_evening_star_bearish(self):
        from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
            CandlestickPatternSetupPlugin,
        )

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, **self._frames(self._bear_features("evening_star"))}
        )
        assert result.get("direction") == -1
        assert "evening_star" in result.get("signal_type", "")

    def test_three_inside_up_bullish(self):
        from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
            CandlestickPatternSetupPlugin,
        )

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, **self._frames(self._bull_features("three_inside_up"))}
        )
        assert result.get("direction") == 1
        assert "three_inside_up" in result.get("signal_type", "")

    def test_three_inside_down_bearish(self):
        from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
            CandlestickPatternSetupPlugin,
        )

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, **self._frames(self._bear_features("three_inside_down"))}
        )
        assert result.get("direction") == -1
        assert "three_inside_down" in result.get("signal_type", "")

    def test_harami_cross_follows_trend(self):
        """harami_cross has no intrinsic direction — aligns with trend_regime."""
        from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
            CandlestickPatternSetupPlugin,
        )

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, **self._frames(self._bull_features("harami_cross"))}
        )
        assert result.get("direction") == 1  # follows bullish trend
        assert "harami_cross" in result.get("signal_type", "")

    def test_dark_cloud_cover_bearish(self):
        from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
            CandlestickPatternSetupPlugin,
        )

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, **self._frames(self._bear_features("dark_cloud_cover"))}
        )
        assert result.get("direction") == -1
        assert "dark_cloud_cover" in result.get("signal_type", "")

    def test_piercing_line_bullish(self):
        from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
            CandlestickPatternSetupPlugin,
        )

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, **self._frames(self._bull_features("piercing_line"))}
        )
        assert result.get("direction") == 1
        assert "piercing_line" in result.get("signal_type", "")
