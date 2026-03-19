"""VolumeProfilePlugin — I4 context tier.

Migrated from I5/patterns/ to I4/context/ and extended with:
- Session-reset track (bars since 09:30 ET)
- Rolling track (last 480 bars)
- POC/VAH/VAL via 70% cumulative volume rule
- Directional HVN/LVN (nearest above/below close)
- Value area context fields (price_in_value_area, va_width_atr, distance_to_vah/val)

Backward-compatible: original 4 fields (nearest_hvn_level, nearest_hvn_dist_atr,
nearest_lvn_level, in_lvn) are preserved unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import numpy as np

from ..context.session_context import _et_from_utc, _extract_ts
from ..plugins import InputSpec

_N_BUCKETS = 50
_HVN_THRESHOLD = 0.80  # top 20% by volume = HVN
_LVN_THRESHOLD = 0.20  # bottom 20% by volume = LVN
_ROLLING_WINDOW = 480   # bars for rolling track


@dataclass
class VolumeProfilePlugin:
    """Volume-weighted price histogram: POC, VAH, VAL, HVN/LVN detection.

    Dual-track computation:
    - Session track: bars since 09:30 ET (resets each day)
    - Rolling track: last 480 bars (continuous window)
    """

    name: str = "ctx_VolumeProfile"
    outputs: frozenset[str] = frozenset(
        {
            # Existing 4 (backward compat)
            "nearest_hvn_level",
            "nearest_hvn_dist_atr",
            "nearest_lvn_level",
            "in_lvn",
            # New 14
            "poc_price",
            "vah",
            "val",
            "nearest_hvn_above",
            "nearest_hvn_below",
            "nearest_lvn_above",
            "nearest_lvn_below",
            "poc_price_rolling",
            "vah_rolling",
            "val_rolling",
            "price_in_value_area",
            "va_width_atr",
            "distance_to_vah_atr",
            "distance_to_val_atr",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=390),)
    _state: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _compute_profile(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close_arr: np.ndarray,
        volume: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, float, float] | None:
        """Build volume-weighted histogram.

        Returns (vol_hist, bucket_prices, bucket_size, price_min).
        """
        typical = (high + low + close_arr) / 3.0
        price_min = float(low.min())
        price_max = float(high.max())
        price_range = price_max - price_min
        if price_range <= 0:
            return None
        bucket_size = price_range / _N_BUCKETS
        bucket_idx = np.clip(
            ((typical - price_min) / bucket_size).astype(int),
            0,
            _N_BUCKETS - 1,
        )
        vol_hist = np.zeros(_N_BUCKETS)
        for i, b in enumerate(bucket_idx):
            vol_hist[b] += volume[i]
        bucket_prices = price_min + (np.arange(_N_BUCKETS) + 0.5) * bucket_size
        return vol_hist, bucket_prices, bucket_size, price_min

    def _compute_value_area(
        self,
        vol_hist: np.ndarray,
        bucket_prices: np.ndarray,
    ) -> tuple[float | None, float | None, float | None]:
        """Compute POC, VAH, VAL from histogram using 70% cumulative volume rule."""
        total_vol = vol_hist.sum()
        if total_vol == 0:
            return None, None, None
        poc_idx = int(np.argmax(vol_hist))
        poc_price = float(bucket_prices[poc_idx])
        target_vol = total_vol * 0.70
        sorted_idx = np.argsort(vol_hist)[::-1]
        cumvol = 0.0
        va_buckets: set[int] = set()
        for idx in sorted_idx:
            cumvol += vol_hist[idx]
            va_buckets.add(int(idx))
            if cumvol >= target_vol:
                break
        vah = float(bucket_prices[max(va_buckets)]) if va_buckets else poc_price
        val = float(bucket_prices[min(va_buckets)]) if va_buckets else poc_price
        return poc_price, vah, val

    def _compute_directional_nodes(
        self,
        vol_hist: np.ndarray,
        bucket_prices: np.ndarray,
        close: float,
    ) -> dict[str, float | None]:
        """Compute directional HVN/LVN (nearest above/below close) and legacy nearest."""
        nonzero_vols = vol_hist[vol_hist > 0]
        if len(nonzero_vols) == 0:
            return {}
        vol_threshold_high = np.quantile(nonzero_vols, _HVN_THRESHOLD)
        vol_threshold_low = np.quantile(nonzero_vols, _LVN_THRESHOLD)

        hvn_mask = vol_hist >= vol_threshold_high
        lvn_mask = (vol_hist > 0) & (vol_hist <= vol_threshold_low)

        result: dict[str, float | None] = {}

        if hvn_mask.any():
            hvn_prices = bucket_prices[hvn_mask]
            hvn_above = hvn_prices[hvn_prices > close]
            hvn_below = hvn_prices[hvn_prices <= close]
            result["nearest_hvn_above"] = float(hvn_above.min()) if len(hvn_above) > 0 else None
            result["nearest_hvn_below"] = float(hvn_below.max()) if len(hvn_below) > 0 else None
            # Legacy: nearest overall HVN
            result["nearest_hvn_level"] = float(
                hvn_prices[np.argmin(np.abs(hvn_prices - close))]
            )
        else:
            result["nearest_hvn_above"] = None
            result["nearest_hvn_below"] = None
            result["nearest_hvn_level"] = None

        if lvn_mask.any():
            lvn_prices = bucket_prices[lvn_mask]
            lvn_above = lvn_prices[lvn_prices > close]
            lvn_below = lvn_prices[lvn_prices <= close]
            result["nearest_lvn_above"] = float(lvn_above.min()) if len(lvn_above) > 0 else None
            result["nearest_lvn_below"] = float(lvn_below.max()) if len(lvn_below) > 0 else None
            result["nearest_lvn_level"] = float(
                lvn_prices[np.argmin(np.abs(lvn_prices - close))]
            )
        else:
            result["nearest_lvn_above"] = None
            result["nearest_lvn_below"] = None
            result["nearest_lvn_level"] = None

        return result

    # ------------------------------------------------------------------
    # Main compute
    # ------------------------------------------------------------------

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = frames.get("features") or {}
        close = float(features.get("close") or df["close"].iloc[-1])
        atr_14 = features.get("atr_14")
        atr_valid = isinstance(atr_14, (int, float)) and atr_14 > 0

        # ----------------------------------------------------------------
        # Session track: filter to bars since 09:30 ET
        # ----------------------------------------------------------------
        ts = _extract_ts(df)
        session_df = df  # fallback: use full df

        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            et = _et_from_utc(ts)
            if et.hour > 9 or (et.hour == 9 and et.minute >= 30):
                ny_open_et = et.replace(hour=9, minute=30, second=0, microsecond=0)
                ny_open_utc = ny_open_et.astimezone(UTC)
                if "timestamp" in df.columns:
                    mask = df["timestamp"] >= ny_open_utc
                    if mask.any():
                        session_df = df[mask]

        # ----------------------------------------------------------------
        # Compute session profile
        # ----------------------------------------------------------------
        s_high = session_df["high"].to_numpy(dtype=float)
        s_low = session_df["low"].to_numpy(dtype=float)
        s_close = session_df["close"].to_numpy(dtype=float)
        s_volume = session_df["volume"].to_numpy(dtype=float)

        session_profile = self._compute_profile(s_high, s_low, s_close, s_volume)
        if session_profile is None:
            return {}

        s_vol_hist, s_bucket_prices, s_bucket_size, s_price_min = session_profile

        total_vol = s_vol_hist.sum()
        if total_vol == 0:
            return {}

        nonzero = s_vol_hist[s_vol_hist > 0]
        poc_price, vah, val = self._compute_value_area(s_vol_hist, s_bucket_prices)
        directional = self._compute_directional_nodes(s_vol_hist, s_bucket_prices, close)

        # in_lvn (legacy): current bucket is a low-volume node
        if len(nonzero) == 0:
            in_lvn_flag = 0.0
        else:
            vol_threshold_low = np.quantile(nonzero, _LVN_THRESHOLD)
            cur_bucket = int(
                np.clip((close - s_price_min) / s_bucket_size, 0, _N_BUCKETS - 1)
            )
            in_lvn_flag = 1.0 if s_vol_hist[cur_bucket] <= vol_threshold_low else 0.0

        # nearest_hvn_dist_atr (legacy)
        nearest_hvn_level = directional.get("nearest_hvn_level")
        nearest_hvn_dist = (
            abs(close - nearest_hvn_level) / float(atr_14)
            if nearest_hvn_level is not None and atr_valid
            else None
        )

        # Value area context fields
        price_in_value_area = (
            1.0
            if val is not None and vah is not None and val <= close <= vah
            else 0.0
        )
        va_width_atr = (
            (vah - val) / float(atr_14)
            if atr_valid and vah is not None and val is not None
            else None
        )
        distance_to_vah_atr = (
            (vah - close) / float(atr_14) if atr_valid and vah is not None else None
        )
        distance_to_val_atr = (
            (close - val) / float(atr_14) if atr_valid and val is not None else None
        )

        # ----------------------------------------------------------------
        # Rolling track: last min(_ROLLING_WINDOW, len(df)) bars
        # ----------------------------------------------------------------
        roll_n = min(_ROLLING_WINDOW, len(df))
        roll_df = df.iloc[-roll_n:]

        r_high = roll_df["high"].to_numpy(dtype=float)
        r_low = roll_df["low"].to_numpy(dtype=float)
        r_close = roll_df["close"].to_numpy(dtype=float)
        r_volume = roll_df["volume"].to_numpy(dtype=float)

        rolling_profile = self._compute_profile(r_high, r_low, r_close, r_volume)
        poc_price_rolling: float | None = None
        vah_rolling: float | None = None
        val_rolling: float | None = None

        if rolling_profile is not None:
            r_vol_hist, r_bucket_prices, _, _ = rolling_profile
            poc_price_rolling, vah_rolling, val_rolling = self._compute_value_area(
                r_vol_hist, r_bucket_prices
            )

        return {
            # Session-track session POC/VAH/VAL
            "poc_price": poc_price,
            "vah": vah,
            "val": val,
            # Rolling-track POC/VAH/VAL
            "poc_price_rolling": poc_price_rolling,
            "vah_rolling": vah_rolling,
            "val_rolling": val_rolling,
            # Directional nodes (session track)
            "nearest_hvn_above": directional.get("nearest_hvn_above"),
            "nearest_hvn_below": directional.get("nearest_hvn_below"),
            "nearest_lvn_above": directional.get("nearest_lvn_above"),
            "nearest_lvn_below": directional.get("nearest_lvn_below"),
            # Value area context
            "price_in_value_area": price_in_value_area,
            "va_width_atr": va_width_atr,
            "distance_to_vah_atr": distance_to_vah_atr,
            "distance_to_val_atr": distance_to_val_atr,
            # Legacy fields (backward compat)
            "nearest_hvn_level": nearest_hvn_level,
            "nearest_hvn_dist_atr": nearest_hvn_dist,
            "nearest_lvn_level": directional.get("nearest_lvn_level"),
            "in_lvn": in_lvn_flag,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = VolumeProfilePlugin()
