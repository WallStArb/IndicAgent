"""trad_DivergenceStack — Dual momentum+volume divergence stack evidence-contributor.

LOCKED DESIGN: Both RSI and volume divergences must agree (dual-gate is non-negotiable).
Single divergence alone is insufficient — requires convergence of momentum + volume evidence.
Evidence contributor for CIS bucket scorer — Phase B input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class DivergenceStackPlugin:
    """I7 evidence contributor: fires when RSI AND volume divergences stack in same direction.

    Gate (long):  rsi_div_bullish > 0.3 AND vol_div_bullish > 0.3
    Gate (short): rsi_div_bearish > 0.3 AND vol_div_bearish > 0.3
    LOCKED: Single divergence returns _no_signal() — both must agree.
    Confidence: 0.4 * rsi_conf + 0.4 * vol_conf + 0.2 (base)
    """

    name: str = "trad_DivergenceStack"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "momentum", "divergence"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=50),)
    divergence_threshold: float = 0.3
    atr_stop_multiplier: float = 1.5
    atr_target_multipliers: tuple = (2.0, 3.5, 5.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        rsi_bull = float(features.get("rsi_div_bullish", 0.0))
        vol_bull = float(features.get("vol_div_bullish", 0.0))
        rsi_bear = float(features.get("rsi_div_bearish", 0.0))
        vol_bear = float(features.get("vol_div_bearish", 0.0))

        thr = self.divergence_threshold

        # Dual-gate: both RSI and volume must agree
        bullish_gate = rsi_bull > thr and vol_bull > thr
        bearish_gate = rsi_bear > thr and vol_bear > thr

        if not bullish_gate and not bearish_gate:
            return self._no_signal()

        # If both somehow fire, take the stronger stack
        if bullish_gate and bearish_gate:
            bull_stack = rsi_bull + vol_bull
            bear_stack = rsi_bear + vol_bear
            if bear_stack >= bull_stack:
                bullish_gate = False
            else:
                bearish_gate = False

        if bullish_gate:
            direction = 1
            rsi_conf = rsi_bull
            vol_conf = vol_bull
        else:
            direction = -1
            rsi_conf = rsi_bear
            vol_conf = vol_bear

        # Get price info for entry/stop/targets
        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        atr = float(features.get("atr_14", 0.0))
        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        entry = float(close[-1])

        if direction == 1:
            stop = entry - atr * self.atr_stop_multiplier
            targets = [round(entry + atr * m, 2) for m in self.atr_target_multipliers]
        else:
            stop = entry + atr * self.atr_stop_multiplier
            targets = [round(entry - atr * m, 2) for m in self.atr_target_multipliers]

        # Confidence: 0.4 * rsi + 0.4 * vol + 0.2 base
        confidence = round(min(0.95, max(0.10, 0.4 * rsi_conf + 0.4 * vol_conf + 0.2)), 4)

        supporting = ["rsi_divergence", "volume_divergence"]
        if rsi_conf > 0.6 and vol_conf > 0.6:
            supporting.append("strong_dual_divergence")

        signal_type = "divergence_stack_long" if direction == 1 else "divergence_stack_short"
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


plugin = DivergenceStackPlugin()
