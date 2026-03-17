from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec

_WEEKLY_BARS = 390  # ~1 trading week on 1m as rolling proxy


@dataclass
class AnchoredVWAPPlugin:
    """Session, swing-anchored, and weekly VWAP with alignment score, std bands, sigma, velocity.

    Migrated from I3/structure/ to I4/context/ to run after I3 swing detection.
    Provides 15 output fields: 8 original + 7 new deviation/band metrics for I7 consumption.
    """

    name: str = "ctx_AnchoredVWAP"
    outputs: frozenset[str] = frozenset(
        {
            # Original 8 fields (backward compatible)
            "session_vwap",
            "session_vwap_dist_pct",
            "swing_vwap",
            "weekly_vwap",
            "above_session_vwap",
            "above_swing_vwap",
            "above_weekly_vwap",
            "vwap_alignment_score",
            # New 7 I4 fields
            "avwap_upper_band",
            "avwap_lower_band",
            "swing_vwap_upper_band",
            "swing_vwap_lower_band",
            "session_vwap_deviation_sigma",
            "swing_vwap_deviation_sigma",
            "session_vwap_deviation_velocity",
        }
    )
    min_lookback: int = 5
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = frames.get("features") or {}
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        current_close = float(features.get("close") or close[-1])

        typical = (high + low + close) / 3.0
        tpv = typical * volume

        # --- Session VWAP ---
        total_vol = float(volume.sum())
        session_vwap = float(tpv.sum() / total_vol) if total_vol > 0 else float(typical[-1])
        session_vwap_dist_pct = (
            (current_close - session_vwap) / session_vwap if session_vwap != 0 else 0.0
        )

        # Session std bands and sigma
        deviations = typical - session_vwap
        session_std = float(np.std(deviations)) if len(deviations) > 1 else 0.0
        if session_std > 0:
            avwap_upper_band = session_vwap + 2.0 * session_std
            avwap_lower_band = session_vwap - 2.0 * session_std
            session_vwap_deviation_sigma = (current_close - session_vwap) / session_std
        else:
            avwap_upper_band = session_vwap
            avwap_lower_band = session_vwap
            session_vwap_deviation_sigma = 0.0

        # --- Swing VWAP ---
        swing_vwap = None
        shi = features.get("swing_high_idx")
        sli = features.get("swing_low_idx")
        anchor_idx = None
        n = len(df)

        if isinstance(shi, (int, float)) and isinstance(sli, (int, float)):
            i_hi, i_lo = int(shi), int(sli)
            if 0 <= i_hi < n and 0 <= i_lo < n:
                anchor_idx = max(i_hi, i_lo)
        elif isinstance(shi, (int, float)):
            idx = int(shi)
            if 0 <= idx < n:
                anchor_idx = idx
        elif isinstance(sli, (int, float)):
            idx = int(sli)
            if 0 <= idx < n:
                anchor_idx = idx

        if anchor_idx is not None and anchor_idx < n - 1:
            slice_vol = volume[anchor_idx:].sum()
            slice_tpv = tpv[anchor_idx:].sum()
            swing_vwap = float(slice_tpv / slice_vol) if slice_vol > 0 else None

        # Swing std bands and sigma
        if swing_vwap is not None and anchor_idx is not None:
            swing_devs = typical[anchor_idx:] - swing_vwap
            swing_std = float(np.std(swing_devs)) if len(swing_devs) > 1 else 0.0
            if swing_std > 0:
                swing_vwap_upper_band: float | None = swing_vwap + 2.0 * swing_std
                swing_vwap_lower_band: float | None = swing_vwap - 2.0 * swing_std
                swing_vwap_deviation_sigma: float | None = (
                    current_close - swing_vwap
                ) / swing_std
            else:
                swing_vwap_upper_band = swing_vwap
                swing_vwap_lower_band = swing_vwap
                swing_vwap_deviation_sigma = 0.0
        else:
            swing_vwap_upper_band = None
            swing_vwap_lower_band = None
            swing_vwap_deviation_sigma = None

        # --- Weekly VWAP ---
        weekly_n = min(_WEEKLY_BARS, n)
        weekly_vol = float(volume[-weekly_n:].sum())
        weekly_vwap = (
            float(tpv[-weekly_n:].sum() / weekly_vol) if weekly_vol > 0 else float(typical[-1])
        )

        above_session = 1.0 if current_close > session_vwap else 0.0
        above_swing = 1.0 if (swing_vwap is not None and current_close > swing_vwap) else 0.0
        above_weekly = 1.0 if current_close > weekly_vwap else 0.0

        alignment_vals = [above_session, above_weekly]
        if swing_vwap is not None:
            alignment_vals.append(above_swing)
        alignment_score = sum(alignment_vals) / len(alignment_vals)

        # --- Velocity via _state (3-bar rolling sigma history) ---
        key = (frames.get("symbol", ""), frames.get("timeframe", ""))
        prev_sigmas = self._state.get(key, {}).get("prev_sigmas", [])
        prev_sigmas = (prev_sigmas + [session_vwap_deviation_sigma])[-3:]
        session_vwap_deviation_velocity = (
            (prev_sigmas[-1] - prev_sigmas[0]) / len(prev_sigmas)
            if len(prev_sigmas) > 1
            else 0.0
        )
        self._state[key] = {"prev_sigmas": prev_sigmas}

        return {
            "session_vwap": session_vwap,
            "session_vwap_dist_pct": session_vwap_dist_pct,
            "swing_vwap": swing_vwap,
            "weekly_vwap": weekly_vwap,
            "above_session_vwap": above_session,
            "above_swing_vwap": above_swing,
            "above_weekly_vwap": above_weekly,
            "vwap_alignment_score": alignment_score,
            "avwap_upper_band": avwap_upper_band,
            "avwap_lower_band": avwap_lower_band,
            "swing_vwap_upper_band": swing_vwap_upper_band,
            "swing_vwap_lower_band": swing_vwap_lower_band,
            "session_vwap_deviation_sigma": session_vwap_deviation_sigma,
            "swing_vwap_deviation_sigma": swing_vwap_deviation_sigma,
            "session_vwap_deviation_velocity": session_vwap_deviation_velocity,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = AnchoredVWAPPlugin()
