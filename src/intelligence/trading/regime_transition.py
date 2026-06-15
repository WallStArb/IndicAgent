"""trad_RegimeTransition — Regime change + CHoCH confirmation evidence-contributor.

Requires BOTH changepoint detection (BOCPD) AND CHoCH structure break for highest-conviction
regime transition signals. Changepoint probability alone or CHoCH alone is insufficient.
Evidence contributor for CIS bucket scorer — Phase B input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import compose_confidence
from .exhaustion_utils import apply_exhaustion_guard
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class RegimeTransitionPlugin:
    """I7 evidence contributor: fires when BOCPD changepoint + CHoCH confirm regime change.

    Gate: cp_probability > 0.5 AND choch_detected == 1.0
    Direction: from choch_direction (required alongside changepoint)
    Confidence: 0.5 * cp_probability + 0.3 if HMM indicates new trend + 0.2 * choch_detected
    """

    name: str = "trad_RegimeTransition"
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
    capability_tags: frozenset[str] = frozenset({"trading", "regime", "smc", "structure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "any"
    cp_threshold: float = 0.5
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        cp_min = (
            cfg.get_sync("threshold.regime_transition.cp_min", self.cp_threshold)
            if cfg
            else self.cp_threshold
        )
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

        cp_probability = float(features.get("cp_probability", 0.0))
        choch_detected = float(features.get("choch_detected", 0.0))

        # Gate: both changepoint AND CHoCH required
        if cp_probability <= cp_min or choch_detected != 1.0:
            return no_signal()

        choch_direction = int(features.get("choch_direction", 0))
        if choch_direction == 0:
            return no_signal()

        direction = choch_direction
        hmm_regime = float(features.get("hmm_regime", 0.0))
        hmm_prob_up = float(features.get("hmm_prob_trending_up", 0.0))
        hmm_prob_down = float(features.get("hmm_prob_trending_down", 0.0))

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        entry = float(close[-1])

        signal_type = signal_type_for_direction("regime_transition", direction)
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        # Confidence: 0.5 * cp_probability + 0.3 if HMM aligns + 0.2 * choch_detected
        raw_conf = 0.5 * cp_probability
        supporting = ["bocpd_changepoint", "choch_detected"]
        regime_ctx = "transitioning"

        # Check if HMM indicates new trend direction
        hmm_aligned = False
        if direction == 1 and (hmm_regime == 1.0 or hmm_prob_up > hmm_prob_down):
            hmm_aligned = True
            regime_ctx = "bullish_transition"
            supporting.append("hmm_trending_up")
        elif direction == -1 and (hmm_regime == 2.0 or hmm_prob_down > hmm_prob_up):
            hmm_aligned = True
            regime_ctx = "bearish_transition"
            supporting.append("hmm_trending_down")

        if hmm_aligned:
            raw_conf += 0.3

        raw_conf += 0.2 * choch_detected

        if cp_probability > 0.8:
            supporting.append("high_cp_probability")

        raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "cp_probability_score": round(min(1.0, cp_probability), 4),
            "hmm_aligned_score": round(1.0 if hmm_aligned else 0.0, 4),
            "choch_detected_score": round(float(choch_detected), 4),
        }

        confidence = compose_confidence(raw_conf)

        signal = make_signal_from_frame(
            tf,
            symbol=frames.get("__symbol__", ""),
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


plugin = RegimeTransitionPlugin()
