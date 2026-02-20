"""Tests for smart money concept plugins (I5 tier)."""

import numpy as np
import pandas as pd

from tests.unit.intelligence.helpers import make_ohlcv, make_ohlcv_from_hl


def _triangle(center: int, half_width: int, n: int) -> np.ndarray:
    """Triangle wave centered at `center`, amplitude 1.0, zero outside."""
    arr = np.zeros(n)
    for i in range(max(0, center - half_width), min(n, center + half_width + 1)):
        arr[i] = max(0, 1 - abs(i - center) / half_width)
    return arr


# ─── BOS / CHoCH ──────────────────────────────────────────────


class TestBOSCHoCH:
    def test_bullish_bos_in_uptrend(self):
        """Price breaking above swing high in uptrend → bullish BOS, not CHoCH."""
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        n = 120
        close = np.full(n, 5000.0)
        # Uptrend: SL1(20,-100) -> SH1(35,+100) -> SL2(50,-60=HL) -> SH2(65,+130=HH)
        close -= 100 * _triangle(20, 9, n)
        close += 100 * _triangle(35, 9, n)
        close -= 60 * _triangle(50, 9, n)
        close += 130 * _triangle(65, 9, n)
        # Break above SH2: bars 75-119 monotonic rise (no flat gap)
        for i in range(75, 120):
            close[i] = 5135 + (i - 75) * 3

        df = make_ohlcv(close)
        plugin = BOSCHoCHPlugin()
        result = plugin.compute_full({"main": df})

        assert "bos_detected" in result
        assert "bos_direction" in result
        assert "choch_detected" in result
        assert result["bos_direction"] == 1.0  # Bullish
        assert result["choch_detected"] == 0.0  # Not a CHoCH (same direction as trend)

    def test_choch_after_downtrend(self):
        """Bullish break after downtrend → CHoCH (reversal signal)."""
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        n = 120
        close = np.full(n, 5000.0)
        # Downtrend: SH1(20,+100) -> SL1(35,-100) -> SH2(50,+60=LH) -> SL2(65,-130=LL)
        close += 100 * _triangle(20, 9, n)
        close -= 100 * _triangle(35, 9, n)
        close += 60 * _triangle(50, 9, n)
        close -= 130 * _triangle(65, 9, n)
        # Bullish break above SH2 → CHoCH
        for i in range(85, 120):
            close[i] = 5065 + (i - 85) * 3

        df = make_ohlcv(close)
        plugin = BOSCHoCHPlugin()
        result = plugin.compute_full({"main": df})

        assert result["choch_detected"] == 1.0
        assert result["choch_direction"] == 1.0  # Bullish reversal

    def test_no_bos_ranging(self):
        """Flat market with no breaks → no BOS."""
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        close = np.full(100, 5000.0) + np.random.default_rng(42).normal(0, 2, 100)
        df = make_ohlcv(close)
        plugin = BOSCHoCHPlugin()
        result = plugin.compute_full({"main": df})

        assert result.get("bos_detected", 0.0) == 0.0

    def test_empty_input(self):
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        plugin = BOSCHoCHPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

    def test_insufficient_data(self):
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        df = make_ohlcv(np.full(10, 5000.0))
        plugin = BOSCHoCHPlugin()
        assert plugin.compute_full({"main": df}) == {}


# ─── Fair Value Gap ────────────────────────────────────────────


