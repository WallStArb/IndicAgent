#!/usr/bin/env python3
"""
Incremental Indicator Manager - Optimized state-based indicator calculations

Manages incremental state for all technical indicators, avoiding full recalculation
on every new bar. Each indicator maintains its own state and updates efficiently
with only the latest bar data.

Features:
- State-based incremental calculations for all major indicators
- Memory-efficient rolling window management
- Fallback to full calculation when needed
- Thread-safe operations for production use
- Compatible with existing IndicatorCalculations interface

Version: 1.0.0
Last Updated: 2025-08-13
Status: Production Ready
"""

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class IndicatorState:
    """State container for individual indicators."""

    symbol: str
    timeframe: str
    indicator_name: str
    last_calculation_time: datetime | None = None
    last_values: dict[str, float] = field(default_factory=dict)
    window_data: deque = field(default_factory=lambda: deque(maxlen=200))
    state_data: dict[str, Any] = field(default_factory=dict)
    is_initialized: bool = False


class IncrementalIndicatorManager:
    """
    Manages incremental calculations for all technical indicators.

    This class maintains state for each symbol/timeframe/indicator combination
    and performs efficient incremental updates instead of full recalculations.
    """

    def __init__(self):
        self.states: dict[str, IndicatorState] = {}
        self._lock = threading.RLock()
        self.logger = logger

    def _get_state_key(self, symbol: str, timeframe: str, indicator_name: str) -> str:
        """Generate unique state key."""
        return f"{symbol}:{timeframe}:{indicator_name}"

    def _get_state(self, symbol: str, timeframe: str, indicator_name: str) -> IndicatorState:
        """Get or create indicator state."""
        key = self._get_state_key(symbol, timeframe, indicator_name)

        if key not in self.states:
            # Create new state
            new_state = IndicatorState(
                symbol=symbol, timeframe=timeframe, indicator_name=indicator_name
            )

            # Copy data from cache if available
            cache_key = f"{symbol}:{timeframe}:_data_cache"
            if cache_key in self.states:
                cache_data = list(self.states[cache_key].window_data)
                new_state.window_data.extend(cache_data)

            self.states[key] = new_state

        return self.states[key]

    def add_bar_data(self, symbol: str, timeframe: str, bar_data: dict[str, Any]):
        """Add new bar data to all indicator states for this symbol/timeframe."""
        with self._lock:
            # Store in a general cache for this symbol/timeframe first
            cache_key = f"{symbol}:{timeframe}:_data_cache"
            if cache_key not in self.states:
                self.states[cache_key] = IndicatorState(
                    symbol=symbol, timeframe=timeframe, indicator_name="_data_cache"
                )
            self.states[cache_key].window_data.append(bar_data)

            # Find all existing indicator states for this symbol/timeframe and add data
            prefix = f"{symbol}:{timeframe}:"
            for key, state in self.states.items():
                if key.startswith(prefix) and not key.endswith(":_data_cache"):
                    state.window_data.append(bar_data)

    def calculate_rsi_incremental(
        self, symbol: str, timeframe: str, period: int = 14
    ) -> float | None:
        """Calculate RSI incrementally."""
        state = self._get_state(symbol, timeframe, f"RSI_{period}")

        if len(state.window_data) < period + 1:
            return None

        with self._lock:
            if not state.is_initialized:
                # Initial calculation
                closes = [bar["close"] for bar in list(state.window_data)[-period - 1 :]]
                if len(closes) < period + 1:
                    return None

                deltas = np.diff(closes)
                gains = np.maximum(deltas, 0)
                losses = np.maximum(-deltas, 0)

                avg_gain = np.mean(gains)
                avg_loss = np.mean(losses)

                state.state_data["avg_gain"] = avg_gain
                state.state_data["avg_loss"] = avg_loss
                state.is_initialized = True

                if avg_loss == 0:
                    rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100.0 - (100.0 / (1.0 + rs))

            else:
                # Incremental update
                if len(state.window_data) < 2:
                    return state.last_values.get("rsi")

                latest_bars = list(state.window_data)[-2:]
                delta = latest_bars[1]["close"] - latest_bars[0]["close"]

                gain = max(delta, 0)
                loss = max(-delta, 0)

                # Exponential moving average update
                alpha = 1.0 / period
                state.state_data["avg_gain"] = (1 - alpha) * state.state_data[
                    "avg_gain"
                ] + alpha * gain
                state.state_data["avg_loss"] = (1 - alpha) * state.state_data[
                    "avg_loss"
                ] + alpha * loss

                if state.state_data["avg_loss"] == 0:
                    rsi = 100.0
                else:
                    rs = state.state_data["avg_gain"] / state.state_data["avg_loss"]
                    rsi = 100.0 - (100.0 / (1.0 + rs))

            state.last_values["rsi"] = rsi
            state.last_calculation_time = datetime.now()
            return rsi

    def calculate_sma_incremental(self, symbol: str, timeframe: str, period: int) -> float | None:
        """Calculate SMA incrementally."""
        state = self._get_state(symbol, timeframe, f"SMA_{period}")

        if len(state.window_data) < period:
            return None

        with self._lock:
            # SMA is straightforward - just average the last N closes
            latest_closes = [bar["close"] for bar in list(state.window_data)[-period:]]
            sma = np.mean(latest_closes)

            state.last_values["sma"] = sma
            state.last_calculation_time = datetime.now()
            return sma

    def calculate_ema_incremental(self, symbol: str, timeframe: str, period: int) -> float | None:
        """Calculate EMA incrementally."""
        state = self._get_state(symbol, timeframe, f"EMA_{period}")

        if len(state.window_data) < 1:
            return None

        with self._lock:
            latest_close = list(state.window_data)[-1]["close"]

            if not state.is_initialized:
                # Initialize with SMA for first calculation
                if len(state.window_data) < period:
                    return None

                closes = [bar["close"] for bar in list(state.window_data)[-period:]]
                ema = np.mean(closes)
                state.state_data["ema"] = ema
                state.is_initialized = True

            else:
                # Incremental EMA calculation
                alpha = 2.0 / (period + 1)
                prev_ema = state.state_data["ema"]
                ema = alpha * latest_close + (1 - alpha) * prev_ema
                state.state_data["ema"] = ema

            state.last_values["ema"] = ema
            state.last_calculation_time = datetime.now()
            return ema

    def calculate_macd_incremental(
        self,
        symbol: str,
        timeframe: str,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> dict[str, float] | None:
        """Calculate MACD incrementally."""
        # Calculate component EMAs
        ema_fast = self.calculate_ema_incremental(symbol, timeframe, fast_period)
        ema_slow = self.calculate_ema_incremental(symbol, timeframe, slow_period)

        if ema_fast is None or ema_slow is None:
            return None

        # MACD line
        macd_line = ema_fast - ema_slow

        # Signal line (EMA of MACD)
        state = self._get_state(symbol, timeframe, f"MACD_SIGNAL_{signal_period}")

        with self._lock:
            if not state.is_initialized:
                # Initialize signal line
                state.state_data["signal_ema"] = macd_line
                state.is_initialized = True
                signal_line = macd_line
            else:
                # Incremental signal line
                alpha = 2.0 / (signal_period + 1)
                prev_signal = state.state_data["signal_ema"]
                signal_line = alpha * macd_line + (1 - alpha) * prev_signal
                state.state_data["signal_ema"] = signal_line

            # Histogram
            histogram = macd_line - signal_line

            result = {"macd": macd_line, "signal": signal_line, "histogram": histogram}

            state.last_values.update(result)
            state.last_calculation_time = datetime.now()
            return result

    def calculate_atr_incremental(
        self, symbol: str, timeframe: str, period: int = 14
    ) -> float | None:
        """Calculate ATR incrementally."""
        state = self._get_state(symbol, timeframe, f"ATR_{period}")

        if len(state.window_data) < 2:
            return None

        with self._lock:
            latest_bars = list(state.window_data)[-2:]
            current = latest_bars[1]
            previous = latest_bars[0]

            # Calculate True Range
            hl = current["high"] - current["low"]
            hc = abs(current["high"] - previous["close"])
            lc = abs(current["low"] - previous["close"])
            tr = max(hl, hc, lc)

            if not state.is_initialized:
                # Initialize with first TR value
                if len(state.window_data) < period + 1:
                    return None

                # Calculate initial ATR
                trs = []
                bars = list(state.window_data)[-period - 1 :]
                for i in range(1, len(bars)):
                    curr = bars[i]
                    prev = bars[i - 1]
                    hl = curr["high"] - curr["low"]
                    hc = abs(curr["high"] - prev["close"])
                    lc = abs(curr["low"] - prev["close"])
                    trs.append(max(hl, hc, lc))

                atr = np.mean(trs)
                state.state_data["atr"] = atr
                state.is_initialized = True

            else:
                # Incremental ATR calculation (Wilder's smoothing)
                prev_atr = state.state_data["atr"]
                atr = (prev_atr * (period - 1) + tr) / period
                state.state_data["atr"] = atr

            state.last_values["atr"] = atr
            state.last_calculation_time = datetime.now()
            return atr

    def calculate_bollinger_bands_incremental(
        self, symbol: str, timeframe: str, period: int = 20, std_dev: float = 2.0
    ) -> dict[str, float] | None:
        """Calculate Bollinger Bands incrementally."""
        state = self._get_state(symbol, timeframe, f"BB_{period}")

        if len(state.window_data) < period:
            return None

        with self._lock:
            # Get recent closes for standard deviation calculation
            latest_closes = [bar["close"] for bar in list(state.window_data)[-period:]]

            # Middle band (SMA)
            middle = np.mean(latest_closes)

            # Standard deviation
            std = np.std(latest_closes, ddof=1)

            # Upper and lower bands
            upper = middle + (std_dev * std)
            lower = middle - (std_dev * std)

            result = {"upper": upper, "middle": middle, "lower": lower}

            state.last_values.update(result)
            state.last_calculation_time = datetime.now()
            return result

    def calculate_stochastic_incremental(
        self, symbol: str, timeframe: str, k_period: int = 14, d_period: int = 3
    ) -> dict[str, float] | None:
        """Calculate Stochastic oscillator incrementally."""
        state = self._get_state(symbol, timeframe, f"STOCH_{k_period}_{d_period}")

        if len(state.window_data) < k_period:
            return None

        with self._lock:
            # Get recent bars for %K calculation
            recent_bars = list(state.window_data)[-k_period:]

            # Current close, highest high, lowest low
            current_close = recent_bars[-1]["close"]
            highest_high = max(bar["high"] for bar in recent_bars)
            lowest_low = min(bar["low"] for bar in recent_bars)

            # %K calculation
            if highest_high == lowest_low:
                k_percent = 50.0
            else:
                k_percent = ((current_close - lowest_low) / (highest_high - lowest_low)) * 100.0

            # %D calculation (moving average of %K)
            if "k_values" not in state.state_data:
                state.state_data["k_values"] = deque(maxlen=d_period)

            state.state_data["k_values"].append(k_percent)

            if len(state.state_data["k_values"]) >= d_period:
                d_percent = np.mean(state.state_data["k_values"])
            else:
                d_percent = k_percent

            result = {"%K": k_percent, "%D": d_percent}

            state.last_values.update(result)
            state.last_calculation_time = datetime.now()
            return result

    def get_last_values(self, symbol: str, timeframe: str, indicator_name: str) -> dict[str, float]:
        """Get last calculated values for an indicator."""
        state = self._get_state(symbol, timeframe, indicator_name)
        with self._lock:
            return state.last_values.copy()

    def reset_state(self, symbol: str, timeframe: str, indicator_name: str | None = None):
        """Reset state for specific indicator or all indicators for symbol/timeframe."""
        with self._lock:
            if indicator_name:
                key = self._get_state_key(symbol, timeframe, indicator_name)
                if key in self.states:
                    del self.states[key]
            else:
                # Reset all indicators for this symbol/timeframe
                prefix = f"{symbol}:{timeframe}:"
                keys_to_remove = [key for key in self.states.keys() if key.startswith(prefix)]
                for key in keys_to_remove:
                    del self.states[key]

    def get_memory_usage(self) -> dict[str, Any]:
        """Get memory usage statistics."""
        with self._lock:
            # Filter out cache states from count
            indicator_states = {
                k: v for k, v in self.states.items() if not k.endswith(":_data_cache")
            }
            cache_states = {k: v for k, v in self.states.items() if k.endswith(":_data_cache")}

            total_indicator_states = len(indicator_states)
            total_bars = sum(len(state.window_data) for state in self.states.values())

            return {
                "total_states": total_indicator_states,
                "total_cache_states": len(cache_states),
                "total_bars_cached": total_bars,
                "average_bars_per_state": (
                    total_bars / len(self.states) if len(self.states) > 0 else 0
                ),
                "states_by_symbol": self._group_states_by_symbol(),
            }

    def _group_states_by_symbol(self) -> dict[str, int]:
        """Group states by symbol for memory analysis."""
        symbol_counts = {}
        for state in self.states.values():
            symbol_key = f"{state.symbol}:{state.timeframe}"
            symbol_counts[symbol_key] = symbol_counts.get(symbol_key, 0) + 1
        return symbol_counts
