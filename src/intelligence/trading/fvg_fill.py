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
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import deduplicate_event
from .trade_framer import frame_trade


@dataclass
class FVGFillPlugin:
    """I7 evidence contributor: fires when institutional FVG fill opportunity present.

    Gate: fvg_type != 0 AND fvg_open_count >= 1.0
    Direction: +1 if fvg_type == 1 (bull FVG), -1 if fvg_type == -1 (bear FVG)
    Confidence: 0.5 + 0.3 * min(1.0, fvg_open_count / 3.0)

    deduplicate_event: fires once per unique FVG zone (fvg_type, fvg_top, fvg_bottom).
    A new zone (different boundaries) fires immediately. Same zone re-fires after
    _DEDUP_MIN_BARS active-condition calls, handling a new fill attempt on an old zone.
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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "mean_reversion"
    requires_i6_confluence: bool = True
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }

        fvg_type = int(features.get("fvg_type", 0))
        fvg_open_count = float(features.get("fvg_open_count", 0.0))
        if fvg_type == 0 or fvg_open_count < 1.0:
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        direction = 1 if fvg_type == 1 else -1
        entry = float(close[-1])
        signal_type = signal_type_for_direction("fvg_fill", direction)
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

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

        ctf_fvg = float(features.get("ctf_fvg_alignment", 0.0))
        if ctf_fvg > 0.3:
            fvg_boost = 0.08 * min(1.0, ctf_fvg / 0.7)
            raw_conf += fvg_boost
            if fvg_boost > 0.04:
                supporting.append("multi_tf_fvg_aligned")

        ctf_ob = float(features.get("ctf_ob_alignment", 0.0))
        if ctf_ob > 0.3:
            ob_boost = 0.06 * min(1.0, ctf_ob / 0.7)
            raw_conf += ob_boost
            if ob_boost > 0.03:
                supporting.append("multi_tf_ob_aligned")

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        # deduplicate_event: one fire per unique FVG zone (type, top, bottom).
        # fvg_top/fvg_bottom are already rounded to 4dp by the upstream plugin.
        symbol = frames.get("__symbol__", "_")
        tf_key = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf_key}"
        event_id = (fvg_type, round(fvg_top, 4), round(fvg_bottom, 4))
        if not deduplicate_event(self._state, state_key, event_id):
            return no_signal()

        regime_ctx = "bullish" if direction == 1 else "bearish"
        signal = make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            supporting_factors=supporting,
        )
        signal["features_snapshot"] = capture_signal_features(
            features,
            direction,
            "smc",
            signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = FVGFillPlugin()
