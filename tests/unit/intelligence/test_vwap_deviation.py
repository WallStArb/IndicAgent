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
        "hmm_prob_ranging": 0.65,  # continuous regime gate (mean_reversion: ranging >= 0.30)
        "ctf_score": 0.40,  # I6 gate (abs >= 0.25)
    }


class TestVWAPDeviation:
    def test_long_signal_below_lower_band(self):
        """Price below vwap_lower_2 → vwap_reversion_long."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 5000.0)
        close[-1] = 4975.0  # below vwap_lower_2 = 4980
        df = make_ohlcv(close)
        features = _features(price=4975.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full(
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

        assert result.get("signal_type") == "vwap_reversion_long"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0
        assert result.get("entry_price") == pytest.approx(4975.0, abs=1.0)
        assert result.get("stop_loss") < result["entry_price"]
        targets = result.get("targets", [])
        assert len(targets) == 2
        assert targets[0] >= 5000.0 - 0.1  # T1 >= vwap (zone expansion may push to vwap_upper_1)

    def test_short_signal_above_upper_band(self):
        """Price above vwap_upper_2 → vwap_reversion_short."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 5000.0)
        close[-1] = 5025.0  # above vwap_upper_2 = 5020
        df = make_ohlcv(close)
        features = _features(price=5025.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full(
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

        assert result.get("signal_type") == "vwap_reversion_short"
        assert result.get("direction") == -1
        assert result.get("stop_loss") > result["entry_price"]
        targets = result.get("targets", [])
        assert len(targets) == 2
        assert targets[0] <= 5000.0 + 0.1  # T1 <= vwap (zone expansion may use vwap_lower_1)

    def test_no_signal_within_bands(self):
        """Price inside ±2σ → no signal."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 5005.0)
        df = make_ohlcv(close)
        features = _features(price=5005.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full(
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

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_no_signal_zero_vwap_std(self):
        """vwap_std = 0 (no volume yet) → no signal."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 4970.0)
        df = make_ohlcv(close)
        features = _features(price=4970.0, vwap_std=0.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full(
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

        assert result.get("signal_type", "none") == "none"

    def test_confidence_scales_with_deviation(self):
        """Larger sigma deviation → higher confidence."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        plugin = VWAPDeviationPlugin()
        close_moderate = np.full(50, 4978.0)  # ~2.2σ below
        close_extreme = np.full(50, 4960.0)  # ~4.0σ below
        features_mod = _features(price=4978.0)
        features_ext = _features(price=4960.0)

        r_mod = plugin.compute_full(
            {
                "main": make_ohlcv(close_moderate),
                "i1": features_mod,
                "i2": features_mod,
                "i3": features_mod,
                "i4": features_mod,
                "i5": features_mod,
                "smc": features_mod,
                "i6": features_mod,
            }
        )
        r_ext = plugin.compute_full(
            {
                "main": make_ohlcv(close_extreme),
                "i1": features_ext,
                "i2": features_ext,
                "i3": features_ext,
                "i4": features_ext,
                "i5": features_ext,
                "smc": features_ext,
                "i6": features_ext,
            }
        )

        assert r_mod.get("signal_type") == "vwap_reversion_long"
        assert r_ext.get("signal_type") == "vwap_reversion_long"
        assert r_ext["confidence"] > r_mod["confidence"]

    def test_regime_context_values(self):
        """regime_context identifies the current overextension direction."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        plugin = VWAPDeviationPlugin()
        close_low = np.full(50, 4970.0)
        close_high = np.full(50, 5030.0)

        r_low = plugin.compute_full(
            {
                "main": make_ohlcv(close_low),
                "i1": _features(price=4970.0),
                "i2": _features(price=4970.0),
                "i3": _features(price=4970.0),
                "i4": _features(price=4970.0),
                "i5": _features(price=4970.0),
                "smc": _features(price=4970.0),
                "i6": _features(price=4970.0),
            }
        )
        r_high = plugin.compute_full(
            {
                "main": make_ohlcv(close_high),
                "i1": _features(price=5030.0),
                "i2": _features(price=5030.0),
                "i3": _features(price=5030.0),
                "i4": _features(price=5030.0),
                "i5": _features(price=5030.0),
                "smc": _features(price=5030.0),
                "i6": _features(price=5030.0),
            }
        )

        assert r_low.get("regime_context") == "vwap_extended_low"
        assert r_high.get("regime_context") == "vwap_extended_high"

    def test_insufficient_data_returns_empty(self):
        """Too few bars → empty dict."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        close = np.array([4975.0, 4974.0, 4973.0])
        df = make_ohlcv(close)
        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result == {} or result.get("signal_type", "none") == "none"

    def test_no_signal_in_high_vol_at_exactly_2sigma(self):
        """High vol (vol_regime=2) at exactly 2.0σ — below 2.5σ threshold, no signal."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        vwap, vwap_std = 5000.0, 10.0
        # Place price at exactly 2.0σ below vwap
        price = vwap - 2.0 * vwap_std  # = 4980.0, exactly at old 2σ boundary
        close = np.full(50, vwap)
        close[-1] = price
        df = make_ohlcv(close)
        features = _features(price=price, vwap=vwap, vwap_std=vwap_std)
        features["garch_vol_regime"] = 2  # high vol — threshold raised to 2.5σ

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full(
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

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_signal_fires_above_dynamic_threshold_in_high_vol(self):
        """High vol (vol_regime=2) at 2.6σ — exceeds 2.5σ threshold, signal fires."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        vwap, vwap_std = 5000.0, 10.0
        price = vwap - 2.6 * vwap_std  # = 4974.0, above 2.5σ threshold
        close = np.full(50, vwap)
        close[-1] = price
        df = make_ohlcv(close)
        features = _features(price=price, vwap=vwap, vwap_std=vwap_std)
        features["garch_vol_regime"] = 2

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full(
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

        assert result.get("direction") == 1
        assert result.get("signal_type") == "vwap_reversion_long"

    def test_extreme_vol_requires_3sigma(self):
        """Extreme vol (vol_regime=3) at 2.9σ — below 3.0σ threshold, no signal."""
        from src.intelligence.archive.trading_i7.vwap_deviation import VWAPDeviationPlugin

        vwap, vwap_std = 5000.0, 10.0
        price = vwap + 2.9 * vwap_std  # = 5029.0, below 3.0σ threshold
        close = np.full(50, vwap)
        close[-1] = price
        df = make_ohlcv(close)
        features = _features(price=price, vwap=vwap, vwap_std=vwap_std)
        features["garch_vol_regime"] = 3  # extreme vol — threshold raised to 3.0σ

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full(
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

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0
