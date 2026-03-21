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
from .atr_utils import get_atr
from .confidence_utils import compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .trade_framer import frame_trade

_SPIKE_THRESHOLD: float = 2.0


@dataclass
class CVDSpikePlugin:
    """Any-regime setup: single-bar CVD exceeds 2 sigma.

    Stateless: reads pre-computed cvd_spike_z from I1.
    Gate: abs(cvd_spike_z) > 2.0
    Direction: sign of cvd_spike_z (positive = buy pressure spike, negative = sell)
    Confidence: compose_confidence(0.50 + abs(cvd_spike_z) * 0.05)

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
            return no_signal()

        cvd_spike_z = features.get("cvd_spike_z")
        if cvd_spike_z is None:
            return no_signal()

        cvd_spike_z = float(cvd_spike_z)
        if abs(cvd_spike_z) <= _SPIKE_THRESHOLD:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        direction = 1 if cvd_spike_z > 0 else -1
        confidence = compose_confidence(0.50 + abs(cvd_spike_z) * 0.05)

        sig_type = signal_type_for_direction("cvd_spike", direction)
        tf = frame_trade(sig_type, direction, entry, features, atr)
        if not tf.viable:
            return no_signal()

        stop_loss = tf.stop
        targets = [t.price for t in tf.targets]

        hmm_regime = features.get("hmm_regime")
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"
        supporting: list[str] = [
            f"cvd_spike_z={cvd_spike_z:.3f}",
        ]

        return {
            "signal_type": sig_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": float(stop_loss),
            "targets": [float(t) for t in targets],
            "confidence": confidence,
            "regime_context": regime_context,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CVDSpikePlugin()
