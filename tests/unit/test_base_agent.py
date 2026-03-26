"""TDD tests for BaseAgent abstract base class.

RED phase: All tests are expected to fail until src/core/agent/base.py is created.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from src.core.agent.base import BaseAgent


class MinimalAgent(BaseAgent):
    """Minimal concrete subclass used for testing. Implements _run as no-op."""

    async def _run(self) -> None:
        pass


@pytest.fixture
def agent() -> MinimalAgent:
    return MinimalAgent(name="test_agent")


def test_base_agent_is_abstract() -> None:
    """BaseAgent cannot be instantiated directly — it is abstract."""
    assert inspect.isabstract(BaseAgent)


def test_minimal_agent_inherits(agent: MinimalAgent) -> None:
    """A concrete subclass with _run() can be instantiated and is a BaseAgent."""
    assert isinstance(agent, BaseAgent)


def test_base_agent_has_lifecycle_methods(agent: MinimalAgent) -> None:
    """Instance has the four required lifecycle methods."""
    assert hasattr(agent, "start")
    assert hasattr(agent, "stop")
    assert hasattr(agent, "_report_consumer_lag")
    assert hasattr(agent, "_register_signal_handlers")


def test_base_agent_name_and_logger(agent: MinimalAgent) -> None:
    """agent.name matches constructor arg; agent.logger is a structlog BoundLogger."""
    assert agent.name == "test_agent"
    # structlog bound logger has a 'bind' method characteristic of BoundLogger
    assert hasattr(agent.logger, "bind")


def test_stop_event_exists(agent: MinimalAgent) -> None:
    """agent._stop_event is an asyncio.Event that starts unset."""
    assert isinstance(agent._stop_event, asyncio.Event)
    assert not agent._stop_event.is_set()


@pytest.mark.asyncio
async def test_report_consumer_lag_is_noop_by_default(agent: MinimalAgent) -> None:
    """_report_consumer_lag() does not raise; it loops until _stop_event is set."""
    # Set stop event immediately so the loop exits on first iteration
    agent._stop_event.set()
    # Should complete without raising
    await agent._report_consumer_lag()
