"""Tests for trad_VWAPDeviation setup plugin."""

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv


def _features(price, vwap=5000.0, vwap_std=10.0, trend_regime=0.0):
    """Build a minimal features dict with VWAP bands centred on vwap."""
    return {
        "vwap": vwap,
        "vwap_std": vwap_std,
        "vwap_upper_1": vwap + vwap_std,
        "vwap_lower_1": vwap - vwap_std,
        "vwap_upper_2": vwap + 2 * vwap_std,
        "vwap_lower_2": vwap - 2 * vwap_std,
        "trend_regime": trend_regime,
        "atr_14": 8.0,
    }


class TestVWAPDeviation:
    def test_long_signal_below_lower_band(self):
        """Price below vwap_lower_2 → vwap_reversion_long."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 5000.0)
        close[-1] = 4975.0          # below vwap_lower_2 = 4980
        df = make_ohlcv(close)
        features = _features(price=4975.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "vwap_reversion_long"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0
        assert result.get("entry_price") == pytest.approx(4975.0, abs=1.0)
        assert result.get("stop_loss") < result["entry_price"]
        targets = result.get("targets", [])
        assert len(targets) == 2
        assert targets[0] == pytest.approx(5000.0, abs=0.1)   # T1 = vwap

    def test_short_signal_above_upper_band(self):
        """Price above vwap_upper_2 → vwap_reversion_short."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 5000.0)
        close[-1] = 5025.0          # above vwap_upper_2 = 5020
        df = make_ohlcv(close)
        features = _features(price=5025.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "vwap_reversion_short"
        assert result.get("direction") == -1
        assert result.get("stop_loss") > result["entry_price"]
        targets = result.get("targets", [])
        assert len(targets) == 2
        assert targets[0] == pytest.approx(5000.0, abs=0.1)   # T1 = vwap

    def test_no_signal_within_bands(self):
        """Price inside ±2σ → no signal."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 5005.0)
        df = make_ohlcv(close)
        features = _features(price=5005.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_no_signal_zero_vwap_std(self):
        """vwap_std = 0 (no volume yet) → no signal."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 4970.0)
        df = make_ohlcv(close)
        features = _features(price=4970.0, vwap_std=0.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_confidence_scales_with_deviation(self):
        """Larger sigma deviation → higher confidence."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        plugin = VWAPDeviationPlugin()
        close_moderate = np.full(50, 4978.0)   # ~2.2σ below
        close_extreme = np.full(50, 4960.0)    # ~4.0σ below
        features_mod = _features(price=4978.0)
        features_ext = _features(price=4960.0)

        r_mod = plugin.compute_full({"main": make_ohlcv(close_moderate), "features": features_mod})
        r_ext = plugin.compute_full({"main": make_ohlcv(close_extreme), "features": features_ext})

        assert r_mod.get("signal_type") == "vwap_reversion_long"
        assert r_ext.get("signal_type") == "vwap_reversion_long"
        assert r_ext["confidence"] > r_mod["confidence"]

    def test_regime_context_values(self):
        """regime_context identifies the current overextension direction."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        plugin = VWAPDeviationPlugin()
        close_low = np.full(50, 4970.0)
        close_high = np.full(50, 5030.0)

        r_low = plugin.compute_full({"main": make_ohlcv(close_low), "features": _features(price=4970.0)})
        r_high = plugin.compute_full({"main": make_ohlcv(close_high), "features": _features(price=5030.0)})

        assert r_low.get("regime_context") == "vwap_extended_low"
        assert r_high.get("regime_context") == "vwap_extended_high"

    def test_insufficient_data_returns_empty(self):
        """Too few bars → empty dict."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.array([4975.0, 4974.0, 4973.0])
        df = make_ohlcv(close)
        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": {}})
        assert result == {} or result.get("signal_type", "none") == "none"

    def test_no_signal_in_high_vol_at_exactly_2sigma(self):
        """High vol (vol_regime=2) at exactly 2.0σ — below 2.5σ threshold, no signal."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        vwap, vwap_std = 5000.0, 10.0
        # Place price at exactly 2.0σ below vwap
        price = vwap - 2.0 * vwap_std   # = 4980.0, exactly at old 2σ boundary
        close = np.full(50, vwap)
        close[-1] = price
        df = make_ohlcv(close)
        features = _features(price=price, vwap=vwap, vwap_std=vwap_std)
        features["garch_vol_regime"] = 2   # high vol — threshold raised to 2.5σ

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_signal_fires_above_dynamic_threshold_in_high_vol(self):
        """High vol (vol_regime=2) at 2.6σ — exceeds 2.5σ threshold, signal fires."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        vwap, vwap_std = 5000.0, 10.0
        price = vwap - 2.6 * vwap_std   # = 4974.0, above 2.5σ threshold
        close = np.full(50, vwap)
        close[-1] = price
        df = make_ohlcv(close)
        features = _features(price=price, vwap=vwap, vwap_std=vwap_std)
        features["garch_vol_regime"] = 2

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("direction") == 1
        assert result.get("signal_type") == "vwap_reversion_long"

    def test_extreme_vol_requires_3sigma(self):
        """Extreme vol (vol_regime=3) at 2.9σ — below 3.0σ threshold, no signal."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        vwap, vwap_std = 5000.0, 10.0
        price = vwap + 2.9 * vwap_std   # = 5029.0, below 3.0σ threshold
        close = np.full(50, vwap)
        close[-1] = price
        df = make_ohlcv(close)
        features = _features(price=price, vwap=vwap, vwap_std=vwap_std)
        features["garch_vol_regime"] = 3   # extreme vol — threshold raised to 3.0σ

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0
