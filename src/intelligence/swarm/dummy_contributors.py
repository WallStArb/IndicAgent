from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.intelligence.schemas import AgentResult, AlphaMultiplier
from src.intelligence.swarm.interface import IAlphaContributor


class DeterministicTrendContributor(IAlphaContributor):
    """
    Path A: Deterministic/Real-time.
    Provides simple trend-following bias adjustment.
    """

    @property
    def is_production_ready(self) -> bool:
        return True

    async def get_multiplier(self, sid: str, context: dict[str, Any]) -> AlphaMultiplier:
        return AlphaMultiplier(
            signal_id=UUID(sid),
            ts=datetime.now(UTC),
            path="deterministic",
            contributors={
                "trend_bias": AgentResult(
                    agent_id="trend_bias_01",
                    multiplier=1.0,
                    confidence=0.9,
                )
            },
            final_alpha_multiplier=1.0,
        )


class SwarmSMCContributor(IAlphaContributor):
    """
    Path B: LLM-Swarm/Shadow.
    Mock contributor simulating LLM-based reasoning (e.g., SMC/Liquidity Hunter).
    """

    @property
    def is_production_ready(self) -> bool:
        return False

    async def get_multiplier(self, sid: str, context: dict[str, Any]) -> AlphaMultiplier:
        return AlphaMultiplier(
            signal_id=UUID(sid),
            ts=datetime.now(UTC),
            path="llm_swarm",
            contributors={
                "smc_liquidity_hunter": AgentResult(
                    agent_id="smc_hunter_01",
                    multiplier=0.8,
                    confidence=0.6,
                    metadata={"reasoning": "Liquidity sweep detected at support."},
                )
            },
            final_alpha_multiplier=0.8,
        )
