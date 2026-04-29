"""SafeAgentWrapper — defensive shell around BaseAIAgent instances."""

from __future__ import annotations

import asyncio
import time

import structlog

from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext
from src.core.ai.output import AgentOutput

logger = structlog.get_logger(__name__)


class SafeAgentWrapper:
    """Defensive shell around any BaseAIAgent.

    Enforces latency_budget_ms via asyncio.wait_for(). On timeout or
    exception, returns a neutral AgentOutput so one failing agent never
    blocks the group dispatch.

    D-51: Latency budget read from agent.latency_budget_ms (configurable),
    not hardcoded.
    """

    def __init__(self, agent: BaseAIAgent) -> None:
        self._agent = agent
        self._agent_id: str = agent.agent_id
        self._shadow_only: bool = agent.shadow_only
        # D-51: configurable latency from agent, not hardcoded
        self._timeout_s: float = agent.latency_budget_ms / 1000.0

    async def compute(self, context: AIContext) -> AgentOutput:
        """Run agent.compute() with timeout + exception safety.

        Returns a neutral AgentOutput on timeout or exception.
        """
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._agent.compute(context),
                timeout=self._timeout_s,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            return result.model_copy(update={"latency_ms": latency_ms})

        except TimeoutError:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "safe_wrapper.timeout",
                agent_id=self._agent_id,
                timeout_s=self._timeout_s,
                latency_ms=round(latency_ms, 1),
            )
            return self._neutral(error=f"timeout after {self._timeout_s:.1f}s",
                                 latency_ms=latency_ms)

        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.exception(
                "safe_wrapper.exception",
                agent_id=self._agent_id,
                error=str(exc),
            )
            return self._neutral(error=str(exc), latency_ms=latency_ms)

    def _neutral(self, error: str, latency_ms: float) -> AgentOutput:
        """Return neutral AgentOutput for error/timeout cases."""
        return AgentOutput(
            agent_id=self._agent_id,
            group="",  # empty for neutral
            output_type="neutral",
            payload={},
            shadow_only=self._shadow_only,
            latency_ms=latency_ms,
            error=error,
        )
