"""trad_PatternCompletion — Chart pattern completion evidence-contributor.

Gates on any I5 pattern confidence > 0.5.
Checks dt_db (double top/bottom), hs (head and shoulders), then triangle.
Takes highest-confidence pattern if multiple fire.
Evidence contributor for CIS bucket scorer — Phase B input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class PatternCompletionPlugin:
    """I7 evidence contributor: fires when a high-confidence chart pattern completes.

    Gate: any pattern confidence > 0.5
    Priority: dt_db first, then hs, then triangle (take highest-confidence)
    Confidence: pattern_confidence * 0.9 (scale to signal-quality range)
    """

    name: str = "trad_PatternCompletion"
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
    capability_tags: frozenset[str] = frozenset({"trading", "pattern", "structure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "any"
    confidence_threshold: float = 0.5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = frames.get("features") or {}

        # Collect all candidate patterns
        candidates: list[tuple[float, int, str]] = []  # (confidence, direction, signal_name)

        dt_db_confidence = float(features.get("dt_db_confidence", 0.0))
        dt_db_pattern = int(features.get("dt_db_pattern", 0))
        if dt_db_confidence > self.confidence_threshold and dt_db_pattern in (1, 2):
            # 1=double_top (bearish), 2=double_bottom (bullish)
            direction = -1 if dt_db_pattern == 1 else 1
            pattern_name = "double_top" if dt_db_pattern == 1 else "double_bottom"
            candidates.append((dt_db_confidence, direction, pattern_name))

        hs_confidence = float(features.get("hs_confidence", 0.0))
        hs_pattern = int(features.get("hs_pattern", 0))
        if hs_confidence > self.confidence_threshold and hs_pattern in (1, 2):
            # 1=hs_top (bearish), 2=hs_bottom/inverted hs (bullish)
            direction = -1 if hs_pattern == 1 else 1
            pattern_name = "hs_top" if hs_pattern == 1 else "hs_bottom"
            candidates.append((hs_confidence, direction, pattern_name))

        tri_confidence = float(features.get("tri_confidence", 0.0))
        tri_breakout_bias = int(features.get("tri_breakout_bias", 0))
        if tri_confidence > self.confidence_threshold and tri_breakout_bias != 0:
            direction = int(tri_breakout_bias)
            candidates.append((tri_confidence, direction, "triangle"))

        if not candidates:
            return no_signal()

        # Take highest-confidence pattern
        best_confidence, direction, pattern_name = max(candidates, key=lambda x: x[0])

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        entry = float(close[-1])

        suffix = "long" if direction == 1 else "short"
        signal_type = f"pattern_{pattern_name}_{suffix}"
        tf = frame_trade(signal_type, direction, entry, features, atr)
        if not tf.viable:
            return no_signal()
        stop = tf.stop
        targets = [round(t.price, 2) for t in tf.targets]

        # Scale confidence to signal-quality range
        supporting = [pattern_name]
        if len(candidates) > 1:
            supporting.append("multiple_patterns")

        raw_conf = best_confidence * 0.9
        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        regime_ctx = "bullish" if direction == 1 else "bearish"

        return make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            confluence_score=0.0,
            supporting_factors=supporting,
            invalidation_conditions=[],
            features_snapshot=capture_signal_features(features, direction, "smc", confidence),
        )

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = PatternCompletionPlugin()
