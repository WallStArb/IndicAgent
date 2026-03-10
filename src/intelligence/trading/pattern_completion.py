"""trad_PatternCompletion — Chart pattern completion evidence-contributor.

Gates on any I5 pattern confidence > 0.5.
Checks dt_db (double top/bottom), hs (head and shoulders), then triangle.
Takes highest-confidence pattern if multiple fire.
Evidence contributor for CIS bucket scorer — Phase B input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class PatternCompletionPlugin:
    """I7 evidence contributor: fires when a high-confidence chart pattern completes.

    Gate: any pattern confidence > 0.5
    Priority: dt_db first, then hs, then triangle (take highest-confidence)
    Confidence: pattern_confidence * 0.9 (scale to signal-quality range)
    """

    name: str = "trad_PatternCompletion"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "pattern", "structure"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe=".*", lookback=50),)
    regime_type: str = "any"
    confidence_threshold: float = 0.5
    atr_stop_multiplier: float = 1.5
    atr_target_multipliers: tuple = (2.0, 3.5, 5.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        # Collect all candidate patterns
        candidates: list[tuple[float, int, str]] = []  # (confidence, direction, signal_name)

        dt_db_confidence = float(features.get("dt_db_confidence", 0.0))
        dt_db_pattern = int(features.get("dt_db_pattern", 0))
        if dt_db_confidence > self.confidence_threshold and dt_db_pattern in (1, 2):
            # 1=double_top (bearish), 2=double_bottom (bullish)
            direction = -1 if dt_db_pattern == 1 else 1
            pattern_name = "double_top" if dt_db_pattern == 1 else "double_bottom"
            candidates.append((dt_db_confidence, direction, pattern_name))

        hs_confidence = float(features.get("hs_confidence", 0.0))
        hs_pattern = int(features.get("hs_pattern", 0))
        if hs_confidence > self.confidence_threshold and hs_pattern in (1, 2):
            # 1=hs_top (bearish), 2=hs_bottom/inverted hs (bullish)
            direction = -1 if hs_pattern == 1 else 1
            pattern_name = "hs_top" if hs_pattern == 1 else "hs_bottom"
            candidates.append((hs_confidence, direction, pattern_name))

        tri_confidence = float(features.get("tri_confidence", 0.0))
        tri_breakout_bias = int(features.get("tri_breakout_bias", 0))
        if tri_confidence > self.confidence_threshold and tri_breakout_bias != 0:
            direction = int(tri_breakout_bias)
            candidates.append((tri_confidence, direction, "triangle"))

        if not candidates:
            return self._no_signal()

        # Take highest-confidence pattern
        best_confidence, direction, pattern_name = max(candidates, key=lambda x: x[0])

        atr = float(features.get("atr_14", 0.0))
        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        entry = float(close[-1])

        # Stop and targets
        if direction == 1:
            stop = entry - atr * self.atr_stop_multiplier
            targets = [round(entry + atr * m, 2) for m in self.atr_target_multipliers]
        else:
            stop = entry + atr * self.atr_stop_multiplier
            targets = [round(entry - atr * m, 2) for m in self.atr_target_multipliers]

        # Scale confidence to signal-quality range
        confidence = round(min(0.95, max(0.10, best_confidence * 0.9)), 4)

        supporting = [pattern_name]
        if len(candidates) > 1:
            supporting.append("multiple_patterns")

        suffix = "long" if direction == 1 else "short"
        signal_type = f"pattern_{pattern_name}_{suffix}"
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


plugin = PatternCompletionPlugin()