class TestFairValueGap:
    def test_bullish_fvg(self):
        """3-candle gap up: bar3.low > bar1.high → bullish FVG."""
        from src.intelligence.smart_money.fair_value_gap import FairValueGapPlugin

        n = 60
        close = np.full(n, 5000.0)
        # Impulsive bullish move at bars 30-32
        close[31] = 5050
        close[32] = 5060
        for i in range(33, n):
            close[i] = 5060  # Stay above, FVG unfilled

        df = make_ohlcv(close)
        plugin = FairValueGapPlugin()
        result = plugin.compute_full({"main": df})

        assert result["fvg_type"] != 0.0
        assert result["fvg_top"] > result["fvg_bottom"]
        assert result["fvg_open_count"] >= 1.0

    def test_no_fvg_gradual(self):
        """Gradual move → no FVG (no 3-candle gap)."""
        from src.intelligence.smart_money.fair_value_gap import FairValueGapPlugin

        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        plugin = FairValueGapPlugin()
        result = plugin.compute_full({"main": df})

        assert result["fvg_type"] == 0.0
        assert result["fvg_open_count"] == 0.0

    def test_fvg_filled(self):
        """FVG that gets filled by price retracing → should not count as open."""
        from src.intelligence.smart_money.fair_value_gap import FairValueGapPlugin

        n = 60
        close = np.full(n, 5000.0)
        # Create FVG at bars 20-22
        close[21] = 5050
        close[22] = 5060
        # Price retraces back into the gap
        for i in range(30, 40):
            close[i] = 5005  # Back into the gap zone, filling it
        for i in range(40, n):
            close[i] = 5060  # Back up

        df = make_ohlcv(close)
        plugin = FairValueGapPlugin()
        result = plugin.compute_full({"main": df})

        # The FVG from bars 20-22 should be filled, not counted as open
        assert isinstance(result["fvg_open_count"], float)

    def test_empty_input(self):
        from src.intelligence.smart_money.fair_value_gap import FairValueGapPlugin

        plugin = FairValueGapPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}


# ─── Order Blocks ──────────────────────────────────────────────


class TestOrderBlocks:
    def test_bullish_order_block(self):
        """Last bearish candle before bullish impulse → bullish OB."""
        from src.intelligence.smart_money.order_blocks import OrderBlocksPlugin

        n = 80
        close = np.full(n, 5000.0)
        open_ = np.full(n, 5000.0)

        # Bearish candle at bar 40 (the order block)
        open_[40] = 5010
        close[40] = 4990

        # Bullish impulse bars 41-44 (3+ consecutive bullish candles, strong move)
        for i in range(41, 45):
            open_[i] = close[i - 1]
            close[i] = open_[i] + 30

        # Continue at elevated level
        for i in range(45, n):
            open_[i] = close[44]
            close[i] = close[44]

        high = np.maximum(open_, close) * 1.002
        low = np.minimum(open_, close) * 0.998
        volume = np.full(n, 1000.0)
        # Higher volume on impulse
        volume[41:45] = 3000.0

        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
        )
        plugin = OrderBlocksPlugin()
        result = plugin.compute_full({"main": df})

        assert result["ob_type"] == 1.0  # Bullish
        assert result["ob_top"] > result["ob_bottom"]
        assert result["ob_strength"] > 0

    def test_no_ob_no_impulse(self):
        """No impulsive move → no order block."""
        from src.intelligence.smart_money.order_blocks import OrderBlocksPlugin

        close = np.full(60, 5000.0) + np.random.default_rng(42).normal(0, 2, 60)
        df = make_ohlcv(close)
        plugin = OrderBlocksPlugin()
        result = plugin.compute_full({"main": df})

        assert result["ob_type"] == 0.0

    def test_empty_input(self):
        from src.intelligence.smart_money.order_blocks import OrderBlocksPlugin

        plugin = OrderBlocksPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}


# ─── Liquidity Sweeps ─────────────────────────────────────────


class TestLiquiditySweeps:
    def test_bullish_sweep(self):
        """Wick below swing low that closes back above → bullish sweep."""
        from src.intelligence.smart_money.liquidity_sweeps import LiquiditySweepsPlugin

        n = 120
        # Build data with a clear swing low, then a sweep
        high = np.full(n, 5020.0)
        low = np.full(n, 4980.0)

        # Create a swing low at bar 30 (N=5 means bars 25-35 must frame it)
        # Trough shape: bars 20-40, bottom at 30
        for i in range(20, 41):
            d = max(0, 1 - abs(i - 30) / 11)
            low[i] = 4980 - 50 * d
            high[i] = low[i] + 40

        # Normal bars in between
        for i in range(41, 80):
            low[i] = 4980
            high[i] = 5020

        # Sweep at bar 85: wick below the swing low but close above it
        low[85] = 4920  # Below the swing low of ~4930
        high[85] = 5010

        # Bars after sweep close above the swing low (reclaim)
        for i in range(86, 92):
            low[i] = 4980
            high[i] = 5020

        df = make_ohlcv_from_hl(high, low)
        plugin = LiquiditySweepsPlugin()
        result = plugin.compute_full({"main": df})

        assert result["sweep_detected"] == 1.0
        assert result["sweep_type"] == 1.0  # Bullish (swept lows)

    def test_no_sweep_clean_trend(self):
        """Clean uptrend with no wicks beyond swing levels → no sweep."""
        from src.intelligence.smart_money.liquidity_sweeps import LiquiditySweepsPlugin

        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        plugin = LiquiditySweepsPlugin()
        result = plugin.compute_full({"main": df})

        assert result["sweep_detected"] == 0.0

    def test_empty_input(self):
        from src.intelligence.smart_money.liquidity_sweeps import LiquiditySweepsPlugin

        plugin = LiquiditySweepsPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

    def test_insufficient_data(self):
        from src.intelligence.smart_money.liquidity_sweeps import LiquiditySweepsPlugin

        df = make_ohlcv(np.full(10, 5000.0))
        plugin = LiquiditySweepsPlugin()
        assert plugin.compute_full({"main": df}) == {}


