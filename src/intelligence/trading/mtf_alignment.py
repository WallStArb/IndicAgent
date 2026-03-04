"""I7 Multi-Timeframe Alignment setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class MTFAlignmentPlugin:
    """MTF Alignment setup: fires when I6 cross-timeframe confluence score
    exceeds threshold and multiple timeframes agree.

    Gate: abs(ctf_score) > 0.7 AND ctf_timeframes_aligned >= 2.
    Wider stops and larger targets since multi-TF moves tend to extend.
    """

    name: str = "trad_MTFAlignment"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "multi_timeframe"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    regime_type: str = "trend"
    ctf_score_threshold: float = 0.7
    min_timeframes_aligned: int = 2
    atr_stop_multiplier: float = 2.0
    atr_target_multipliers: tuple = (2.0, 4.0, 6.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        ctf_score = features.get("ctf_score", 0.0)
        ctf_timeframes_aligned = features.get("ctf_timeframes_aligned", 0.0)
        atr = features.get("atr_14", 0.0)

        # Gate: score must exceed threshold AND multiple timeframes must agree
        if abs(ctf_score) <= self.ctf_score_threshold:
            return self._no_signal()
        if ctf_timeframes_aligned < self.min_timeframes_aligned:
            return self._no_signal()

        direction = 1 if ctf_score > 0 else -1

        close = df["close"].to_numpy(dtype=float)
        price = float(close[-1])
        low = df["low"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)

        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        entry = price
        if direction == 1:
            stop = entry - atr * self.atr_stop_multiplier
            targets = [round(entry + atr * m, 2) for m in self.atr_target_multipliers]
        else:
            stop = entry + atr * self.atr_stop_multiplier
            targets = [round(entry - atr * m, 2) for m in self.atr_target_multipliers]

        # Confidence directly from abs(ctf_score)
        confidence = round(min(1.0, max(0.0, abs(ctf_score))), 4)

        # Supporting factors
        supporting = [f"{int(ctf_timeframes_aligned)}_timeframes_aligned"]

        highest_tf = features.get("ctf_highest_aligned_tf", None)
        if highest_tf is not None:
            supporting.append(f"highest_tf_{int(highest_tf)}m")

        ctf_trend = features.get("ctf_trend_alignment", 0.0)
        if abs(ctf_trend) >= 0.5:
            supporting.append("trend_alignment_strong")

        ctf_structure = features.get("ctf_structure_alignment", 0.0)
        if abs(ctf_structure) >= 0.5:
            supporting.append("structure_alignment_strong")

        ctf_regime = features.get("ctf_regime_agreement", 0.0)
        if ctf_regime >= 0.5:
            supporting.append("regime_agreement_strong")

        signal_type = "mtf_alignment_long" if direction == 1 else "mtf_alignment_short"
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


plugin = MTFAlignmentPlugin()
