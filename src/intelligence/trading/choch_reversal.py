"""trad_CHoCHReversal — Change of Character reversal evidence-contributor.

Gates on choch_detected==1.0 (SMC BOS/CHoCH plugin output).
Direction from choch_direction. Confidence boosted by HMM regime alignment.
Evidence contributor for CIS bucket scorer — Phase B input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "any"
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

        # Confidence: 0.5 base + continuous HMM regime alignment + 0.3 * abs(direction)
        raw_conf = 0.5
        regime_ctx = "neutral"
        supporting = ["choch_detected"]

        # Continuous HMM regime alignment (regime_type="any")
        up_w = hmm_regime_weight(features, "up")
        down_w = hmm_regime_weight(features, "down")
        if direction == 1:
            # Bullish CHoCH aligned with trending-up probability
            raw_conf += 0.2 * up_w
            supporting.append("hmm_regime_bullish")
        elif direction == -1:
            # Bearish CHoCH aligned with trending-down probability
            raw_conf += 0.2 * down_w
            supporting.append("hmm_regime_bearish")

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

        # I6 confluence: Cross-timeframe structure alignment (Renaissance principle)
        ctf_structure = float(features.get("ctf_structure_alignment", 0.0))
        if ctf_structure > 0.3:
            # Weight by magnitude: stronger multi-TF CHoCH/BOS alignment = higher confidence
            structure_boost = 0.08 * min(1.0, ctf_structure / 0.7)
            raw_conf += structure_boost
            if structure_boost > 0.04:
                supporting.append("multi_tf_structure_aligned")

        # I6 confluence: Cross-timeframe trend alignment
        ctf_trend = float(features.get("ctf_trend_alignment", 0.0))
        if ctf_trend > 0.3:
            # Weight by magnitude: trend direction agreement across TFs
            trend_boost = 0.06 * min(1.0, ctf_trend / 0.7)
            raw_conf += trend_boost
            if trend_boost > 0.03:
                supporting.append("multi_tf_trend_aligned")

        # I6 confluence: Overall cross-timeframe score (directional confirmation)
        ctf_score = float(features.get("ctf_score", 0.0))
        if abs(ctf_score) > 0.3 and math.copysign(1, ctf_score) == direction:
            # Weight by magnitude: stronger overall alignment
            overall_boost = 0.05 * min(1.0, abs(ctf_score) / 0.7)
            raw_conf += overall_boost
            if overall_boost > 0.03:
                supporting.append("ctf_directionally_aligned")

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

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


plugin = CHoCHReversalPlugin()