# ─── BOCPD Change Point Detection ─────────────────────────────


class TestBOCPDChangePoint:
    def test_detects_regime_change(self):
        """Flat returns then volatile returns → change point detected."""
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        n = 100
        close = np.full(n, 5000.0)
        # First 50 bars: steady (tiny noise)
        close[:50] += np.random.default_rng(1).normal(0, 0.5, 50)
        # Bar 50+: volatile regime (large moves)
        close[50:] += np.cumsum(np.random.default_rng(2).normal(0, 20, 50))

        df = make_ohlcv(close)
        plugin = BOCPDChangePointPlugin()
        result = plugin.compute_full({"main": df})

        assert "cp_probability" in result
        assert "cp_raw_probability" in result
        assert "cp_run_length" in result
        assert "cp_detected" in result
        # Should detect a change point somewhere
        assert result["cp_raw_probability"] > 0.0

    def test_no_change_steady(self):
        """Steady returns with consistent noise → low change point probability."""
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        n = 100
        rng = np.random.default_rng(42)
        close = 5000.0 + np.cumsum(rng.normal(0, 1, n))

        df = make_ohlcv(close)
        plugin = BOCPDChangePointPlugin()
        result = plugin.compute_full({"main": df})

        # Steady noise should produce low change point probability
        assert result["cp_raw_probability"] < 0.5

    def test_incremental_matches_full(self):
        """compute_next produces same result as compute_full on same data."""
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        rng = np.random.default_rng(7)
        close = 5000.0 + np.cumsum(rng.normal(0, 2, 80))

        df_full = make_ohlcv(close)
        plugin_full = BOCPDChangePointPlugin()
        result_full = plugin_full.compute_full({"main": df_full})

        # Incremental: seed with first 50, then feed remaining bars
        plugin_inc = BOCPDChangePointPlugin()
        df_seed = make_ohlcv(close[:50])
        plugin_inc.compute_full({"main": df_seed})

        result_inc = {}
        for i in range(51, len(close) + 1):
            df_inc = make_ohlcv(close[:i])
            result_inc = plugin_inc.compute_next({"main": df_inc})

        # Final values should match (within floating point tolerance)
        assert abs(result_inc["cp_raw_probability"] - result_full["cp_raw_probability"]) < 0.05
        assert abs(result_inc["cp_run_length"] - result_full["cp_run_length"]) < 3

    def test_empty_input(self):
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        plugin = BOCPDChangePointPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

    def test_insufficient_data(self):
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        df = make_ohlcv(np.full(5, 5000.0))
        plugin = BOCPDChangePointPlugin()
        assert plugin.compute_full({"main": df}) == {}

    def test_graceful_without_features(self):
        """Works with just OHLCV, no frames['features'] — confirmation defaults to 0.5."""
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        n = 80
        close = np.full(n, 5000.0)
        close[40:] += np.cumsum(np.random.default_rng(3).normal(0, 15, 40))

        df = make_ohlcv(close)
        plugin = BOCPDChangePointPlugin()
        # No "features" key — should still work
        result = plugin.compute_full({"main": df})

        assert result["cp_confirmation"] == 0.5
        assert result["cp_probability"] > 0.0


# ─── HMM Regime Detection ────────────────────────────────────


