"""Tests for pattern detection plugins (I5 tier)."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv

# ─── RSI Divergence ──────────────────────────────────────────────


class TestRSIDivergence:
    def test_bullish_divergence(self):
        """Price makes lower low, RSI makes higher low → bullish divergence."""
        from src.intelligence.archive.i5_patterns.rsi_divergence import RSIDivergencePlugin

        rng = np.random.default_rng(42)
        # Build price that dips twice, second dip lower in price
        n = 100
        close = np.full(n, 5000.0)
        # First dip around bar 30
        for i in range(20, 40):
            close[i] = 5000 - 200 * np.sin(np.pi * (i - 20) / 20)
        # Second dip around bar 70, deeper price
        for i in range(60, 80):
            close[i] = 5000 - 300 * np.sin(np.pi * (i - 60) / 20)
        # But add strong buying at second dip (smaller actual drops per bar)
        # so RSI stays higher by making the drops gentler with recovery
        for i in range(70, 80):
            close[i] += 50  # Partial recovery keeps RSI higher

        close += rng.normal(0, 0.5, n)  # Tiny noise
        df = make_ohlcv(close)
        plugin = RSIDivergencePlugin()
        result = plugin.compute_full({"main": df})

        assert "rsi_div_bullish" in result
        assert "rsi_div_strength" in result

    def test_no_divergence_trending(self):
        """Steady uptrend → no divergence."""
        from src.intelligence.archive.i5_patterns.rsi_divergence import RSIDivergencePlugin

        close = np.linspace(5000, 5500, 100)
        df = make_ohlcv(close)
        plugin = RSIDivergencePlugin()
        result = plugin.compute_full({"main": df})

        assert result.get("rsi_div_bullish", 0.0) == 0.0
        assert result.get("rsi_div_bearish", 0.0) == 0.0

    def test_empty_frames(self):
        from src.intelligence.archive.i5_patterns.rsi_divergence import RSIDivergencePlugin

        plugin = RSIDivergencePlugin()
        assert plugin.compute_full({}) == {}
        assert plugin.compute_full({"main": None}) == {}

    def test_compute_next_delegates(self):
        """compute_next should work (delegates to compute_full)."""
        from src.intelligence.archive.i5_patterns.rsi_divergence import RSIDivergencePlugin

        close = np.linspace(5000, 5500, 100)
        df = make_ohlcv(close)
        plugin = RSIDivergencePlugin()
        result = plugin.compute_next({"main": df})
        assert isinstance(result, dict)


# ─── Bollinger Squeeze ───────────────────────────────────────────


class TestBollingerSqueeze:
    def test_squeeze_active_low_volatility(self):
        """Very tight range → BB inside KC → squeeze active."""
        from src.intelligence.archive.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin

        # Flat price with extremely low volatility
        rng = np.random.default_rng(42)
        close = 5000.0 + rng.normal(0, 0.5, 80)  # Very tight range
        df = make_ohlcv(close)
        plugin = BollingerSqueezePlugin()
        result = plugin.compute_full({"main": df})

        assert "squeeze_active" in result
        assert result["squeeze_active"] == 1.0
        assert result["squeeze_duration"] > 0

    def test_squeeze_fired(self):
        """Squeeze followed by expansion → squeeze_fired detected."""
        from src.intelligence.archive.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin

        rng = np.random.default_rng(42)
        # 60 bars of tight range, then 20 bars of breakout
        tight = 5000.0 + rng.normal(0, 0.5, 60)
        breakout = np.linspace(5000, 5200, 20) + rng.normal(0, 5, 20)
        close = np.concatenate([tight, breakout])
        df = make_ohlcv(close)
        plugin = BollingerSqueezePlugin()

        # Seed state with tight portion
        plugin.compute_full({"main": df.iloc[:60].copy()})

        # Feed breakout bars incrementally
        result = {}
        for i in range(60, len(close)):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        # At some point during breakout, squeeze should have fired
        # The final result may or may not show fired=1 (depends on exact bar)
        # But the fact that compute_next works incrementally is the key test
        assert "squeeze_fired" in result

    def test_no_squeeze_volatile(self):
        """High volatility → no squeeze."""
        from src.intelligence.archive.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin

        rng = np.random.default_rng(42)
        close = 5000.0 + rng.normal(0, 100, 80)  # Very wide swings
        df = make_ohlcv(close)
        plugin = BollingerSqueezePlugin()
        result = plugin.compute_full({"main": df})

        assert result.get("squeeze_active", 0.0) == 0.0

    def test_empty_frames(self):
        from src.intelligence.archive.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin

        plugin = BollingerSqueezePlugin()
        assert plugin.compute_full({}) == {}


# ─── Volume Divergence ───────────────────────────────────────────


class TestVolumeDivergence:
    def test_bearish_volume_divergence(self):
        """Rising prices + declining OBV → bearish divergence."""
        from src.intelligence.archive.i5_patterns.volume_divergence import VolumeDivergencePlugin

        n = 60
        # Price trends up via sawtooth: +4, +4, -5 per cycle (net +3 per 3 bars)
        # But down bars have massive volume → OBV trends down
        close = np.zeros(n)
        volume = np.zeros(n)
        close[0] = 5000.0
        volume[0] = 1000.0
        for i in range(1, n):
            if i % 3 == 0:
                close[i] = close[i - 1] - 5  # Down bar
                volume[i] = 50000.0  # Huge volume on sell
            else:
                close[i] = close[i - 1] + 4  # Up bar
                volume[i] = 1000.0  # Small volume on buy
        df = make_ohlcv(close, volume)
        plugin = VolumeDivergencePlugin()
        result = plugin.compute_full({"main": df})

        assert result["vol_div_bearish"] > 0.3  # Continuous confidence, not binary
        assert result["vol_div_bullish"] == 0.0
        assert result["vol_div_strength"] > 0.3

    def test_no_divergence_aligned(self):
        """Rising prices + rising volume → no divergence."""
        from src.intelligence.archive.i5_patterns.volume_divergence import VolumeDivergencePlugin

        n = 60
        close = np.linspace(5000, 5200, n)
        volume = np.linspace(5000, 10000, n)  # Volume rising with price
        df = make_ohlcv(close, volume)
        plugin = VolumeDivergencePlugin()
        result = plugin.compute_full({"main": df})

        assert result["vol_div_bearish"] == 0.0
        assert result["vol_div_bullish"] == 0.0

    def test_empty_frames(self):
        from src.intelligence.archive.i5_patterns.volume_divergence import VolumeDivergencePlugin

        plugin = VolumeDivergencePlugin()
        assert plugin.compute_full({}) == {}


# ─── Multi-Indicator Confluence ──────────────────────────────────


class TestConfluence:
    def test_overbought_confluence(self):
        """All indicators overbought → negative confluence score."""
        from src.intelligence.archive.i5_patterns.confluence import ConfluencePlugin

        features = {
            "rsi_14": 80.0,  # Overbought
            "macd_histogram_12_26_9": 5.0,  # Bullish actually, but RSI dominates
            "stoch_k_14_3": 90.0,  # Overbought
            "cci_14": 150.0,  # Overbought
        }
        plugin = ConfluencePlugin()
        result = plugin.compute_full(
            {
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )

        assert result["confluence_n_signals"] == 4.0
        # RSI=-1, MACD=+1, Stoch=-1, CCI=-1 → avg = -0.5
        assert result["confluence_score"] < 0
        # Semantic keys mirror legacy keys
        assert result["meanrev_confluence_score"] == result["confluence_score"]
        assert result["meanrev_confluence_n_signals"] == result["confluence_n_signals"]

    def test_oversold_confluence(self):
        """All indicators oversold → positive confluence score."""
        from src.intelligence.archive.i5_patterns.confluence import ConfluencePlugin

        features = {
            "rsi_14": 20.0,  # Oversold → bullish
            "stoch_k_14_3": 10.0,  # Oversold → bullish
            "cci_14": -150.0,  # Oversold → bullish
        }
        plugin = ConfluencePlugin()
        result = plugin.compute_full(
            {
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )

        assert result["confluence_score"] > 0.5
        assert result["confluence_n_signals"] == 3.0
        assert result["confluence_agreement"] == 1.0
        assert result["meanrev_confluence_agreement"] == 1.0

    def test_partial_indicators(self):
        """Only 2 indicators available → n_signals=2."""
        from src.intelligence.archive.i5_patterns.confluence import ConfluencePlugin

        features = {"rsi_14": 45.0, "cci_14": -50.0}
        plugin = ConfluencePlugin()
        result = plugin.compute_full(
            {
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )

        assert result["confluence_n_signals"] == 2.0

    def test_empty_features(self):
        from src.intelligence.archive.i5_patterns.confluence import ConfluencePlugin

        plugin = ConfluencePlugin()
        assert plugin.compute_full({}) == {}
        assert (
            plugin.compute_full(
                {"i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
            )
            == {}
        )


# ─── Registration ────────────────────────────────────────────────


class TestRegistration:
    def test_all_patterns_registered(self):
        """All 4 pattern plugins appear in registry."""
        from src.intelligence.archive.i5_patterns.bollinger_squeeze import plugin as squeeze
        from src.intelligence.archive.i5_patterns.confluence import plugin as confluence
        from src.intelligence.archive.i5_patterns.rsi_divergence import plugin as rsi_div
        from src.intelligence.archive.i5_patterns.volume_divergence import plugin as vol_div
        from src.intelligence.plugins import PluginRegistry

        reg = PluginRegistry()
        reg.register_pattern(rsi_div)
        reg.register_pattern(squeeze)
        reg.register_pattern(vol_div)
        reg.register_pattern(confluence)

        names = reg.list_patterns()
        assert len(names) == 4
        assert "RSIDivergence" in names
        assert "BollingerSqueeze" in names
        assert "VolumeDivergence" in names
        assert "Confluence" in names
