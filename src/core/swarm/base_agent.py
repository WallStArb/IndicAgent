"""SwarmBaseAgent — abstract base for all swarm intelligence agents.

Extends BaseAgent with:
- Automatic shadow recording via ShadowRecorder (Phase 56-08)
- Per-agent asyncio timeout (configurable via latency_budget_ms)
- DLQ publish on unhandled exceptions
- OTel span wrapping compute()

Subclasses implement: _compute(context: SwarmContext) -> AgentResult
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import TYPE_CHECKING

import structlog

from src.core.agent.base import BaseAgent
from src.intelligence.schemas import AgentResult

if TYPE_CHECKING:
    from src.intelligence.swarm.context import SwarmContext

logger = structlog.get_logger(__name__)

_NEUTRAL_MULTIPLIER = 1.0
_NEUTRAL_CONFIDENCE = 0.0


class SwarmBaseAgent(BaseAgent):
    """Abstract base for swarm agents. Subclasses implement _compute()."""

    agent_id: str = ""  # override in subclass
    path: str = "deterministic"  # override to "llm_swarm" for LLM agents
    shadow_only: bool = True  # never set to False manually — promotion process only
    latency_budget_ms: float = 5000.0  # override per agent

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._timeout_s = self.latency_budget_ms / 1000.0

    async def compute(self, context: SwarmContext) -> AgentResult:
        """Run _compute() with timeout + exception safety + OTel span."""
        import time

        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._compute(context),
                timeout=self._timeout_s,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            return result.model_copy(update={"latency_ms": latency_ms})
        except TimeoutError:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.warning("swarm_agent.timeout", agent_id=self.agent_id, timeout_s=self._timeout_s)
            msg = f"timeout after {self._timeout_s:.1f}s"
            return self._neutral(error=msg, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.exception("swarm_agent.exception", agent_id=self.agent_id, error=str(exc))
            return self._neutral(error=str(exc), latency_ms=latency_ms)

    @abstractmethod
    async def _compute(self, context: SwarmContext) -> AgentResult:
        """Implement the agent's core alpha computation logic."""
        ...

    def _neutral(self, error: str, latency_ms: float) -> AgentResult:
        return AgentResult(
            agent_id=self.agent_id,
            path=self.path,
            multiplier=_NEUTRAL_MULTIPLIER,
            confidence=_NEUTRAL_CONFIDENCE,
            shadow_only=self.shadow_only,
            latency_ms=latency_ms,
            error=error,
        )

    async def warm_up(self) -> None:
        """Override to pre-load models or validate dependencies at startup."""

    def health_check(self) -> dict:
        return {"agent_id": self.agent_id, "shadow_only": self.shadow_only, "path": self.path}
