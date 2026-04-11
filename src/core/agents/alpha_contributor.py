"""IAlphaContributor — protocol for all swarm intelligence agents.

Canonical location: src/core/agents/alpha_contributor.py
Imported by src/intelligence/swarm/interface.py for backward compat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.intelligence.schemas import AgentResult
    from src.intelligence.swarm.context import SwarmContext


@runtime_checkable
class IAlphaContributor(Protocol):
    """Standard interface for all swarm intelligence contributors."""

    agent_id: str
    path: Literal["deterministic", "llm_swarm"]
    shadow_only: bool
    latency_budget_ms: float

    async def compute(self, context: SwarmContext) -> AgentResult:
        """Compute alpha contribution. Must not raise — return neutral AgentResult on any error."""
        ...

    async def warm_up(self) -> None:
        """Called once at service start — pre-load models, validate dependencies."""
        ...

    def health_check(self) -> dict[str, Any]:
        """Return health metadata for Prometheus scrape endpoint."""
        ...
