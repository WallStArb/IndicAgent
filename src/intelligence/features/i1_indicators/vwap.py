"""VWAP plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full VWAP computation
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract cumulative volume/price state
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class VWAPPlugin(IncrementalMixin):
    name: str = "VWAP"
    outputs: frozenset[str] = frozenset(
        {"vwap", "vwap_upper_1", "vwap_lower_1", "vwap_upper_2", "vwap_lower_2", "vwap_std"}
    )
    min_lookback: int = 1
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=390),)

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full VWAP computation. Returns outputs only (no _state)."""
        df = frames.get("main")
        required = {"high", "low", "close", "volume"}
        if df is None or len(df) == 0 or not required.issubset(df.columns):
            return {}

        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        vol = df["volume"]

        # Session reset: find the last date boundary
        session_start = 0
        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"], utc=True)
            last_date = ts.iloc[-1].date()
            mask = ts.dt.date == last_date
            session_start = mask.values.argmax()

        tp_session = tp.iloc[session_start:].to_numpy(dtype=float)
        vol_session = vol.iloc[session_start:].to_numpy(dtype=float)

        cum_vol = np.cumsum(vol_session)
        cum_pv = np.cumsum(tp_session * vol_session)
        cum_tp_sq_vol = np.cumsum(tp_session**2 * vol_session)

        if cum_vol[-1] == 0:
            return {}

        vwap_val = cum_pv[-1] / cum_vol[-1]
        variance = cum_tp_sq_vol[-1] / cum_vol[-1] - vwap_val**2
        std = math.sqrt(max(variance, 0.0))

        return {
            "vwap": float(vwap_val),
            "vwap_upper_1": float(vwap_val + std),
            "vwap_lower_1": float(vwap_val - std),
            "vwap_upper_2": float(vwap_val + 2 * std),
            "vwap_lower_2": float(vwap_val - 2 * std),
            "vwap_std": float(std),
        }

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract cumulative volume/price state for incremental seeding."""
        df = frames.get("main")
        required = {"high", "low", "close", "volume"}
        if df is None or len(df) == 0 or not required.issubset(df.columns):
            return {}

        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        vol = df["volume"]

        session_start = 0
        session_date = None
        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"], utc=True)
            last_date = ts.iloc[-1].date()
            session_date = last_date
            mask = ts.dt.date == last_date
            session_start = mask.values.argmax()

        tp_session = tp.iloc[session_start:].to_numpy(dtype=float)
        vol_session = vol.iloc[session_start:].to_numpy(dtype=float)

        cum_vol = np.cumsum(vol_session)
        cum_pv = np.cumsum(tp_session * vol_session)
        cum_tp_sq_vol = np.cumsum(tp_session**2 * vol_session)

        return {
            "cum_pv": float(cum_pv[-1]),
            "cum_vol": float(cum_vol[-1]),
            "cum_tp_sq_vol": float(cum_tp_sq_vol[-1]),
            "session_date": session_date,
        }

    def _compute_next_core(self, windows: dict[str, pd.DataFrame], state: dict) -> dict[str, Any]:
        """Single-bar incremental VWAP update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]

        # Reset on session boundary (new trading day)
        if "timestamp" in df.columns:
            bar_date = pd.to_datetime(row["timestamp"], utc=True).date()
            if bar_date != state.get("session_date"):
                # Delegate to full computation via compute_full (mixin will handle _state)
                # Since we're in _compute_next_core we return {} to signal fallback needed.
                # We do a manual full recompute here using the frames directly.
                return self._recompute_from_frames(windows, state)

        tp = (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0
        vol = float(row["volume"])
        state["cum_pv"] += tp * vol
        state["cum_vol"] += vol
        state["cum_tp_sq_vol"] += tp**2 * vol
        if state["cum_vol"] == 0:
            return {}
        vwap_val = state["cum_pv"] / state["cum_vol"]
        variance = state["cum_tp_sq_vol"] / state["cum_vol"] - vwap_val**2
        std = math.sqrt(max(variance, 0.0))
        return {
            "vwap": vwap_val,
            "vwap_upper_1": vwap_val + std,
            "vwap_lower_1": vwap_val - std,
            "vwap_upper_2": vwap_val + 2 * std,
            "vwap_lower_2": vwap_val - 2 * std,
            "vwap_std": std,
        }

    def _recompute_from_frames(
        self, frames: dict[str, pd.DataFrame], state: dict
    ) -> dict[str, Any]:
        """Recompute on session boundary, mutating state in place."""
        df = frames.get("main")
        required = {"high", "low", "close", "volume"}
        if df is None or len(df) == 0 or not required.issubset(df.columns):
            return {}

        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        vol = df["volume"]

        session_start = 0
        session_date = None
        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"], utc=True)
            last_date = ts.iloc[-1].date()
            session_date = last_date
            mask = ts.dt.date == last_date
            session_start = mask.values.argmax()

        tp_session = tp.iloc[session_start:].to_numpy(dtype=float)
        vol_session = vol.iloc[session_start:].to_numpy(dtype=float)

        cum_vol = np.cumsum(vol_session)
        cum_pv = np.cumsum(tp_session * vol_session)
        cum_tp_sq_vol = np.cumsum(tp_session**2 * vol_session)

        if cum_vol[-1] == 0:
            return {}

        vwap_val = cum_pv[-1] / cum_vol[-1]
        variance = cum_tp_sq_vol[-1] / cum_vol[-1] - vwap_val**2
        std = math.sqrt(max(variance, 0.0))

        # Mutate state in place
        state["cum_pv"] = float(cum_pv[-1])
        state["cum_vol"] = float(cum_vol[-1])
        state["cum_tp_sq_vol"] = float(cum_tp_sq_vol[-1])
        state["session_date"] = session_date

        return {
            "vwap": float(vwap_val),
            "vwap_upper_1": float(vwap_val + std),
            "vwap_lower_1": float(vwap_val - std),
            "vwap_upper_2": float(vwap_val + 2 * std),
            "vwap_lower_2": float(vwap_val - 2 * std),
            "vwap_std": float(std),
        }


plugin = VWAPPlugin()
