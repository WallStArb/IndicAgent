"""SwarmAggregator — combines AgentResult lists into a final AlphaMultiplier.

Path A (deterministic) and Path B (LLM) are aggregated separately,
then combined with a discount factor on Path B confidence.
production_multiplier is conservatively clamped to [0.7, 1.3] for safety.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from src.intelligence.schemas import AgentResult, AlphaMultiplier

_PRODUCTION_CLAMP_LOW = 0.7
_PRODUCTION_CLAMP_HIGH = 1.3
_NEUTRAL = 1.0
_PATH_B_DISCOUNT = 0.3


def _weighted_mean(results: list[AgentResult]) -> float:
    """Confidence-weighted mean multiplier. Returns 1.0 for empty list."""
    if not results:
        return _NEUTRAL
    total_weight = sum(r.confidence for r in results)
    if total_weight == 0.0:
        return _NEUTRAL
    return sum(r.multiplier * r.confidence for r in results) / total_weight


class SwarmAggregator:
    """Combine Path A + Path B AgentResult lists into AlphaMultiplier."""

    def aggregate(
        self,
        signal_id: UUID,
        symbol: str,
        timeframe: str,
        ts: datetime,
        path_a_results: list[AgentResult],
        path_b_results: list[AgentResult],
    ) -> AlphaMultiplier:
        path_a_mult = _weighted_mean(path_a_results) if path_a_results else None
        path_b_mult = _weighted_mean(path_b_results) if path_b_results else None

        # Combine paths — Path B discounted
        components = []
        weights = []
        if path_a_results:
            components.append(path_a_mult)
            a_weight = sum(r.confidence for r in path_a_results)
            weights.append(a_weight)
        if path_b_results:
            components.append(path_b_mult)
            b_weight = sum(r.confidence for r in path_b_results) * (1.0 - _PATH_B_DISCOUNT)
            weights.append(b_weight)

        if not components:
            final = _NEUTRAL
        else:
            total_weight = sum(weights)
            final = sum(c * w for c, w in zip(components, weights)) / max(total_weight, 1e-9)

        production = max(_PRODUCTION_CLAMP_LOW, min(_PRODUCTION_CLAMP_HIGH, final))

        all_contributors = {r.agent_id: r for r in (path_a_results + path_b_results)}
        any_shadow = any(r.shadow_only for r in all_contributors.values()) if all_contributors else True

        return AlphaMultiplier(
            signal_id=signal_id,
            symbol=symbol,
            timeframe=timeframe,
            ts=ts,
            path_a_multiplier=path_a_mult,
            path_b_multiplier=path_b_mult,
            contributors=all_contributors,
            final_alpha_multiplier=round(final, 4),
            production_multiplier=round(production, 4),
            shadow_only=any_shadow,
        )
