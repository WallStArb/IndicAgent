"""trad_CHoCHReversal — Change of Character reversal evidence-contributor.

Gates on choch_detected==1.0 (SMC BOS/CHoCH plugin output).
Direction from choch_direction. Confidence boosted by HMM regime alignment.
Evidence contributor for CIS bucket scorer — Phase B input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_confluence_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .trade_framer import frame_trade


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
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = frames.get("features") or {}

        choch_detected = float(features.get("choch_detected", 0.0))
        if choch_detected != 1.0:
            return no_signal()

        choch_direction = int(features.get("choch_direction", 0))
        if choch_direction == 0:
            return no_signal()

        hmm_regime = float(features.get("hmm_regime", 0.0))

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        direction = choch_direction
        entry = float(close[-1])

        signal_type = signal_type_for_direction("choch_reversal", direction)
        tf = frame_trade(signal_type, direction, entry, features, atr)
        if not tf.viable:
            return no_signal()
        stop = tf.stop
        targets = [round(t.price, 2) for t in tf.targets]

        # Confidence: 0.5 base + 0.2 if HMM regime aligns + 0.3 * abs(direction)
        raw_conf = 0.5
        regime_ctx = "neutral"
        supporting = ["choch_detected"]

        if direction == 1 and hmm_regime == 1.0:
            # HMM says trending up — bullish CHoCH aligns
            raw_conf += 0.2
            regime_ctx = "bullish"
            supporting.append("hmm_regime_bullish")
        elif direction == -1 and hmm_regime == 2.0:
            # HMM says trending down — bearish CHoCH aligns
            raw_conf += 0.2
            regime_ctx = "bearish"
            supporting.append("hmm_regime_bearish")
        elif hmm_regime == 0.0:
            regime_ctx = "ranging"
        elif direction == 1:
            regime_ctx = "bullish"
        else:
            regime_ctx = "bearish"

        raw_conf += 0.3 * abs(direction)
        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        signal = {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_confluence_features(
            features, direction, "smc", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CHoCHReversalPlugin()
