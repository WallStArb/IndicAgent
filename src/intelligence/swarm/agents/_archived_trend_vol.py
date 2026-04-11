"""DEPRECATED: Old get_multiplier(sid, dict) contract stub — archived 2026-04-10.

Replaced by: Phase 66 will create the first real IAlphaContributor (SkepticAgent).
Why archived: Implemented get_multiplier(sid, dict) — wrong contract.
              New contract: IAlphaContributor.compute(SwarmContext) → AgentResult.
              Contains no real logic (placeholder values only).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.intelligence.schemas import AgentResult, AlphaMultiplier
from src.intelligence.swarm.interface import IAlphaContributor


class TrendVolatilityContributor(IAlphaContributor):
    """
    Path A: Deterministic/Real-time.
    Calculates volatility-adjusted trend bias.
    """

    @property
    def is_production_ready(self) -> bool:
        return False  # TODO: set True after replacing placeholder logic with real ATR/momentum

    async def get_multiplier(self, sid: str, context: dict[str, Any]) -> AlphaMultiplier:
        confidence = context.get("confidence", 0.5)

        # Placeholder deterministic logic — replace with ATR-based momentum/volatility
        momentum_score = 0.8
        volatility_regime = "low"

        multiplier = 1.0 + (momentum_score * 0.5) if volatility_regime == "low" else 1.0

        return AlphaMultiplier(
            signal_id=UUID(sid),
            ts=datetime.now(UTC),
            path="deterministic",
            contributors={
                "trend_vol": AgentResult(
                    agent_id="trend_vol_01",
                    multiplier=multiplier,
                    confidence=confidence,
                    metadata={
                        "momentum_score": momentum_score,
                        "volatility_regime": volatility_regime,
                    },
                )
            },
            final_alpha_multiplier=multiplier,
        )
