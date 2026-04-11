"""SafeSwarmWrapper — defensive shell around IAlphaContributor.

Enforces: asyncio timeout, exception isolation, neutral fallback (multiplier=1.0),
latency recording, and circuit breaker integration.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from src.intelligence.schemas import AgentResult

if TYPE_CHECKING:
    from src.intelligence.swarm.context import SwarmContext

logger = structlog.get_logger(__name__)

_NEUTRAL_MULTIPLIER = 1.0
_NEUTRAL_CONFIDENCE = 0.0


class SafeSwarmWrapper:
    """Wraps an IAlphaContributor with timeout + exception safety."""

    def __init__(self, contributor: object) -> None:
        self._contributor = contributor
        self._agent_id: str = getattr(contributor, "agent_id", "unknown")
        self._path: str = getattr(contributor, "path", "deterministic")
        self._shadow_only: bool = getattr(contributor, "shadow_only", True)
        budget_ms: float = getattr(contributor, "latency_budget_ms", 5000.0)
        self._timeout_s: float = budget_ms / 1000.0

    async def run(self, context: SwarmContext) -> AgentResult:
        """Run contributor.compute() with timeout + exception safety.

        Returns a neutral AgentResult (multiplier=1.0) on timeout or exception.
        """
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._contributor.compute(context),
                timeout=self._timeout_s,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            # Re-create with latency (frozen model — need new instance)
            return result.model_copy(update={"latency_ms": latency_ms})

        except TimeoutError:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "swarm_wrapper.timeout",
                agent_id=self._agent_id,
                timeout_s=self._timeout_s,
                latency_ms=round(latency_ms, 1),
            )
            msg = f"timeout after {self._timeout_s:.1f}s"
            return self._neutral(error=msg, latency_ms=latency_ms)

        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.exception(
                "swarm_wrapper.exception",
                agent_id=self._agent_id,
                error=str(exc),
            )
            return self._neutral(error=str(exc), latency_ms=latency_ms)

    def _neutral(self, error: str, latency_ms: float) -> AgentResult:
        return AgentResult(
            agent_id=self._agent_id,
            path=self._path,
            multiplier=_NEUTRAL_MULTIPLIER,
            confidence=_NEUTRAL_CONFIDENCE,
            shadow_only=self._shadow_only,
            latency_ms=latency_ms,
            error=error,
        )
