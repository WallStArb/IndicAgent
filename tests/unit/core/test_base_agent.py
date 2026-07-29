"""TDD tests for BaseDaemon abstract base class.

RED phase: All new tests are expected to fail until src/core/agent/base.py is enhanced.
Existing tests (Plan 01) must continue to pass.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock, patch

import pytest

from src.core.agent.base import BaseDaemon


class MinimalAgent(BaseDaemon):
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
    """BaseDaemon cannot be instantiated directly — it is abstract."""
    assert inspect.isabstract(BaseDaemon)


def test_minimal_agent_inherits(agent: MinimalAgent) -> None:
    """A concrete subclass with _run() can be instantiated and is a BaseDaemon."""
    assert isinstance(agent, BaseDaemon)


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


def test_no_metrics_port_attribute() -> None:
    """metrics_port has been removed — accessing _metrics_port raises AttributeError."""
    a = MinimalAgent(name="x")
    with pytest.raises(AttributeError):
        _ = a._metrics_port


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

    class OrderAgent(BaseDaemon):
        async def _setup(self) -> None:
            call_order.append("setup")

        async def _run(self) -> None:
            call_order.append("run")

    with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
        a = OrderAgent(name="order")
        await a.start()

    assert call_order.index("setup") < call_order.index("run")


@pytest.mark.asyncio
async def test_teardown_called_after_run() -> None:
    """_teardown() is called after _run() completes normally."""
    call_order: list[str] = []

    class TeardownAgent(BaseDaemon):
        async def _run(self) -> None:
            call_order.append("run")

        async def _teardown(self) -> None:
            call_order.append("teardown")

    with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
        a = TeardownAgent(name="td")
        await a.start()

    assert call_order.index("run") < call_order.index("teardown")


@pytest.mark.asyncio
async def test_teardown_called_on_run_exception() -> None:
    """_teardown() is called even when _run() raises an exception."""
    teardown_called = False

    class ExcAgent(BaseDaemon):
        async def _run(self) -> None:
            raise RuntimeError("boom")

        async def _teardown(self) -> None:
            nonlocal teardown_called
            teardown_called = True

    with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
        a = ExcAgent(name="exc")
        with pytest.raises(RuntimeError):
            await a.start()

    assert teardown_called


@pytest.mark.asyncio
async def test_exception_capture_logs_and_reraises() -> None:
    """start() logs agent.run_failed via logger.exception and re-raises the exception."""

    class ExcAgent(BaseDaemon):
        async def _run(self) -> None:
            raise RuntimeError("boom")

    with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
        a = ExcAgent(name="exc")
        mock_logger = MagicMock()
        a.logger = mock_logger

        with pytest.raises(RuntimeError):
            await a.start()

    mock_logger.exception.assert_called_once()
    call_args = mock_logger.exception.call_args
    assert call_args[0][0] == "daemon.run_failed"


@pytest.mark.asyncio
async def test_send_to_dlq_logs_and_does_not_raise(agent: MinimalAgent) -> None:
    """_send_to_dlq() logs an error and does not raise."""
    mock_logger = MagicMock()
    agent.logger = mock_logger

    await agent._send_to_dlq({"key": "val"}, ValueError("bad"))

    mock_logger.error.assert_called_once()
    # Should not raise at all — test passes if we get here


@pytest.mark.asyncio
async def test_otel_providers_initialized_on_start_no_metrics_port() -> None:
    """BaseDaemon initializes OTel providers on start — no HTTP metrics server."""
    import src.core.agent.base as base_module

    with patch("src.core.agent.base.init_otel_providers") as mock_init:
        with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
            original = base_module._tracing_initialized
            base_module._tracing_initialized = False
            try:
                a = MinimalAgent(name="x")
                await a.start()
            finally:
                base_module._tracing_initialized = original

    mock_init.assert_called_once_with(service_name="x")


@pytest.mark.asyncio
async def test_otel_providers_initialized_on_start() -> None:
    """init_otel_providers is called once when BaseDaemon.start() is invoked."""
    import src.core.agent.base as base_module

    with patch("src.core.agent.base.init_otel_providers") as mock_init:
        with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
            # Reset module-level flag to ensure init is called
            original = base_module._tracing_initialized
            base_module._tracing_initialized = False
            try:
                a = MinimalAgent(name="x")
                await a.start()
            finally:
                base_module._tracing_initialized = original

    mock_init.assert_called_once_with(service_name="x")


# ---------------------------------------------------------------------------
# Watchdog notify tests
# ---------------------------------------------------------------------------


class _ConcreteAgent(BaseDaemon):
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
# RED: fails before the try/except around _setup() is added to BaseDaemon.start()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_failure_logs_agent_setup_failed() -> None:
    """When _setup() raises, agent.setup_failed is logged with exception info."""

    class BrokenSetupAgent(BaseDaemon):
        async def _setup(self) -> None:
            raise RuntimeError("kafka connection refused")

        async def _run(self) -> None:  # never reached
            pass

    with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
        a = BrokenSetupAgent(name="broken")
        mock_logger = MagicMock()
        a.logger = mock_logger
        with pytest.raises(RuntimeError, match="kafka connection refused"):
            await a.start()

    logged_events = [c[0][0] for c in mock_logger.exception.call_args_list]
    assert (
        "daemon.setup_failed" in logged_events
    ), "Expected daemon.setup_failed to be logged via logger.exception when _setup() raises"


@pytest.mark.asyncio
async def test_setup_failure_does_not_log_run_failed() -> None:
    """When _setup() raises, agent.run_failed is NOT logged (run was never called)."""

    class BrokenSetupAgent(BaseDaemon):
        async def _setup(self) -> None:
            raise RuntimeError("boom")

        async def _run(self) -> None:
            pass

    with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
        a = BrokenSetupAgent(name="broken2")
        mock_logger = MagicMock()
        a.logger = mock_logger
        with pytest.raises(RuntimeError):
            await a.start()

    logged_events = [c[0][0] for c in mock_logger.exception.call_args_list]
    assert (
        "daemon.run_failed" not in logged_events
    ), "daemon.run_failed must not be logged when _setup() fails — _run() was never called"


# ---------------------------------------------------------------------------
# Plan 067-01 Task 1: BaseDaemon Observability + Alert Publishing — RED phase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_agent_has_crash_metrics() -> None:
    """BaseDaemon tracks crashes via agent_crash_total counter (OTel .add call)."""
    from unittest.mock import MagicMock, patch

    class CrashAgent(BaseDaemon):
        async def _run(self) -> None:
            raise RuntimeError("simulated crash")

    mock_counter = MagicMock()
    with (
        patch("src.core.agent.base.BaseDaemon._register_signal_handlers"),
        patch("src.core.agent.base.AGENT_CRASH_TOTAL", mock_counter),
    ):
        a = CrashAgent(name="crash_test")
        with pytest.raises(RuntimeError):
            await a.start()
    # OTel counter: .add(1, {"agent": "crash_test"}) must have been called
    mock_counter.add.assert_called_once_with(1, {"agent": "crash_test"})


@pytest.mark.asyncio
async def test_base_agent_tracks_setup_success() -> None:
    """BaseDaemon tracks successful _setup() completion (OTel .add call)."""
    from unittest.mock import MagicMock, patch

    class SuccessAgent(BaseDaemon):
        async def _setup(self) -> None:
            pass

        async def _run(self) -> None:
            self._stop_event.set()

    mock_counter = MagicMock()
    with (
        patch("src.core.agent.base.BaseDaemon._register_signal_handlers"),
        patch("src.core.agent.base.AGENT_SETUP_SUCCESS_TOTAL", mock_counter),
    ):
        a = SuccessAgent(name="success_test")
        await a.start()
    mock_counter.add.assert_called_once_with(1, {"agent": "success_test"})


@pytest.mark.asyncio
async def test_base_agent_tracks_setup_failure() -> None:
    """BaseDaemon tracks failed _setup() with error_type attribute (OTel .add call)."""
    from unittest.mock import MagicMock, patch

    class FailSetupAgent(BaseDaemon):
        async def _setup(self) -> None:
            raise ValueError("config error")

        async def _run(self) -> None:
            pass

    mock_counter = MagicMock()
    with (
        patch("src.core.agent.base.BaseDaemon._register_signal_handlers"),
        patch("src.core.agent.base.AGENT_SETUP_FAILURE_TOTAL", mock_counter),
    ):
        a = FailSetupAgent(name="fail_setup_test")
        with pytest.raises(ValueError):
            await a.start()
    mock_counter.add.assert_called_once_with(
        1, {"agent": "fail_setup_test", "error_type": "ValueError"}
    )


@pytest.mark.asyncio
async def test_base_agent_send_alert_publishes_to_kafka() -> None:
    """BaseDaemon._send_alert() publishes to alert.requests topic via Kafka producer."""

    class AlertAgent(BaseDaemon):
        async def _run(self) -> None:
            self._stop_event.set()

    with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
        a = AlertAgent(name="alert_test")
        # Mock the producer with an async method
        from unittest.mock import AsyncMock

        mock_producer = AsyncMock()
        a._producer = mock_producer
        # settings.env_name drives the topic key (real topic_alert_requests() runs unmocked)
        a.settings = MagicMock()
        a.settings.env_name = "test"
        # Call _send_alert
        await a._send_alert("CRITICAL", "test alert", context={"symbol": "ES"})
        # Verify producer.publish was called
        mock_producer.publish.assert_called_once()
        call_args = mock_producer.publish.call_args
        assert "alert.requests" in call_args[0][0]  # topic contains alert.requests
        payload = call_args[0][1]
        assert payload["severity"] == "CRITICAL"
        assert payload["message"] == "test alert"
        assert payload["source"] == "alert_test"
        assert "timestamp" in payload
        assert payload["symbol"] == "ES"


@pytest.mark.asyncio
async def test_base_agent_send_alert_noop_without_producer() -> None:
    """BaseDaemon._send_alert() is graceful no-op when producer not configured."""

    class NoProducerAgent(BaseDaemon):
        async def _run(self) -> None:
            self._stop_event.set()

    with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
        a = NoProducerAgent(name="no_producer_test")
        # No _producer attribute set
        # Should not raise
        await a._send_alert("CRITICAL", "test")
        # If we get here, test passes


# ---------------------------------------------------------------------------
# Phase 084-01: INFRA-03 class attr configurability + INFRA-05 circuit breaker
# ---------------------------------------------------------------------------


def test_setup_retry_class_attrs_default() -> None:
    """BaseDaemon exposes SETUP_RETRY_ATTEMPTS=3, SETUP_RETRY_BACKOFF_S=2.0, circuit_breaker=False."""
    assert BaseDaemon.SETUP_RETRY_ATTEMPTS == 3
    assert BaseDaemon.SETUP_RETRY_BACKOFF_S == 2.0
    assert BaseDaemon.circuit_breaker is False


def test_setup_retry_class_attrs_overridable() -> None:
    """Subclasses can override SETUP_RETRY_ATTEMPTS and SETUP_RETRY_BACKOFF_S."""

    class FastRetryAgent(BaseDaemon):
        SETUP_RETRY_ATTEMPTS = 1
        SETUP_RETRY_BACKOFF_S = 0.1

        async def _run(self) -> None:
            pass

    a = FastRetryAgent(name="fast_retry")
    assert a.SETUP_RETRY_ATTEMPTS == 1
    assert a.SETUP_RETRY_BACKOFF_S == 0.1
    # Verify BaseDaemon defaults are unchanged
    assert BaseDaemon.SETUP_RETRY_ATTEMPTS == 3
    assert BaseDaemon.SETUP_RETRY_BACKOFF_S == 2.0


def test_circuit_breaker_default_off() -> None:
    """BaseDaemon.circuit_breaker is False by default; agent._cb_open starts False."""
    assert BaseDaemon.circuit_breaker is False
    a = MinimalAgent(name="cb_default_test")
    assert a._cb_open is False


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_all_retries_fail() -> None:
    """When circuit_breaker=True and all retries fail, _cb_open is set to True."""

    class AlwaysFailSetupAgent(BaseDaemon):
        circuit_breaker = True
        SETUP_RETRY_ATTEMPTS = 2
        SETUP_RETRY_BACKOFF_S = 0.0

        async def _setup(self) -> None:
            raise RuntimeError("always fails")

        async def _run(self) -> None:
            pass

    with patch("src.core.agent.base.BaseDaemon._register_signal_handlers"):
        a = AlwaysFailSetupAgent(name="cb_open_test")
        with pytest.raises(RuntimeError):
            await a.start()

    assert a._cb_open is True


@pytest.mark.asyncio
async def test_setup_retry_counter_increments_on_retry() -> None:
    """AGENT_SETUP_RETRIES_TOTAL is incremented once per pre-final retry attempt."""
    from unittest.mock import MagicMock

    class RetryAgent(BaseDaemon):
        circuit_breaker = True
        SETUP_RETRY_ATTEMPTS = 3
        SETUP_RETRY_BACKOFF_S = 0.0

        async def _setup(self) -> None:
            raise RuntimeError("fail on every attempt")

        async def _run(self) -> None:
            pass

    mock_counter = MagicMock()
    with (
        patch("src.core.agent.base.BaseDaemon._register_signal_handlers"),
        patch("src.core.agent.base.AGENT_SETUP_RETRIES_TOTAL", mock_counter),
    ):
        a = RetryAgent(name="retry_counter_test")
        with pytest.raises(RuntimeError):
            await a.start()

    # With SETUP_RETRY_ATTEMPTS=3, there are 2 retries before the final raise
    assert mock_counter.add.call_count == 2
