"""Tests for I2 composite indicator event plugins."""



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

    def test_hist_accel_increasing(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        # prev_hist = -0.5, hist = -0.3 → accel = -0.3 - (-0.5) = 0.2
        features, prev = self._features(hist=-0.3, prev_hist=-0.5)
        result = MACDEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert abs(result["macd_hist_accel"] - 0.2) < 1e-9

    def test_hist_accel_decreasing(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        # prev_hist = 0.5, hist = 0.3 → accel = 0.3 - 0.5 = -0.2
        features, prev = self._features(hist=0.3, prev_hist=0.5)
        result = MACDEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert abs(result["macd_hist_accel"] - (-0.2)) < 1e-9

    def test_hist_accel_no_prev(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        # No prev_features → macd_hist_accel = 0.0
        features, _ = self._features(hist=1.0)
        result = MACDEventsPlugin().compute_full({"features": features})
        assert result["macd_hist_accel"] == 0.0

    def test_hist_contracting_true(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        # abs(0.5) < abs(0.8) → macd_hist_contracting = 1
        features, prev = self._features(hist=0.5, prev_hist=0.8)
        result = MACDEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result["macd_hist_contracting"] == 1

    def test_hist_contracting_false(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        # abs(0.8) > abs(0.3) → macd_hist_contracting = 0
        features, prev = self._features(hist=0.8, prev_hist=0.3)
        result = MACDEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result["macd_hist_contracting"] == 0

    def test_hist_contracting_no_prev(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        # No prev_features → macd_hist_contracting = 0
        features, _ = self._features(hist=1.0)
        result = MACDEventsPlugin().compute_full({"features": features})
        assert result["macd_hist_contracting"] == 0

    def test_new_fields_in_outputs(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        p = MACDEventsPlugin()
        assert "macd_hist_accel" in p.outputs
        assert "macd_hist_contracting" in p.outputs


class TestRSIEvents:
    def test_rsi_crossed_30_up(self):
        from src.intelligence.composites.rsi_events import RSIEventsPlugin
        features = {"rsi_14": 32.0}
        prev = {"rsi_14": 27.0}
        result = RSIEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("rsi_crossed_30_up") == 1

    def test_rsi_extreme_reversal_from_oversold(self):
        from src.intelligence.composites.rsi_events import RSIEventsPlugin
        features = {"rsi_14": 28.0}
        prev = {"rsi_14": 24.0}
        result = RSIEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("rsi_extreme_reversal") == 1

    def test_no_signal_on_neutral_rsi(self):
        from src.intelligence.composites.rsi_events import RSIEventsPlugin
        features = {"rsi_14": 55.0}
        prev = {"rsi_14": 53.0}
        result = RSIEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("rsi_crossed_30_up") == 0
        assert result.get("rsi_crossed_70_down") == 0

    def test_empty_returns_empty(self):
        from src.intelligence.composites.rsi_events import RSIEventsPlugin
        assert RSIEventsPlugin().compute_full({}) == {}


class TestStochasticEvents:
    def test_bullish_cross_k_crosses_d_up(self):
        from src.intelligence.composites.stochastic_events import StochasticEventsPlugin
        features = {"stoch_k_14_3": 25.0, "stoch_d_14_3": 22.0}
        prev = {"stoch_k_14_3": 18.0, "stoch_d_14_3": 22.0}
        result = StochasticEventsPlugin().compute_full(
            {"features": features, "prev_features": prev}
        )
        assert result.get("stoch_cross_bullish") == 1

    def test_both_oversold(self):
        from src.intelligence.composites.stochastic_events import StochasticEventsPlugin
        features = {"stoch_k_14_3": 15.0, "stoch_d_14_3": 18.0}
        result = StochasticEventsPlugin().compute_full({"features": features})
        assert result.get("stoch_both_oversold") == 1


class TestADXEvents:
    def test_trend_confirmed_when_adx_crosses_25(self):
        from src.intelligence.composites.adx_events import ADXEventsPlugin
        features = {"adx_14": 26.0, "plus_di_14": 30.0, "minus_di_14": 20.0}
        prev = {"adx_14": 23.0, "plus_di_14": 28.0, "minus_di_14": 22.0}
        result = ADXEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("adx_trend_confirmed") == 1

    def test_di_spread_is_plus_minus_di_difference(self):
        from src.intelligence.composites.adx_events import ADXEventsPlugin
        features = {"adx_14": 30.0, "plus_di_14": 35.0, "minus_di_14": 20.0}
        result = ADXEventsPlugin().compute_full({"features": features})
        assert abs(result.get("di_spread", 0) - 15.0) < 0.01


class TestVolumeEvents:
    def test_vol_spike_detected(self):
        from src.intelligence.composites.volume_events import VolumeEventsPlugin
        features = {
            "volume": 5000.0, "volume_sma_20": 1000.0, "volume_std_20": 500.0, "close": 5100.0
        }
        result = VolumeEventsPlugin().compute_full({"features": features})
        assert result.get("vol_spike") == 1

    def test_empty_returns_empty(self):
        from src.intelligence.composites.volume_events import VolumeEventsPlugin
        assert VolumeEventsPlugin().compute_full({}) == {}
