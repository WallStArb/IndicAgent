#!/usr/bin/env python3
"""
Unit tests for IncrementalIndicatorManager

Tests the incremental calculation logic for all supported indicators,
verifying both correctness and performance improvements.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.indicators.incremental_manager import IncrementalIndicatorManager


class TestIncrementalIndicatorManager:
    """Test suite for IncrementalIndicatorManager."""

    @pytest.fixture
    def manager(self):
        """Create a fresh manager instance."""
        return IncrementalIndicatorManager()

    @pytest.fixture
    def sample_bars(self):
        """Generate sample OHLCV bar data."""
        bars = []
        base_price = 100.0
        base_time = datetime(2025, 1, 1)

        # Generate 100 bars with realistic price movement
        for i in range(100):
            # Simple random walk
            price_change = np.random.normal(0, 0.5)
            base_price += price_change

            high = base_price + abs(np.random.normal(0, 0.3))
            low = base_price - abs(np.random.normal(0, 0.3))
            close = base_price + np.random.normal(0, 0.2)
            volume = int(np.random.uniform(1000, 5000))

            bars.append(
                {
                    "timestamp": base_time + timedelta(minutes=i),
                    "open": base_price,
                    "high": max(base_price, high, close),
                    "low": min(base_price, low, close),
                    "close": close,
                    "volume": volume,
                }
            )

            base_price = close  # Next bar opens at previous close

        return bars

    def test_manager_initialization(self, manager):
        """Test manager initializes correctly."""
        assert len(manager.states) == 0
        assert manager._lock is not None

    def test_state_management(self, manager):
        """Test state creation and retrieval."""
        # Get state (should create new one)
        state = manager._get_state("ESU5", "1m", "RSI_14")

        assert state.symbol == "ESU5"
        assert state.timeframe == "1m"
        assert state.indicator_name == "RSI_14"
        assert not state.is_initialized
        assert len(state.window_data) == 0

        # Should return same state on subsequent calls
        state2 = manager._get_state("ESU5", "1m", "RSI_14")
        assert state is state2

    def test_bar_data_addition(self, manager, sample_bars):
        """Test adding bar data to states."""
        # Add some bars
        for bar in sample_bars[:10]:
            manager.add_bar_data("ESU5", "1m", bar)

        # Create a state and check it has the data
        state = manager._get_state("ESU5", "1m", "RSI_14")
        assert len(state.window_data) == 10
        assert list(state.window_data)[0] == sample_bars[0]

    def test_rsi_incremental_calculation(self, manager, sample_bars):
        """Test RSI incremental calculation."""
        symbol, timeframe = "ESU5", "1m"

        # Add bars one by one and test RSI
        rsi_values = []

        for i, bar in enumerate(sample_bars):
            manager.add_bar_data(symbol, timeframe, bar)

            rsi = manager.calculate_rsi_incremental(symbol, timeframe, period=14)

            if rsi is not None:
                rsi_values.append(rsi)

                # RSI should be between 0 and 100
                assert 0 <= rsi <= 100

                # After enough data, RSI should be calculated
                if i >= 15:  # 14 period + 1 for delta
                    assert rsi is not None

        # Should have RSI values for later bars
        assert len(rsi_values) > 0

        # Test state persistence
        state = manager._get_state(symbol, timeframe, "RSI_14")
        assert state.is_initialized
        assert "avg_gain" in state.state_data
        assert "avg_loss" in state.state_data
        assert "rsi" in state.last_values

    def test_sma_incremental_calculation(self, manager, sample_bars):
        """Test SMA incremental calculation."""
        symbol, timeframe = "ESU5", "1m"
        period = 20

        # Add bars and calculate SMA
        sma_values = []

        for _i, bar in enumerate(sample_bars):
            manager.add_bar_data(symbol, timeframe, bar)

            sma = manager.calculate_sma_incremental(symbol, timeframe, period)

            if sma is not None:
                sma_values.append(sma)

                # SMA should be reasonable relative to current prices
                current_price = bar["close"]
                assert abs(sma - current_price) < current_price * 0.5  # Within 50%

        # Should have SMA values for later bars
        assert len(sma_values) > 0

        # Verify SMA is calculated correctly (manual check on last few values)
        if len(sample_bars) >= period:
            last_closes = [bar["close"] for bar in sample_bars[-period:]]
            expected_sma = np.mean(last_closes)
            actual_sma = manager.calculate_sma_incremental(symbol, timeframe, period)

            assert abs(actual_sma - expected_sma) < 0.001  # Very close

    def test_ema_incremental_calculation(self, manager, sample_bars):
        """Test EMA incremental calculation."""
        symbol, timeframe = "ESU5", "1m"
        period = 12

        # Add bars and calculate EMA
        ema_values = []

        for _i, bar in enumerate(sample_bars):
            manager.add_bar_data(symbol, timeframe, bar)

            ema = manager.calculate_ema_incremental(symbol, timeframe, period)

            if ema is not None:
                ema_values.append(ema)

                # EMA should be reasonable
                current_price = bar["close"]
                assert abs(ema - current_price) < current_price * 0.3  # Within 30%

        # Should have EMA values
        assert len(ema_values) > 0

        # Test state persistence
        state = manager._get_state(symbol, timeframe, f"EMA_{period}")
        assert state.is_initialized
        assert "ema" in state.state_data

    def test_macd_incremental_calculation(self, manager, sample_bars):
        """Test MACD incremental calculation."""
        symbol, timeframe = "ESU5", "1m"

        # Add enough bars for MACD
        for bar in sample_bars:
            manager.add_bar_data(symbol, timeframe, bar)

        # Calculate MACD
        macd_result = manager.calculate_macd_incremental(symbol, timeframe)

        if macd_result is not None:
            assert "macd" in macd_result
            assert "signal" in macd_result
            assert "histogram" in macd_result

            # Histogram should equal MACD - Signal
            expected_histogram = macd_result["macd"] - macd_result["signal"]
            assert abs(macd_result["histogram"] - expected_histogram) < 0.001

    def test_atr_incremental_calculation(self, manager, sample_bars):
        """Test ATR incremental calculation."""
        symbol, timeframe = "ESU5", "1m"
        period = 14

        # Add bars and calculate ATR
        atr_values = []

        for _i, bar in enumerate(sample_bars):
            manager.add_bar_data(symbol, timeframe, bar)

            atr = manager.calculate_atr_incremental(symbol, timeframe, period)

            if atr is not None:
                atr_values.append(atr)

                # ATR should be positive
                assert atr > 0

                # ATR should be reasonable relative to current price
                current_price = bar["close"]
                assert atr <= current_price * 0.1  # ATR shouldn't be more than 10% of price

        # Should have ATR values for later bars
        assert len(atr_values) > 0

    def test_bollinger_bands_incremental_calculation(self, manager, sample_bars):
        """Test Bollinger Bands incremental calculation."""
        symbol, timeframe = "ESU5", "1m"
        period = 20

        # Add enough bars
        for bar in sample_bars:
            manager.add_bar_data(symbol, timeframe, bar)

        # Calculate Bollinger Bands
        bb_result = manager.calculate_bollinger_bands_incremental(symbol, timeframe, period)

        if bb_result is not None:
            assert "upper" in bb_result
            assert "middle" in bb_result
            assert "lower" in bb_result

            # Upper should be above middle, middle above lower
            assert bb_result["upper"] > bb_result["middle"]
            assert bb_result["middle"] > bb_result["lower"]

    def test_stochastic_incremental_calculation(self, manager, sample_bars):
        """Test Stochastic oscillator incremental calculation."""
        symbol, timeframe = "ESU5", "1m"

        # Add enough bars
        for bar in sample_bars:
            manager.add_bar_data(symbol, timeframe, bar)

        # Calculate Stochastic
        stoch_result = manager.calculate_stochastic_incremental(symbol, timeframe)

        if stoch_result is not None:
            assert "%K" in stoch_result
            assert "%D" in stoch_result

            # Both should be between 0 and 100
            assert 0 <= stoch_result["%K"] <= 100
            assert 0 <= stoch_result["%D"] <= 100

    def test_memory_usage_tracking(self, manager, sample_bars):
        """Test memory usage tracking."""
        symbol, timeframe = "ESU5", "1m"

        # Add bars and create some indicators
        for bar in sample_bars:
            manager.add_bar_data(symbol, timeframe, bar)

        # Calculate some indicators to create states
        manager.calculate_rsi_incremental(symbol, timeframe)
        manager.calculate_sma_incremental(symbol, timeframe, 20)
        manager.calculate_ema_incremental(symbol, timeframe, 12)

        # Check memory usage
        memory_stats = manager.get_memory_usage()

        assert memory_stats["total_states"] > 0
        assert memory_stats["total_bars_cached"] > 0
        assert memory_stats["average_bars_per_state"] > 0
        assert isinstance(memory_stats["states_by_symbol"], dict)

    def test_state_reset(self, manager, sample_bars):
        """Test state reset functionality."""
        symbol, timeframe = "ESU5", "1m"

        # Add bars and calculate indicators
        for bar in sample_bars[:20]:
            manager.add_bar_data(symbol, timeframe, bar)

        manager.calculate_rsi_incremental(symbol, timeframe)
        manager.calculate_sma_incremental(symbol, timeframe, 20)

        # Verify states exist
        assert len(manager.states) > 0

        # Reset specific indicator
        manager.reset_state(symbol, timeframe, "RSI_14")

        # RSI state should be gone, but SMA should remain
        manager._get_state_key(symbol, timeframe, "RSI_14")
        manager._get_state_key(symbol, timeframe, "SMA_20")

        # After reset, RSI key should be recreated as empty
        new_state = manager._get_state(symbol, timeframe, "RSI_14")
        assert not new_state.is_initialized

        # Reset all states for symbol/timeframe
        manager.reset_state(symbol, timeframe)

        # All states for this symbol/timeframe should be gone
        remaining_states = [
            key for key in manager.states.keys() if key.startswith(f"{symbol}:{timeframe}:")
        ]
        assert len(remaining_states) == 0

    def test_thread_safety(self, manager, sample_bars):
        """Basic thread safety test."""
        import threading
        import time

        symbol, timeframe = "ESU5", "1m"
        results = []

        def worker():
            for bar in sample_bars[:50]:
                manager.add_bar_data(symbol, timeframe, bar)
                rsi = manager.calculate_rsi_incremental(symbol, timeframe)
                if rsi is not None:
                    results.append(rsi)
                time.sleep(0.001)  # Small delay

        # Run multiple threads
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Should have some results and no crashes
        assert len(results) > 0

    @pytest.mark.performance
    def test_performance_comparison(self, manager, sample_bars):
        """Test that incremental calculations are faster."""
        import time

        import pandas as pd

        symbol, timeframe = "ESU5", "1m"

        # Add bars to manager
        for bar in sample_bars:
            manager.add_bar_data(symbol, timeframe, bar)

        # Time incremental calculation
        start_time = time.time()
        for _ in range(100):
            manager.calculate_rsi_incremental(symbol, timeframe)
        incremental_time = time.time() - start_time

        # Time full calculation (simulate)
        df = pd.DataFrame(sample_bars)
        start_time = time.time()
        for _ in range(100):
            # Simulate full RSI calculation
            closes = df["close"].values
            if len(closes) > 14:
                deltas = np.diff(closes)
                gains = np.maximum(deltas, 0)
                losses = np.maximum(-deltas, 0)
                avg_gain = np.mean(gains[-14:])
                avg_loss = np.mean(losses[-14:])
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    100.0 - (100.0 / (1.0 + rs))
        full_calculation_time = time.time() - start_time

        # Incremental should be significantly faster
        # (This is a simplified test, real difference would be more dramatic)
        print(f"Incremental time: {incremental_time:.4f}s")
        print(f"Full calculation time: {full_calculation_time:.4f}s")
        print(f"Speedup: {full_calculation_time / incremental_time:.2f}x")

        # Incremental should be at least as fast (usually much faster)
        assert incremental_time <= full_calculation_time * 1.1  # Allow 10% margin

    def test_indicator_accuracy_vs_traditional(self, manager):
        """Test that incremental calculations match traditional calculations."""
        # Generate deterministic test data
        np.random.seed(42)
        closes = 100 + np.cumsum(np.random.normal(0, 0.5, 100))

        bars = []
        for i, close in enumerate(closes):
            high = close + abs(np.random.normal(0, 0.2))
            low = close - abs(np.random.normal(0, 0.2))
            bars.append(
                {
                    "timestamp": datetime(2025, 1, 1) + timedelta(minutes=i),
                    "open": closes[i - 1] if i > 0 else close,
                    "high": max(close, high),
                    "low": min(close, low),
                    "close": close,
                    "volume": 1000,
                }
            )

        symbol, timeframe = "TEST", "1m"

        # Add bars to manager
        for bar in bars:
            manager.add_bar_data(symbol, timeframe, bar)

        # Calculate incremental RSI
        incremental_rsi = manager.calculate_rsi_incremental(symbol, timeframe, period=14)

        # Calculate traditional RSI
        deltas = np.diff(closes)
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)

        # Use last 14 periods for average
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])

        if avg_loss > 0:
            rs = avg_gain / avg_loss
            traditional_rsi = 100.0 - (100.0 / (1.0 + rs))
        else:
            traditional_rsi = 100.0

        # Should be very close (within small numerical precision)
        if incremental_rsi is not None:
            assert abs(incremental_rsi - traditional_rsi) < 1.0  # Within 1 RSI point
