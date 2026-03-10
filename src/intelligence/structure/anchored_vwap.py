from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec

_WEEKLY_BARS = 390  # ~1 trading week on 1m as rolling proxy


@dataclass
class AnchoredVWAPPlugin:
    """Session, swing-anchored, and weekly VWAP with alignment score."""

    name: str = "struct_AnchoredVWAP"
    outputs: set[str] = frozenset(
        {
            "session_vwap",
            "session_vwap_dist_pct",
            "swing_vwap",
            "weekly_vwap",
            "above_session_vwap",
            "above_swing_vwap",
            "above_weekly_vwap",
            "vwap_alignment_score",
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
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        current_close = float(features.get("close") or close[-1])

        typical = (high + low + close) / 3.0
        tpv = typical * volume

        # Session VWAP: cumulative from bar 0
        total_vol = float(volume.sum())
        session_vwap = float(tpv.sum() / total_vol) if total_vol > 0 else float(typical[-1])
        session_vwap_dist_pct = (
            (current_close - session_vwap) / session_vwap if session_vwap != 0 else 0.0
        )

        # Swing VWAP: anchored to most recent swing high or low index
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

        # Weekly VWAP: rolling last WEEKLY_BARS
        weekly_n = min(_WEEKLY_BARS, n)
        weekly_vol = float(volume[-weekly_n:].sum())
        weekly_vwap = (
            float(tpv[-weekly_n:].sum() / weekly_vol)
            if weekly_vol > 0
            else float(typical[-1])
        )

        above_session = 1.0 if current_close > session_vwap else 0.0
        above_swing = (
            1.0 if (swing_vwap is not None and current_close > swing_vwap) else 0.0
        )
        above_weekly = 1.0 if current_close > weekly_vwap else 0.0

        alignment_vals = [above_session, above_weekly]
        if swing_vwap is not None:
            alignment_vals.append(above_swing)
        alignment_score = sum(alignment_vals) / len(alignment_vals)

        return {
            "session_vwap": session_vwap,
            "session_vwap_dist_pct": session_vwap_dist_pct,
            "swing_vwap": swing_vwap,
            "weekly_vwap": weekly_vwap,
            "above_session_vwap": above_session,
            "above_swing_vwap": above_swing,
            "above_weekly_vwap": above_weekly,
            "vwap_alignment_score": alignment_score,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = AnchoredVWAPPlugin()
