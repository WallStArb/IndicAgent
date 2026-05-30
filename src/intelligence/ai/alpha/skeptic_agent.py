"""skeptic_agent.py -- SkepticEvaluator (Evaluator subclass).

Pure compute class: prompt building + LLM call + JSON parse + transfer function.
No Kafka, no DB, no infrastructure -- all owned by dispatch layer.
"""

from __future__ import annotations

from typing import Any, ClassVar

import structlog

from src.core.ai.context import SignalContext, Tier
from src.core.ai.evaluator import Evaluator
from src.core.ai.output import AgentOutput
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.alpha.skeptic_prompts import (
    ACTIVE_VERSION,
    SkepticResult,
    build_skeptic_prompt,
)

logger = structlog.get_logger(__name__)

_SYSTEM_MESSAGE = (
    "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
    "Your entire response must be a single JSON object starting with { and ending with }. "
    "Schema: "
    '{"failure_probability": float, "confidence": float, '
    '"risk_factors": [str], "reasoning": str} '
    "reasoning must be under 100 words."
)


class SkepticEvaluator(Evaluator):
    """Devil's advocate alpha agent -- predicts signal failure probability.

    Per D-03: extends Evaluator, declares output_schema ClassVar.
    Per D-34: returns AgentOutput via _build_multiplier_output.
    Pure compute class -- dispatch layer owns infrastructure.
    """

    output_schema: ClassVar[dict] = {
        "failure_probability": float,
        "confidence": float,
        "risk_factors": list,
        "reasoning": str,
    }

    agent_id = "skeptic_v1"
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
        super().__init__(name="SkepticEvaluator", **kwargs)
        self._llm = llm_chain

    async def _compute(self, context: SignalContext) -> AgentOutput:
        """Core computation: build prompt -> call LLM -> parse JSON -> transfer function.

        Per D-01: full SignalContext dump in prompt.
        Per D-04: multiplier = (1.0 - failure_probability) * llm_confidence.
        Per D-06: raw values stored in payload, never overwrites signal_ledger.
        """
        # Build prompt — v2 passes SignalContext directly; v1 uses dict adapter
        if ACTIVE_VERSION == "skeptic_v2":
            prompt = build_skeptic_prompt(context)
        else:
            prompt = build_skeptic_prompt(_context_to_dict(context))

        result, call_id = await self._llm_generate_structured(
            context,
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            response_model=SkepticResult,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if result is None:
            logger.warning(
                "skeptic_agent.structured_output_failed",
                agent_id=self.agent_id,
            )
            # Do NOT call _report_parse_failure here: the chain already published a failure
            # audit row with succeeded=False/parse_success=False. _report_parse_failure is
            # only for the _llm_generate (unstructured) path where the initial audit row
            # records success and a corrective update is needed.
            return self._neutral(error="Structured output failed", latency_ms=0.0)

        failure_probability = result.failure_probability
        llm_confidence = result.confidence
        multiplier = (1.0 - failure_probability) * llm_confidence

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=llm_confidence,
            payload={
                "failure_probability": failure_probability,
                "risk_factors": result.risk_factors,
                "reasoning": result.reasoning,
            },
            prompt_version=ACTIVE_VERSION,
        )


def _context_to_dict(context: SignalContext) -> dict:
    """Convert SignalContext to dict for prompt building (v1 adapter — kept for rollback).

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
