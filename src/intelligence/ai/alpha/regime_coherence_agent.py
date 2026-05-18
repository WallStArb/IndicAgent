"""RegimeCoherenceComputeAgent — setup-vs-regime fit multiplier (Phase 80, D-05)."""

from __future__ import annotations

from typing import Any, ClassVar

import structlog

from src.core.ai.context import AIContext, Tier
from src.core.ai.multiplier_agent import BaseMultiplierAgent
from src.core.ai.output import AgentOutput
from src.core.ai.prompt_utils import clamp
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.alpha.regime_coherence_prompts import (
    ACTIVE_VERSION,
    build_regime_coherence_prompt,
)

logger = structlog.get_logger(__name__)

_SYSTEM_MESSAGE = (
    "/no_think\n\n"
    "You are a regime-coherence analyst. Output strictly valid JSON. "
    "Phase 80 policy: discount-only — regime_fit and confidence in [0.0, 1.0]. "
    "Keep reasoning under 100 words."
)


def _validate_regime_coherence_fields(data: dict) -> dict[str, Any] | None:
    """Validate and sanitize regime coherence LLM response fields.

    Returns None on type failure.
    """
    if not isinstance(data, dict):
        return None

    regime_fit = data.get("regime_fit")
    confidence = data.get("confidence")

    if not isinstance(regime_fit, (int, float)) or not isinstance(confidence, (int, float)):
        return None

    regime_fit = clamp(float(regime_fit), 0.0, 1.0)
    confidence = clamp(float(confidence), 0.0, 1.0)

    mismatches = data.get("mismatches", [])
    if not isinstance(mismatches, list):
        mismatches = [str(mismatches)]
    else:
        mismatches = [str(m) for m in mismatches]

    reasoning = data.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)

    return {
        "regime_fit": regime_fit,
        "confidence": confidence,
        "mismatches": mismatches,
        "reasoning": reasoning,
    }


class RegimeCoherenceComputeAgent(BaseMultiplierAgent):
    """Setup TYPE vs regime fit — is mean-reversion firing in a strong trend?"""

    output_schema: ClassVar[dict] = {
        "regime_fit": float,
        "confidence": float,
        "mismatches": list,
        "reasoning": str,
    }

    agent_id = "regime_coherence_v1"
    prompt_version = ACTIVE_VERSION
    group = "alpha"
    tiers_needed = frozenset({Tier.I4, Tier.I7, Tier.SMC})
    latency_budget_ms = 120000.0
    shadow_only = True

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name=self.__class__.__name__, **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: AIContext) -> AgentOutput:
        """Core computation: build prompt -> call LLM -> parse JSON -> multiplier.

        Phase 80 policy: discount-only — regime_fit × confidence.
        """
        prompt = build_regime_coherence_prompt(context)

        response, call_id = await self._llm_generate(
            context,
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if not response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        parsed = self._parse_multiplier_response(response, _validate_regime_coherence_fields)
        if parsed is None:
            logger.warning(
                "regime_coherence_agent.json_parse_failed",
                agent_id=self.agent_id,
                raw_response=response[:200],
            )
            await self._report_parse_failure(call_id)
            return self._neutral(error="JSON parse failed", latency_ms=0.0)

        regime_fit = parsed["regime_fit"]
        llm_confidence = parsed["confidence"]
        multiplier = regime_fit * llm_confidence

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=llm_confidence,
            payload={
                "regime_fit": regime_fit,
                "mismatches": parsed["mismatches"],
                "reasoning": parsed["reasoning"],
            },
            prompt_version=ACTIVE_VERSION,
        )
