"""TDD tests for BaseAgent abstract base class.

RED phase: All new tests are expected to fail until src/core/agent/base.py is enhanced.
Existing tests (Plan 01) must continue to pass.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.agent.base import BaseAgent


class MinimalAgent(BaseAgent):
    """Minimal concrete subclass used for testing. Implements _run as no-op."""

    async def _run(self) -> None:
        pass


@pytest.fixture
def agent() -> MinimalAgent:
    return MinimalAgent(name="test_agent")


# ---------------------------------------------------------------------------
# Existing tests (Plan 01) — must remain GREEN
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# New tests (Plan 02) — RED phase: will fail before implementation
# ---------------------------------------------------------------------------


def test_metrics_port_none_by_default() -> None:
    """metrics_port defaults to None when not specified."""
    a = MinimalAgent(name="x")
    assert a._metrics_port is None


def test_metrics_port_stored() -> None:
    """metrics_port value is stored in _metrics_port."""
    a = MinimalAgent(name="x", metrics_port=9999)
    assert a._metrics_port == 9999


def test_tracer_attribute_exists() -> None:
    """agent.tracer is not None and has start_span method."""
    a = MinimalAgent(name="x")
    assert a.tracer is not None
    assert hasattr(a.tracer, "start_span")


def test_running_property_initially_true(agent: MinimalAgent) -> None:
    """Fresh agent: running is True because stop_event is not set."""
    assert agent.running is True


def test_running_property_after_stop_event(agent: MinimalAgent) -> None:
    """After setting stop_event, running becomes False."""
    agent._stop_event.set()
    assert agent.running is False


def test_topics_consumed_default_empty(agent: MinimalAgent) -> None:
    """topics_consumed returns empty list by default."""
    assert agent.topics_consumed == []


def test_topics_produced_default_empty(agent: MinimalAgent) -> None:
    """topics_produced returns empty list by default."""
    assert agent.topics_produced == []


def test_lag_threshold_default_1000(agent: MinimalAgent) -> None:
    """lag_threshold_messages returns 1000 by default."""
    assert agent.lag_threshold_messages == 1000


@pytest.mark.asyncio
async def test_setup_called_before_run() -> None:
    """_setup() is called before _run() when start() is invoked."""
    call_order: list[str] = []

    class OrderAgent(BaseAgent):
        async def _setup(self) -> None:
            call_order.append("setup")

        async def _run(self) -> None:
            call_order.append("run")

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = OrderAgent(name="order")
        await a.start()

    assert call_order.index("setup") < call_order.index("run")


@pytest.mark.asyncio
async def test_teardown_called_after_run() -> None:
    """_teardown() is called after _run() completes normally."""
    call_order: list[str] = []

    class TeardownAgent(BaseAgent):
        async def _run(self) -> None:
            call_order.append("run")

        async def _teardown(self) -> None:
            call_order.append("teardown")

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = TeardownAgent(name="td")
        await a.start()

    assert call_order.index("run") < call_order.index("teardown")


@pytest.mark.asyncio
async def test_teardown_called_on_run_exception() -> None:
    """_teardown() is called even when _run() raises an exception."""
    teardown_called = False

    class ExcAgent(BaseAgent):
        async def _run(self) -> None:
            raise RuntimeError("boom")

        async def _teardown(self) -> None:
            nonlocal teardown_called
            teardown_called = True

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = ExcAgent(name="exc")
        with pytest.raises(RuntimeError):
            await a.start()

    assert teardown_called


@pytest.mark.asyncio
async def test_exception_capture_logs_and_reraises() -> None:
    """start() logs agent.run_failed via logger.exception and re-raises the exception."""

    class ExcAgent(BaseAgent):
        async def _run(self) -> None:
            raise RuntimeError("boom")

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = ExcAgent(name="exc")
        mock_logger = MagicMock()
        a.logger = mock_logger

        with pytest.raises(RuntimeError):
            await a.start()

    mock_logger.exception.assert_called_once()
    call_args = mock_logger.exception.call_args
    assert call_args[0][0] == "agent.run_failed"


@pytest.mark.asyncio
async def test_send_to_dlq_logs_and_does_not_raise(agent: MinimalAgent) -> None:
    """_send_to_dlq() logs an error and does not raise."""
    mock_logger = MagicMock()
    agent.logger = mock_logger

    await agent._send_to_dlq({"key": "val"}, ValueError("bad"))

    mock_logger.error.assert_called_once()
    # Should not raise at all — test passes if we get here


@pytest.mark.asyncio
async def test_metrics_server_started_when_port_set() -> None:
    """start_metrics_server is called with the configured port when metrics_port is set."""
    with (
        patch("src.core.agent.base.start_metrics_server") as mock_start,
        patch("src.core.agent.base.BaseAgent._register_signal_handlers"),
    ):
        a = MinimalAgent(name="x", metrics_port=9999)
        await a.start()

    mock_start.assert_called_once_with(port=9999)


@pytest.mark.asyncio
async def test_metrics_server_not_started_when_port_none() -> None:
    """start_metrics_server is NOT called when metrics_port is None."""
    with (
        patch("src.core.agent.base.start_metrics_server") as mock_start,
        patch("src.core.agent.base.BaseAgent._register_signal_handlers"),
    ):
        a = MinimalAgent(name="x")
        await a.start()

    mock_start.assert_not_called()
