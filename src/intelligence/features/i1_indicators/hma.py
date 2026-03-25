# src/intelligence/indicators/hma.py
"""Hull Moving Average (HMA) I1 plugin.

HMA(n=20) formula:
    half  = WMA(n//2, close[-n//2:])
    full  = WMA(n,    close[-n:])
    diff  = 2 * half - full
    hma   = WMA(int(round(sqrt(n))), diff_buffer[-sqrt_n:])

The diff series is accumulated in _state["diff_buffer"] as a rolling deque
of the last sqrt_n values so we can apply the final WMA.

min_lookback = 20 (need 20 bars for the full-period WMA).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec


def _wma(series: np.ndarray, k: int) -> float:
    """Weighted Moving Average over the last k values of series.

    weights = [1, 2, ..., k] (linearly increasing).
    """
    if len(series) < k:
        return float("nan")
    tail = series[-k:]
    weights = np.arange(1, k + 1, dtype=float)
    return float(np.dot(weights, tail) / weights.sum())


@dataclass
class HMAPlugin:
    name: str = "HMA"
    outputs: frozenset = field(default_factory=lambda: frozenset({"hma_20"}))
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset = field(default_factory=lambda: frozenset({"trend"}))
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=20),)
    _state: dict = field(default_factory=dict)

    # HMA parameters (n=20)
    _n: int = field(default=20, init=False, repr=False)
    _half: int = field(default=10, init=False, repr=False)  # n // 2
    _sqrt_n: int = field(default=4, init=False, repr=False)  # int(round(sqrt(20)))

    def __post_init__(self) -> None:
        self._half = self._n // 2
        self._sqrt_n = int(round(math.sqrt(self._n)))

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self._n:
            return {}

        close = df["close"].to_numpy(dtype=float)

        # Seed the diff_buffer from all available bars so that compute_full
        # on a historical batch produces a valid HMA value.  We need the last
        # sqrt_n diff values; each diff[i] = 2*WMA(half, close[:i+1]) - WMA(n, close[:i+1]).
        # We compute the last sqrt_n of them (indices -sqrt_n .. -1 of the series).
        buf: deque = deque(maxlen=self._sqrt_n)

        # We only need the last sqrt_n diff values — compute each one from a
        # progressively longer prefix of close ending at that bar.
        start = len(close) - self._sqrt_n
        if start < self._n - 1:
            return {}  # not enough bars to compute even the first needed diff

        for i in range(start, len(close)):
            sub = close[: i + 1]
            wh = _wma(sub, self._half)
            wf = _wma(sub, self._n)
            if math.isnan(wh) or math.isnan(wf):
                return {}
            buf.append(2.0 * wh - wf)

        self._state["diff_buffer"] = buf

        # Final WMA over the diff buffer
        diff_arr = np.array(buf, dtype=float)
        hma_20 = _wma(diff_arr, self._sqrt_n)

        if math.isnan(hma_20):
            return {}

        return {"hma_20": float(hma_20)}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = HMAPlugin()
