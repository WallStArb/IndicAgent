"""NarrativeComputeAgent -- LLM-driven market narrative generation.

On-demand (not hot-path): instantiated per HTTP request, not managed by
BaseGroupService. Per D-35: TF gate rejects 1m bars (only 5m+ allowed).
Per D-34: returns AgentOutput with narrative text in payload.

Renaissance design:
  - Prompt version in every output payload (auditable, A/B testable)
  - Confidence-segmented instruction depth (pipeline decides, not LLM)
  - Model name captured for cost/quality tracking
  - Every generation is a labeled training sample (persisted by route)
"""

from __future__ import annotations

from typing import Any

import structlog

from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.narrative.narrative_prompts import (
    ACTIVE_VERSION,
    build_narrative_prompt,
)

logger = structlog.get_logger(__name__)


class NarrativeComputeAgent(BaseAIAgent):
    """Generate per-signal market narratives using LLM.

    Per D-35: TF gate rejects 1m bars (narrative only meaningful on higher TFs).
    Per D-51: 60s latency budget for prose generation (longer than alpha agents).
    Per D-34: returns AgentOutput with text in payload.
    """

    agent_id = "narrative_v1"
    prompt_version = ACTIVE_VERSION
    group = "narrative"
    tiers_needed = frozenset({Tier.I4, Tier.I6, Tier.I7})
    shadow_only = False
    latency_budget_ms = 120000.0

    _NARRATIVE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name="NarrativeComputeAgent", **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: AIContext) -> AgentOutput:
        """Generate narrative text from AIContext via LLM chain."""
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

        system_prompt, user_prompt = build_narrative_prompt(context)

        response, _call_id = await self._llm_generate(
            context,
            prompt=user_prompt,
            system=system_prompt,
            max_tokens=300,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if not response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        i7 = context.i7
        direction = (i7.winner_direction if i7 else None) or 0
        action_bias = "bullish" if direction > 0 else ("bearish" if direction < 0 else "neutral")
        winner_plugin = (i7.winner_plugin if i7 else None) or ""
        action_tag = (
            f"[{action_bias.upper()} {winner_plugin.replace('_', ' ').upper()}]"
            if winner_plugin
            else f"[{action_bias.upper()}]"
        )
        text = response.strip()

        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            signal_id=context.signal_id,
            symbol=context.symbol,
            timeframe=context.timeframe,
            ts=context.ts,
            output_type="narrative",
            payload={
                "text": text,
                "narrative": text,
                "narrative_type": "short",
                "action_bias": action_bias,
                "action_tag": action_tag,
                "model": self._llm.last_provider_id or "",
                "prompt_version": ACTIVE_VERSION,
            },
            shadow_only=self.shadow_only,
        )
