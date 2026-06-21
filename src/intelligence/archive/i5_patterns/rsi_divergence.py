from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import find_peaks, find_troughs


@dataclass
class RSIDivergencePlugin:
    name: str = "RSIDivergence"
    outputs: frozenset[str] = frozenset({"rsi_div_bullish", "rsi_div_bearish", "rsi_div_strength"})
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern", "momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    rsi_period: int = 14
    neighbor: int = 5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        close = df["close"].to_numpy(dtype=float)
        rsi = self._rsi_series(close, self.rsi_period)

        # Find swings in PRICE only, then check RSI at those same bar indices
        price_peaks = find_peaks(close, self.neighbor)
        price_troughs = find_troughs(close, self.neighbor)

        bullish = 0.0
        bearish = 0.0
        strength = 0.0

        # Bullish divergence: price lower low + RSI higher low at SAME bars
        if len(price_troughs) >= 2:
            i_prev, i_curr = price_troughs[-2], price_troughs[-1]
            if (
                i_prev >= self.rsi_period
                and close[i_curr] < close[i_prev]
                and rsi[i_curr] > rsi[i_prev]
            ):
                price_drop = (close[i_prev] - close[i_curr]) / close[i_prev]
                rsi_rise = (rsi[i_curr] - rsi[i_prev]) / 100.0
                bullish = min(1.0, 0.3 + price_drop * 5.0 + rsi_rise * 3.0)
                strength = max(strength, bullish)

        # Bearish divergence: price higher high + RSI lower high at SAME bars
        if len(price_peaks) >= 2:
            i_prev, i_curr = price_peaks[-2], price_peaks[-1]
            if (
                i_prev >= self.rsi_period
                and close[i_curr] > close[i_prev]
                and rsi[i_curr] < rsi[i_prev]
            ):
                price_rise = (close[i_curr] - close[i_prev]) / close[i_prev]
                rsi_drop = (rsi[i_prev] - rsi[i_curr]) / 100.0
                bearish = min(1.0, 0.3 + price_rise * 5.0 + rsi_drop * 3.0)
                strength = max(strength, bearish)

        return {
            "rsi_div_bullish": round(bullish, 4),
            "rsi_div_bearish": round(bearish, 4),
            "rsi_div_strength": round(strength, 4),
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _rsi_series(close: np.ndarray, period: int) -> np.ndarray:
        """Compute RSI series using Wilder's smoothing."""
        deltas = np.diff(close)
        rsi = np.full_like(close, 50.0)
        if len(deltas) < period:
            return rsi
        seed = deltas[:period]
        avg_gain = float(seed.clip(min=0).sum() / period)
        avg_loss = float(-seed.clip(max=0).sum() / period)
        if avg_loss != 0:
            rsi[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        else:
            rsi[period] = 100.0
        for i in range(period + 1, len(close)):
            d = deltas[i - 1]
            avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period
            if avg_loss != 0:
                rsi[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
            else:
                rsi[i] = 100.0
        return rsi


plugin = RSIDivergencePlugin()
