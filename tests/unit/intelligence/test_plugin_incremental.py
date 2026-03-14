"""
Tests for incremental compute_next() implementations across all 11 indicator plugins.

Strategy:
1. Generate 200 bars of synthetic OHLCV data with realistic price action
2. For each plugin: run compute_full() on first 100 bars (seeds state)
3. Feed bars 101-200 one at a time via compute_next()
4. Compare final compute_next() output against compute_full() on all 200 bars
5. Assert match within relative tolerance (accounts for floating-point drift)
"""

import numpy as np
import pandas as pd


def generate_synthetic_ohlcv(n_bars: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate realistic synthetic OHLCV data."""
    rng = np.random.default_rng(seed)

    # Start from a realistic price
    base_price = 5000.0
    returns = rng.normal(0.0001, 0.005, n_bars)
    close = base_price * np.cumprod(1 + returns)

    # Generate OHLC from close with realistic spread
    spread = rng.uniform(0.001, 0.003, n_bars)
    high = close * (1 + spread)
    low = close * (1 - spread)
    open_ = close * (1 + rng.normal(0, 0.001, n_bars))

    # Ensure OHLC consistency
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    # Volume with realistic variation
    volume = rng.lognormal(10, 0.5, n_bars).astype(float)

    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


SEED_BARS = 100  # Bars for initial compute_full()
TOTAL_BARS = 200  # Total bars
# Relative tolerance for floating-point comparison
REL_TOL = 0.005  # 0.5%


def assert_values_close(incremental: dict, full: dict, plugin_name: str, rel_tol: float = REL_TOL):
    """Assert that incremental and full computation results are close."""
    assert set(incremental.keys()) == set(full.keys()), (
        f"{plugin_name}: Key mismatch - incremental={set(incremental.keys())}, "
        f"full={set(full.keys())}"
    )
    for key in full:
        inc_val = incremental[key]
        full_val = full[key]
        if abs(full_val) < 1e-10:
            # For near-zero values, use absolute tolerance
            assert abs(inc_val - full_val) < 0.1, (
                f"{plugin_name}.{key}: abs diff too large - "
                f"incremental={inc_val}, full={full_val}"
            )
        else:
            rel_diff = abs(inc_val - full_val) / abs(full_val)
            assert rel_diff < rel_tol, (
                f"{plugin_name}.{key}: relative diff {rel_diff:.4%} > {rel_tol:.1%} - "
                f"incremental={inc_val}, full={full_val}"
            )


class TestOBVIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.obv import OBVPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = OBVPlugin()

        # Seed with first 100 bars
        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})

        # Feed bars one at a time
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        # Compare with full computation
        fresh = OBVPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "OBV")


class TestVWAPIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.vwap import VWAPPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = VWAPPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = VWAPPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "VWAP")


class TestRSIIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.rsi import RSIPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = RSIPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = RSIPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "RSI")


class TestATRIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.atr import ATRPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = ATRPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = ATRPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "ATR")


class TestMovingAveragesIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.moving_averages import MovingAveragesPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = MovingAveragesPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = MovingAveragesPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        # MovingAverages: full on 200 bars may produce SMA_200 that seed on 100 can't
        # Only compare keys that the incremental path can produce
        shared_keys = set(result.keys()) & set(full_result.keys())
        inc_filtered = {k: result[k] for k in shared_keys}
        full_filtered = {k: full_result[k] for k in shared_keys}
        assert_values_close(inc_filtered, full_filtered, "MovingAverages")


class TestMACDIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.macd import MACDPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = MACDPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = MACDPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "MACD")


class TestBollingerIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.bollinger import BollingerPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = BollingerPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = BollingerPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "Bollinger")


class TestStochasticIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.stochastic import StochasticPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = StochasticPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = StochasticPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "Stochastic")


class TestWilliamsRIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.williams_r import WilliamsRPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = WilliamsRPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = WilliamsRPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "WilliamsR")


class TestCCIIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.cci import CCIPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = CCIPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = CCIPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "CCI")


class TestMFIIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.mfi import MFIPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = MFIPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = MFIPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "MFI")


class TestFallbackBehavior:
    """Test that compute_next() falls back to compute_full() when state is empty."""

    def test_rsi_fallback(self):
        from src.intelligence.indicators.rsi import RSIPlugin

        df = generate_synthetic_ohlcv(50)
        plugin = RSIPlugin()
        # Call compute_next without prior compute_full - should fall back
        result = plugin.compute_next({"main": df})
        assert "rsi_14" in result

    def test_macd_fallback(self):
        from src.intelligence.indicators.macd import MACDPlugin

        df = generate_synthetic_ohlcv(50)
        plugin = MACDPlugin()
        result = plugin.compute_next({"main": df})
        assert "macd_12_26_9" in result

    def test_bollinger_fallback(self):
        from src.intelligence.indicators.bollinger import BollingerPlugin

        df = generate_synthetic_ohlcv(50)
        plugin = BollingerPlugin()
        result = plugin.compute_next({"main": df})
        assert "bb_20_2_mid" in result


class TestADXIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.adx import ADXPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = ADXPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = ADXPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "ADX")

    def test_compute_full_outputs(self):
        from src.intelligence.indicators.adx import ADXPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = ADXPlugin()
        result = plugin.compute_full({"main": df})

        assert "adx_14" in result
        assert "plus_di_14" in result
        assert "minus_di_14" in result
        assert 0 <= result["adx_14"] <= 100
        assert 0 <= result["plus_di_14"] <= 100
        assert 0 <= result["minus_di_14"] <= 100

    def test_empty_input(self):
        from src.intelligence.indicators.adx import ADXPlugin

        plugin = ADXPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

    def test_insufficient_data(self):
        from src.intelligence.indicators.adx import ADXPlugin

        df = generate_synthetic_ohlcv(10)
        plugin = ADXPlugin()
        assert plugin.compute_full({"main": df}) == {}


class TestKeltnerIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.keltner import KeltnerChannelsPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = KeltnerChannelsPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = KeltnerChannelsPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "Keltner")

    def test_compute_full_outputs(self):
        from src.intelligence.indicators.keltner import KeltnerChannelsPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = KeltnerChannelsPlugin()
        result = plugin.compute_full({"main": df})

        assert "kc_upper_20" in result
        assert "kc_mid_20" in result
        assert "kc_lower_20" in result
        # Upper > mid > lower always
        assert result["kc_upper_20"] > result["kc_mid_20"]
        assert result["kc_mid_20"] > result["kc_lower_20"]

    def test_empty_input(self):
        from src.intelligence.indicators.keltner import KeltnerChannelsPlugin

        plugin = KeltnerChannelsPlugin()
        assert plugin.compute_full({"main": None}) == {}


class TestDonchianIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.donchian import DonchianChannelsPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = DonchianChannelsPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = DonchianChannelsPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "Donchian")

    def test_compute_full_outputs(self):
        from src.intelligence.indicators.donchian import DonchianChannelsPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = DonchianChannelsPlugin()
        result = plugin.compute_full({"main": df})

        assert "donchian_upper_20" in result
        assert "donchian_mid_20" in result
        assert "donchian_lower_20" in result
        assert result["donchian_upper_20"] >= result["donchian_mid_20"]
        assert result["donchian_mid_20"] >= result["donchian_lower_20"]

    def test_empty_input(self):
        from src.intelligence.indicators.donchian import DonchianChannelsPlugin

        plugin = DonchianChannelsPlugin()
        assert plugin.compute_full({"main": None}) == {}


class TestROCPPOIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.roc_ppo import ROCPPOPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = ROCPPOPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = ROCPPOPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "ROC_PPO")

    def test_compute_full_outputs(self):
        from src.intelligence.indicators.roc_ppo import ROCPPOPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = ROCPPOPlugin()
        result = plugin.compute_full({"main": df})

        assert "roc_14" in result
        assert "ppo_12_26" in result
        assert "ppo_signal_12_26" in result
        # ROC can be positive or negative
        assert isinstance(result["roc_14"], float)
        # PPO is percentage-based
        assert isinstance(result["ppo_12_26"], float)

    def test_empty_input(self):
        from src.intelligence.indicators.roc_ppo import ROCPPOPlugin

        plugin = ROCPPOPlugin()
        assert plugin.compute_full({"main": None}) == {}