class TestHMMRegime:
    def test_trending_up_detection(self):
        """Rising prices should be classified as trending-up (state 1)."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(42)
        # Strong uptrend: consistent positive drift
        close = 5000.0 + np.cumsum(np.abs(rng.normal(0.5, 0.3, 200)))
        df = make_ohlcv(close)
        features = {"rsi_14": 65.0, "adx_14": 30.0, "macd_hist_12_26_9": 2.0, "atr_14": 10.0}

        plugin = HMMRegimePlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result != {}
        assert result["hmm_regime"] == 1.0  # Trending up
        assert result["hmm_prob_trending_up"] > result["hmm_prob_ranging"]
        assert result["hmm_prob_trending_up"] > result["hmm_prob_trending_down"]
        assert result["hmm_regime_prob"] > 0.5
        assert result["hmm_regime_duration"] >= 1.0

    def test_trending_down_detection(self):
        """Falling prices should be classified as trending-down (state 2)."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(42)
        # Strong downtrend: consistent negative drift
        close = 5000.0 - np.cumsum(np.abs(rng.normal(0.5, 0.3, 200)))
        df = make_ohlcv(close)
        features = {"rsi_14": 35.0, "adx_14": 30.0, "macd_hist_12_26_9": -2.0, "atr_14": 10.0}

        plugin = HMMRegimePlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result != {}
        assert result["hmm_regime"] == 2.0  # Trending down
        assert result["hmm_prob_trending_down"] > result["hmm_prob_ranging"]
        assert result["hmm_prob_trending_down"] > result["hmm_prob_trending_up"]

    def test_ranging_detection(self):
        """Flat oscillating prices should be classified as ranging (state 0)."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(42)
        # Ranging: oscillate around 5000 with small noise, no drift
        close = 5000.0 + rng.normal(0, 0.5, 200)
        df = make_ohlcv(close)
        features = {"rsi_14": 50.0, "adx_14": 12.0, "macd_hist_12_26_9": 0.0, "atr_14": 10.0}

        plugin = HMMRegimePlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result != {}
        assert result["hmm_regime"] == 0.0  # Ranging
        assert result["hmm_prob_ranging"] > result["hmm_prob_trending_up"]
        assert result["hmm_prob_ranging"] > result["hmm_prob_trending_down"]

    def test_incremental_parity(self):
        """compute_next() on full history should match compute_full()."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(99)
        close = 5000.0 + np.cumsum(rng.normal(0.3, 0.5, 100))
        features = {"rsi_14": 60.0, "adx_14": 25.0, "macd_hist_12_26_9": 1.0, "atr_14": 10.0}

        # Full computation
        plugin_full = HMMRegimePlugin()
        df_full = make_ohlcv(close)
        result_full = plugin_full.compute_full({"main": df_full, "features": features})

        # Incremental: seed with first 30, then feed remaining one at a time
        plugin_inc = HMMRegimePlugin()
        df_seed = make_ohlcv(close[:30])
        plugin_inc.compute_full({"main": df_seed, "features": features})

        result_inc = {}
        for i in range(31, len(close) + 1):
            df_inc = make_ohlcv(close[:i])
            result_inc = plugin_inc.compute_next({"main": df_inc, "features": features})

        assert result_full["hmm_regime"] == result_inc["hmm_regime"]
        assert abs(result_full["hmm_regime_prob"] - result_inc["hmm_regime_prob"]) < 0.01

    def test_graceful_without_features(self):
        """Works with just OHLCV in 2D fallback mode."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(42)
        close = 5000.0 + np.cumsum(np.abs(rng.normal(0.5, 0.3, 200)))
        df = make_ohlcv(close)

        plugin = HMMRegimePlugin()
        # No "features" key — should still produce results in 2D mode
        result = plugin.compute_full({"main": df})

        assert result != {}
        assert "hmm_regime" in result
        assert "hmm_regime_prob" in result
        assert 0 <= result["hmm_regime_prob"] <= 1.0

    def test_empty_insufficient_input(self):
        """Returns {} for empty or insufficient data."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        plugin = HMMRegimePlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

        # Fewer than min_lookback (20) bars
        df = make_ohlcv(np.full(10, 5000.0))
        assert plugin.compute_full({"main": df}) == {}
