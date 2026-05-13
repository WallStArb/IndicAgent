"""CounterfactualComputeAgent — validation/invalidation reasoning multiplier (Phase 80, D-06)."""

from __future__ import annotations

from typing import Any, ClassVar

import structlog

from src.core.ai.context import AIContext, Tier
from src.core.ai.multiplier_agent import BaseMultiplierAgent
from src.core.ai.output import AgentOutput
from src.core.ai.prompt_utils import clamp
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.alpha.counterfactual_prompts import (
    ACTIVE_VERSION,
    build_counterfactual_prompt,
)

logger = structlog.get_logger(__name__)

_SYSTEM_MESSAGE = (
    "You are a counterfactual reasoning analyst. Output strictly valid JSON. "
    "Phase 80 policy: discount-only — plausibility and confidence in [0.0, 1.0]."
)


class CounterfactualComputeAgent(BaseMultiplierAgent):
    """Counterfactual reasoning — what must be true for this signal to work?"""

    output_schema: ClassVar[dict] = {
        "plausibility": float,
        "confidence": float,
        "validation_conditions": list,
        "invalidation_conditions": list,
        "reasoning": str,
    }

    agent_id = "counterfactual_v1"
    group = "alpha"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I7})
    latency_budget_ms = 45000.0
    shadow_only = True

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name="CounterfactualComputeAgent", **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: AIContext) -> AgentOutput:
        """Core computation: build prompt -> call LLM -> parse JSON -> multiplier.

        multiplier = plausibility × llm_confidence.
        Phase 80 policy: discount-only — multiplier stays <= 1.0 until calibration.
        """
        prompt = build_counterfactual_prompt(context)

        response = await self._llm.generate(
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=2000,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if not response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        parsed = self._parse_multiplier_response(response, _validate_counterfactual_fields)
        if parsed is None:
            logger.warning(
                "counterfactual_agent.json_parse_failed",
                agent_id=self.agent_id,
                raw_response=response[:200],
            )
            return self._neutral(error="JSON parse failed", latency_ms=0.0)

        plausibility = parsed["plausibility"]
        llm_confidence = parsed["confidence"]
        multiplier = plausibility * llm_confidence

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=llm_confidence,
            payload={
                "plausibility": plausibility,
                "validation_conditions": parsed["validation_conditions"],
                "invalidation_conditions": parsed["invalidation_conditions"],
                "reasoning": parsed["reasoning"],
            },
            prompt_version=ACTIVE_VERSION,
        )


def _validate_counterfactual_fields(data: dict) -> dict[str, Any] | None:
    """Validate and sanitize the parsed counterfactual response fields.

    - Rejects non-dict input.
    - Rejects non-numeric plausibility or confidence.
    - Clamps both to [0.0, 1.0].
    - Coerces validation_conditions and invalidation_conditions to list[str].
    - Returns dict with all five keys; None on failure.
    """
    if not isinstance(data, dict):
        return None

    plausibility = data.get("plausibility")
    confidence = data.get("confidence")

    if not isinstance(plausibility, (int, float)) or not isinstance(confidence, (int, float)):
        return None

    plausibility = clamp(float(plausibility), 0.0, 1.0)
    confidence = clamp(float(confidence), 0.0, 1.0)

    validation_conditions = data.get("validation_conditions", [])
    if not isinstance(validation_conditions, list):
        validation_conditions = [str(validation_conditions)]
    else:
        validation_conditions = [str(x) for x in validation_conditions]

    invalidation_conditions = data.get("invalidation_conditions", [])
    if not isinstance(invalidation_conditions, list):
        invalidation_conditions = [str(invalidation_conditions)]
    else:
        invalidation_conditions = [str(x) for x in invalidation_conditions]

    reasoning = str(data.get("reasoning", ""))

    return {
        "plausibility": plausibility,
        "confidence": confidence,
        "validation_conditions": validation_conditions,
        "invalidation_conditions": invalidation_conditions,
        "reasoning": reasoning,
    }
