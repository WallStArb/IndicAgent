"""trad_CVDSpike — I7 any-regime setup consuming CVD I1 features.

Fires when a single-bar CVD exceeds 2 sigma above the rolling mean.
Symmetric with trad_OFISpike but based on Cumulative Volume Delta.
Stateless: reads pre-computed cvd_spike_z from I1 CVDPlugin.

Renaissance principles:
- Instrument everything: z-score magnitude logged
- Segment relentlessly: fires in any regime (microstructure signal is regime-agnostic)
- Degrade gracefully: missing cvd_spike_z → no signal
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec

_SPIKE_THRESHOLD: float = 2.0


@dataclass
class CVDSpikePlugin:
    """Any-regime setup: single-bar CVD exceeds 2 sigma.

    Stateless: reads pre-computed cvd_spike_z from I1.
    Gate: abs(cvd_spike_z) > 2.0
    Direction: sign of cvd_spike_z (positive = buy pressure spike, negative = sell)
    Confidence: min(0.80, 0.50 + abs(cvd_spike_z) * 0.05)

    Symmetric with trad_OFISpike.
    """

    name: str = "trad_CVDSpike"
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
    capability_tags: frozenset[str] = frozenset({"trading", "spike", "cvd"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "any"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        cvd_spike_z = features.get("cvd_spike_z")
        if cvd_spike_z is None:
            return self._no_signal()

        cvd_spike_z = float(cvd_spike_z)
        if abs(cvd_spike_z) <= _SPIKE_THRESHOLD:
            return self._no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        direction = 1 if cvd_spike_z > 0 else -1
        confidence = round(min(0.80, 0.50 + abs(cvd_spike_z) * 0.05), 4)

        signal_type = "cvd_spike_long" if direction == 1 else "cvd_spike_short"

        hmm_regime = features.get("hmm_regime")
        supporting: list[str] = [
            f"cvd_spike_z={cvd_spike_z:.3f}",
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


plugin = CVDSpikePlugin()
