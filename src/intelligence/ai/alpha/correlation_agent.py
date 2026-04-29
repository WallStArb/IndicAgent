"""correlation_agent.py -- CorrelationAgentComputeAgent (BaseAIAgent subclass).

Per D-16: reads context.lead_context for lead index data.
Pure compute class -- no infrastructure code.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.alpha.correlation_prompts import (
    ACTIVE_VERSION,
    build_correlation_prompt,
)

logger = structlog.get_logger(__name__)

_SYSTEM_MESSAGE = (
    "You are a cross-asset correlation analyst specializing in detecting "
    "divergence between assets and their lead indices. Always respond with "
    "valid JSON. "
    '{"failure_probability": float, "confidence": float, '
    '"risk_factors": [str], "reasoning": str}'
)

_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class CorrelationAgentComputeAgent(BaseAIAgent):
    """Cross-asset correlation agent -- detects decorrelation from lead index.

    Per D-16: reads context.lead_context (set by dispatch layer).
    Per D-34: extends BaseAIAgent, returns AgentOutput.
    """

    agent_id = "correlation_v1"
    group = "alpha"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7})
    latency_budget_ms = 5000.0

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name="CorrelationAgentComputeAgent", **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: AIContext) -> AgentOutput:
        """Build prompt from lead_context -> call LLM -> parse -> transfer."""
        # Build prompt from AIContext - convert to dict for prompt building
        prompt = build_correlation_prompt(_context_to_dict(context))

        response = await self._llm.generate(
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if not response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        parsed = _parse_correlation_response(response)
        if parsed is None:
            logger.warning(
                "correlation_agent.json_parse_failed",
                agent_id=self.agent_id,
                raw_response=response[:200],
            )
            return self._neutral(error="JSON parse failed", latency_ms=0.0)

        failure_prob = parsed["failure_probability"]
        llm_confidence = parsed["confidence"]
        multiplier = (1.0 - failure_prob) * llm_confidence

        lead_symbol = context.lead_context.symbol if context.lead_context else None

        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            signal_id=context.signal_id,
            symbol=context.symbol,
            timeframe=context.timeframe,
            ts=context.ts,
            output_type="multiplier",
            payload={
                "multiplier": max(0.0, min(2.0, multiplier)),
                "confidence": llm_confidence,
                "failure_probability": failure_prob,
                "risk_factors": parsed["risk_factors"],
                "reasoning": parsed["reasoning"],
                "prompt_version": ACTIVE_VERSION,
                "lead_symbol": lead_symbol,
            },
            shadow_only=self.shadow_only,
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


def _context_to_dict(context: AIContext) -> dict:
    """Convert AIContext to dict for prompt building (temporary adapter)."""
    i1_ctx = context.i1
    i4_ctx = context.i4
    i6_ctx = context.i6
    i7_ctx = context.i7
    bar_ctx = context.bar

    # Extract lead context if available
    lead_ctx = context.lead_context
    lead_dict = {}
    if lead_ctx:
        lead_i1 = lead_ctx.i1
        lead_i4 = lead_ctx.i4
        lead_i6 = lead_ctx.i6
        lead_dict = {
            "lead_symbol": lead_ctx.symbol,
            "lead_trend_regime": lead_i4.trend_regime if lead_i4 else None,
            "lead_rsi": lead_i1.rsi if lead_i1 else None,
            "lead_adx": lead_i1.adx if lead_i1 else None,
            "lead_hmm_regime": lead_i4.hmm_regime if lead_i4 else None,
            "lead_ctf_trend_alignment": lead_i6.ctf_trend_alignment if lead_i6 else None,
        }
        # Calculate trend regime divergence if both available
        if (
            i4_ctx
            and i4_ctx.trend_regime is not None
            and lead_i4
            and lead_i4.trend_regime is not None
        ):
            lead_dict["trend_regime_divergence"] = i4_ctx.trend_regime - lead_i4.trend_regime

    return {
        "symbol": context.symbol,
        "timeframe": context.timeframe,
        "ts": context.ts,
        "winner_plugin": i7_ctx.winner_plugin if i7_ctx else None,
        "winner_direction": i7_ctx.winner_direction if i7_ctx else None,
        "winner_confidence": i7_ctx.winner_confidence if i7_ctx else None,
        "atr": i1_ctx.atr if i1_ctx else None,
        "rsi": i1_ctx.rsi if i1_ctx else None,
        "adx": i1_ctx.adx if i1_ctx else None,
        "hmm_regime": i4_ctx.hmm_regime if i4_ctx else None,
        "trend_regime": i4_ctx.trend_regime if i4_ctx else None,
        "vol_regime": i4_ctx.vol_regime if i4_ctx else None,
        "ctf_trend_alignment": i6_ctx.ctf_trend_alignment if i6_ctx else None,
        "ctf_regime_agreement": i6_ctx.ctf_regime_agreement if i6_ctx else None,
        "ctf_fvg_alignment": i6_ctx.ctf_fvg_alignment if i6_ctx else None,
        "ctf_ob_alignment": i6_ctx.ctf_ob_alignment if i6_ctx else None,
        "price": bar_ctx.close if bar_ctx else None,
        "volume": bar_ctx.volume if bar_ctx else None,
        **lead_dict,
    }
