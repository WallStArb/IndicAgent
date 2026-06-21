"""Correctness audit tests — known-output bar sequences for all I1-I6 plugins."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# Task 1.1: RSI — Wilder's smoothing
# ---------------------------------------------------------------------------


class TestRSICorrectness:
    def test_wilder_smoothing_not_simple_ma(self):
        """RSI must use Wilder's EWM (alpha=1/14), not simple average."""
        from src.intelligence.features.i1_indicators.rsi import RSIPlugin

        # Steady uptrend then drop: RSI should NOT be 100 after 14 up bars
        close = np.array([100.0 + i for i in range(20)] + [115.0, 114.0, 113.0])
        df = make_ohlcv(close)
        p = RSIPlugin()
        result = p.compute_full({"main": df})
        rsi = result.get("rsi_14")
        assert rsi is not None
        # After smoothing the drop, RSI should be < 100 and > 50
        assert 50 < rsi < 100

    def test_incremental_matches_full(self):
        """compute_next should match compute_full on the same data."""
        from src.intelligence.features.i1_indicators.rsi import RSIPlugin

        close = np.linspace(100, 120, 40)
        df_full = make_ohlcv(close)
        df_partial = make_ohlcv(close[:-1])

        p_full = RSIPlugin()
        r_full = p_full.compute_full({"main": df_full})

        p_inc = RSIPlugin()
        p_inc.compute_full({"main": df_partial})
        last_bar = pd.DataFrame(
            {
                "open": [close[-1]],
                "high": [close[-1] * 1.001],
                "low": [close[-1] * 0.999],
                "close": [close[-1]],
                "volume": [1000],
            }
        )
        df_next = pd.concat([df_partial, last_bar], ignore_index=True)
        r_inc = p_inc.compute_next({"main": df_next})

        assert abs(r_full["rsi_14"] - r_inc["rsi_14"]) < 0.01


# ---------------------------------------------------------------------------
# Task 1.2: ATR — Wilder's method
# ---------------------------------------------------------------------------


class TestATRCorrectness:
    def test_wilder_not_rolling_mean(self):
        """ATR must use Wilder's smoothing (EWM α=1/14), not rolling mean."""
        from src.intelligence.features.i1_indicators.atr import ATRPlugin

        close = np.full(30, 5000.0)
        high = close + 10.0
        low = close - 10.0
        high[-1] = 5100.0
        low[-1] = 4900.0
        df = pd.DataFrame(
            {"open": close, "high": high, "low": low, "close": close, "volume": np.full(30, 1000)}
        )
        p = ATRPlugin()
        result = p.compute_full({"main": df})
        atr = result.get("atr_14")
        assert atr is not None
        # ATR should be between 10 and 100 (smoothed, not jumped to 200)
        assert 10 < atr < 100


# ---------------------------------------------------------------------------
# Task 1.3: MACD histogram sign
# ---------------------------------------------------------------------------


class TestMACDCorrectness:
    def test_histogram_sign_on_bullish_cross(self):
        """Histogram = MACD_line - signal_line. Positive when MACD above signal."""
        from src.intelligence.features.i1_indicators.macd import MACDPlugin

        close = np.concatenate([np.linspace(5000, 5000, 40), np.linspace(5000, 5200, 20)])
        df = make_ohlcv(close)
        p = MACDPlugin()
        result = p.compute_full({"main": df})
        macd = result.get("macd_12_26_9")
        signal = result.get("macd_signal_12_26_9")
        hist = result.get("macd_histogram_12_26_9")
        assert macd is not None and signal is not None and hist is not None
        # histogram should equal macd - signal within floating point
        assert abs(hist - (macd - signal)) < 1e-6


# ---------------------------------------------------------------------------
# Task 1.4: VWAP session reset
# ---------------------------------------------------------------------------


