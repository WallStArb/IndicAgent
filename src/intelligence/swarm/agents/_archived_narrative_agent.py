"""DEPRECATED: Old get_multiplier(sid, dict) contract stub — archived 2026-04-10.

Replaced by: Phase 66 will create the first real IAlphaContributor (SkepticAgent).
Why archived: Implemented get_multiplier(sid, dict) — wrong contract.
              New contract: IAlphaContributor.compute(SwarmContext) → AgentResult.
              Contains no real logic (placeholder values only).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.intelligence.schemas import AgentResult, AlphaMultiplier
from src.intelligence.swarm.interface import IAlphaContributor


class NarrativeMarketAgent(IAlphaContributor):
    """
    Path B: LLM-Swarm/Shadow.
    Quantifies market narrative/sentiment into an alpha multiplier.
    """

    @property
    def is_production_ready(self) -> bool:
        return False

    async def get_multiplier(self, sid: str, context: dict[str, Any]) -> AlphaMultiplier:
        # 1. Fetch current narrative state (Simulated: In production, read from AI Narrative Service cache)
        # 2. Logic: If narrative contains "CPI" or "Volatility", dampen multiplier
        # 3. Reasoning: Attach narrative insight to metadata

        reasoning = (
            "Sector rotation into defensive staples; macro outlook bearish due to CPI release."
        )
        sentiment = -0.3  # bearish

        # Mapping: sentiment [-1, 1] to multiplier [0, 1.5]
        # (sentiment + 1) / 2 = 0.35 * 1.5 = 0.525
        multiplier = ((sentiment + 1) / 2) * 1.5

        return AlphaMultiplier(
            signal_id=UUID(sid),
            ts=datetime.now(UTC),
            path="llm_swarm",
            contributors={
                "narrative_agent": AgentResult(
                    agent_id="narrative_macro_01",
                    multiplier=multiplier,
                    confidence=0.7,
                    metadata={"reasoning": reasoning},
                )
            },
            final_alpha_multiplier=multiplier,
        )
