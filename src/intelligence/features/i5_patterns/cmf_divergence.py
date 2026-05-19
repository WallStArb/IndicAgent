from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import linreg_slope


@dataclass
class CMFDivergencePlugin:
    """I5 pattern plugin: detects divergence using Chaikin Money Flow (CMF) series.

    Bullish divergence: price slope negative + CMF slope positive (accumulation during decline).
    Bearish divergence: price slope positive + CMF slope negative (distribution during rise).
    Uses linear regression slopes over lookback window — same pattern as VolumeDivergencePlugin.
    """

    name: str = "patt_CMFDivergence"
    outputs: frozenset[str] = frozenset({"cmf_div_bullish", "cmf_div_bearish", "cmf_div_strength"})
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern", "volume"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    lookback: int = 20
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)

        # Compute CMF series using raw bar data (not features scalar)
        # Money Flow Multiplier = (2*close - high - low) / (high - low + eps)
        # Money Flow Volume = MFM * volume
        # CMF = sum(MFV, window) / sum(volume, window) — rolling
        hl_range = high - low + 1e-10
        mfm = (2.0 * close - high - low) / hl_range
        mfv = mfm * volume

        cmf_window = 20
        n = len(close)
        cmf_series = np.zeros(n)
        for i in range(cmf_window - 1, n):
            vol_sum = float(np.sum(volume[i - cmf_window + 1 : i + 1]))
            if vol_sum > 0:
                cmf_series[i] = float(np.sum(mfv[i - cmf_window + 1 : i + 1])) / vol_sum

        # Use linear regression slopes over lookback window
        window = min(self.lookback, n)
        price_slope = linreg_slope(close[-window:])
        cmf_slope = linreg_slope(cmf_series[-window:])

        bullish = 0.0
        bearish = 0.0

        if price_slope < 0 and cmf_slope > 0:
            # Price declining + CMF rising → accumulation (bullish divergence)
            mag = abs(price_slope) + abs(cmf_slope)
            bullish = min(1.0, 0.3 + mag * 2.0)
        elif price_slope > 0 and cmf_slope < 0:
            # Price rising + CMF declining → distribution (bearish divergence)
            mag = abs(price_slope) + abs(cmf_slope)
            bearish = min(1.0, 0.3 + mag * 2.0)

        strength = max(bullish, bearish)

        return {
            "cmf_div_bullish": round(bullish, 4),
            "cmf_div_bearish": round(bearish, 4),
            "cmf_div_strength": round(strength, 4),
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CMFDivergencePlugin()
