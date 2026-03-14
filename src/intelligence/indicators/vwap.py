from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec


@dataclass
class VWAPPlugin:
    name: str = "VWAP"
    outputs: frozenset[str] = frozenset(
        {"vwap", "vwap_upper_1", "vwap_lower_1", "vwap_upper_2", "vwap_lower_2", "vwap_std"}
    )
    min_lookback: int = 1
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=390),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        required = {"high", "low", "close", "volume"}
        if df is None or len(df) == 0 or not required.issubset(df.columns):
            return {}

        # Detect session boundary: use last day's data only
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        vol = df["volume"]

        # Session reset: find the last date boundary
        session_start = 0
        session_date = None
        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"])
            last_date = ts.iloc[-1].date()
            session_date = last_date
            mask = ts.dt.date == last_date
            session_start = mask.values.argmax()  # first True index

        tp_session = tp.iloc[session_start:].to_numpy(dtype=float)
        vol_session = vol.iloc[session_start:].to_numpy(dtype=float)

        cum_vol = np.cumsum(vol_session)
        cum_pv = np.cumsum(tp_session * vol_session)
        cum_tp_sq_vol = np.cumsum(tp_session**2 * vol_session)

        if cum_vol[-1] == 0:
            return {}

        vwap_val = cum_pv[-1] / cum_vol[-1]

        # Volume-weighted standard deviation
        variance = cum_tp_sq_vol[-1] / cum_vol[-1] - vwap_val**2
        std = math.sqrt(max(variance, 0.0))

        # Seed state for incremental (unused in production but maintains protocol)
        self._state["cum_pv"] = float(cum_pv[-1])
        self._state["cum_vol"] = float(cum_vol[-1])
        self._state["cum_tp_sq_vol"] = float(cum_tp_sq_vol[-1])
        self._state["session_date"] = session_date

        return {
            "vwap": float(vwap_val),
            "vwap_upper_1": float(vwap_val + std),
            "vwap_lower_1": float(vwap_val - std),
            "vwap_upper_2": float(vwap_val + 2 * std),
            "vwap_lower_2": float(vwap_val - 2 * std),
            "vwap_std": float(std),
        }

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]

        # Reset on session boundary (new trading day)
        if "timestamp" in df.columns:
            bar_date = pd.to_datetime(row["timestamp"]).date()
            if bar_date != self._state.get("session_date"):
                return self.compute_full(windows)

        tp = (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0
        vol = float(row["volume"])
        self._state["cum_pv"] += tp * vol
        self._state["cum_vol"] += vol
        self._state["cum_tp_sq_vol"] += tp**2 * vol
        if self._state["cum_vol"] == 0:
            return {}
        vwap_val = self._state["cum_pv"] / self._state["cum_vol"]
        variance = self._state["cum_tp_sq_vol"] / self._state["cum_vol"] - vwap_val**2
        std = math.sqrt(max(variance, 0.0))
        return {
            "vwap": vwap_val,
            "vwap_upper_1": vwap_val + std,
            "vwap_lower_1": vwap_val - std,
            "vwap_upper_2": vwap_val + 2 * std,
            "vwap_lower_2": vwap_val - 2 * std,
            "vwap_std": std,
        }


plugin = VWAPPlugin()
