"""Tests for Trend Confluence pattern plugin."""

from src.intelligence.archive.i5_patterns.trend_confluence import TrendConfluencePlugin


class TestTrendConfluence:
    def test_all_bullish_signals(self):
        """All signals bullish → score near +1, high agreement."""
        features = {
            "sma_20_gt_50": True,
            "adx_14": 30,
            "plus_di_14": 25,
            "minus_di_14": 15,
            "swing_pattern": 1,
            "macd_histogram_12_26_9": 0.5,
            "supertrend_dir": 1,
            "trend_regime": 0.8,
        }
        plugin = TrendConfluencePlugin()
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
        assert result["trend_confluence_score"] > 0.5
        assert result["trend_confluence_agreement"] > 0.8
        assert result["trend_confluence_n_signals"] == 6

    def test_all_bearish_signals(self):
        """All signals bearish → score near -1."""
        features = {
            "sma_20_gt_50": False,
            "adx_14": 30,
            "plus_di_14": 15,
            "minus_di_14": 25,
            "swing_pattern": -1,
            "macd_histogram_12_26_9": -0.5,
            "supertrend_dir": -1,
            "trend_regime": -0.8,
        }
        plugin = TrendConfluencePlugin()
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
        assert result["trend_confluence_score"] < -0.5
        assert result["trend_confluence_agreement"] > 0.8

    def test_mixed_signals_low_agreement(self):
        """Mixed signals should produce low agreement."""
        features = {
            "sma_20_gt_50": True,
            "adx_14": 30,
            "plus_di_14": 15,  # bearish DI
            "minus_di_14": 25,
            "swing_pattern": -1,
            "macd_histogram_12_26_9": 0.5,
            "supertrend_dir": -1,
            "trend_regime": 0.5,
        }
        plugin = TrendConfluencePlugin()
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
        assert result["trend_confluence_agreement"] < 0.8

    def test_adx_below_20_skipped(self):
        """ADX < 20 means no directional signal (weak trend)."""
        features = {
            "adx_14": 15,
            "plus_di_14": 25,
            "minus_di_14": 15,
            "macd_histogram_12_26_9": 0.5,
        }
        plugin = TrendConfluencePlugin()
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
        # Only MACD should count (ADX skipped due to weak trend)
        assert result["trend_confluence_n_signals"] == 1

    def test_partial_signals_still_works(self):
        """Should work with only some signals available."""
        features = {"supertrend_dir": 1, "trend_regime": 0.5}
        plugin = TrendConfluencePlugin()
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
        assert result["trend_confluence_n_signals"] == 2
        assert result["trend_confluence_score"] > 0

    def test_no_features_returns_empty(self):
        plugin = TrendConfluencePlugin()
        result = plugin.compute_full({})
        assert result == {}

    def test_empty_features_returns_empty(self):
        plugin = TrendConfluencePlugin()
        result = plugin.compute_full(
            {"i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result == {}

    def test_strength_output(self):
        """Strength = abs(score) * agreement."""
        features = {
            "sma_20_gt_50": True,
            "supertrend_dir": 1,
            "trend_regime": 1.0,
        }
        plugin = TrendConfluencePlugin()
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
        expected_strength = (
            abs(result["trend_confluence_score"]) * result["trend_confluence_agreement"]
        )
        assert abs(result["trend_confluence_strength"] - expected_strength) < 1e-6

    def test_output_keys(self):
        features = {"supertrend_dir": 1}
        plugin = TrendConfluencePlugin()
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
        assert "trend_confluence_score" in result
        assert "trend_confluence_n_signals" in result
        assert "trend_confluence_agreement" in result
        assert "trend_confluence_strength" in result
