"""trad_CHoCHReversal — Change of Character reversal evidence-contributor.

Gates on choch_detected==1.0 (SMC BOS/CHoCH plugin output).
Direction from choch_direction. Confidence from intrinsic pattern quality.
Evidence contributor for CIS bucket scorer — Phase B input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import compose_confidence
from .plugin_utils import (
    build_features_from_tiers,
    extract_ohlcv,
    no_signal,
    signal_type_for_direction,
)
from .signal_schema import make_signal_from_frame
from .state_utils import deduplicate_event
from .trade_framer import frame_trade


@dataclass
class CHoCHReversalPlugin:
    """I7 evidence contributor: fires when CHoCH structure break detected.

    Gate: choch_detected == 1.0
    Direction: from choch_direction (-1 or +1)

    deduplicate_event: fires once per unique (choch_direction, bos_level) identity.
    A new structural break at a different level fires immediately. Same break
    re-fires after _DEDUP_MIN_BARS active-condition calls.
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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "any"
    # Phase 126 IC audit: statistically anti-predictive on existing data
    # (IC=-0.014, hit_rate CI upper=0.221, n=38393); redesign required.
    shadow_only: bool = True
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = build_features_from_tiers(frames)

        choch_detected = float(features.get("choch_detected", 0.0))
        if choch_detected != 1.0:
            return no_signal()

        choch_direction = int(features.get("choch_direction", 0))
        if choch_direction == 0:
            return no_signal()

        hmm_regime = float(features.get("hmm_regime", 0.0))

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        direction = choch_direction
        entry = float(close[-1])
        signal_type = signal_type_for_direction("choch_reversal", direction)
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        raw_conf = 0.5
        regime_ctx = "neutral"
        supporting = ["choch_detected"]

        if hmm_regime == 0.0:
            regime_ctx = "ranging"
        elif hmm_regime == 1.0:
            regime_ctx = "bullish"
        elif hmm_regime == 2.0:
            regime_ctx = "bearish"
        elif direction == 1:
            regime_ctx = "bullish"
        else:
            regime_ctx = "bearish"

        raw_conf += 0.3 * abs(direction)

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "choch_strength": round(min(1.0, raw_conf), 4),
        }

        confidence = compose_confidence(raw_conf)

        # deduplicate_event: one fire per unique structural break identity.
        # bos_level changes when a new swing structure forms, distinguishing
        # genuinely new CHoCH events from persistent lookback echoes.
        symbol = frames.get("__symbol__", "_")
        tf_key = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf_key}"
        bos_level = round(float(features.get("bos_level", 0.0)), 4)
        event_id = (choch_direction, bos_level)
        if not deduplicate_event(self._state, state_key, event_id):
            return no_signal()

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
            factor_scores=factor_scores,
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CHoCHReversalPlugin()
