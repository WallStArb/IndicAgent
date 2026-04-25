"""correlation_agent.py -- CorrelationAgentComputeAgent (SwarmBaseAgent subclass).

Per D-16: reads context.lead_context for lead index data.
Pure compute class -- no infrastructure code.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from src.core.llm.chain import LLMProviderChain
from src.core.swarm.base_agent import SwarmBaseAgent
from src.intelligence.schemas import AgentResult
from src.intelligence.swarm.agents.correlation_prompts import (
    ACTIVE_VERSION,
    build_correlation_prompt,
)
from src.intelligence.swarm.context import SwarmContext

logger = structlog.get_logger(__name__)

_SYSTEM_MESSAGE = (
    "You are a cross-asset correlation analyst specializing in detecting "
    "divergence between assets and their lead indices. Always respond with "
    "valid JSON. "
    '{"failure_probability": float, "confidence": float, '
    '"risk_factors": [str], "reasoning": str}'
)

_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class CorrelationAgentComputeAgent(SwarmBaseAgent):
    """Cross-asset correlation agent -- detects decorrelation from lead index.

    Per D-16: reads context.lead_context (set by SwarmDispatchComputeAgent._enrich_context).
    """

    agent_id = "correlation_v1"
    path = "llm_swarm"
    shadow_only = True
    latency_budget_ms = 5000.0

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name="CorrelationAgentComputeAgent", **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: SwarmContext) -> AgentResult:
        """Build prompt from lead_context -> call LLM -> parse -> transfer."""
        prompt = build_correlation_prompt(context)

        response = await self._llm.generate(
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if not response:
            return self._neutral("LLM returned empty response", latency_ms=0.0)

        parsed = _parse_correlation_response(response)
        if parsed is None:
            logger.warning(
                "correlation_agent.json_parse_failed",
                agent_id=self.agent_id,
                raw_response=response[:200],
            )
            return self._neutral("JSON parse failed", latency_ms=0.0)

        failure_prob = parsed["failure_probability"]
        llm_confidence = parsed["confidence"]
        multiplier = (1.0 - failure_prob) * llm_confidence

        return AgentResult(
            agent_id=self.agent_id,
            path=self.path,
            multiplier=max(0.0, min(2.0, multiplier)),
            confidence=llm_confidence,
            shadow_only=self.shadow_only,
            metadata={
                "failure_probability": failure_prob,
                "confidence": llm_confidence,
                "risk_factors": parsed["risk_factors"],
                "reasoning": parsed["reasoning"],
                "prompt_version": ACTIVE_VERSION,
                "lead_symbol": (
                    context.lead_context.symbol
                    if context.lead_context else None
                ),
            },
        )


def _parse_correlation_response(raw: str) -> dict[str, Any] | None:
    """Parse structured JSON from LLM response.

    Handles: clean JSON, JSON in markdown code block, JSON with preamble.
    Returns dict with keys: failure_probability, confidence, risk_factors,
    reasoning. Returns None on parse failure.
    """
    try:
        data = json.loads(raw.strip())
        return _validate_correlation_fields(data)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            data = json.loads(match.group())
            return _validate_correlation_fields(data)
        except json.JSONDecodeError:
            pass

    return None


def _validate_correlation_fields(data: dict) -> dict[str, Any] | None:
    """Validate and sanitize the parsed correlation response fields."""
    if not isinstance(data, dict):
        return None

    fp = data.get("failure_probability")
    conf = data.get("confidence")

    if not isinstance(fp, (int, float)) or not isinstance(conf, (int, float)):
        return None

    fp = max(0.0, min(1.0, float(fp)))
    conf = max(0.0, min(1.0, float(conf)))

    risk_factors = data.get("risk_factors", [])
    if not isinstance(risk_factors, list):
        risk_factors = [str(risk_factors)]
    else:
        risk_factors = [str(rf) for rf in risk_factors]

    reasoning = data.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)

    return {
        "failure_probability": fp,
        "confidence": conf,
        "risk_factors": risk_factors,
        "reasoning": reasoning,
    }
