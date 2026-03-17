"""trad_DivergenceStack -- 5-input weighted divergence convergence score.

Replaces the 2-input AND-gate with a weighted score across 5 divergence sources:
RSI (0.30), MACD (0.25), Volume/OBV (0.20), OBV (0.15), CMF (0.10).

Gate: score > DIVERGENCE_SCORE_THRESHOLD AND n_agreeing >= DIVERGENCE_MIN_AGREEING.

Always-log: div_weighted_score, div_n_agreeing, per-input scores, age_bars, magnitudes
are returned on EVERY bar regardless of whether a signal fires. These flow to
intelligence_features.i7 JSONB via _build_i7_payload() in signal_generator_service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec

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


@dataclass
class DivergenceStackPlugin:
    """I7 evidence contributor: fires when weighted divergence score exceeds gate.

    5-input weighted convergence: RSI (0.30) + MACD (0.25) + vol (0.20) + OBV (0.15) + CMF (0.10).
    Gate: score > 0.40 AND n_agreeing >= 3.
    Always logs: div_weighted_score, div_n_agreeing, per-input scores, age_bars, magnitudes.
    """

    name: str = "trad_DivergenceStack"
    regime_type: str = "any"
    outputs: frozenset[str] = frozenset(
        {
            # Signal fields
            "signal_type",
            "direction",
            "confidence",
            "supporting_factors",
            "entry_price",
            "targets",
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
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"signal", "divergence"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < 20:
            return {}

        symbol = frames.get("symbol", "_")
        timeframe = frames.get("timeframe", "_")
        state_key = (symbol, timeframe)
        if state_key not in self._state:
            self._state[state_key] = {}

        # Read all 5 divergence input pairs from features dict (I5 outputs)
        inputs_map: dict[str, tuple[float, float]] = {
            "rsi": (float(features.get("rsi_div_bullish") or 0), float(features.get("rsi_div_bearish") or 0)),
            "macd": (float(features.get("macd_div_bullish") or 0), float(features.get("macd_div_bearish") or 0)),
            "vol": (float(features.get("vol_div_bullish") or 0), float(features.get("vol_div_bearish") or 0)),
            "obv": (float(features.get("obv_div_bullish") or 0), float(features.get("obv_div_bearish") or 0)),
            "cmf": (float(features.get("cmf_div_bullish") or 0), float(features.get("cmf_div_bearish") or 0)),
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
        weighted_score = sum(
            DIVERGENCE_WEIGHTS[name] * score for name, score in per_input_scores.items()
        )

        # Update divergence age tracking in state
        state = self._state[state_key]
        for name, score in per_input_scores.items():
            age_key = f"{name}_age"
            if score > 0:
                state[age_key] = state.get(age_key, 0) + 1
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
        if weighted_score > DIVERGENCE_SCORE_THRESHOLD and n_agreeing >= DIVERGENCE_MIN_AGREEING:
            # Determine overall direction from majority of agreeing inputs (weighted)
            bull_weight = sum(
                DIVERGENCE_WEIGHTS[name]
                for name, d in per_input_direction.items()
                if d == 1 and per_input_scores[name] > 0
            )
            bear_weight = sum(
                DIVERGENCE_WEIGHTS[name]
                for name, d in per_input_direction.items()
                if d == -1 and per_input_scores[name] > 0
            )

            if bull_weight >= bear_weight:
                direction = 1
                direction_str = "long"
            else:
                direction = -1
                direction_str = "short"

            # Confidence proportional to weighted_score
            confidence = round(min(1.0, weighted_score / 0.60), 4)

            supporting = [
                name
                for name, s in per_input_scores.items()
                if s > 0
            ]
            supporting_factors = [f"div_{name}" for name in supporting]

            entry = float(df["close"].iloc[-1])

            return {
                **base_output,
                "signal_type": f"divergence_{direction_str}",
                "direction": direction,
                "confidence": confidence,
                "supporting_factors": supporting_factors,
                "entry_price": round(entry, 2),
                "targets": [],
                "ttl_bars": 10,
            }

        # No signal — return base_output with neutral signal fields
        return {
            **base_output,
            "signal_type": "none",
            "direction": 0,
            "confidence": 0.0,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = DivergenceStackPlugin()
