"""Tests for I2 composite indicator event plugins."""
import numpy as np
import pandas as pd

from tests.unit.intelligence.helpers import make_ohlcv


class TestMACompositeExtended:
    def test_golden_cross_active_when_sma50_gt_sma200(self):
        """When sma_50 > sma_200 in features, golden_cross_active = 1."""
        from src.intelligence.composites.ma_composites import MACompositePlugin
        features = {"sma_50": 5100.0, "sma_200": 5000.0, "close": 5150.0}
        p = MACompositePlugin()
        result = p.compute_full({"features": features})
        assert result.get("golden_cross_active") == 1

    def test_death_cross_active_when_sma50_lt_sma200(self):
        """When sma_50 < sma_200 in features, death_cross_active = 1."""
        from src.intelligence.composites.ma_composites import MACompositePlugin
        features = {"sma_50": 4900.0, "sma_200": 5000.0, "close": 4850.0}
        p = MACompositePlugin()
        result = p.compute_full({"features": features})
        assert result.get("death_cross_active") == 1
        assert result.get("golden_cross_active") == 0

    def test_price_above_sma200(self):
        """When price > sma_200, price_above_sma200 = 1. If SMA200 missing, returns None."""
        from src.intelligence.composites.ma_composites import MACompositePlugin
        features = {"sma_200": 5000.0, "close": 5100.0}
        result = MACompositePlugin().compute_full({"features": features})
        assert result.get("price_above_sma200") == 1

    def test_empty_returns_empty(self):
        """Empty features dict returns empty dict."""
        from src.intelligence.composites.ma_composites import MACompositePlugin
        assert MACompositePlugin().compute_full({}) == {}


class TestMACDEvents:
    def _features(self, macd=10.0, signal=5.0, hist=5.0,
                  prev_macd=4.0, prev_signal=6.0, prev_hist=-2.0,
                  close=5100.0, prev_close=5050.0):
        return {
            "macd_12_26_9": macd, "macd_signal_12_26_9": signal,
            "macd_histogram_12_26_9": hist,
            "close": close,
        }, {
            "macd_12_26_9": prev_macd, "macd_signal_12_26_9": prev_signal,
            "macd_histogram_12_26_9": prev_hist,
            "close": prev_close,
        }

    def test_bullish_cross_detected(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        # prev: macd < signal, now: macd > signal
        features, prev = self._features(macd=10, signal=8, prev_macd=4, prev_signal=6)
        result = MACDEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("macd_cross_bullish") == 1
        assert result.get("macd_cross_bearish") == 0

    def test_hist_positive_flag(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        features, _ = self._features(hist=5.0)
        result = MACDEventsPlugin().compute_full({"features": features})
        assert result.get("macd_hist_positive") == 1

    def test_hist_turning_up_from_negative(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        features, prev = self._features(hist=-1.0, prev_hist=-5.0)
        result = MACDEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("macd_hist_turning_up") == 1

    def test_empty_returns_empty(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        assert MACDEventsPlugin().compute_full({}) == {}
