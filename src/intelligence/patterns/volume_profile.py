from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec

_N_BUCKETS = 50
_HVN_THRESHOLD = 0.80  # top 20% = HVN
_LVN_THRESHOLD = 0.20  # bottom 20% = LVN


@dataclass
class VolumeProfilePlugin:
    """Volume-weighted price histogram: HVN and LVN detection."""

    name: str = "patt_VolumeProfile"
    outputs: frozenset[str] = frozenset(
        {
            "nearest_hvn_level",
            "nearest_hvn_dist_atr",
            "nearest_lvn_level",
            "in_lvn",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = frames.get("features") or {}
        close = float(features.get("close") or df["close"].iloc[-1])
        atr_14 = features.get("atr_14")

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        close_arr = df["close"].to_numpy(dtype=float)
        typical = (high + low + close_arr) / 3.0

        price_min = float(low.min())
        price_max = float(high.max())
        price_range = price_max - price_min

        if price_range <= 0:
            return {}

        # Build volume-weighted price histogram using typical price
        bucket_size = price_range / _N_BUCKETS
        bucket_idx = np.clip(
            ((typical - price_min) / bucket_size).astype(int),
            0,
            _N_BUCKETS - 1,
        )
        vol_hist = np.zeros(_N_BUCKETS)
        for i, b in enumerate(bucket_idx):
            vol_hist[b] += volume[i]

        total_vol = vol_hist.sum()
        if total_vol == 0:
            return {}

        # Bucket center prices
        bucket_prices = price_min + (np.arange(_N_BUCKETS) + 0.5) * bucket_size

        # HVN: top 20% by volume
        nonzero_vols = vol_hist[vol_hist > 0]

        # Guard against empty volume data (e.g., market open with no range)
        if len(nonzero_vols) == 0:
            return {}

        vol_threshold_high = np.quantile(nonzero_vols, _HVN_THRESHOLD)
        vol_threshold_low = np.quantile(nonzero_vols, _LVN_THRESHOLD)

        # Use np.where() to get valid indices instead of boolean indexing
        hvn_mask = vol_hist >= vol_threshold_high
        lvn_mask = vol_hist <= vol_threshold_low

        # Only use masks for indexing if they contain True values
        # Keep as numpy arrays for calculations (convert to float at end)
        hvn_prices = np.array([])
        lvn_prices = np.array([])
        if hvn_mask.any():
            hvn_prices = bucket_prices[hvn_mask]
        if lvn_mask.any():
            lvn_prices = bucket_prices[lvn_mask]

        # Return early if no valid price indices (empty masks)
        if not hvn_mask.any() and not lvn_mask.any():
            return {}

        nearest_hvn = None
        nearest_hvn_dist = None
        if len(hvn_prices) > 0:
            nearest_hvn = float(hvn_prices[np.argmin(np.abs(hvn_prices - close))])
            nearest_hvn_dist = (
                abs(close - nearest_hvn) / float(atr_14)
                if isinstance(atr_14, (int, float)) and atr_14 > 0
                else None
            )

        nearest_lvn = None
        in_lvn_flag = 0.0
        if len(lvn_prices) > 0:
            nearest_lvn = float(lvn_prices[np.argmin(np.abs(lvn_prices - close))])
            # In LVN if current bucket is a low-volume node
            cur_bucket = int(np.clip((close - price_min) / bucket_size, 0, _N_BUCKETS - 1))
            in_lvn_flag = 1.0 if vol_hist[cur_bucket] <= vol_threshold_low else 0.0

        return {
            "nearest_hvn_level": nearest_hvn,
            "nearest_hvn_dist_atr": nearest_hvn_dist,
            "nearest_lvn_level": nearest_lvn,
            "in_lvn": in_lvn_flag,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = VolumeProfilePlugin()
