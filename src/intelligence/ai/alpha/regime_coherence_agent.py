"""RegimeCoherenceAnalyzer — setup-vs-regime fit multiplier (Phase 80, D-05)."""

from __future__ import annotations

from typing import Any, ClassVar

import structlog
from pydantic import BaseModel, field_validator

from src.core.ai.context import SignalContext, Tier
from src.core.ai.evaluator import Evaluator
from src.core.ai.output import AgentOutput
from src.core.llm.chain import LLMProviderChain
from src.intelligence.ai.alpha.regime_coherence_prompts import (
    ACTIVE_VERSION,
    build_regime_coherence_prompt,
)

logger = structlog.get_logger(__name__)

_SYSTEM_MESSAGE = (
    "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
    "Your entire response must be a single JSON object starting with { and ending with }. "
    "Phase 80 policy: discount-only — regime_fit and confidence in [0.0, 1.0]. "
    "reasoning must be under 100 words."
)


class RegimeCoherenceResult(BaseModel):
    """Pydantic model for validated regime coherence agent LLM output."""

    regime_fit: float
    confidence: float
    mismatches: list[str]
    reasoning: str

    @field_validator("regime_fit", "confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("mismatches", mode="before")
    @classmethod
    def _coerce_list(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return [str(v)]
        return [str(m) for m in v]

    @field_validator("reasoning", mode="before")
    @classmethod
    def _coerce_str(cls, v: object) -> str:
        return str(v) if v is not None else ""


class RegimeCoherenceAnalyzer(Evaluator):
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
    # Phase 109: shadow_only defaults to True (FAIL-CLOSED).
    # Promotion to live requires an explicit ai.agent.<agent_id>.shadow_mode=false
    # config entry. If config load fails or the key is missing, agent STAYS shadow.
    shadow_only: bool = True

    def _apply_shadow_mode_config(self) -> None:
        """Read ai.agent.<self.agent_id>.shadow_mode from config; fail-closed on miss.

        Called by:
          - AlphaSwarm._setup() after agents are constructed (initial load)
          - AlphaSwarm._on_config_message_received() on Kafka update
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

    async def _compute(self, context: SignalContext) -> AgentOutput:
        """Core computation: build prompt -> call LLM -> parse JSON -> multiplier.

        Phase 80 policy: discount-only — regime_fit × confidence.
        """
        prompt = build_regime_coherence_prompt(context)

        result, call_id = await self._llm_generate_structured(
            context,
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            response_model=RegimeCoherenceResult,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )

        if result is None:
            logger.warning(
                "regime_coherence_agent.structured_output_failed",
                agent_id=self.agent_id,
            )
            # Do NOT call _report_parse_failure here: the chain already published a failure
            # audit row with succeeded=False/parse_success=False. _report_parse_failure is
            # only for the _llm_generate (unstructured) path where the initial audit row
            # records success and a corrective update is needed.
            return self._neutral(error="Structured output failed", latency_ms=0.0)

        regime_fit = result.regime_fit
        llm_confidence = result.confidence
        multiplier = regime_fit * llm_confidence

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=llm_confidence,
            payload={
                "regime_fit": regime_fit,
                "mismatches": result.mismatches,
                "reasoning": result.reasoning,
            },
            prompt_version=ACTIVE_VERSION,
        )
