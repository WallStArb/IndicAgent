"""BaseAIAgent — universal base class for all AI agents."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

import structlog
from opentelemetry.trace import StatusCode
from pydantic import BaseModel

from src.core.agent.base import BaseAgent
from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput
from src.core.service_utils import format_iso_ts
from src.observability.metrics import (
    AI_AGENT_DURATION_MS,
    AI_AGENT_ERRORS_TOTAL,
    AI_AGENT_INVOCATIONS_TOTAL,
    LLM_EMPTY_RESPONSES,
    LLM_PARSE_FAILURES,
)
from src.observability.spans import ATTR_AGENT_ID, ATTR_SYMBOL, ATTR_TF

if TYPE_CHECKING:
    from src.core.ai.lineage import LineageRecorder
    from src.core.llm.chain import LLMProviderChain

logger = structlog.get_logger(__name__)


@runtime_checkable
class IAIAgent(Protocol):
    """Protocol for AI agents — enables isinstance() checks and type hints.

    All AI agents must implement this interface. BaseAIAgent provides
    the default implementation; subclasses only override _compute().
    """

    agent_id: str
    group: str
    tiers_needed: frozenset[Tier]
    shadow_only: bool
    latency_budget_ms: float

    async def compute(self, context: AIContext) -> AgentOutput: ...
    async def _compute(self, context: AIContext) -> AgentOutput: ...


class BaseAIAgent(BaseAgent, ABC):
    """Abstract base for all AI agents.

    Provides:
    - Wall-clock timing capture in compute() wrapper
    - asyncio.wait_for timeout enforcement (configurable via latency_budget_ms)
    - Exception handling with neutral AgentOutput fallback
    - Extension hooks (_on_error, _on_guardrail_violation, _audit_payload)

    Subclasses must implement:
    - _compute(context: AIContext) -> AgentOutput

    Inherits from BaseAgent for full lifecycle:
    - SIGTERM/SIGINT handling
    - Structured logging (self.logger)
    - OTel tracing (self.tracer)

    D-51: Latency budgets configurable via latency_budget_ms class attribute.
    Default 5000ms ceiling; tuned per agent (alpha: 3000ms, narrative: 60000ms).
    """

    agent_id: str = ""  # override in subclass
    group: str = ""  # "alpha", "narrative", "risk"
    tiers_needed: frozenset[Tier] = frozenset()
    shadow_only: bool = True  # D-37: always True, graduation_loop flips it
    latency_budget_ms: float = 5000.0  # D-51: default ceiling, tuned per agent
    prompt_version: str = ""  # override in subclass, e.g. "skeptic_v2"

    def __init__(self, name: str | None = None, *args: Any, **kwargs: Any) -> None:
        # If name not provided, use class name or agent_id
        if name is None:
            name = self.__class__.__name__
        super().__init__(*args, name=name, **kwargs)
        self._timeout_s = self.latency_budget_ms / 1000.0
        self._lineage: LineageRecorder | None = None
        self._llm: LLMProviderChain | None = None
        self._agent_labels: dict[str, str] = {"agent_id": self.agent_id, "group": self.group}

    async def compute(self, context: AIContext) -> AgentOutput:
        """Run _compute() with timing capture + exception safety.

        Returns AgentOutput with latency_ms populated.
        Returns neutral AgentOutput on timeout or exception.
        """
        with self.tracer.start_as_current_span(
            "agent.compute",
            attributes={
                ATTR_AGENT_ID: self.agent_id,
                "group": self.group,
                ATTR_SYMBOL: context.symbol,
                ATTR_TF: context.timeframe,
            },
        ) as span:
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self._compute(context),
                    timeout=self._timeout_s,
                )
                latency_ms = (time.monotonic() - t0) * 1000
                self._record_metrics("success", latency_ms)
                span.set_attribute("status", "success")
                span.set_attribute("latency_ms", round(latency_ms, 1))
                return result.model_copy(update={"latency_ms": latency_ms})

            except TimeoutError as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                self._record_metrics("timeout", latency_ms)
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                span.set_attribute("status", "timeout")
                span.set_attribute("latency_ms", round(latency_ms, 1))
                logger.warning(
                    "ai_agent.timeout",
                    agent_id=self.agent_id,
                    timeout_s=self._timeout_s,
                    latency_ms=round(latency_ms, 1),
                )
                await self._on_error(TimeoutError(f"timeout after {self._timeout_s:.1f}s"))
                return self._neutral(
                    error=f"timeout after {self._timeout_s:.1f}s", latency_ms=latency_ms
                )

            except Exception as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                self._record_metrics("error", latency_ms)
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                span.set_attribute("status", "error")
                span.set_attribute("error", str(exc)[:200])
                logger.exception(
                    "ai_agent.exception",
                    agent_id=self.agent_id,
                    error=str(exc),
                )
                await self._on_error(exc)
                return self._neutral(error=str(exc), latency_ms=latency_ms)

    async def _run(self) -> None:
        """BaseAIAgent subclasses are compute objects driven by BaseGroupService.

        They must not be started as standalone agents. This satisfies BaseAgent's
        abstract requirement while failing loudly if misused.
        """
        raise RuntimeError(
            f"{self.__class__.__name__} is a compute agent and cannot be run standalone. "
            "Use within a BaseGroupService."
        )

    @abstractmethod
    async def _compute(self, context: AIContext) -> AgentOutput:
        """Implement the agent's core computation logic.

        Subclasses must override this method. Returns AgentOutput with
        payload dict containing agent-specific results.
        """
        ...

    def _record_metrics(self, status: str, latency_ms: float) -> None:
        AI_AGENT_INVOCATIONS_TOTAL.add(1, {**self._agent_labels, "status": status})
        AI_AGENT_DURATION_MS.record(latency_ms, self._agent_labels)

    def _neutral(self, error: str, latency_ms: float) -> AgentOutput:
        """Return neutral AgentOutput for error/timeout cases."""
        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            output_type="neutral",
            payload={},
            shadow_only=self.shadow_only,
            latency_ms=latency_ms,
            error=error,
        )

    async def _llm_generate(
        self,
        context: AIContext,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
        model: str = "default",
        extra_audit: dict | None = None,
    ) -> tuple[str | None, str]:
        """Generate LLM response with automatic audit trail.

        Wraps self._llm.generate() with auto-injected audit_context so every
        LLM call is captured for model scoring. Agents MUST use this instead of
        calling self._llm.generate() directly — instrumentation should be
        impossible to forget.

        Returns (response, call_id). call_id is used by agents to publish
        corrective parse_success=False updates via _report_parse_failure().
        """
        with self.tracer.start_as_current_span(
            "agent.llm_generate",
            attributes={
                ATTR_AGENT_ID: self.agent_id,
                ATTR_SYMBOL: context.symbol,
                ATTR_TF: context.timeframe,
                "model": model,
            },
        ) as span:
            try:
                call_id = str(uuid4())
                audit_context: dict[str, Any] = {
                    "call_id": call_id,
                    "called_at": format_iso_ts(datetime.now(UTC)),
                    "symbol": context.symbol,
                    "signal_id": str(context.signal_id) if context.signal_id else None,
                    "group_name": self.group,
                    "agent_id": self.agent_id,
                    "prompt_version": self.prompt_version,
                    "timeframe": context.timeframe,
                    "prompt": prompt,
                    "succeeded": True,
                    "parse_success": True,
                }

                if context.smc is not None:
                    regime = getattr(context.smc, "hmm_regime", None)
                    if regime is not None:
                        audit_context["regime"] = str(int(regime))

                if extra_audit:
                    audit_context.update(extra_audit)

                result = await self._llm.generate(
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    model=model,
                    audit_context=audit_context,
                )
                if result is None:
                    span.set_attribute("llm.empty_response", True)
                    LLM_EMPTY_RESPONSES.add(1, self._agent_labels)
                return result, call_id
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                raise

    async def _llm_generate_structured(
        self,
        context: AIContext,
        prompt: str,
        system: str,
        response_model: type[BaseModel],
        max_tokens: int,
        timeout: float,
        extra_audit: dict | None = None,
    ) -> tuple[BaseModel | None, str]:
        """Generate structured output via instructor with automatic audit trail.

        Mirrors _llm_generate() -- same audit context, same span setup, same call_id
        returned for _report_parse_failure(). Supports extra_audit kwarg for additional
        audit fields, same as _llm_generate() (M4).

        Returns (result, call_id). result is None when instructor exhausts retries.
        Caller must invoke _report_parse_failure(call_id) on None result.
        """
        with self.tracer.start_as_current_span(
            "agent.llm_generate_structured",
            attributes={
                ATTR_AGENT_ID: self.agent_id,
                ATTR_SYMBOL: context.symbol,
                ATTR_TF: context.timeframe,
            },
        ) as span:
            try:
                call_id = str(uuid4())
                audit_context: dict[str, Any] = {
                    "call_id": call_id,
                    "called_at": format_iso_ts(datetime.now(UTC)),
                    "symbol": context.symbol,
                    "signal_id": str(context.signal_id) if context.signal_id else None,
                    "group_name": self.group,
                    "agent_id": self.agent_id,
                    "prompt_version": self.prompt_version,
                    "timeframe": context.timeframe,
                    "prompt": prompt,
                    "succeeded": True,
                    "parse_success": True,
                }

                if context.smc is not None:
                    regime = getattr(context.smc, "hmm_regime", None)
                    if regime is not None:
                        audit_context["regime"] = str(int(regime))

                if extra_audit:
                    audit_context.update(extra_audit)

                result = await self._llm.generate_structured(
                    prompt=prompt,
                    system=system,
                    response_model=response_model,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    audit_context=audit_context,
                    extra_audit=extra_audit,
                )
                if result is None:
                    span.set_attribute("llm.empty_response", True)
                    LLM_EMPTY_RESPONSES.add(1, self._agent_labels)
                return result, call_id
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                raise

    async def _report_parse_failure(self, call_id: str) -> None:
        """Publish a corrective parse_success=False update for the given call_id.

        Called by agents after _llm_generate succeeds (got a response) but
        JSON parsing of that response fails. Routes through the LLM chain's
        producer so the writer can UPDATE the llm_calls row.
        """
        LLM_PARSE_FAILURES.add(1, self._agent_labels)
        try:
            await self._llm._publish_parse_failure(call_id)
        except Exception as exc:
            logger.warning("agent.parse_failure_report_failed", call_id=call_id, error=str(exc))

    # -----------------------------------------------------------------------
    # Extension hooks (D-42, D-43, D-44) — future phases wire these to OTel,
    # guardrails, and data classification. Default implementations are no-ops.
    # -----------------------------------------------------------------------

    async def _on_error(self, error: Exception) -> None:
        """Hook: called when _compute() raises exception.

        Emits AI_AGENT_ERRORS_TOTAL counter with agent_id and error_type labels.
        Publishes an agent_prediction lineage event when self._lineage is set.
        """
        AI_AGENT_ERRORS_TOTAL.add(
            1,
            {**self._agent_labels, "error_type": type(error).__name__},
        )
        if self._lineage is not None:
            self._lineage.record(
                signal_id=UUID(int=0),
                event_type="agent_prediction",
                source=self.agent_id,
                metadata={"error": str(error), "error_type": type(error).__name__},
            )

    async def _on_guardrail_violation(self, output: AgentOutput) -> None:
        """Hook: called when guardrails detect policy violation.

        Future phase: wire to content filtering.
        """
        pass

    @property
    def _audit_payload(self) -> dict:
        """Hook: returns audit metadata for data classification.

        Future phase: use for data governance tracking.
        """
        return {}
