"""MarketProfile plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full TPO market profile computation
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract volume_buckets and tick_size state
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class MarketProfilePlugin(IncrementalMixin):
    """TPO-based market profile: Point of Control and Value Area."""

    name: str = "struct_MarketProfile"
    outputs: frozenset[str] = frozenset(
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
            "va_position_pct",
            "va_distance_atr",
        }
    )
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"structure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=120),)

    def _compute_full_core(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Full TPO market profile computation. Returns outputs only (no _state)."""
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

        return self._build_output(close, poc_level, va_high, va_low, atr_14)

    def _seed_state(self, frames: dict[str, Any]) -> dict:
        """Extract volume_buckets and tick_size state for incremental seeding."""
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        price_range = float(high.max() - low.min())
        if price_range <= 0:
            return {}

        tick_size = price_range / 100.0
        buckets = np.arange(float(low.min()), float(high.max()) + tick_size, tick_size)
        if len(buckets) < 2:
            return {}

        low_2d = low[:, np.newaxis]
        high_2d = high[:, np.newaxis]
        b_2d = buckets[np.newaxis, :]
        tpo_counts = ((b_2d >= low_2d) & (b_2d <= high_2d)).sum(axis=0).astype(float)

        bucket_dict: dict[float, float] = {}
        for idx, cnt in enumerate(tpo_counts):
            if cnt > 0:
                bucket_dict[round(float(buckets[idx]), 10)] = float(cnt)

        return {
            "tick_size": tick_size,
            "price_min": float(low.min()),
            "volume_buckets": bucket_dict,
            "bar_count": len(df),
            "session_id": "full",
        }

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Incremental volume profile update. Mutates state in place.

        State keys:
            tick_size (float): price bucket size, seeded by _seed_state; read-only here.
            volume_buckets (dict[float, float]): accumulated TPO counts per price level.
            bar_count (int): running bar count since last compute_full.
        """
        df = windows.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = windows.get("features") or {}
        close = float(features.get("close") or df["close"].iloc[-1])
        atr_14 = features.get("atr_14")

        bar = df.iloc[-1]
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])

        tick_size = state.get("tick_size")
        if tick_size is None or tick_size <= 0:
            return {}

        volume_buckets: dict[float, float] = {
            float(k): v for k, v in state.get("volume_buckets", {}).items()
        }

        # Distribute this bar's TPO count incrementally
        bucket_low = round(bar_low - (bar_low % tick_size), 10)
        bucket = bucket_low
        while bucket <= bar_high + tick_size * 0.5:
            key = round(bucket, 10)
            volume_buckets[key] = volume_buckets.get(key, 0.0) + 1.0
            bucket = round(bucket + tick_size, 10)

        state["volume_buckets"] = volume_buckets
        state["bar_count"] = state.get("bar_count", 0) + 1

        # Recompute POC/VAH/VAL from accumulated buckets
        if not volume_buckets:
            return {}

        sorted_prices = sorted(float(k) for k in volume_buckets.keys())
        sorted_counts = [volume_buckets[p] for p in sorted_prices]
        total_tpo = sum(sorted_counts)

        if total_tpo == 0:
            return {}

        poc_idx = int(np.argmax(sorted_counts))
        poc_level = sorted_prices[poc_idx]

        va_target = total_tpo * 0.70
        lo = poc_idx
        hi = poc_idx
        va_tpo = sorted_counts[poc_idx]
        n = len(sorted_counts)

        while va_tpo < va_target:
            add_lo = sorted_counts[lo - 1] if lo > 0 else -1.0
            add_hi = sorted_counts[hi + 1] if hi < n - 1 else -1.0
            if add_lo < 0 and add_hi < 0:
                break
            if add_hi >= add_lo:
                hi += 1
                va_tpo += sorted_counts[hi]
            else:
                lo -= 1
                va_tpo += sorted_counts[lo]

        va_high = sorted_prices[hi]
        va_low = sorted_prices[lo]

        return self._build_output(close, poc_level, va_high, va_low, atr_14)

    def _build_output(
        self,
        close: float,
        poc_level: float,
        va_high: float,
        va_low: float,
        atr_14: Any,
    ) -> dict[str, Any]:
        """Build the output dict from computed VA/POC values."""
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

        va_width = va_high - va_low
        if price_in_va and va_width > 0:
            va_position_pct = (close - va_low) / va_width
        elif price_above_va:
            va_position_pct = 1.0
        else:
            va_position_pct = 0.0

        if isinstance(atr_14, (int, float)) and float(atr_14) > 0:
            if price_above_va:
                va_distance_atr = round((close - va_high) / float(atr_14), 4)
            elif price_below_va:
                va_distance_atr = round((va_low - close) / float(atr_14), 4)
            else:
                va_distance_atr = 0.0
        else:
            va_distance_atr = None

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
            "va_position_pct": round(va_position_pct, 4),
            "va_distance_atr": va_distance_atr,
        }


plugin = MarketProfilePlugin()
