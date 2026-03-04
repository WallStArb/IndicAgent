"""I7 SessionExtremesSetup — fade setups triggered by price approaching Asian session extremes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class SessionExtremesSetupPlugin:
    """I7 trading setup: fade when price approaches Asian session high or low during London/NY.

    SESS-01: Asian session H/L must be available from struct_SessionLevels.
    SESS-02: Signal only fires during London (03:00–12:00 ET) or NY session window.
    SESS-03: At least one confirming factor required: trend alignment, volume spike, or RSI extreme.

    Entry style: at_limit — limit order placed at the session extreme level.
    """

    name: str = "trad_SessionExtremesSetup"
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "bias",
            "proximity_atr",
            "confidence",
            "entry_type",
            "entry_price",
            "stop_loss",
            "targets",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "session"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    proximity_atr_mult: float = 0.3
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        # SESS-01: Asian extremes must be available
        asian_high = features.get("asian_session_high")
        asian_low = features.get("asian_session_low")
        if not isinstance(asian_high, (int, float)) or not isinstance(asian_low, (int, float)):
            return self._no_signal()

        # SESS-02: London or NY session only
        session_london = float(features.get("session_london", 0.0))
        session_ny = float(features.get("session_ny", 0.0))
        if not (session_london or session_ny):
            return self._no_signal()

        # ATR with fallback
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        atr = float(features.get("atr_14") or 0.0)
        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        # Gate 3: proximity to Asian extreme
        close = float(df["close"].iloc[-1])
        dist_high = abs(close - asian_high) / atr
        dist_low = abs(close - asian_low) / atr
        near_high = dist_high <= self.proximity_atr_mult
        near_low = dist_low <= self.proximity_atr_mult

        if not (near_high or near_low):
            return self._no_signal()

        # If simultaneously near both (very tight Asian range), pick closer
        if near_high and near_low:
            near_high = dist_high <= dist_low
            near_low = not near_high

        direction = -1 if near_high else 1  # fade: near high → short, near low → long
        proximity_atr = dist_high if near_high else dist_low

        # SESS-03: At least one confirming factor
        supporting: list[str] = []

        trend_regime = float(features.get("trend_regime", 0.0))
        trend_aligns = (direction == -1 and trend_regime < -0.3) or (
            direction == 1 and trend_regime > 0.3
        )
        if trend_aligns:
            supporting.append("trend_align")

        vol = df["volume"].to_numpy(dtype=float)
        vol_mean = float(np.mean(vol[-21:-1])) if len(vol) > 21 else float(np.mean(vol[:-1]))
        vol_spike = vol_mean > 0 and vol[-1] > 1.5 * vol_mean
        if vol_spike:
            supporting.append("volume_spike")

        rsi = features.get("rsi_14")
        rsi_extreme = isinstance(rsi, (int, float)) and (
            (direction == -1 and rsi > 65) or (direction == 1 and rsi < 35)
        )
        if rsi_extreme:
            supporting.append("rsi_extreme")

        if not supporting:
            return self._no_signal()

        # Entry, stop, targets
        entry_price = asian_high if near_high else asian_low
        stop_loss = entry_price - direction * 1.5 * atr
        targets = [
            round(entry_price + direction * 1.0 * atr, 2),
            round(entry_price + direction * 2.0 * atr, 2),
            round(entry_price + direction * 3.0 * atr, 2),
        ]

        confidence = round(min(0.90, 0.45 + 0.15 * len(supporting)), 4)

        extreme = "high" if near_high else "low"
        side = "short" if direction == -1 else "long"
        signal_type = f"session_extreme_{extreme}_fade_{side}"
        if session_london and session_ny:
            session_ctx = "both"
        elif session_london:
            session_ctx = "london"
        else:
            session_ctx = "ny"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "bias": side,
            "proximity_atr": round(proximity_atr, 4),
            "confidence": confidence,
            "entry_type": "at_limit",
            "entry_price": round(entry_price, 2),
            "stop_loss": round(stop_loss, 2),
            "targets": targets,
            "regime_context": session_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = SessionExtremesSetupPlugin()
