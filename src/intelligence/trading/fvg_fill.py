"""trad_FVGFill — Fair Value Gap fill-seeking evidence-contributor.

Gates on fvg_type != 0 AND fvg_open_count >= 1.0.
Direction: +1 for bull FVG (price seeks to fill upside gap), -1 for bear FVG.
Confidence scales with open FVG count — more open FVGs = stronger magnetic pull.
Evidence contributor for CIS bucket scorer — Phase B input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .trade_framer import frame_trade


@dataclass
class FVGFillPlugin:
    """I7 evidence contributor: fires when institutional FVG fill opportunity present.

    Gate: fvg_type != 0 AND fvg_open_count >= 1.0
    Direction: +1 if fvg_type == 1 (bull FVG), -1 if fvg_type == -1 (bear FVG)
    Confidence: 0.5 + 0.3 * min(1.0, fvg_open_count / 3.0)
    """

    name: str = "trad_FVGFill"
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
    capability_tags: frozenset[str] = frozenset({"trading", "smc", "fvg", "institutional"})
    # timeframe=".*" — InputSpec.timeframe is not enforced by the registry or service;
    # signal_generator_service passes current-TF OHLCV regardless. ".*" makes intent clear.
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=50),)
    regime_type: str = "mean_reversion"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = frames.get("features") or {}

        fvg_type = int(features.get("fvg_type", 0))
        fvg_open_count = float(features.get("fvg_open_count", 0.0))

        # Gate: must have an open FVG with at least 1 open gap
        if fvg_type == 0 or fvg_open_count < 1.0:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        direction = 1 if fvg_type == 1 else -1
        entry = float(close[-1])

        signal_type = signal_type_for_direction("fvg_fill", direction)
        tf = frame_trade(signal_type, direction, entry, features, atr)
        if not tf.viable:
            return no_signal()
        stop = tf.stop
        targets = [round(t.price, 2) for t in tf.targets]

        # Confidence: 0.5 base + 0.3 * min(1.0, open_count/3.0)
        magnetism = min(1.0, fvg_open_count / 3.0)
        raw_conf = 0.5 + 0.3 * magnetism

        supporting = ["fvg_detected"]
        if fvg_open_count >= 3.0:
            supporting.append("high_fvg_count")
        elif fvg_open_count >= 2.0:
            supporting.append("multiple_fvgs")

        fvg_top = float(features.get("fvg_top", 0.0))
        fvg_bottom = float(features.get("fvg_bottom", 0.0))
        if fvg_top > 0 and fvg_bottom > 0:
            supporting.append("fvg_bounds_present")

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        regime_ctx = "bullish" if direction == 1 else "bearish"

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
        signal["_shadow"] = capture_signal_features(
            features, direction, "smc", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = FVGFillPlugin()
