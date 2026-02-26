"""Tests for I4 context plugins — trend/volatility regime classification."""

import numpy as np
import pandas as pd

from tests.unit.intelligence.helpers import make_ohlcv

# ─── Volatility Regime ─────────────────────────────────────────


class TestVolatilityRegime:
    def test_high_volatility(self):
        """Large swings → high vol_regime and vol_percentile."""
        from src.intelligence.context.volatility_regime import VolatilityRegimePlugin

        # Start flat, then inject big swings at the end
        n = 100
        close = np.full(n, 5000.0)
        # Last 20 bars: large oscillations
        for i in range(80, n):
            close[i] = 5000 + 200 * ((-1) ** i)
        df = make_ohlcv(close)
        plugin = VolatilityRegimePlugin()
        result = plugin.compute_full({"main": df})

        assert result != {}
        assert result["vol_regime"] >= 1.0
        assert result["vol_percentile"] > 0.7

    def test_low_volatility(self):
        """Flat data → low vol_regime and low percentile."""
        from src.intelligence.context.volatility_regime import VolatilityRegimePlugin

        # Mostly volatile, then go flat at the end
        n = 100
        rng = np.random.default_rng(42)
        close = 5000 + np.cumsum(rng.normal(0, 20, n))
        # Last 20 bars: nearly flat
        for i in range(80, n):
            close[i] = close[79] + rng.normal(0, 0.1)
        df = make_ohlcv(close)
        plugin = VolatilityRegimePlugin()
        result = plugin.compute_full({"main": df})

        assert result != {}
        assert result["vol_regime"] == -1.0
        assert result["vol_percentile"] < 0.3

    def test_empty_frames(self):
        """Empty/missing data → empty dict."""
        from src.intelligence.context.volatility_regime import VolatilityRegimePlugin

        plugin = VolatilityRegimePlugin()
        assert plugin.compute_full({}) == {}
        assert plugin.compute_full({"main": None}) == {}

    def test_bb_width_present(self):
        """BB width outputs are produced for valid data."""
        from src.intelligence.context.volatility_regime import VolatilityRegimePlugin

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        plugin = VolatilityRegimePlugin()
        result = plugin.compute_full({"main": df})

        assert "bb_width_pct" in result
        assert "bb_width_percentile" in result
        assert 0.0 <= result["bb_width_percentile"] <= 1.0


# ─── Trend Regime ──────────────────────────────────────────────


class TestTrendRegime:
    def test_uptrend(self):
        """Price > SMA-20 > SMA-50 → positive trend_regime and ma_alignment."""
        from src.intelligence.context.trend_regime import TrendRegimePlugin

        # Strong uptrend: monotonically rising
        close = np.linspace(4800, 5200, 100)
        df = make_ohlcv(close)
        plugin = TrendRegimePlugin()
        result = plugin.compute_full({"main": df})

        assert result["trend_regime"] > 0
        assert result["ma_alignment"] > 0
        assert result["price_vs_sma20_pct"] > 0

    def test_downtrend(self):
        """Price < SMA-20 < SMA-50 → negative trend_regime."""
        from src.intelligence.context.trend_regime import TrendRegimePlugin

        close = np.linspace(5200, 4800, 100)
        df = make_ohlcv(close)
        plugin = TrendRegimePlugin()
        result = plugin.compute_full({"main": df})

        assert result["trend_regime"] < 0
        assert result["ma_alignment"] < 0

    def test_with_i3_features(self):
        """I3 structure features blended → confidence produced."""
        from src.intelligence.context.trend_regime import TrendRegimePlugin

        close = np.linspace(4800, 5200, 100)
        df = make_ohlcv(close)
        features = {"trend_direction": 1.0, "trend_strength": 0.8}
        plugin = TrendRegimePlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result["trend_confidence"] > 0
        assert result["trend_regime"] > 0

    def test_empty_frames(self):
        """Empty data → empty dict."""
        from src.intelligence.context.trend_regime import TrendRegimePlugin

        plugin = TrendRegimePlugin()
        assert plugin.compute_full({}) == {}
        assert plugin.compute_full({"main": None}) == {}


# ─── TrendRegime Feature Consumption ─────────────────────────


