"""Cumulative Volume Delta (CVD) — I1 microstructure indicator.

Tracks buy/sell volume imbalance cumulatively within each trading session,
resetting at 09:30 ET (New York session open).

Two computation paths:
- Tick path (primary): Uses raw tick data via tick rule to compute per-bar delta.
- Proxy path (fallback): When tick_buffer is empty, uses OHLCV proxy
  `(2*close - high - low) / (high - low + epsilon) * volume`.

Outputs: cvd, cvd_slope_5bar, cvd_divergence, cvd_spike_z
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec

_ET_TZ = ZoneInfo("America/New_York")
_PROXY_EPSILON: float = 1e-9


@dataclass
class CVDPlugin:
    name: str = "ind_CVD"
    outputs: frozenset[str] = frozenset(
        {"cvd", "cvd_slope_5bar", "cvd_divergence", "cvd_spike_z"}
    )
    min_lookback: int = 2
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume", "microstructure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        tick_buf = frames.get("tick_buffer") or []

        if df is None or len(df) < self.min_lookback:
            return {}

        # Session reset check: extract timestamp and convert to ET
        ts = self._extract_ts(df)
        if ts is not None:
            et_dt = ts.astimezone(_ET_TZ)
            et_hour = et_dt.hour
            et_minute = et_dt.minute
            et_date: date = et_dt.date()
            last_session_date = self._state.get("last_session_date")
            if (
                et_hour == 9
                and et_minute >= 30
                and et_date != last_session_date
            ):
                self._state["cum_cvd"] = 0.0
                self._state["last_session_date"] = et_date

        # Compute single-bar delta
        if tick_buf:
            bar_delta = self._compute_tick_delta(tick_buf)
        else:
            bar_delta = self._compute_proxy_delta(df)

        # Accumulate CVD
        self._state["cum_cvd"] = self._state.get("cum_cvd", 0.0) + bar_delta

        # Update CVD history (for slope)
        if "cvd_history" not in self._state:
            self._state["cvd_history"] = deque(maxlen=100)
        self._state["cvd_history"].append(self._state["cum_cvd"])

        # Update delta history (for spike_z)
        if "delta_history" not in self._state:
            self._state["delta_history"] = deque(maxlen=100)
        self._state["delta_history"].append(bar_delta)

        # Slope: polyfit over last 5 CVD values
        cvd_hist = list(self._state["cvd_history"])
        if len(cvd_hist) >= 5:
            last_5 = cvd_hist[-5:]
            slope = float(np.polyfit(np.arange(5), last_5, 1)[0])
        else:
            slope = 0.0

        # Divergence: compare cvd_slope_5bar sign vs 5-bar price change sign
        close_series = df["close"]
        if len(close_series) >= 5:
            price_change_5 = float(close_series.iloc[-1]) - float(close_series.iloc[-5])
        elif len(close_series) >= 2:
            price_change_5 = float(close_series.iloc[-1]) - float(close_series.iloc[0])
        else:
            price_change_5 = 0.0

        slope_dir = 1 if slope > 0 else (-1 if slope < 0 else 0)
        price_dir = 1 if price_change_5 > 0 else (-1 if price_change_5 < 0 else 0)
        divergence = float(slope_dir - price_dir)

        # Spike z-score: current bar_delta vs rolling 100-bar delta history
        delta_hist = list(self._state["delta_history"])
        if len(delta_hist) >= 5:
            hist_arr = np.array(delta_hist[:-1])  # exclude current bar
            mean = float(np.mean(hist_arr))
            std = float(np.std(hist_arr)) + 1e-9
            spike_z = (bar_delta - mean) / std
        else:
            spike_z = 0.0

        return {
            "cvd": round(float(self._state["cum_cvd"]), 6),
            "cvd_slope_5bar": round(slope, 6),
            "cvd_divergence": round(divergence, 4),
            "cvd_spike_z": round(spike_z, 4),
        }

    def _extract_ts(self, df: Any) -> Any:
        """Extract the last timestamp from df."""
        if df is None or len(df) == 0:
            return None
        if "timestamp" not in df.columns:
            return None
        val = df["timestamp"].iloc[-1]
        if hasattr(val, "to_pydatetime"):
            return val.to_pydatetime()
        return val

    def _compute_tick_delta(self, tick_buf: list[dict]) -> float:
        """Tick rule: buy_vol - sell_vol from sequential tick price changes."""
        buy_vol = 0.0
        sell_vol = 0.0
        prev_price: float | None = None
        for tick in tick_buf:
            try:
                price = float(tick.get("price", 0) or 0)
                size = float(tick.get("size") or 0)
            except (TypeError, ValueError):
                continue
            if prev_price is not None:
                if price > prev_price:
                    buy_vol += size
                elif price < prev_price:
                    sell_vol += size
            prev_price = price
        return buy_vol - sell_vol

    def _compute_proxy_delta(self, df: pd.DataFrame) -> float:
        """Bar proxy: (2*close - high - low) / (high - low + epsilon) * volume."""
        row = df.iloc[-1]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        volume = float(row["volume"])
        return (2 * close - high - low) / (high - low + _PROXY_EPSILON) * volume

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CVDPlugin()
