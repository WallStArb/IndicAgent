"""TEMPLATE_agent.py — copy this file when adding a new AI agent.

Steps:
  1. Copy this file to src/intelligence/ai/<group>/<name>_agent.py.
  2. Rename class to <Name>ComputeAgent.
  3. Set the five class attributes (agent_id, group, tiers_needed, latency_budget_ms, shadow_only).
  4. Implement `_compute(context: AIContext) -> AgentOutput`.
  5. Create matching <name>_prompts.py with PROMPT_REGISTRY + ACTIVE_VERSION.
  6. Add the agent class to AlphaSwarmComputeAgent._agents (or the relevant group's agent list).
  7. If shadow_only=True, call shadow_registry_ensure() at startup so the graduation loop sees the agent.

Required reading:
  - src/intelligence/ai/AUTHORING.md — full protocol
  - src/intelligence/ai/alpha/skeptic_agent.py — canonical reference implementation
"""

from __future__ import annotations

from typing import Any

import structlog

from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput
from src.core.llm.chain import LLMProviderChain

logger = structlog.get_logger(__name__)


class TemplateComputeAgent(BaseAIAgent):
    """One-line description of what this agent decides and why."""

    # Required class attributes — every AI agent MUST set these five.
    agent_id = "template_v1"  # MUST match shadow_registry.component_name
    group = "alpha"  # one of: "alpha", "narrative", "risk"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6})  # tiers consumed
    latency_budget_ms = 5000.0  # asyncio.wait_for in BaseAIAgent.compute
    shadow_only = True  # start in shadow; graduation loop promotes if rho>0, p<0.05, n>=100

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name=self.__class__.__name__, **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: AIContext) -> AgentOutput:
        """Build prompt -> call LLM -> parse -> return AgentOutput.

        Contract:
          - Return AgentOutput.payload as a JSON-serializable dict.
          - On error, return self._neutral(error=..., latency_ms=...).
          - Never raise — BaseAIAgent.compute wraps with neutral fallback,
            but explicit error returns are clearer.
          - prompt_version (e.g. "template_v1") MUST be included in payload
            so LineageRecorder attribution is correct.
        """
        raise NotImplementedError("Replace this body — see skeptic_agent.py")
