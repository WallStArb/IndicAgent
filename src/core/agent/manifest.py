"""ProcessManifest — self-describing declaration of a process's agents, topics, and thresholds.

Replaces AgentRegistry (Phase 52.6). Not a singleton — passed explicitly (dependency injection).
Safe to instantiate multiple times in tests.
"""

from __future__ import annotations

import asyncio

from src.core.agent.base import BaseAgent


class ProcessManifest:
    """Self-describing declaration of a process's agents, topics, and thresholds.

    Each systemd service instantiates one ProcessManifest. It is not a singleton —
    it is passed explicitly to any code that needs it (dependency injection, not
    global state). Safe to instantiate multiple times in tests.
    """

    def __init__(self, agents: list[BaseAgent]) -> None:
        names = [a.name for a in agents]
        if len(names) != len(set(names)):
            duplicates = [n for n in set(names) if names.count(n) > 1]
            raise ValueError(f"Duplicate agent names in manifest: {duplicates}")
        self._agents: dict[str, BaseAgent] = {a.name: a for a in agents}

    # ── Topology ─────────────────────────────────────────────────────────

    @property
    def topics_consumed(self) -> set[str]:
        """Union of all topics consumed across agents."""
        return {t for a in self._agents.values() for t in a.topics_consumed}

    @property
    def topics_produced(self) -> set[str]:
        """Union of all topics produced across agents."""
        return {t for a in self._agents.values() for t in a.topics_produced}

    def topology(self) -> dict:
        """DAG-compatible description of this process node.

        Returns a dict keyed by agent name. Each value has:
        - "consumes": list of topic strings this agent reads
        - "produces": list of topic strings this agent writes
        - "lag_threshold": consumer lag threshold before alerting
        """
        return {
            name: {
                "consumes": agent.topics_consumed,
                "produces": agent.topics_produced,
                "lag_threshold": agent.lag_threshold_messages,
            }
            for name, agent in self._agents.items()
        }

    # ── Health ────────────────────────────────────────────────────────────

    def health(self) -> dict:
        """Per-agent health snapshot. Suitable for a /health HTTP endpoint."""
        return {
            name: {"running": agent.running}
            for name, agent in self._agents.items()
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Start all agents concurrently."""
        await asyncio.gather(*[a.start() for a in self._agents.values()])

    async def stop_all(self) -> None:
        """Stop all agents concurrently.

        Future: drain in reverse topological order (consumers before producers)
        once multi-agent processes exist and topology sort is needed.
        """
        await asyncio.gather(*[a.stop() for a in self._agents.values()])

    # ── Validation ────────────────────────────────────────────────────────

    async def validate_topics(self, admin_client) -> list[str]:
        """Return list of declared topics that don't exist in Redpanda.

        Call before start_all() to fail fast rather than silently consume nothing.
        A missing topic at startup is a configuration error, not a runtime error —
        surface it immediately.

        Full implementation deferred to Phase 52.7 (Grafana Tempo infra phase)
        when KafkaAdminClient.list_topics() comparison will be wired alongside
        OTEL_EXPORTER_OTLP_ENDPOINT configuration.
        """
        raise NotImplementedError(
            "validate_topics() will be implemented in Phase 52.7 alongside "
            "Grafana Tempo infrastructure. At that point, this method compares "
            "self.topics_consumed | self.topics_produced against "
            "admin_client.list_topics() and returns any missing topic names."
        )
