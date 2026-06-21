"""trad_DivergenceStack -- 5-input weighted divergence convergence score.

Replaces the 2-input AND-gate with a weighted score across 5 divergence sources:
RSI (0.30), MACD (0.25), Volume/OBV (0.20), OBV (0.15), CMF (0.10).

Gate: score > DIVERGENCE_SCORE_THRESHOLD AND n_agreeing >= DIVERGENCE_MIN_AGREEING.

Always-log: div_weighted_score, div_n_agreeing, per-input scores, age_bars, magnitudes
are returned on EVERY bar regardless of whether a signal fires. These flow to
intelligence_features.i7 JSONB via the DAG winner pipeline in signal_generator_service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import clamp01, compose_confidence
from .plugin_utils import (
    build_features_from_tiers,
    default_compute_next,
    no_signal,
    signal_type_for_direction,
)
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

# ---------------------------------------------------------------------------
# Tunable weight configuration -- module-level for hot-reload without deploy
# ---------------------------------------------------------------------------

DIVERGENCE_WEIGHTS: dict[str, float] = {
    "rsi": 0.30,
    "macd": 0.25,
    "vol": 0.20,
    "obv": 0.15,
    "cmf": 0.10,
}

DIVERGENCE_SCORE_THRESHOLD: float = 0.40
DIVERGENCE_MIN_AGREEING: int = 3
# Normalization denominator: expected max score when top-3 inputs all fire at 1.0
# (0.30 + 0.25 + 0.20 = 0.75 theoretical max, but 0.60 used as practical 3-signal max)
DIVERGENCE_CONFIDENCE_NORM: float = 0.60


@dataclass
class DivergenceStackPlugin:
    """I7 evidence contributor: fires when weighted divergence score exceeds gate.

    5-input weighted convergence: RSI (0.30) + MACD (0.25) + vol (0.20) + OBV (0.15) + CMF (0.10).
    Gate: score > 0.40 AND n_agreeing >= 3.
    Always logs: div_weighted_score, div_n_agreeing, per-input scores, age_bars, magnitudes.
    """

    name: str = "trad_DivergenceStack"
    shadow_only: bool = True
    regime_type: str = "any"
    outputs: frozenset[str] = frozenset(
        {
            # Signal fields
            "signal_type",
            "direction",
            "confidence",
            "supporting_factors",
            "entry_price",
            "stop_loss",
            "targets",
            "regime_context",
            "ttl_bars",
            # Always-logged scoring fields
            "div_weighted_score",
            "div_n_agreeing",
            # Per-input scores (always logged)
            "rsi_div_score",
            "macd_div_score",
            "vol_div_score",
            "obv_div_score",
            "cmf_div_score",
            # Per-input age bars (always logged)
            "rsi_divergence_age_bars",
            "macd_divergence_age_bars",
            "vol_divergence_age_bars",
            "obv_divergence_age_bars",
            "cmf_divergence_age_bars",
            # Per-input magnitude/strength (always logged)
            "rsi_divergence_magnitude",
            "macd_divergence_magnitude",
            "vol_divergence_magnitude",
            "obv_divergence_magnitude",
            "cmf_divergence_magnitude",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"signal", "divergence"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = build_features_from_tiers(frames)
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        cfg = self._config_service
        score_threshold = (
            cfg.get_sync("threshold.divergence_stack.score_threshold", DIVERGENCE_SCORE_THRESHOLD)
            if cfg
            else DIVERGENCE_SCORE_THRESHOLD
        )
        min_agreeing = (
            int(cfg.get_sync("feature.divergence_stack.min_agreeing", DIVERGENCE_MIN_AGREEING))
            if cfg
            else DIVERGENCE_MIN_AGREEING
        )
        confidence_norm = (
            cfg.get_sync("feature.divergence_stack.confidence_norm", DIVERGENCE_CONFIDENCE_NORM)
            if cfg
            else DIVERGENCE_CONFIDENCE_NORM
        )
        weights = {
            k: (
                cfg.get_sync(f"weights.divergence_stack.{k}", DIVERGENCE_WEIGHTS[k])
                if cfg
                else DIVERGENCE_WEIGHTS[k]
            )
            for k in DIVERGENCE_WEIGHTS
        }

        symbol = frames.get("symbol", "_")
        timeframe = frames.get("timeframe", "_")
        state_key = (symbol, timeframe)
        state = self._state.setdefault(state_key, {})

        # Read all 5 divergence input pairs from features dict (I5 outputs)
        inputs_map: dict[str, tuple[float, float]] = {
            "rsi": (
                float(features.get("rsi_div_bullish") or 0),
                float(features.get("rsi_div_bearish") or 0),
            ),
            "macd": (
                float(features.get("macd_div_bullish") or 0),
                float(features.get("macd_div_bearish") or 0),
            ),
            "vol": (
                float(features.get("vol_div_bullish") or 0),
                float(features.get("vol_div_bearish") or 0),
            ),
            "obv": (
                float(features.get("obv_div_bullish") or 0),
                float(features.get("obv_div_bearish") or 0),
            ),
            "cmf": (
                float(features.get("cmf_div_bullish") or 0),
                float(features.get("cmf_div_bearish") or 0),
            ),
        }

        # Per-input scores: max(bullish, bearish) — divergence presence score
        per_input_scores: dict[str, float] = {}
        per_input_direction: dict[str, int] = {}
        for name, (bull, bear) in inputs_map.items():
            score = max(bull, bear)
            per_input_scores[name] = score
            if bull > bear:
                per_input_direction[name] = 1
            elif bear > bull:
                per_input_direction[name] = -1
            else:
                per_input_direction[name] = 0

        # n_agreeing: inputs with score > 0
        n_agreeing = sum(1 for s in per_input_scores.values() if s > 0)

        # Weighted score
        weighted_score = sum(weights[name] * score for name, score in per_input_scores.items())

        # Update divergence age tracking in state; collect active ages in the same pass
        active_ages: list[int] = []
        for name, score in per_input_scores.items():
            age_key = f"{name}_age"
            if score > 0:
                state[age_key] = state.get(age_key, 0) + 1
                active_ages.append(state[age_key])
            else:
                state[age_key] = 0

        # Strength magnitudes from I5 feature values
        base_output: dict[str, Any] = {
            "div_weighted_score": round(weighted_score, 4),
            "div_n_agreeing": n_agreeing,
            "rsi_div_score": round(per_input_scores["rsi"], 4),
            "macd_div_score": round(per_input_scores["macd"], 4),
            "vol_div_score": round(per_input_scores["vol"], 4),
            "obv_div_score": round(per_input_scores["obv"], 4),
            "cmf_div_score": round(per_input_scores["cmf"], 4),
            # Per-input age bars
            "rsi_divergence_age_bars": state.get("rsi_age", 0),
            "macd_divergence_age_bars": state.get("macd_age", 0),
            "vol_divergence_age_bars": state.get("vol_age", 0),
            "obv_divergence_age_bars": state.get("obv_age", 0),
            "cmf_divergence_age_bars": state.get("cmf_age", 0),
            # Per-input magnitude (strength values from I5)
            "rsi_divergence_magnitude": float(features.get("rsi_div_strength") or 0),
            "macd_divergence_magnitude": float(features.get("macd_div_strength") or 0),
            "vol_divergence_magnitude": float(features.get("vol_div_strength") or 0),
            "obv_divergence_magnitude": float(features.get("obv_div_strength") or 0),
            "cmf_divergence_magnitude": float(features.get("cmf_div_strength") or 0),
        }

        # Gate: score > threshold AND n_agreeing >= min_agreeing
        if weighted_score > score_threshold and n_agreeing >= min_agreeing:
            # Determine overall direction from majority of agreeing inputs (weighted)
            bull_weight = sum(
                weights[name]
                for name, d in per_input_direction.items()
                if d == 1 and per_input_scores[name] > 0
            )
            bear_weight = sum(
                weights[name]
                for name, d in per_input_direction.items()
                if d == -1 and per_input_scores[name] > 0
            )

            if bull_weight >= bear_weight:
                direction = 1
            else:
                direction = -1

            atr = get_atr_with_floor_from_frames(frames)
            if atr is None:
                return {
                    **base_output,
                    "signal_type": "none",
                    "direction": 0,
                    "confidence": 0.0,
                    "supporting_factors": [],
                }

            entry = float(df["close"].iloc[-1])
            signal_type = signal_type_for_direction("divergence_stack", direction)
            tf = frame_trade(
                signal_type, direction, entry, features, atr, regime_type=self.regime_type
            )
            if not tf.viable:
                return {
                    **base_output,
                    "signal_type": "none",
                    "direction": 0,
                    "confidence": 0.0,
                    "supporting_factors": [],
                }

            supporting = [name for name, s in per_input_scores.items() if s > 0]
            supporting_factors = [f"div_{name}" for name in supporting]

            # 4-factor intrinsic composite — each factor clamped [0, 1] before weighting.
            # Weights: 0.40 + 0.25 + 0.20 + 0.15 = 1.00 exactly.

            # Factor 1 — base weighted score (normalized by practical 3-signal max)
            base_score = clamp01(weighted_score / confidence_norm)

            # Factor 2 — direction purity (1.0 = unanimous, 0.5 = perfectly split)
            total_active_weight = bull_weight + bear_weight
            purity_score = (
                clamp01(max(bull_weight, bear_weight) / total_active_weight)
                if total_active_weight > 0
                else 0.5
            )

            # Factor 3 — breadth: how many inputs agree beyond the minimum gate
            breadth_range = 5 - min_agreeing
            breadth_score = (
                clamp01((n_agreeing - min_agreeing) / breadth_range) if breadth_range > 0 else 1.0
            )

            # Factor 4 — freshness persistence: most-recently-confirmed active component.
            # Freshness, not max-age — a stale stack (all inputs aging out) is lower quality
            # than one with a component just confirmed this bar. We invert the MINIMUM age so
            # that a freshly-confirmed input (min_age small) scores high.
            # active_ages was accumulated in the age-tracking loop above.
            if active_ages:
                persistence_score = clamp01(1.0 - min(active_ages) / 10.0)
            else:
                persistence_score = 0.5

            raw_div_conf = (
                0.40 * base_score
                + 0.25 * purity_score
                + 0.20 * breadth_score
                + 0.15 * persistence_score
            )

            # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
            factor_scores = {
                "base_score": round(base_score, 4),
                "purity_score": round(purity_score, 4),
                "breadth_score": round(breadth_score, 4),
                "persistence_score": round(persistence_score, 4),
            }

            confidence = compose_confidence(raw_div_conf)

            signal = make_signal_from_frame(
                tf,
                symbol=frames.get("symbol", ""),
                timeframe=features.get("timeframe", ""),
                timestamp=features.get("timestamp", ""),
                signal_type=signal_type,
                setup_plugin="trad_DivergenceStack",
                direction=direction,
                confidence=confidence,
                regime_context="any",
                supporting_factors=supporting_factors,
                factor_scores=factor_scores,
            )
            # Merge always-logged scoring fields on top of the framed signal
            signal.update(base_output)
            return signal

        # No signal — return base_output with neutral signal fields
        return {
            **base_output,
            "signal_type": "none",
            "direction": 0,
            "confidence": 0.0,
            "supporting_factors": [],
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return default_compute_next(self, windows)


plugin = DivergenceStackPlugin()
