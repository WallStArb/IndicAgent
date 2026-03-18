"""trad_OFISpike — I7 any-regime setup consuming OFI I1 features.

Fires when a single-bar OFI exceeds 2 sigma above the rolling mean.
Stateless: reads pre-computed ofi_spike_z from I1 OFIPlugin.

Renaissance principles:
- Instrument everything: z-score magnitude logged
- Segment relentlessly: fires in any regime (microstructure signal is regime-agnostic)
- Degrade gracefully: missing ofi_spike_z → no signal (don't estimate)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec

_SPIKE_THRESHOLD: float = 2.0


@dataclass
class OFISpikePlugin:
    """Any-regime setup: single-bar OFI exceeds 2 sigma.

    Stateless: reads pre-computed ofi_spike_z from I1.
    Gate: abs(ofi_spike_z) > 2.0
    Direction: sign of ofi_spike_z (positive = buy spike, negative = sell spike)
    Confidence: min(0.80, 0.50 + abs(ofi_spike_z) * 0.05)
    """

    name: str = "trad_OFISpike"
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
    capability_tags: frozenset[str] = frozenset({"trading", "spike", "ofi"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "any"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        ofi_spike_z = features.get("ofi_spike_z")
        if ofi_spike_z is None:
            return self._no_signal()

        ofi_spike_z = float(ofi_spike_z)
        if abs(ofi_spike_z) <= _SPIKE_THRESHOLD:
            return self._no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        direction = 1 if ofi_spike_z > 0 else -1
        confidence = round(min(0.80, 0.50 + abs(ofi_spike_z) * 0.05), 4)

        signal_type = "ofi_spike_long" if direction == 1 else "ofi_spike_short"

        hmm_regime = features.get("hmm_regime")
        supporting: list[str] = [
            f"ofi_spike_z={ofi_spike_z:.3f}",
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


plugin = OFISpikePlugin()
