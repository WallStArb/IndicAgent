"""TDD tests for AgentRegistry singleton.

RED phase: All tests are expected to fail until src/core/agent/registry.py is created.
"""

from __future__ import annotations

import pytest

from src.core.agent.base import BaseAgent
from src.core.agent.registry import AgentRegistry


class FakeAgent(BaseAgent):
    """Minimal concrete agent used for registry testing."""

    async def _run(self) -> None:
        pass


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Reset the AgentRegistry singleton before each test to prevent state leaks."""
    AgentRegistry._instance = None
    yield
    AgentRegistry._instance = None


def test_register_and_list() -> None:
    """Registering an agent makes its name appear in list_names()."""
    registry = AgentRegistry()
    agent = FakeAgent(name="fake")
    registry.register(agent)
    assert "fake" in registry.list_names()


def test_registry_is_singleton() -> None:
    """Multiple instantiations of AgentRegistry return the same object."""
    r1 = AgentRegistry()
    r2 = AgentRegistry()
    assert r1 is r2


def test_get_registered_agent() -> None:
    """get() returns the exact agent instance that was registered."""
    registry = AgentRegistry()
    agent = FakeAgent(name="fake")
    registry.register(agent)
    assert registry.get("fake") is agent


def test_get_unknown_returns_none() -> None:
    """get() returns None for an agent name that was never registered."""
    registry = AgentRegistry()
    assert registry.get("nonexistent") is None


def test_list_names_empty_initially() -> None:
    """A fresh registry (after singleton reset) has an empty list_names()."""
    registry = AgentRegistry()
    assert registry.list_names() == []
