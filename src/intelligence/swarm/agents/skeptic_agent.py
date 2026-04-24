"""skeptic_agent.py -- SkepticAgentComputeAgent (SwarmBaseAgent subclass).

Pure compute class: prompt building + LLM call + JSON parse + transfer function.
No Kafka, no DB, no infrastructure -- all owned by SwarmDispatchService.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from src.core.llm.chain import LLMProviderChain
from src.core.swarm.base_agent import SwarmBaseAgent
from src.intelligence.schemas import AgentResult
from src.intelligence.swarm.agents.skeptic_prompts import (
    ACTIVE_VERSION,
    build_skeptic_prompt,
)
from src.intelligence.swarm.context import SwarmContext

logger = structlog.get_logger(__name__)

_SYSTEM_MESSAGE = (
    "You are a financial trading risk analyst specializing in identifying "
    "signal weaknesses. Always respond with valid JSON. "
    '{"failure_probability": float, "confidence": float, '
    '"risk_factors": [str], "reasoning": str}'
)

_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class SkepticAgentComputeAgent(SwarmBaseAgent):
    """Devil's advocate swarm agent -- predicts signal failure probability.

    Per D-15: pure compute class. SwarmDispatchService owns infrastructure.
    Per D-11: SwarmBaseAgent.compute() handles timeout + exception isolation.
    """

    agent_id = "skeptic_v1"
    path = "llm_swarm"
    shadow_only = True
    latency_budget_ms = 5000.0

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name="SkepticAgentComputeAgent", **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: SwarmContext) -> AgentResult:
        """Core computation: build prompt -> call LLM -> parse JSON -> transfer function.

        Per D-01: full SwarmContext dump in prompt.
        Per D-04: multiplier = (1.0 - failure_probability) * llm_confidence.
        Per D-06: raw values stored in metadata, never overwrites signal_ledger.
        """
        prompt = build_skeptic_prompt(context)

        response = await self._llm.generate(
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if not response:
            return self._neutral("LLM returned empty response", latency_ms=0.0)

        parsed = _parse_skeptic_response(response)
        if parsed is None:
            logger.warning(
                "skeptic_agent.json_parse_failed",
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
            },
        )


def _parse_skeptic_response(raw: str) -> dict[str, Any] | None:
    """Parse structured JSON from LLM response.

    Handles: clean JSON, JSON in markdown code block, JSON with preamble text.
    Returns dict with keys: failure_probability, confidence, risk_factors, reasoning.
    Returns None on parse failure.
    """
    try:
        data = json.loads(raw.strip())
        return _validate_skeptic_fields(data)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            data = json.loads(match.group())
            return _validate_skeptic_fields(data)
        except json.JSONDecodeError:
            pass

    return None


def _validate_skeptic_fields(data: dict) -> dict[str, Any] | None:
    """Validate and sanitize the parsed skeptic response fields."""
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
