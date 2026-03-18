"""trad_DeltaExhaustion — I7 mean-reversion setup consuming CVD I1 features.

Fires when a large CVD spike occurs but price fails to follow through.
This is the "exhaustion" pattern: informed buyers/sellers pushed volume but price
didn't respond, suggesting the aggressive side is exhausted and price will reverse.

Renaissance principles:
- Segment relentlessly: requires both CVD spike AND price failure (dual gate)
- Instrument everything: price_follow_ratio, cvd_spike_z all logged
- Earn the right through proof: price must fail to follow (< 0.3 ATR move)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..plugins import InputSpec

_SPIKE_Z_THRESHOLD: float = 1.5  # lower than OFI/CVD spike (1.5 vs 2.0 — captures more cases)
_PRICE_FOLLOW_THRESHOLD: float = 0.3  # price must move < 0.3 ATR for exhaustion


@dataclass
class DeltaExhaustionPlugin:
    """Mean-reversion setup: large CVD spike but price fails to follow through.

    Gates:
    - abs(cvd_spike_z) > 1.5 (significant CVD spike)
    - abs(price_change) < 0.3 * atr (price fails to follow CVD direction)

    Direction: opposite of CVD spike direction (exhaustion → reversal)
    Confidence: min(0.75, 0.45 + abs(cvd_spike_z) * 0.05 + (1.0 - price_follow_ratio) * 0.10)
    """

    name: str = "trad_DeltaExhaustion"
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
    capability_tags: frozenset[str] = frozenset({"trading", "exhaustion", "cvd", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "mean_reversion"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        cvd_spike_z = features.get("cvd_spike_z")
        if cvd_spike_z is None:
            return self._no_signal()

        cvd_spike_z = float(cvd_spike_z)
        if abs(cvd_spike_z) <= _SPIKE_Z_THRESHOLD:
            return self._no_signal()

        # ATR from features or fallback
        atr = features.get("atr_14")
        if atr is not None:
            atr = float(atr)
        else:
            high = df["high"].to_numpy(dtype=float)
            low = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high[-14:] - low[-14:]))

        if atr <= 0:
            return self._no_signal()

        # Price follow-through: compare current close to previous close
        close = df["close"].to_numpy(dtype=float)
        if len(close) < 2:
            return self._no_signal()

        entry = float(close[-1])
        prev_close = float(close[-2])
        price_change = abs(entry - prev_close)
        price_follow_ratio = price_change / atr

        # CVD direction: positive spike = buying pressure
        cvd_direction = 1 if cvd_spike_z > 0 else -1

        # Price failed to follow: price change is less than threshold
        if price_follow_ratio >= _PRICE_FOLLOW_THRESHOLD:
            return self._no_signal()

        # Also check: price moved in CVD direction (if it moved away from CVD, not exhaustion)
        price_dir = 1 if (entry - prev_close) > 0 else -1 if (entry - prev_close) < 0 else 0
        if price_dir == cvd_direction and price_follow_ratio >= 0.5:
            # Price moved significantly with CVD — not exhaustion
            return self._no_signal()

        # Exhaustion: opposite of CVD direction
        direction = -cvd_direction

        confidence = round(
            min(0.75, 0.45 + abs(cvd_spike_z) * 0.05 + (1.0 - price_follow_ratio) * 0.10),
            4,
        )

        signal_type = "delta_exhaustion_long" if direction == 1 else "delta_exhaustion_short"
        hmm_regime = features.get("hmm_regime")

        supporting: list[str] = [
            f"cvd_spike_z={cvd_spike_z:.3f}",
            f"price_follow_ratio={price_follow_ratio:.3f}",
            f"atr={atr:.2f}",
        ]

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": None,
            "targets": None,
            "confidence": confidence,
            "regime_context": {"hmm_regime": hmm_regime},
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = DeltaExhaustionPlugin()
