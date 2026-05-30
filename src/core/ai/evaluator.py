"""Evaluator — abstract base for Phase 80 swarm multiplier agents."""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable
from typing import Any, ClassVar

import structlog

from src.core.ai.base_agent import BaseAIWorker
from src.core.ai.context import SignalContext
from src.core.ai.output import AgentOutput
from src.core.ai.prompt_utils import clamp, parse_llm_json

logger = structlog.get_logger(__name__)


class Evaluator(BaseAIWorker, ABC):
    """Abstract base for all multiplier-output swarm agents.

    Provides:
    - _parse_multiplier_response(raw, validator_fn) — direct JSON → regex fallback → None
    - _build_multiplier_output(context, multiplier, confidence, payload, prompt_version)
      — canonical AgentOutput with multiplier clamped to [0.0, 2.0]
    - Abstract output_schema: ClassVar[dict] — documents expected LLM JSON keys

    All concrete swarm agents extend this, NEVER BaseAIWorker directly.
    Phase 80 policy is discount-only (formulas should produce multiplier <= 1.0
    until calibration data exists). Clamp range [0.0, 2.0] preserved for future boosting.
    """

    output_schema: ClassVar[dict]  # subclasses MUST override with expected LLM JSON key types

    def _parse_multiplier_response(
        self, raw: str, validator_fn: Callable[[dict], dict | None]
    ) -> dict | None:
        """Parse LLM JSON response: direct parse → regex fallback → None.

        Delegates to prompt_utils.parse_llm_json — single source of truth.
        """
        return parse_llm_json(raw, validator_fn)

    def _build_multiplier_output(
        self,
        context: SignalContext,
        multiplier: float,
        confidence: float,
        payload: dict[str, Any],
        prompt_version: str,
    ) -> AgentOutput:
        """Construct canonical AgentOutput with multiplier clamped to [0.0, 2.0]."""
        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            signal_id=context.signal_id,
            symbol=context.symbol,
            timeframe=context.timeframe,
            ts=context.ts,
            output_type="multiplier",
            payload={
                "multiplier": clamp(multiplier, 0.0, 2.0),
                "confidence": clamp(confidence, 0.0, 1.0),
                "prompt_version": prompt_version,
                **payload,
            },
            shadow_only=self.shadow_only,
        )
