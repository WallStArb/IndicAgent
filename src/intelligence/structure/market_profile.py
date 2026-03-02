from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class MarketProfilePlugin:
    """TPO-based market profile: Point of Control and Value Area."""

    name: str = "struct_MarketProfile"
    outputs: set[str] = frozenset(
        {
            "poc_level",
            "va_high",
            "va_low",
            "va_width_pct",
            "price_in_va",
            "price_above_va",
            "price_below_va",
            "poc_dist_pct",
            "poc_dist_atr",
        }
    )
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"structure"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        features = frames.get("features") or {}
        close = float(features.get("close") or df["close"].iloc[-1])
        atr_14 = features.get("atr_14")

        price_range = float(high.max() - low.min())
        if price_range <= 0:
            return {}

        tick_size = price_range / 100.0
        buckets = np.arange(float(low.min()), float(high.max()) + tick_size, tick_size)
        if len(buckets) < 2:
            return {}

        # Vectorized TPO: count bars that include each price bucket
        low_2d = low[:, np.newaxis]
        high_2d = high[:, np.newaxis]
        b_2d = buckets[np.newaxis, :]
        tpo_counts = ((b_2d >= low_2d) & (b_2d <= high_2d)).sum(axis=0).astype(float)

        total_tpo = tpo_counts.sum()
        if total_tpo == 0:
            return {}

        poc_idx = int(np.argmax(tpo_counts))
        poc_level = float(buckets[poc_idx])

        # Expand value area to 70% of total TPO
        va_target = total_tpo * 0.70
        lo = poc_idx
        hi = poc_idx
        va_tpo = float(tpo_counts[poc_idx])
        n = len(tpo_counts)

        while va_tpo < va_target:
            add_lo = float(tpo_counts[lo - 1]) if lo > 0 else -1.0
            add_hi = float(tpo_counts[hi + 1]) if hi < n - 1 else -1.0
            if add_lo < 0 and add_hi < 0:
                break
            if add_hi >= add_lo:
                hi += 1
                va_tpo += float(tpo_counts[hi])
            else:
                lo -= 1
                va_tpo += float(tpo_counts[lo])

        va_high = float(buckets[hi])
        va_low = float(buckets[lo])
        va_width_pct = (va_high - va_low) / va_low if va_low != 0 else 0.0
        price_in_va = 1.0 if va_low <= close <= va_high else 0.0
        price_above_va = 1.0 if close > va_high else 0.0
        price_below_va = 1.0 if close < va_low else 0.0
        poc_dist_pct = (close - poc_level) / poc_level if poc_level != 0 else 0.0
        poc_dist_atr = (
            abs(close - poc_level) / float(atr_14)
            if isinstance(atr_14, (int, float)) and atr_14 > 0
            else None
        )

        return {
            "poc_level": poc_level,
            "va_high": va_high,
            "va_low": va_low,
            "va_width_pct": va_width_pct,
            "price_in_va": price_in_va,
            "price_above_va": price_above_va,
            "price_below_va": price_below_va,
            "poc_dist_pct": poc_dist_pct,
            "poc_dist_atr": poc_dist_atr,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MarketProfilePlugin()
