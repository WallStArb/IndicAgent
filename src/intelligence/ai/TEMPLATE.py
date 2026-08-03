"""TEMPLATE.py — canonical skeleton for Phase 80 multiplier agents.

Copy this file when adding a new swarm agent. Required steps:
1. Pick a unique agent_id ending in _v1 (lowercase, underscored).
2. Define output_schema ClassVar with the LLM JSON keys you expect.
3. Create a paired <name>_prompts.py exposing PROMPT_REGISTRY and ACTIVE_VERSION; move
   ACTIVE_VERSION, build_template_prompt(), and _validate_template_fields() there and
   import them at module level (see src/intelligence/ai/alpha/skeptic_prompts.py for the
   shape). Until you do, the placeholders below keep this file self-contained and
   importable -- ACTIVE_VERSION MUST stay a module-level name either way: it's read at
   class-body-evaluation time by prompt_version = ACTIVE_VERSION, and _build_audit_context()
   raises RuntimeError on first LLM call if that attribute is unset.
4. Implement _compute(): build prompt → LLM call → parse → return multiplier output.
5. Register in services/alpha_swarm.py self._agents list.

Reference implementation: src/intelligence/ai/alpha/skeptic_agent.py
Authoring protocol: src/intelligence/ai/AUTHORING.md

Always extend Evaluator, never BaseAIWorker directly.
"""

from __future__ import annotations

from typing import Any, ClassVar

import structlog

from src.core.ai.evaluator import Evaluator
from src.core.ai.output import AgentOutput
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.context import SignalContext, Tier

logger = structlog.get_logger(__name__)

# Replace with a real system message for the agent's role.
_SYSTEM_MESSAGE = (
    "You are a trading analysis agent. Always respond with valid JSON. "
    '{"score": float, "confidence": float, "reasoning": str}'
)

# Placeholders -- move these three to a paired <name>_prompts.py (step 3 above) and
# import them at module level instead. Kept here so this file stays self-contained
# and importable as shipped (e.g. by the DAG-invariant module sweep in
# tests/unit/intelligence/test_dag_invariants.py).
ACTIVE_VERSION = "template_v1"


def build_template_prompt(context: SignalContext) -> str:
    """Replace with real prompt construction from context."""
    raise NotImplementedError("copy this template and implement build_<name>_prompt()")


def _validate_template_fields(parsed: dict) -> dict | None:
    """Replace with real field validation matching output_schema."""
    raise NotImplementedError("copy this template and implement _validate_<name>_fields()")


class TemplateEvaluator(Evaluator):
    """One-line description of what this evaluator decides and why."""

    # Required class attributes — every multiplier evaluator MUST set these seven.
    output_schema: ClassVar[dict] = {
        "score": float,  # agent-specific key (rename per agent)
        "confidence": float,  # always required
        "reasoning": str,  # always required
    }

    agent_id = "template_evaluator"  # MUST match shadow_registry.component_name
    prompt_version = ACTIVE_VERSION  # required -- _build_audit_context() raises if unset
    group = "alpha"  # one of: "alpha", "narrative", "risk"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6})  # tiers consumed
    latency_budget_ms = 5000.0  # asyncio.wait_for in BaseAIWorker.compute
    shadow_only = True  # start in shadow; graduation loop promotes if rho>0, p<0.05, n>=100

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._llm = llm_chain

    async def _compute(self, context: SignalContext) -> AgentOutput:
        """Build prompt -> call LLM -> parse -> return multiplier output.

        Contract:
          - Return AgentOutput via self._build_multiplier_output().
          - On error, return self._neutral(error=..., latency_ms=...).
          - Never raise — BaseAIWorker.compute wraps with neutral fallback,
            but explicit error returns are clearer.
          - prompt_version MUST be included via _build_multiplier_output()
            so LineageRecorder attribution is correct.

        Phase 80: discount-only formula — multiplier should be <= 1.0 until
        calibration data exists. Clamp range [0.0, 2.0] preserved for future boosting.
        """
        prompt = build_template_prompt(context)
        response, call_id = await self._llm_generate(
            context,
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )
        if not response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        parsed = self._parse_multiplier_response(response, _validate_template_fields)
        if parsed is None:
            await self._report_parse_failure(call_id)
            logger.warning(
                "template_agent.json_parse_failed",
                agent_id=self.agent_id,
                raw_response=response[:200],
                expected_schema=self.output_schema,
            )
            return self._neutral(error="JSON parse failed", latency_ms=0.0)

        score = parsed["score"]
        confidence = parsed["confidence"]
        # Phase 80: discount-only formula — multiplier should be <= 1.0 until calibration data exists
        multiplier = score * confidence

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=confidence,
            payload={"score": score, "reasoning": parsed["reasoning"]},
            prompt_version=ACTIVE_VERSION,
        )