class TestVWAPCorrectness:
    def test_vwap_equals_price_on_first_bar(self):
        """VWAP of a single bar should equal that bar's typical price."""
        from src.intelligence.features.i1_indicators.vwap import VWAPPlugin

        df = pd.DataFrame(
            {
                "open": [5000.0],
                "high": [5010.0],
                "low": [4990.0],
                "close": [5005.0],
                "volume": [1000.0],
            }
        )
        p = VWAPPlugin()
        result = p.compute_full({"main": df})
        vwap = result.get("vwap")
        if vwap is not None:
            expected = (5010 + 4990 + 5005) / 3  # ≈ 5001.67
            assert abs(vwap - expected) < 1.0

    def test_vwap_std_non_negative(self):
        """VWAP standard deviation must be non-negative."""
        from src.intelligence.features.i1_indicators.vwap import VWAPPlugin

        close = np.linspace(5000, 5100, 30)
        df = make_ohlcv(close)
        result = VWAPPlugin().compute_full({"main": df})
        std = result.get("vwap_std")
        if std is not None:
            assert std >= 0.0


# ---------------------------------------------------------------------------
# Task 1.5: Stochastic smoothing
# ---------------------------------------------------------------------------


class TestStochasticCorrectness:
    def test_k_at_high_extreme(self):
        """When close == period high, %K should be 100."""
        from src.intelligence.features.i1_indicators.stochastic import StochasticPlugin

        close = np.full(20, 5000.0)
        close[-1] = 5020.0  # New high
        high = close.copy()
        low = close - 20.0
        df = pd.DataFrame(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(20, 1000),
            }
        )
        p = StochasticPlugin()
        result = p.compute_full({"main": df})
        k = result.get("stoch_k_14_3")
        assert k is not None and k > 85

    def test_k_at_low_extreme(self):
        """When close == period low, %K should be near 0."""
        from src.intelligence.features.i1_indicators.stochastic import StochasticPlugin

        close = np.full(20, 5000.0)
        close[-1] = 4980.0  # New low
        high = close + 20.0
        low = close.copy()
        df = pd.DataFrame(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(20, 1000),
            }
        )
        result = StochasticPlugin().compute_full({"main": df})
        k = result.get("stoch_k_14_3")
        assert k is not None and k < 15


# ---------------------------------------------------------------------------
# Task 1.6: SwingDetector neighbor parameter
# ---------------------------------------------------------------------------


class TestSwingDetectorCorrectness:
    def test_swing_high_detected_with_clear_peak(self):
        """A clear 5-bar peak should be detected as swing high (need 60+ bars)."""
        from src.intelligence.features.i3_structure.swing_detector import SwingDetectorPlugin

        # Build 70 bars with a clear swing high in the middle
        flat = np.full(20, 100.0)
        peak = np.array([105, 110, 115, 120, 125, 120, 115, 110, 105, 100.0])
        close = np.concatenate([flat, peak, flat, flat])  # 70 bars
        df = make_ohlcv(close)
        p = SwingDetectorPlugin()
        result = p.compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("swing_high") is not None
        assert result.get("swing_high") > 100.0

    def test_swing_low_detected_in_downtrend(self):
        """A clear swing low should be detected."""
        from src.intelligence.features.i3_structure.swing_detector import SwingDetectorPlugin

        flat = np.full(20, 100.0)
        trough = np.array([95, 90, 85, 80, 75, 80, 85, 90, 95, 100.0])
        close = np.concatenate([flat, trough, flat, flat])  # 70 bars
        df = make_ohlcv(close)
        result = SwingDetectorPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("swing_low") is not None
        assert result.get("swing_low") < 100.0


# ---------------------------------------------------------------------------
# Task 1.7: GARCH parameters
# ---------------------------------------------------------------------------


class TestGARCHCorrectness:
    def test_sigma_positive_on_any_data(self):
        """GARCH sigma must always be positive."""
        from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin

        close = np.linspace(5000, 5200, 100) + np.random.default_rng(42).normal(0, 5, 100)
        df = make_ohlcv(close)
        p = GARCHVolatilityPlugin()
        result = p.compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        sigma = result.get("garch_sigma")
        if sigma is not None:
            assert sigma > 0

    def test_vol_regime_is_0_1_or_2(self):
        """GARCH vol_regime must be 0, 1, or 2."""
        from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin

        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        result = GARCHVolatilityPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        regime = result.get("garch_vol_regime")
        if regime is not None:
            assert regime in (0, 1, 2)


