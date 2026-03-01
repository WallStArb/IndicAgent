from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils import is_num


@dataclass
class MomentumContextPlugin:
    """Score overall momentum direction from multiple oscillators."""

    name: str = "ctx_MomentumContext"
    outputs: set[str] = frozenset(
        {"momentum_bias", "momentum_strength", "momentum_agreement", "momentum_n_signals"}
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"context"})
    inputs: list[InputSpec] = ()  # Consumes upstream feature dicts
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features")
        if not features:
            return {}

        scores: list[float] = []

        # RSI: centered at 50, maps to [-1, +1]
        rsi = features.get("rsi_14")
        if is_num(rsi):
            scores.append(max(-1.0, min(1.0, (rsi - 50) / 50)))

        # MACD vs signal: direction indicator
        macd = features.get("macd_12_26_9")
        signal = features.get("macd_signal_12_26_9")
        if is_num(macd) and is_num(signal):
            scores.append(1.0 if macd > signal else -1.0 if macd < signal else 0.0)

        # Stochastic %K: centered at 50
        stoch_k = features.get("stoch_k_14_3")
        if is_num(stoch_k):
            scores.append(max(-1.0, min(1.0, (stoch_k - 50) / 50)))

        # CCI: scaled by 200
        cci = features.get("cci_14")
        if is_num(cci):
            scores.append(max(-1.0, min(1.0, cci / 200)))

        if not scores:
            return {}

        momentum_bias = sum(scores) / len(scores)
        momentum_strength = abs(momentum_bias)

        # Agreement: fraction of signals matching the majority sign
        if momentum_bias == 0:
            momentum_agreement = 0.0
        else:
            majority_positive = momentum_bias > 0
            agreeing = sum(1 for s in scores if (s > 0) == majority_positive)
            momentum_agreement = agreeing / len(scores)

        return {
            "momentum_bias": round(momentum_bias, 4),
            "momentum_strength": round(momentum_strength, 4),
            "momentum_agreement": round(momentum_agreement, 4),
            "momentum_n_signals": float(len(scores)),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MomentumContextPlugin()
