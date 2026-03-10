from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec

_FIB_RATIOS = [0.236, 0.382, 0.500, 0.618, 0.786]
_FIB_KEYS = ["fib_236", "fib_382", "fib_500", "fib_618", "fib_786"]


@dataclass
class FibonacciZonesPlugin:
    """Fibonacci retracement zones from swing high/low."""

    name: str = "struct_FibonacciZones"
    outputs: set[str] = frozenset(
        {
            "fib_swing_high",
            "fib_swing_low",
            "fib_236",
            "fib_382",
            "fib_500",
            "fib_618",
            "fib_786",
            "nearest_fib_level",
            "nearest_fib_ratio",
            "nearest_fib_dist_atr",
            "fib_cluster_strength",
            "in_fib_discount_zone",
        }
    )
    min_lookback: int = 5
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"structure"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = frames.get("features") or {}
        close = float(features.get("close") or df["close"].iloc[-1])
        atr_14 = features.get("atr_14")

        swing_high = features.get("swing_high")
        swing_low = features.get("swing_low")

        # Fallback to rolling high/low when swing levels not available
        if not isinstance(swing_high, (int, float)) or not isinstance(swing_low, (int, float)):
            n_lb = min(50, len(df))
            swing_high = float(df["high"].iloc[-n_lb:].max())
            swing_low = float(df["low"].iloc[-n_lb:].min())

        swing_high = float(swing_high)
        swing_low = float(swing_low)
        swing_range = swing_high - swing_low

        if swing_range <= 0:
            return {}

        levels = {
            key: swing_low + ratio * swing_range
            for ratio, key in zip(_FIB_RATIOS, _FIB_KEYS, strict=False)
        }

        nearest_key = min(levels, key=lambda k: abs(levels[k] - close))
        nearest_level = levels[nearest_key]
        nearest_ratio = _FIB_RATIOS[_FIB_KEYS.index(nearest_key)]
        nearest_dist_atr = (
            abs(close - nearest_level) / float(atr_14)
            if isinstance(atr_14, (int, float)) and atr_14 > 0
            else None
        )

        # Discount zone: price between 50%–78.6% retracement
        in_discount = 1.0 if levels["fib_500"] <= close <= levels["fib_786"] else 0.0

        # Cluster strength: fraction of fib pairs within ATR/2 of each other
        threshold = (
            float(atr_14) / 2.0
            if isinstance(atr_14, (int, float)) and atr_14 > 0
            else swing_range / 20.0
        )
        level_vals = list(levels.values())
        cluster_count = sum(
            1
            for i in range(len(level_vals))
            for j in range(i + 1, len(level_vals))
            if abs(level_vals[i] - level_vals[j]) < threshold
        )
        max_pairs = len(level_vals) * (len(level_vals) - 1) / 2
        cluster_strength = cluster_count / max_pairs if max_pairs > 0 else 0.0

        return {
            "fib_swing_high": swing_high,
            "fib_swing_low": swing_low,
            **levels,
            "nearest_fib_level": nearest_level,
            "nearest_fib_ratio": nearest_ratio,
            "nearest_fib_dist_atr": nearest_dist_atr,
            "fib_cluster_strength": cluster_strength,
            "in_fib_discount_zone": in_discount,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = FibonacciZonesPlugin()
