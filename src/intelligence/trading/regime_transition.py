"""trad_RegimeTransition — Regime change + CHoCH confirmation evidence-contributor.

Requires BOTH changepoint detection (BOCPD) AND CHoCH structure break for highest-conviction
regime transition signals. Changepoint probability alone or CHoCH alone is insufficient.
Evidence contributor for CIS bucket scorer — Phase B input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class RegimeTransitionPlugin:
    """I7 evidence contributor: fires when BOCPD changepoint + CHoCH confirm regime change.

    Gate: cp_probability > 0.5 AND choch_detected == 1.0
    Direction: from choch_direction (required alongside changepoint)
    Confidence: 0.5 * cp_probability + 0.3 if HMM indicates new trend + 0.2 * choch_detected
    """

    name: str = "trad_RegimeTransition"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "regime", "smc", "structure"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=50),)
    cp_threshold: float = 0.5
    atr_stop_multiplier: float = 1.5
    atr_target_multipliers: tuple = (2.0, 3.5, 5.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        cp_probability = float(features.get("cp_probability", 0.0))
        choch_detected = float(features.get("choch_detected", 0.0))

        # Gate: both changepoint AND CHoCH required
        if cp_probability <= self.cp_threshold or choch_detected != 1.0:
            return self._no_signal()

        choch_direction = int(features.get("choch_direction", 0))
        if choch_direction == 0:
            return self._no_signal()

        direction = choch_direction
        hmm_regime = float(features.get("hmm_regime", 0.0))
        hmm_prob_up = float(features.get("hmm_prob_trending_up", 0.0))
        hmm_prob_down = float(features.get("hmm_prob_trending_down", 0.0))

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        atr = float(features.get("atr_14", 0.0))
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

        # Confidence: 0.5 * cp_probability + 0.3 if HMM aligns + 0.2 * choch_detected
        confidence = 0.5 * cp_probability
        supporting = ["bocpd_changepoint", "choch_detected"]
        regime_ctx = "transitioning"

        # Check if HMM indicates new trend direction
        hmm_aligned = False
        if direction == 1 and (hmm_regime == 1.0 or hmm_prob_up > hmm_prob_down):
            hmm_aligned = True
            regime_ctx = "bullish_transition"
            supporting.append("hmm_trending_up")
        elif direction == -1 and (hmm_regime == 2.0 or hmm_prob_down > hmm_prob_up):
            hmm_aligned = True
            regime_ctx = "bearish_transition"
            supporting.append("hmm_trending_down")

        if hmm_aligned:
            confidence += 0.3

        confidence += 0.2 * choch_detected
        confidence = round(min(0.95, max(0.10, confidence)), 4)

        if cp_probability > 0.8:
            supporting.append("high_cp_probability")

        signal_type = "regime_transition_long" if direction == 1 else "regime_transition_short"

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


plugin = RegimeTransitionPlugin()