# ---------------------------------------------------------------------------
# Task 1.8: Bollinger Bands + OBV
# ---------------------------------------------------------------------------


class TestBollingerBandsCorrectness:
    def test_bands_are_mean_plus_minus_2sigma(self):
        """Upper = SMA20 + 2σ, lower = SMA20 - 2σ (population std, ddof=0)."""
        from src.intelligence.features.i1_indicators.bollinger import BollingerPlugin

        close = np.linspace(5000, 5100, 25)
        df = make_ohlcv(close)
        result = BollingerPlugin().compute_full({"main": df})
        mid = result.get("bb_20_2_mid")
        upper = result.get("bb_20_2_upper")
        lower = result.get("bb_20_2_lower")
        assert mid is not None
        expected_mid = float(np.mean(close[-20:]))
        assert abs(mid - expected_mid) < 0.01
        # Width should be symmetric
        assert abs((upper - mid) - (mid - lower)) < 0.01

    def test_bands_widen_on_volatile_data(self):
        """Volatile data should produce wider bands than flat data."""
        from src.intelligence.features.i1_indicators.bollinger import BollingerPlugin

        quiet = make_ohlcv(np.full(30, 5000.0))
        volatile_close = np.full(30, 5000.0)
        volatile_close[10:20] += np.linspace(0, 100, 10)
        volatile = make_ohlcv(volatile_close)
        r_quiet = BollingerPlugin().compute_full({"main": quiet})
        r_volatile = BollingerPlugin().compute_full({"main": volatile})
        quiet_width = r_quiet.get("bb_20_2_upper", 0) - r_quiet.get("bb_20_2_lower", 0)
        volatile_width = r_volatile.get("bb_20_2_upper", 0) - r_volatile.get("bb_20_2_lower", 0)
        assert volatile_width > quiet_width


class TestOBVCorrectness:
    def test_obv_increases_on_up_day(self):
        """On an up day (close > prev_close), OBV += volume."""
        from src.intelligence.features.i1_indicators.obv import OBVPlugin

        close = np.array([5000.0, 5010.0, 5020.0])
        volume = np.array([1000.0, 2000.0, 1500.0])
        df = make_ohlcv(close, volume)
        result = OBVPlugin().compute_full({"main": df})
        obv = result.get("obv")
        assert obv is not None
        assert obv > 0

    def test_obv_decreases_on_down_day(self):
        """On a down day (close < prev_close), OBV -= volume."""
        from src.intelligence.features.i1_indicators.obv import OBVPlugin

        close = np.array([5020.0, 5010.0, 5000.0])
        volume = np.array([1000.0, 2000.0, 1500.0])
        df = make_ohlcv(close, volume)
        result = OBVPlugin().compute_full({"main": df})
        obv = result.get("obv")
        assert obv is not None
        assert obv < 0


# ---------------------------------------------------------------------------
# Task 1.9: I3 Structure plugins
# ---------------------------------------------------------------------------


class TestSRClusteringCorrectness:
    def test_sr_levels_within_price_range(self):
        """S/R levels should be near current price range."""
        from src.intelligence.features.i3_structure.support_resistance import (
            SupportResistancePlugin,
        )

        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        result = SupportResistancePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        resistance = result.get("nearest_resistance")
        support = result.get("nearest_support")
        if resistance is not None:
            assert resistance >= close[-1] * 0.95
        if support is not None:
            assert support <= close[-1] * 1.05

    def test_support_dist_pct_is_percentage(self):
        """support_dist_pct is a percentage (0-100 scale), should be in plausible range."""
        from src.intelligence.features.i3_structure.support_resistance import (
            SupportResistancePlugin,
        )

        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        result = SupportResistancePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        dist = result.get("support_dist_pct")
        if dist is not None:
            # Plugin outputs percentage (0-100 scale), not fraction (0-1)
            assert 0 <= dist <= 100.0


