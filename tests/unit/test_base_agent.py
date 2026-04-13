"""TDD tests for BaseAgent abstract base class.

RED phase: All new tests are expected to fail until src/core/agent/base.py is enhanced.
Existing tests (Plan 01) must continue to pass.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# Watchdog notify tests
# ---------------------------------------------------------------------------


class _ConcreteAgent(BaseAgent):
    async def _run(self) -> None:
        self._stop_event.set()


@pytest.mark.asyncio
async def test_watchdog_notify_noop_when_no_socket():
    """_watchdog_notify exits immediately when NOTIFY_SOCKET is not set."""
    import os

    agent = _ConcreteAgent("test_agent")
    with patch.dict(os.environ, {}, clear=True):
        task = asyncio.create_task(agent._watchdog_notify())
        await asyncio.sleep(0.05)
        assert task.done()


@pytest.mark.asyncio
async def test_watchdog_notify_sends_when_socket_set():
    """_watchdog_notify calls sdnotify.notify('WATCHDOG=1') when socket is set."""
    import os
    from unittest.mock import MagicMock

    agent = _ConcreteAgent("test_agent")
    agent._stop_event = asyncio.Event()

    with patch.dict(os.environ, {"NOTIFY_SOCKET": "/run/test.sock", "WATCHDOG_USEC": "2000000"}):
        with patch("sdnotify.SystemdNotifier") as mock_cls:
            mock_notifier = MagicMock()
            mock_cls.return_value = mock_notifier

            task = asyncio.create_task(agent._watchdog_notify())
            await asyncio.sleep(0.15)
            agent._stop_event.set()
            await asyncio.sleep(0.05)
            task.cancel()

            assert mock_notifier.notify.call_count >= 1
            mock_notifier.notify.assert_called_with("WATCHDOG=1")


# ---------------------------------------------------------------------------
# Fix: _setup() failure must be logged (agent.setup_failed)
# RED: fails before the try/except around _setup() is added to BaseAgent.start()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_failure_logs_agent_setup_failed() -> None:
    """When _setup() raises, agent.setup_failed is logged with exception info."""

    class BrokenSetupAgent(BaseAgent):
        async def _setup(self) -> None:
            raise RuntimeError("kafka connection refused")

        async def _run(self) -> None:  # never reached
            pass

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = BrokenSetupAgent(name="broken")
        mock_logger = MagicMock()
        a.logger = mock_logger
        with pytest.raises(RuntimeError, match="kafka connection refused"):
            await a.start()

    logged_events = [c[0][0] for c in mock_logger.exception.call_args_list]
    assert "agent.setup_failed" in logged_events, (
        "Expected agent.setup_failed to be logged via logger.exception when _setup() raises"
    )


@pytest.mark.asyncio
async def test_setup_failure_does_not_log_run_failed() -> None:
    """When _setup() raises, agent.run_failed is NOT logged (run was never called)."""

    class BrokenSetupAgent(BaseAgent):
        async def _setup(self) -> None:
            raise RuntimeError("boom")

        async def _run(self) -> None:
            pass

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = BrokenSetupAgent(name="broken2")
        mock_logger = MagicMock()
        a.logger = mock_logger
        with pytest.raises(RuntimeError):
            await a.start()

    logged_events = [c[0][0] for c in mock_logger.exception.call_args_list]
    assert "agent.run_failed" not in logged_events, (
        "agent.run_failed must not be logged when _setup() fails — _run() was never called"
    )


# ---------------------------------------------------------------------------
# Plan 067-01 Task 1: BaseAgent Observability + Alert Publishing — RED phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_agent_has_crash_metrics() -> None:
    """BaseAgent tracks crashes via agent_crash_total counter."""

    class CrashAgent(BaseAgent):
        async def _run(self) -> None:
            raise RuntimeError("simulated crash")

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = CrashAgent(name="crash_test")
        # Get the crash total before and after
        from src.core.agent.base import AGENT_CRASH_TOTAL
        before = AGENT_CRASH_TOTAL.labels(agent="crash_test")._value.get()
        with pytest.raises(RuntimeError):
            await a.start()
        after = AGENT_CRASH_TOTAL.labels(agent="crash_test")._value.get()
        # Counter should have incremented
        assert after == before + 1


@pytest.mark.asyncio
async def test_base_agent_tracks_setup_success() -> None:
    """BaseAgent tracks successful _setup() completion."""

    class SuccessAgent(BaseAgent):
        async def _setup(self) -> None:
            pass

        async def _run(self) -> None:
            self._stop_event.set()

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = SuccessAgent(name="success_test")
        from src.core.agent.base import AGENT_SETUP_SUCCESS_TOTAL
        before = AGENT_SETUP_SUCCESS_TOTAL.labels(agent="success_test")._value.get()
        await a.start()
        after = AGENT_SETUP_SUCCESS_TOTAL.labels(agent="success_test")._value.get()
        assert after == before + 1


@pytest.mark.asyncio
async def test_base_agent_tracks_setup_failure() -> None:
    """BaseAgent tracks failed _setup() with error_type label."""

    class FailSetupAgent(BaseAgent):
        async def _setup(self) -> None:
            raise ValueError("config error")

        async def _run(self) -> None:
            pass

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = FailSetupAgent(name="fail_setup_test")
        from src.core.agent.base import AGENT_SETUP_FAILURE_TOTAL
        before = AGENT_SETUP_FAILURE_TOTAL.labels(agent="fail_setup_test", error_type="ValueError")._value.get()
        with pytest.raises(ValueError):
            await a.start()
        after = AGENT_SETUP_FAILURE_TOTAL.labels(agent="fail_setup_test", error_type="ValueError")._value.get()
        assert after == before + 1


@pytest.mark.asyncio
@pytest.mark.skip(reason="Task 4: topic_alert_requests not yet added to stream_keys.py")
async def test_base_agent_send_alert_publishes_to_kafka() -> None:
    """BaseAgent._send_alert() publishes to alert.requests topic via Kafka producer."""

    class AlertAgent(BaseAgent):
        async def _run(self) -> None:
            self._stop_event.set()

    # Mock topic_alert_requests at import point in base.py (Task 4 will add it to stream_keys.py)
    with patch("src.core.agent.base.topic_alert_requests", return_value="test.alert.requests"):
        with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
            a = AlertAgent(name="alert_test")
            # Mock the producer with an async method
            from unittest.mock import AsyncMock
            mock_producer = AsyncMock()
            a._producer = mock_producer
            # Mock settings for env_name
            a._settings = MagicMock()
            a._settings.env_name = "test"
            # Call _send_alert
            await a._send_alert("CRITICAL", "test alert", context={"symbol": "ES"})
            # Verify producer.publish was called
            mock_producer.produce.assert_called_once()
            call_args = mock_producer.produce.call_args
            assert "alert.requests" in call_args[0][0]  # topic contains alert.requests
            payload = call_args[0][1]
            assert payload["severity"] == "CRITICAL"
            assert payload["message"] == "test alert"
            assert payload["source"] == "alert_test"
            assert "timestamp" in payload
            assert payload["symbol"] == "ES"


@pytest.mark.asyncio
async def test_base_agent_send_alert_noop_without_producer() -> None:
    """BaseAgent._send_alert() is graceful no-op when producer not configured."""

    class NoProducerAgent(BaseAgent):
        async def _run(self) -> None:
            self._stop_event.set()

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = NoProducerAgent(name="no_producer_test")
        # No _producer attribute set
        # Should not raise
        await a._send_alert("CRITICAL", "test")
        # If we get here, test passes
