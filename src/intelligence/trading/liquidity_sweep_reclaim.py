"""I7 Liquidity Sweep Reclaim setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class LiquiditySweepReclaimPlugin:
    """Highest-conviction SMC setup: fires when a liquidity sweep is reclaimed.

    Gate: sweep_detected == 1.0 AND sweep_reclaimed == 1.0.
    Optional confidence boosts from FVG, order block, and cross-timeframe confluence.
    """

    name: str = "trad_LiquiditySweepReclaim"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "supporting_factors",
    })
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "smc", "sweep"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        sweep_detected = features.get("sweep_detected", 0.0)
        sweep_reclaimed = features.get("sweep_reclaimed", 0.0)

        if sweep_detected != 1.0 or sweep_reclaimed != 1.0:
            return self._no_signal()

        sweep_type = features.get("sweep_type", 0.0)
        sweep_level = features.get("sweep_level", 0.0)
        atr = features.get("atr_14", 0.0)

        if sweep_type == 0.0 or atr <= 0:
            return self._no_signal()

        direction = 1 if sweep_type > 0 else -1

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        entry = float(close[-1])

        # Fallback ATR if not provided
        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        # Stop loss
        if direction == 1:
            stop = sweep_level - atr * 0.5
        else:
            stop = sweep_level + atr * 0.5

        # Targets
        if direction == 1:
            t1 = entry + atr * 1.5
            t2 = entry + atr * 3.0
        else:
            t1 = entry - atr * 1.5
            t2 = entry - atr * 3.0
        targets = [round(t1, 2), round(t2, 2)]

        # Confidence scoring
        confidence = 0.55
        supporting = ["sweep_reclaimed"]

        fvg_detected = features.get("fvg_detected", 0.0)
        fvg_type = features.get("fvg_type", 0.0)
        if fvg_detected == 1.0 and fvg_type == float(direction):
            confidence += 0.15
            supporting.append("fvg_confirmed")

        ob_detected = features.get("ob_detected", 0.0)
        ob_type = features.get("ob_type", 0.0)
        if ob_detected == 1.0 and ob_type == float(direction):
            confidence += 0.10
            supporting.append("order_block_confirmed")

        ctf_score = features.get("ctf_score", 0.0)
        if abs(ctf_score) > 0.3:
            confidence += 0.05
            supporting.append("cross_timeframe_aligned")

        confidence = round(min(1.0, confidence), 4)

        signal_type = "sweep_reclaim_long" if direction == 1 else "sweep_reclaim_short"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = LiquiditySweepReclaimPlugin()
