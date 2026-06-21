from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import find_peaks, find_troughs


@dataclass
class MACDDivergencePlugin:
    """I5 pattern plugin: detects divergence using MACD histogram series.

    Bullish divergence: price makes lower trough but MACD histogram makes higher trough.
    Bearish divergence: price makes higher peak but MACD histogram makes lower peak.
    Uses find_peaks/find_troughs on price for swing detection, then checks histogram at same bars.
    """

    name: str = "patt_MACDDivergence"
    outputs: frozenset[str] = frozenset(
        {"macd_div_bullish", "macd_div_bearish", "macd_div_strength"}
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern", "momentum"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    neighbor: int = 5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        hist = self._macd_histogram_series(close)

        # Find swings in PRICE, check histogram values at those same bar indices
        price_peaks = find_peaks(close, self.neighbor)
        price_troughs = find_troughs(close, self.neighbor)

        bullish = 0.0
        bearish = 0.0
        strength = 0.0

        # Bullish divergence: price lower low + histogram higher low at same bars
        if len(price_troughs) >= 2:
            i_prev, i_curr = price_troughs[-2], price_troughs[-1]
            if (
                i_prev >= 26  # need enough bars for MACD computation
                and close[i_curr] < close[i_prev]
                and hist[i_curr] > hist[i_prev]
            ):
                price_drop = (close[i_prev] - close[i_curr]) / (abs(close[i_prev]) + 1e-10)
                hist_rise = abs(hist[i_curr] - hist[i_prev]) / (abs(hist[i_prev]) + 1e-10)
                bullish = min(1.0, 0.3 + price_drop * 5.0 + hist_rise * 2.0)
                strength = max(strength, bullish)

        # Bearish divergence: price higher high + histogram lower high at same bars
        if len(price_peaks) >= 2:
            i_prev, i_curr = price_peaks[-2], price_peaks[-1]
            if i_prev >= 26 and close[i_curr] > close[i_prev] and hist[i_curr] < hist[i_prev]:
                price_rise = (close[i_curr] - close[i_prev]) / (abs(close[i_prev]) + 1e-10)
                hist_drop = abs(hist[i_prev] - hist[i_curr]) / (abs(hist[i_prev]) + 1e-10)
                bearish = min(1.0, 0.3 + price_rise * 5.0 + hist_drop * 2.0)
                strength = max(strength, bearish)

        return {
            "macd_div_bullish": round(bullish, 4),
            "macd_div_bearish": round(bearish, 4),
            "macd_div_strength": round(strength, 4),
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _macd_histogram_series(
        close: np.ndarray,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> np.ndarray:
        """Compute MACD histogram from close series using EMA."""
        n = len(close)
        hist = np.zeros(n)
        if n < slow + signal:
            return hist

        def ema_series(arr: np.ndarray, period: int) -> np.ndarray:
            k = 2.0 / (period + 1)
            out = np.empty_like(arr)
            out[0] = arr[0]
            for i in range(1, len(arr)):
                out[i] = arr[i] * k + out[i - 1] * (1 - k)
            return out

        ema_fast = ema_series(close, fast)
        ema_slow = ema_series(close, slow)
        macd_line = ema_fast - ema_slow
        signal_line = ema_series(macd_line, signal)
        hist = macd_line - signal_line
        return hist


plugin = MACDDivergencePlugin()
