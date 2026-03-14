"""trad_CHoCHReversal — Change of Character reversal evidence-contributor.

Gates on choch_detected==1.0 (SMC BOS/CHoCH plugin output).
Direction from choch_direction. Confidence boosted by HMM regime alignment.
Evidence contributor for CIS bucket scorer — Phase B input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class CHoCHReversalPlugin:
    """I7 evidence contributor: fires when CHoCH structure break detected.

    Gate: choch_detected == 1.0
    Direction: from choch_direction (-1 or +1)
    Confidence: 0.5 base + 0.2 if HMM regime aligns + 0.3 * abs(choch_direction)
    """

    name: str = "trad_CHoCHReversal"
    outputs: frozenset[str] = frozenset(
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
    capability_tags: frozenset[str] = frozenset({"trading", "smc", "structure", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=50),)
    regime_type: str = "any"
    atr_stop_multiplier: float = 1.5
    atr_target_multipliers: tuple = (2.0, 3.5, 5.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        choch_detected = float(features.get("choch_detected", 0.0))
        if choch_detected != 1.0:
            return self._no_signal()

        choch_direction = int(features.get("choch_direction", 0))
        if choch_direction == 0:
            return self._no_signal()

        hmm_regime = float(features.get("hmm_regime", 0.0))
        atr = float(features.get("atr_14", 0.0))

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        direction = choch_direction
        entry = float(close[-1])

        # Stop and targets
        if direction == 1:
            stop = entry - atr * self.atr_stop_multiplier
            targets = [round(entry + atr * m, 2) for m in self.atr_target_multipliers]
        else:
            stop = entry + atr * self.atr_stop_multiplier
            targets = [round(entry - atr * m, 2) for m in self.atr_target_multipliers]

        # Confidence: 0.5 base + 0.2 if HMM regime aligns + 0.3 * abs(direction)
        confidence = 0.5
        regime_ctx = "neutral"
        supporting = ["choch_detected"]

        if direction == 1 and hmm_regime == 1.0:
            # HMM says trending up — bullish CHoCH aligns
            confidence += 0.2
            regime_ctx = "bullish"
            supporting.append("hmm_regime_bullish")
        elif direction == -1 and hmm_regime == 2.0:
            # HMM says trending down — bearish CHoCH aligns
            confidence += 0.2
            regime_ctx = "bearish"
            supporting.append("hmm_regime_bearish")
        elif hmm_regime == 0.0:
            regime_ctx = "ranging"
        elif direction == 1:
            regime_ctx = "bullish"
        else:
            regime_ctx = "bearish"

        confidence += 0.3 * abs(direction)
        confidence = round(min(0.95, max(0.10, confidence)), 4)

        signal_type = "choch_reversal_long" if direction == 1 else "choch_reversal_short"

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


plugin = CHoCHReversalPlugin()
