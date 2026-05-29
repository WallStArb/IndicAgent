"""CorrelationComputeAgent — cross-asset coherence multiplier (Phase 80, D-04)."""

from __future__ import annotations

from typing import Any, ClassVar

import structlog

from src.core.ai.context import AIContext, Tier
from src.core.ai.multiplier_agent import BaseMultiplierAgent
from src.core.ai.output import AgentOutput
from src.core.ai.prompt_utils import clamp
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.alpha.correlation_prompts import (
    ACTIVE_VERSION,
    build_correlation_prompt,
)

logger = structlog.get_logger(__name__)

_SYSTEM_MESSAGE = (
    "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
    "Your entire response must be a single JSON object starting with { and ending with }. "
    "Phase 80 policy: discount-only — coherence_score and confidence in [0.0, 1.0]. "
    "reasoning must be under 100 words."
)


def _validate_correlation_fields(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    score = data.get("coherence_score")
    conf = data.get("confidence")
    if not isinstance(score, (int, float)) or not isinstance(conf, (int, float)):
        return None
    score = clamp(score, 0.0, 1.0)
    conf = clamp(conf, 0.0, 1.0)
    assets = data.get("contradicting_assets", [])
    if not isinstance(assets, list):
        assets = [str(assets)]
    else:
        assets = [str(a) for a in assets]
    reasoning = str(data.get("reasoning", ""))
    return {
        "coherence_score": score,
        "confidence": conf,
        "contradicting_assets": assets,
        "reasoning": reasoning,
    }


class CorrelationComputeAgent(BaseMultiplierAgent):
    """Cross-asset coherence — does ZN/VIX/ES/CL behavior support this signal?

    Per D-04: multiplier = coherence_score × confidence (discount-only, Phase 80).
    Shadow-only at deploy; graduation via 100+ resolved signals with positive CI.
    """

    output_schema: ClassVar[dict] = {
        "coherence_score": float,
        "confidence": float,
        "contradicting_assets": list,
        "reasoning": str,
    }

    agent_id = "correlation_v1"
    prompt_version = ACTIVE_VERSION
    group = "alpha"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7, Tier.SMC})
    latency_budget_ms = 120000.0
    # Phase 109: shadow_only defaults to True (FAIL-CLOSED).
    # Promotion to live requires an explicit ai.agent.<agent_id>.shadow_mode=false
    # config entry. If config load fails or the key is missing, agent STAYS shadow.
    shadow_only: bool = True

    def _apply_shadow_mode_config(self) -> None:
        """Read ai.agent.<self.agent_id>.shadow_mode from config; fail-closed on miss.

        Called by:
          - AlphaSwarmComputeAgent._setup() after agents are constructed (initial load)
          - AlphaSwarmComputeAgent._on_config_message_received() on Kafka update
            (hot-reload -- see alpha_swarm_agent.py Part B)
        """
        override = self.get_config(f"ai.agent.{self.agent_id}.shadow_mode", None)
        if override is None:
            return  # keep class default True (fail-closed)
        # override may arrive as bool (from RUNTIME_DEFAULTS) or str (from Kafka); normalize:
        if isinstance(override, bool):
            self.shadow_only = override
        elif isinstance(override, str):
            self.shadow_only = override.strip().lower() in ("true", "1", "yes")
        # Unknown type - keep fail-closed (do nothing)

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name=self.__class__.__name__, **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: AIContext) -> AgentOutput:
        prompt = build_correlation_prompt(context)
        response, call_id = await self._llm_generate(
            context,
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )
        if not response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        parsed = self._parse_multiplier_response(response, _validate_correlation_fields)
        if parsed is None:
            logger.warning(
                "correlation_agent.json_parse_failed",
                agent_id=self.agent_id,
                raw_response=response[:200],
                expected_schema=self.output_schema,
            )
            await self._report_parse_failure(call_id)
            return self._neutral(error="JSON parse failed", latency_ms=0.0)

        coherence_score = parsed["coherence_score"]
        llm_confidence = parsed["confidence"]
        multiplier = coherence_score * llm_confidence  # D-04 formula

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=llm_confidence,
            payload={
                "coherence_score": coherence_score,
                "contradicting_assets": parsed["contradicting_assets"],
                "reasoning": parsed["reasoning"],
            },
            prompt_version=ACTIVE_VERSION,
        )