class TestTrendRegimeFeatureConsumption:
    def test_uses_upstream_sma_when_available(self):
        """TrendRegime should read sma_20/sma_50 from features dict."""
        from src.intelligence.context.trend_regime import TrendRegimePlugin

        rng = np.random.default_rng(42)
        close = 5000.0 + np.cumsum(rng.standard_normal(100) * 0.5)
        df = pd.DataFrame({"close": close, "high": close + 1, "low": close - 1})

        # Inject known SMA values via features — these should override computation
        known_sma20 = 4990.0  # Below price → bullish signal
        known_sma50 = 4980.0  # Below SMA20 → strong bullish
        features = {"sma_20": known_sma20, "sma_50": known_sma50}

        plugin = TrendRegimePlugin()
        result = plugin.compute_full({"main": df, "features": features})

        # Should use the injected values, producing strong bullish if price > sma20 > sma50
        assert result["ma_alignment"] == 2.0  # strong bullish

    def test_falls_back_when_features_missing(self):
        """Without upstream SMAs, should compute from OHLCV (existing behavior)."""
        from src.intelligence.context.trend_regime import TrendRegimePlugin

        rng = np.random.default_rng(42)
        close = 5000.0 + np.cumsum(rng.standard_normal(100) * 0.5)
        df = pd.DataFrame({"close": close, "high": close + 1, "low": close - 1})

        plugin = TrendRegimePlugin()
        result = plugin.compute_full({"main": df})
        assert "trend_regime" in result


# ─── Momentum Context ─────────────────────────────────────────


class TestMomentumContext:
    def test_all_bullish(self):
        """All oscillators bullish → positive bias."""
        from src.intelligence.context.momentum_context import MomentumContextPlugin

        features = {
            "rsi_14": 65,
            "macd_12_26_9": 5.0,
            "macd_signal_12_26_9": 2.0,
            "stoch_k_14_3": 70,
            "cci_14": 80,
        }
        plugin = MomentumContextPlugin()
        result = plugin.compute_full({"features": features})

        assert result["momentum_bias"] > 0.3
        assert result["momentum_strength"] > 0.3
        assert result["momentum_n_signals"] == 4.0

    def test_all_bearish(self):
        """All oscillators bearish → negative bias."""
        from src.intelligence.context.momentum_context import MomentumContextPlugin

        features = {
            "rsi_14": 35,
            "macd_12_26_9": -5.0,
            "macd_signal_12_26_9": -2.0,
            "stoch_k_14_3": 30,
            "cci_14": -80,
        }
        plugin = MomentumContextPlugin()
        result = plugin.compute_full({"features": features})

        assert result["momentum_bias"] < -0.3
        assert result["momentum_strength"] > 0.3

    def test_mixed_signals(self):
        """Mixed oscillators → low agreement."""
        from src.intelligence.context.momentum_context import MomentumContextPlugin

        features = {
            "rsi_14": 65,  # bullish
            "macd_12_26_9": -5.0,  # bearish
            "macd_signal_12_26_9": -2.0,
            "stoch_k_14_3": 70,  # bullish
            "cci_14": -80,  # bearish
        }
        plugin = MomentumContextPlugin()
        result = plugin.compute_full({"features": features})

        assert result["momentum_agreement"] < 1.0

    def test_empty_features(self):
        """No features → empty dict."""
        from src.intelligence.context.momentum_context import MomentumContextPlugin

        plugin = MomentumContextPlugin()
        assert plugin.compute_full({}) == {}
        assert plugin.compute_full({"features": {}}) == {}


# ─── Registration ──────────────────────────────────────────────


class TestContextRegistration:
    def test_all_context_plugins_registered(self):
        """All 3 context plugins appear in registry."""
        from src.intelligence.context.momentum_context import plugin as mc
        from src.intelligence.context.trend_regime import plugin as tr
        from src.intelligence.context.volatility_regime import plugin as vr
        from src.intelligence.plugins import PluginRegistry

        reg = PluginRegistry()
        reg.register_pattern(vr)
        reg.register_pattern(tr)
        reg.register_pattern(mc)

        names = reg.list_patterns()
        assert len(names) == 3
        assert "ctx_VolatilityRegime" in names
        assert "ctx_TrendRegime" in names
        assert "ctx_MomentumContext" in names
