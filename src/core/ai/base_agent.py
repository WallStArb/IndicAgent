"""BaseAIAgent — universal base class for all AI agents."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

import structlog

from src.core.agent.base import BaseAgent
from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput

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
    - Prometheus metrics (if metrics_port set)
    - OTel tracing (self.tracer)

    D-51: Latency budgets configurable via latency_budget_ms class attribute.
    Default 5000ms ceiling; tuned per agent (alpha: 3000ms, narrative: 60000ms).
    """

    agent_id: str = ""  # override in subclass
    group: str = ""  # "alpha", "narrative", "risk"
    tiers_needed: frozenset[Tier] = frozenset()
    shadow_only: bool = True  # D-37: always True, graduation_loop flips it
    latency_budget_ms: float = 5000.0  # D-51: default ceiling, tuned per agent

    def __init__(self, name: str | None = None, *args: Any, **kwargs: Any) -> None:
        # If name not provided, use class name or agent_id
        if name is None:
            name = self.__class__.__name__
        super().__init__(name=name, *args, **kwargs)
        self._timeout_s = self.latency_budget_ms / 1000.0

    async def compute(self, context: AIContext) -> AgentOutput:
        """Run _compute() with timing capture + exception safety.

        Returns AgentOutput with latency_ms populated.
        Returns neutral AgentOutput on timeout or exception.
        """
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._compute(context),
                timeout=self._timeout_s,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            # D-45: Timer context manager — latency captured via model_copy
            return result.model_copy(update={"latency_ms": latency_ms})

        except TimeoutError:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "ai_agent.timeout",
                agent_id=self.agent_id,
                timeout_s=self._timeout_s,
                latency_ms=round(latency_ms, 1),
            )
            await self._on_error(TimeoutError(f"timeout after {self._timeout_s:.1f}s"))
            return self._neutral(error=f"timeout after {self._timeout_s:.1f}s",
                                 latency_ms=latency_ms)

        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.exception(
                "ai_agent.exception",
                agent_id=self.agent_id,
                error=str(exc),
            )
            await self._on_error(exc)
            return self._neutral(error=str(exc), latency_ms=latency_ms)

    @abstractmethod
    async def _compute(self, context: AIContext) -> AgentOutput:
        """Implement the agent's core computation logic.

        Subclasses must override this method. Returns AgentOutput with
        payload dict containing agent-specific results.
        """
        ...

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

    # -----------------------------------------------------------------------
    # Extension hooks (D-42, D-43, D-44) — future phases wire these to OTel,
    # guardrails, and data classification. Default implementations are no-ops.
    # -----------------------------------------------------------------------

    async def _on_error(self, error: Exception) -> None:
        """Hook: called when _compute() raises exception.

        Future phase: wire to OTel span + alert.
        """
        pass

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
