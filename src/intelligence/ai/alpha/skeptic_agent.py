"""skeptic_agent.py -- SkepticAgentComputeAgent (BaseAIAgent subclass).

Pure compute class: prompt building + LLM call + JSON parse + transfer function.
No Kafka, no DB, no infrastructure -- all owned by dispatch layer.
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
from src.intelligence.ai.alpha.skeptic_prompts import (
    ACTIVE_VERSION,
    build_skeptic_prompt,
)

logger = structlog.get_logger(__name__)

_SYSTEM_MESSAGE = (
    "You are a financial trading risk analyst specializing in identifying "
    "signal weaknesses. Always respond with valid JSON. "
    '{"failure_probability": float, "confidence": float, '
    '"risk_factors": [str], "reasoning": str}'
)

_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class SkepticAgentComputeAgent(BaseAIAgent):
    """Devil's advocate alpha agent -- predicts signal failure probability.

    Per D-34: extends BaseAIAgent, returns AgentOutput.
    Pure compute class -- dispatch layer owns infrastructure.
    """

    agent_id = "skeptic_v1"
    group = "alpha"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7, Tier.SMC})
    latency_budget_ms = 5000.0

    def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
        super().__init__(name="SkepticAgentComputeAgent", **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: AIContext) -> AgentOutput:
        """Core computation: build prompt -> call LLM -> parse JSON -> transfer function.

        Per D-01: full AIContext dump in prompt.
        Per D-04: multiplier = (1.0 - failure_probability) * llm_confidence.
        Per D-06: raw values stored in payload, never overwrites signal_ledger.
        """
        # Build prompt — v2 passes AIContext directly; v1 uses dict adapter
        if ACTIVE_VERSION == "skeptic_v2":
            prompt = build_skeptic_prompt(context)
        else:
            prompt = build_skeptic_prompt(_context_to_dict(context))

        response = await self._llm.generate(
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if not response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        parsed = _parse_skeptic_response(response)
        if parsed is None:
            logger.warning(
                "skeptic_agent.json_parse_failed",
                agent_id=self.agent_id,
                raw_response=response[:200],
            )
            return self._neutral(error="JSON parse failed", latency_ms=0.0)

        failure_prob = parsed["failure_probability"]
        llm_confidence = parsed["confidence"]
        multiplier = (1.0 - failure_prob) * llm_confidence

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
            },
            shadow_only=self.shadow_only,
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


def _context_to_dict(context: AIContext) -> dict:
    """Convert AIContext to dict for prompt building (v1 adapter — kept for rollback).

    Used when ACTIVE_VERSION == "skeptic_v1". Preserved intact per plan instructions.
    NOTE: hmm_regime comes from ctx.smc (SMCContext), not ctx.i4 — schemas.I4Context
    does not have hmm_regime (D-09/D-10 rewrite, Plan 05).
    """
    i1_ctx = context.i1
    i4_ctx = context.i4
    i6_ctx = context.i6
    i7_ctx = context.i7
    bar_ctx = context.bar
    smc_ctx = context.smc

    return {
        "symbol": context.symbol,
        "timeframe": context.timeframe,
        "ts": context.ts,
        "winner_plugin": i7_ctx.winner_plugin if i7_ctx else None,
        "winner_direction": i7_ctx.winner_direction if i7_ctx else None,
        "winner_confidence": i7_ctx.winner_confidence if i7_ctx else None,
        "atr": i1_ctx.atr_14 if i1_ctx else None,
        "rsi": i1_ctx.rsi_14 if i1_ctx else None,
        "adx": i1_ctx.adx_14 if i1_ctx else None,
        # hmm_regime lives on SMCContext (not I4Context) per schemas.py
        "hmm_regime": smc_ctx.hmm_regime if smc_ctx else None,
        "trend_regime": i4_ctx.trend_regime if i4_ctx else None,
        "vol_regime": i4_ctx.vol_regime if i4_ctx else None,
        "garch_vol_ratio": i4_ctx.garch_vol_ratio if i4_ctx else None,
        "ctf_trend_alignment": i6_ctx.ctf_trend_alignment if i6_ctx else None,
        "ctf_regime_agreement": i6_ctx.ctf_regime_agreement if i6_ctx else None,
        "ctf_fvg_alignment": i6_ctx.ctf_fvg_alignment if i6_ctx else None,
        "ctf_ob_alignment": i6_ctx.ctf_ob_alignment if i6_ctx else None,
        "vwap": i4_ctx.vwap if i4_ctx else None,
        "poc_price": i4_ctx.poc_price if i4_ctx else None,
        "poc_price_rolling": i4_ctx.poc_price_rolling if i4_ctx else None,
        "price": bar_ctx.close if bar_ctx else None,
        "volume": bar_ctx.volume if bar_ctx else None,
    }
