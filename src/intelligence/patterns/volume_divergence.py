from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class VolumeDivergencePlugin:
    name: str = "VolumeDivergence"
    outputs: frozenset[str] = frozenset({"vol_div_bullish", "vol_div_bearish", "vol_div_strength"})
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern", "volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=60),)
    lookback: int = 20
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)

        # Compute OBV
        obv = np.zeros(len(close))
        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                obv[i] = obv[i - 1] + volume[i]
            elif close[i] < close[i - 1]:
                obv[i] = obv[i - 1] - volume[i]
            else:
                obv[i] = obv[i - 1]

        # Linear regression slopes over lookback window
        window = min(self.lookback, len(close))
        price_slope = self._linreg_slope(close[-window:])
        obv_slope = self._linreg_slope(obv[-window:])

        # Normalize slopes to percentage scale
        price_mean = float(np.mean(close[-window:]))
        obv_range = float(np.ptp(obv[-window:])) if np.ptp(obv[-window:]) != 0 else 1.0
        norm_price = price_slope / price_mean if price_mean != 0 else 0.0
        norm_obv = obv_slope / obv_range if obv_range != 0 else 0.0

        bullish = 0.0
        bearish = 0.0

        if norm_price > 0 and norm_obv < 0:
            # Price up, OBV down → distribution (bearish divergence)
            mag = abs(norm_price) + abs(norm_obv)
            bearish = min(1.0, 0.3 + mag * 2.0)
        elif norm_price < 0 and norm_obv > 0:
            # Price down, OBV up → accumulation (bullish divergence)
            mag = abs(norm_price) + abs(norm_obv)
            bullish = min(1.0, 0.3 + mag * 2.0)

        strength = max(bullish, bearish)

        return {
            "vol_div_bullish": round(bullish, 4),
            "vol_div_bearish": round(bearish, 4),
            "vol_div_strength": round(strength, 4),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _linreg_slope(y: np.ndarray) -> float:
        """Simple linear regression slope: Σ((x - x̄)(y - ȳ)) / Σ((x - x̄)²)."""
        n = len(y)
        if n < 2:
            return 0.0
        x = np.arange(n, dtype=float)
        x_mean = (n - 1) / 2.0
        y_mean = float(np.mean(y))
        num = float(np.sum((x - x_mean) * (y - y_mean)))
        den = float(np.sum((x - x_mean) ** 2))
        return num / den if den != 0 else 0.0


plugin = VolumeDivergencePlugin()
