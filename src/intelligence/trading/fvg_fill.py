"""trad_FVGFill — Fair Value Gap fill-seeking evidence-contributor.

Gates on fvg_type != 0 AND fvg_open_count >= 1.0.
Direction: +1 for bull FVG (price seeks to fill upside gap), -1 for bear FVG.
Confidence scales with open FVG count — more open FVGs = stronger magnetic pull.
Evidence contributor for CIS bucket scorer — Phase B input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class FVGFillPlugin:
    """I7 evidence contributor: fires when institutional FVG fill opportunity present.

    Gate: fvg_type != 0 AND fvg_open_count >= 1.0
    Direction: +1 if fvg_type == 1 (bull FVG), -1 if fvg_type == -1 (bear FVG)
    Confidence: 0.5 + 0.3 * min(1.0, fvg_open_count / 3.0)
    """

    name: str = "trad_FVGFill"
    outputs: set[str] = frozenset(
        {
            "signal_type",
            "direction",
            "entry_price",
            "stop_loss",
            "targets",
            "confidence",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "smc", "fvg", "institutional"})
    # timeframe=".*" — InputSpec.timeframe is not enforced by the registry or service;
    # signal_generator_service passes current-TF OHLCV regardless. ".*" makes intent clear.
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=50),)
    regime_type: str = "mean_reversion"
    atr_stop_multiplier: float = 1.5
    atr_target_multipliers: tuple = (2.0, 3.5, 5.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        fvg_type = int(features.get("fvg_type", 0))
        fvg_open_count = float(features.get("fvg_open_count", 0.0))

        # Gate: must have an open FVG with at least 1 open gap
        if fvg_type == 0 or fvg_open_count < 1.0:
            return self._no_signal()

        atr = float(features.get("atr_14", 0.0))
        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        direction = 1 if fvg_type == 1 else -1
        entry = float(close[-1])

        # Stop and targets
        if direction == 1:
            stop = entry - atr * self.atr_stop_multiplier
            targets = [round(entry + atr * m, 2) for m in self.atr_target_multipliers]
        else:
            stop = entry + atr * self.atr_stop_multiplier
            targets = [round(entry - atr * m, 2) for m in self.atr_target_multipliers]

        # Confidence: 0.5 base + 0.3 * min(1.0, open_count/3.0)
        magnetism = min(1.0, fvg_open_count / 3.0)
        confidence = 0.5 + 0.3 * magnetism
        confidence = round(min(0.95, max(0.10, confidence)), 4)

        supporting = ["fvg_detected"]
        if fvg_open_count >= 3.0:
            supporting.append("high_fvg_count")
        elif fvg_open_count >= 2.0:
            supporting.append("multiple_fvgs")

        fvg_top = float(features.get("fvg_top", 0.0))
        fvg_bottom = float(features.get("fvg_bottom", 0.0))
        if fvg_top > 0 and fvg_bottom > 0:
            supporting.append("fvg_bounds_present")

        signal_type = "fvg_fill_long" if direction == 1 else "fvg_fill_short"
        regime_ctx = "bullish" if direction == 1 else "bearish"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = FVGFillPlugin()
