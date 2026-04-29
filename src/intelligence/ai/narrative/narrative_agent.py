"""NarrativeComputeAgent -- LLM-driven market narrative generation.

Refactored from NarrativeOrchestrator to extend BaseAIAgent.
Per D-35: TF gate rejects 1m bars (only 5m, 15m, 1h, 4h, 1d allowed).
Per D-34: returns AgentOutput instead of str.
"""
from __future__ import annotations

from typing import Any

import structlog

from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput
from src.core.llm.chain import LLMProviderChain

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a professional equity futures market analyst. "
    "Be direct and precise. No fluff. Use trader terminology. "
    "Never hedge with 'may', 'might', 'could' — state what the data shows."
)


class NarrativeComputeAgent(BaseAIAgent):
    """Generate per-signal market narratives using LLM.

    Per D-35: TF gate rejects 1m bars (narrative only meaningful on higher TFs).
    Per D-51: 60s latency budget for prose generation (longer than alpha agents).
    Per D-34: returns AgentOutput with text in payload.
    """

    agent_id = "narrative_v1"
    group = "narrative"
    tiers_needed = frozenset({Tier.I4, Tier.I6, Tier.I7})
    shadow_only = True
    latency_budget_ms = 60000.0  # D-51: narrative needs 60s for prose

    # D-35: Narrative TF gate - only these timeframes are valid
    _NARRATIVE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name="NarrativeComputeAgent", **kwargs)
        self._chain = llm_chain

    async def _compute(self, context: AIContext) -> AgentOutput:
        """Generate narrative text from AIContext.

        D-35: TF gate - reject before any LLM call for invalid TFs.
        Returns AgentOutput with output_type="narrative" and text in payload.
        """
        # D-35: TF gate — reject before any LLM call
        if context.timeframe not in self._NARRATIVE_TFS:
            return AgentOutput(
                agent_id=self.agent_id,
                group=self.group,
                signal_id=context.signal_id,
                symbol=context.symbol,
                timeframe=context.timeframe,
                ts=context.ts,
                output_type="neutral",
                payload={},
                shadow_only=self.shadow_only,
                error=f"tf_gate:{context.timeframe}",
            )

        # Build prompt from AIContext
        # Note: prompt builders currently expect BarIntelligenceRecord
        # For now, return neutral - prompt builders will be updated in future plans
        # to accept AIContext directly
        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            signal_id=context.signal_id,
            symbol=context.symbol,
            timeframe=context.timeframe,
            ts=context.ts,
            output_type="narrative",
            payload={"text": "Narrative generation pending prompt builder update"},
            shadow_only=self.shadow_only,
        )