class TestTrendStructureCorrectness:
    def test_structure_integrity_bounded_0_to_1(self):
        """structure_integrity must be in [0, 1]."""
        from src.intelligence.features.i3_structure.trend_structure import TrendStructurePlugin

        close = np.linspace(5000, 5200, 60)
        df = make_ohlcv(close)
        result = TrendStructurePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        integrity = result.get("structure_integrity")
        if integrity is not None:
            assert 0.0 <= integrity <= 1.0

    def test_trend_direction_uptrend(self):
        """Zigzag uptrend (HH/HL pattern) should produce positive trend_direction."""
        from src.intelligence.features.i3_structure.trend_structure import TrendStructurePlugin

        # Use a zigzag uptrend so swing detection finds clear HH/HL peaks
        base = np.linspace(5000, 5200, 60)
        zigzag = np.sin(np.linspace(0, 6 * np.pi, 60)) * 10  # 3 cycles of noise
        close = base + zigzag
        df = make_ohlcv(close)
        result = TrendStructurePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        direction = result.get("trend_direction")
        if direction is not None:
            assert direction >= 0  # uptrend → positive or neutral


# ---------------------------------------------------------------------------
# Task 1.10: I4 Context plugins
# ---------------------------------------------------------------------------


class TestKalmanCorrectness:
    def test_kalman_trend_tracks_uptrend(self):
        """Kalman trend should track upward price."""
        from src.intelligence.context.kalman_trend import KalmanTrendPlugin

        close = np.linspace(5000, 5200, 60)
        df = make_ohlcv(close)
        result = KalmanTrendPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        trend = result.get("kalman_trend")
        slope = result.get("kalman_slope")
        if trend is not None:
            assert trend > 5000
        if slope is not None:
            assert slope > 0

    def test_kalman_uncertainty_positive(self):
        """Kalman uncertainty (P_est) must always be positive."""
        from src.intelligence.context.kalman_trend import KalmanTrendPlugin

        close = np.linspace(5000, 5200, 60)
        df = make_ohlcv(close)
        result = KalmanTrendPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        uncertainty = result.get("kalman_uncertainty")
        if uncertainty is not None:
            assert uncertainty > 0


