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
from .atr_utils import get_atr
from .confidence_utils import capture_confluence_features, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .trade_framer import frame_trade

_SPIKE_THRESHOLD: float = 2.0


@dataclass
class OFISpikePlugin:
    """Any-regime setup: single-bar OFI exceeds 2 sigma.

    Stateless: reads pre-computed ofi_spike_z from I1.
    Gate: abs(ofi_spike_z) > 2.0
    Direction: sign of ofi_spike_z (positive = buy spike, negative = sell spike)
    Confidence: compose_confidence(0.50 + abs(ofi_spike_z) * 0.05)
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
            return no_signal()

        ofi_spike_z = features.get("ofi_spike_z")
        if ofi_spike_z is None:
            return no_signal()

        ofi_spike_z = float(ofi_spike_z)
        if abs(ofi_spike_z) <= _SPIKE_THRESHOLD:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        direction = 1 if ofi_spike_z > 0 else -1
        confidence = compose_confidence(0.50 + abs(ofi_spike_z) * 0.05)

        sig_type = signal_type_for_direction("ofi_spike", direction)
        tf = frame_trade(sig_type, direction, entry, features, atr)
        if not tf.viable:
            return no_signal()

        stop_loss = tf.stop
        targets = [t.price for t in tf.targets]

        hmm_regime = features.get("hmm_regime")
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"
        supporting: list[str] = [
            f"ofi_spike_z={ofi_spike_z:.3f}",
        ]

        # exhaustion: not applicable — spike/divergence signals are regime-independent;
        # Phase 49 will learn gate behavior from shadow data
        signal = {
            "signal_type": sig_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": float(stop_loss),
            "targets": [float(t) for t in targets],
            "confidence": confidence,
            "regime_context": regime_context,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_confluence_features(
            features, direction, "microstructure", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFISpikePlugin()
