"""Tests for ProcessManifest — self-describing process topology (Phase 52.6)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.core.agent.base import BaseAgent
from src.core.agent.manifest import ProcessManifest


class FakeAgent(BaseAgent):
    """Minimal concrete agent for ProcessManifest testing."""

    def __init__(
        self,
        name: str,
        consumed: list[str] | None = None,
        produced: list[str] | None = None,
        lag: int = 1000,
    ):
        super().__init__(name=name)
        self._consumed = consumed or []
        self._produced = produced or []
        self._lag = lag

    @property
    def topics_consumed(self) -> list[str]:
        return self._consumed

    @property
    def topics_produced(self) -> list[str]:
        return self._produced

    @property
    def lag_threshold_messages(self) -> int:
        return self._lag

    async def _run(self) -> None:
        pass


@pytest.fixture
def agent_a() -> FakeAgent:
    return FakeAgent(
        name="agent_a",
        consumed=["topic.bars"],
        produced=["topic.indicators"],
        lag=500,
    )


@pytest.fixture
def agent_b() -> FakeAgent:
    return FakeAgent(
        name="agent_b",
        consumed=["topic.indicators"],
        produced=["topic.signals"],
        lag=1000,
    )


@pytest.fixture
def manifest(agent_a: FakeAgent, agent_b: FakeAgent) -> ProcessManifest:
    return ProcessManifest([agent_a, agent_b])


def test_topology_contains_all_agents(
    manifest: ProcessManifest, agent_a: FakeAgent, agent_b: FakeAgent
) -> None:
    topo = manifest.topology()
    assert "agent_a" in topo
    assert "agent_b" in topo


def test_topology_agent_fields(manifest: ProcessManifest) -> None:
    topo = manifest.topology()
    assert topo["agent_a"]["consumes"] == ["topic.bars"]
    assert topo["agent_a"]["produces"] == ["topic.indicators"]
    assert topo["agent_a"]["lag_threshold"] == 500


def test_topics_consumed_union(manifest: ProcessManifest) -> None:
    assert manifest.topics_consumed == {"topic.bars", "topic.indicators"}


def test_topics_produced_union(manifest: ProcessManifest) -> None:
    assert manifest.topics_produced == {"topic.indicators", "topic.signals"}


def test_health_all_running(manifest: ProcessManifest) -> None:
    h = manifest.health()
    assert h["agent_a"]["running"] is True
    assert h["agent_b"]["running"] is True


def test_health_after_stop_event(
    manifest: ProcessManifest, agent_a: FakeAgent
) -> None:
    agent_a._stop_event.set()
    h = manifest.health()
    assert h["agent_a"]["running"] is False
    assert h["agent_b"]["running"] is True


def test_duplicate_agent_name_raises() -> None:
    a1 = FakeAgent(name="duplicate")
    a2 = FakeAgent(name="duplicate")
    with pytest.raises(ValueError, match="Duplicate agent names"):
        ProcessManifest([a1, a2])


@pytest.mark.asyncio
async def test_validate_topics_raises_not_implemented(
    manifest: ProcessManifest,
) -> None:
    with pytest.raises(NotImplementedError):
        await manifest.validate_topics(admin_client=None)


@pytest.mark.asyncio
async def test_start_all_calls_each_agent(
    agent_a: FakeAgent, agent_b: FakeAgent
) -> None:
    manifest = ProcessManifest([agent_a, agent_b])
    agent_a.start = AsyncMock()
    agent_b.start = AsyncMock()
    await manifest.start_all()
    agent_a.start.assert_called_once()
    agent_b.start.assert_called_once()


@pytest.mark.asyncio
async def test_stop_all_calls_each_agent(
    agent_a: FakeAgent, agent_b: FakeAgent
) -> None:
    manifest = ProcessManifest([agent_a, agent_b])
    agent_a.stop = AsyncMock()
    agent_b.stop = AsyncMock()
    await manifest.stop_all()
    agent_a.stop.assert_called_once()
    agent_b.stop.assert_called_once()


def test_not_a_singleton() -> None:
    a = FakeAgent(name="x")
    m1 = ProcessManifest([a])
    b = FakeAgent(name="y")
    m2 = ProcessManifest([b])
    assert m1 is not m2