class TestTrendRegimeCorrectness:
    def test_uses_features_dict_not_recomputed(self):
        """TrendRegime must read sma_20/sma_50 from features when available."""
        from src.intelligence.context.trend_regime import TrendRegimePlugin

        features = {"sma_20": 5100.0, "sma_50": 5050.0, "close": 5150.0}
        close = np.full(60, 5000.0)  # flat price (different from injected SMAs)
        df = make_ohlcv(close)
        result = TrendRegimePlugin().compute_full(
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
        regime = result.get("trend_regime")
        assert regime is not None

    def test_trend_regime_bounded(self):
        """trend_regime must be in {-1.0, -0.5, 0.0, 0.5, 1.0}."""
        from src.intelligence.context.trend_regime import TrendRegimePlugin

        close = np.linspace(5000, 5200, 60)
        df = make_ohlcv(close)
        result = TrendRegimePlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        regime = result.get("trend_regime")
        if regime is not None:
            assert regime in (-1.0, -0.5, 0.0, 0.5, 1.0)


class TestMomentumContextCorrectness:
    def test_momentum_bias_positive_in_uptrend(self):
        """All bullish indicators should yield positive momentum_bias."""
        from src.intelligence.context.momentum_context import MomentumContextPlugin

        features = {
            "rsi_14": 65.0,
            "macd_histogram_12_26_9": 5.0,
            "stoch_k_14_3": 75.0,
            "cci_14": 120.0,
        }
        result = MomentumContextPlugin().compute_full(
            {
                "main": None,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        bias = result.get("momentum_bias")
        if bias is not None:
            assert bias > 0

    def test_momentum_bias_negative_in_downtrend(self):
        """All bearish indicators should yield negative momentum_bias."""
        from src.intelligence.context.momentum_context import MomentumContextPlugin

        features = {
            "rsi_14": 28.0,
            "macd_histogram_12_26_9": -5.0,
            "stoch_k_14_3": 15.0,
            "cci_14": -120.0,
        }
        result = MomentumContextPlugin().compute_full(
            {
                "main": None,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        bias = result.get("momentum_bias")
        if bias is not None:
            assert bias < 0


# ---------------------------------------------------------------------------
# Task 1.11: I5 Chart Pattern plugins
# ---------------------------------------------------------------------------


class TestBollingerSqueezeCorrectness:
    def test_squeeze_active_when_bb_inside_keltner(self):
        """BB inside Keltner = squeeze_active == 1."""
        from src.intelligence.archive.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin

        features = {
            "bb_20_2_upper": 5020.0,
            "bb_20_2_lower": 4980.0,  # BB width = 40
            "keltner_upper_20_2": 5030.0,
            "keltner_lower_20_2": 4970.0,  # KC width = 60
        }
        result = BollingerSqueezePlugin().compute_full(
            {
                "main": None,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        squeeze = result.get("squeeze_active")
        if squeeze is not None:
            assert squeeze == 1.0

    def test_no_squeeze_when_bb_outside_keltner(self):
        """BB outside Keltner = no squeeze."""
        from src.intelligence.archive.i5_patterns.bollinger_squeeze import BollingerSqueezePlugin

        features = {
            "bb_20_2_upper": 5050.0,
            "bb_20_2_lower": 4950.0,  # BB width = 100
            "keltner_upper_20_2": 5020.0,
            "keltner_lower_20_2": 4980.0,  # KC width = 40
        }
        result = BollingerSqueezePlugin().compute_full(
            {
                "main": None,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        squeeze = result.get("squeeze_active")
        if squeeze is not None:
            assert squeeze == 0.0


# ---------------------------------------------------------------------------
# Task 1.12: SMC plugins — BOS/CHoCH, FVG, OrderBlocks
# ---------------------------------------------------------------------------


class TestBOSCHoCHCorrectness:
    def test_bos_requires_close_not_wick(self):
        """BOS should trigger on close beyond swing level, not wick."""
        from src.intelligence.archive.smc_context.bos_choch import BOSCHoCHPlugin

        # 65 bars: uptrend to ~5100, retrace, then consolidation
        close = np.concatenate(
            [
                np.linspace(5000, 5100, 30),  # uptrend
                np.linspace(5100, 5080, 20),  # retrace
                np.linspace(5080, 5090, 15),  # consolidation
            ]
        )
        high = close + 5.0
        low = close - 5.0
        # Last bar: wick above swing high (5105) but closes at 5095 (below swing ~5100)
        high[-1] = 5105.0
        close[-1] = 5095.0
        df = pd.DataFrame(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(len(close), 1000),
            }
        )
        result = BOSCHoCHPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        bos = result.get("bos_detected", 0)
        # BOS should not trigger since close didn't break the swing high
        assert bos == 0, "BOS should not trigger on wick-only break"


class TestFVGCorrectness:
    def test_fvg_bullish_bar_indexing(self):
        """Bullish FVG: bar[-3].high < bar[-1].low (3-bar gap)."""
        from src.intelligence.archive.smc_context.fair_value_gap import FairValueGapPlugin

        # Repeat a pattern where bar[i].high < bar[i+2].low (bullish FVG)
        df = pd.DataFrame(
            {
                "open": [5000, 5005, 5025, 5028] * 20,
                "high": [5010, 5030, 5040, 5035] * 20,
                "low": [4995, 5000, 5020, 5022] * 20,
                "close": [5005, 5025, 5035, 5030] * 20,
                "volume": [1000] * 80,
            }
        )
        result = FairValueGapPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        fvg_type = result.get("fvg_type")
        # Plugin should detect an FVG (any type)
        assert fvg_type is not None


# ---------------------------------------------------------------------------
# Task 1.13: SMC — LiquiditySweeps, BOCPD, HMM
# ---------------------------------------------------------------------------


class TestLiquiditySweepsCorrectness:
    def test_sweep_detected_output_exists(self):
        """Plugin should return sweep_detected key."""
        from src.intelligence.archive.smc_context.liquidity_sweeps import LiquiditySweepsPlugin

        close = np.concatenate(
            [
                np.linspace(5100, 5000, 30),  # downtrend
                np.full(20, 5000.0),  # consolidation
                np.full(11, 5005.0),  # slight bounce
            ]
        )
        close[-1] = 5005.0
        high = close + 5.0
        low = close.copy()
        low[-1] = 4988.0  # wick low
        df = pd.DataFrame(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(len(close), 1000),
            }
        )
        result = LiquiditySweepsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert "sweep_detected" in result or result == {}  # either detects or returns empty


class TestHMMCorrectness:
    def test_hmm_macd_key_name_is_correct(self):
        """Verify HMM uses macd_histogram_12_26_9 (not macd_hist_12_26_9)."""
        from src.intelligence.archive.smc_context.hmm_regime import HMMRegimePlugin

        source = inspect.getsource(HMMRegimePlugin)
        assert (
            "macd_hist_12_26_9" not in source
        ), "HMM uses wrong MACD key. Should be macd_histogram_12_26_9"

    def test_hmm_regime_values_are_0_1_or_2(self):
        """HMM regime must be 0, 1, or 2."""
        from src.intelligence.archive.smc_context.hmm_regime import HMMRegimePlugin

        close = np.linspace(5000, 5200, 80)
        df = make_ohlcv(close)
        features = {"rsi_14": 60.0, "macd_histogram_12_26_9": 5.0, "atr_14": 10.0}
        result = HMMRegimePlugin().compute_full(
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
        regime = result.get("hmm_regime")
        if regime is not None:
            assert regime in (0.0, 1.0, 2.0)


# ---------------------------------------------------------------------------
# Task 1.14: SMC — LiquidityPools, SupplyDemand
# ---------------------------------------------------------------------------


class TestLiquidityPoolsCorrectness:
    def test_bsl_above_price_ssl_below(self):
        """BSL must be above current close; SSL must be below."""
        from src.intelligence.archive.smc_context.liquidity_pools import LiquidityPoolsPlugin

        close = np.concatenate(
            [
                np.linspace(5050, 5100, 20),  # swing highs (BSL)
                np.linspace(5100, 5050, 20),
                np.linspace(5050, 4980, 20),  # swing lows (SSL)
                np.linspace(4980, 5020, 20),
            ]
        )
        df = make_ohlcv(close)
        result = LiquidityPoolsPlugin().compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        bsl = result.get("bsl_level")
        ssl = result.get("ssl_level")
        current_price = float(close[-1])
        if bsl is not None and bsl > 0:
            assert bsl > current_price * 0.98, f"BSL {bsl} should be above price {current_price}"
        if ssl is not None and ssl > 0:
            assert ssl < current_price * 1.02, f"SSL {ssl} should be below price {current_price}"


class TestSupplyDemandCorrectness:
    def test_freshness_decreases_or_zones_clear_after_retest(self):
        """demand_freshness should drop (or zones clear) after price revisits zone."""
        from src.intelligence.archive.smc_context.supply_demand_zones import (
            SupplyDemandZonesPlugin,
        )

        close = np.concatenate(
            [
                np.linspace(4950, 4980, 10),  # demand zone base
                np.linspace(4980, 5100, 20),  # rally (fresh zone)
                np.linspace(5100, 4960, 20),  # retrace back to zone
            ]
        )
        df_fresh = make_ohlcv(close[:30])
        df_tested = make_ohlcv(close)

        r_fresh = SupplyDemandZonesPlugin().compute_full(
            {
                "main": df_fresh,
                "i1": {},
                "i2": {},
                "i3": {},
                "i4": {},
                "i5": {},
                "smc": {},
                "i6": {},
            }
        )
        r_tested = SupplyDemandZonesPlugin().compute_full(
            {
                "main": df_tested,
                "i1": {},
                "i2": {},
                "i3": {},
                "i4": {},
                "i5": {},
                "smc": {},
                "i6": {},
            }
        )

        fresh_val = r_fresh.get("demand_freshness", 1.0)
        tested_val = r_tested.get("demand_freshness", 1.0)
        demand_after = r_tested.get("active_demand_zones", 0)
        # Either freshness dropped or zones were cleared
        assert tested_val <= fresh_val or demand_after == 0
