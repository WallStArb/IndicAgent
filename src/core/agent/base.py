"""BaseAgent — abstract base class for all IndicAgent pipeline agents.

Provides the Renaissance Agentic DAG standard lifecycle:
- SIGTERM/SIGINT drain via asyncio event (asyncio.get_running_loop, not deprecated get_event_loop)
- Structured logging via structlog bound with agent name (configured before logger creation)
- Consumer lag reporting scaffolding (override in concrete agents)
- OTel MeterProvider + TracerProvider via init_otel_providers(name) — graceful degradation
- _setup()/_teardown() lifecycle hooks (no-op by default, override in subclasses)
- running property derived from stop_event state
- topics_consumed/topics_produced/lag_threshold_messages for ProcessManifest (Plan 03)
- _send_to_dlq() stub — logs and discards; override when DLQ topics are provisioned
- start/stop/run contract enforced via abc.ABC

Logging Setup:
  BaseAgent auto-configures logging before creating the logger using convention-over-configuration:
  - Default: log path derived from agent name (PascalCase → snake_case conversion: logs/{name}.log)
  - Override: call setup_service_logging(custom_path) BEFORE super().__init__() for custom paths
    (e.g., from environment variable or config file)
  This fixes the ordering bug where setup_service_logging() was called after super().__init__(),
  causing loggers to be created with default config (no file output).
"""

from __future__ import annotations

import abc
import asyncio
import os
import signal
import sys
import time

import structlog
from opentelemetry import metrics as _otel_metrics

from src.config.settings import Settings, get_settings
from src.core.service_utils import setup_service_logging
from src.observability.metrics import (
    AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS,
    PERSISTENCE_CONSUMER_LAG,
)
from src.observability.otel import get_meter, get_tracer, init_otel_providers

# ---------------------------------------------------------------------------
# BaseAgent Observability Metrics (Phase 67)
# ---------------------------------------------------------------------------

_base_meter = _otel_metrics.get_meter("indicagent")

AGENT_CRASH_TOTAL = _base_meter.create_counter(
    "agent_crash_total",
    description="Agent crashes (uncaught exceptions) from BaseAgent._run()",
)

AGENT_SETUP_SUCCESS_TOTAL = _base_meter.create_counter(
    "agent_setup_success_total",
    description="Successful BaseAgent._setup() completions",
)

AGENT_SETUP_FAILURE_TOTAL = _base_meter.create_counter(
    "agent_setup_failure_total",
    description="Failed BaseAgent._setup() completions",
)

AGENT_SETUP_LATENCY_SECONDS = _base_meter.create_histogram(
    "agent_setup_latency_seconds",
    description="BaseAgent._setup() execution time in seconds",
    unit="s",
)

# Module-level flag to ensure init_tracing() is called only once per process
_tracing_initialized: bool = False


class BaseAgent(abc.ABC):
    """Abstract base for all pipeline agents.

    Subclasses must implement ``_run()``. The lifecycle is:
    1. ``start()`` — registers signal handlers, optionally starts metrics server,
       calls ``_setup()``, starts lag reporter, calls ``_run()``.
    2. ``_run()`` — main loop; runs until ``_stop_event`` is set.
    3. ``_teardown()`` — called in finally block after ``_run()`` exits (or raises).
    4. ``stop()`` — called after ``_teardown()``; override to add flush logic.
    """

    def __init__(
        self,
        name: str,
        max_idle_seconds: int = 0,
        settings: Settings | None = None,
    ) -> None:
        # Configure logging BEFORE creating logger using convention-over-configuration
        # Convert PascalCase agent names to snake_case for log files
        import re

        log_name = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
        log_path = f"logs/{log_name}.log"
        # Guard: only configure if this exact path has not already been set up.
        # Multiple agent instantiations (e.g., in tests) would otherwise redirect
        # all logging to the most recently instantiated agent's log file.
        if getattr(BaseAgent, "_log_configured_path", None) != log_path:
            setup_service_logging(log_path)
            BaseAgent._log_configured_path = log_path

        self.name = name
        self.max_idle_seconds = max_idle_seconds
        self._stop_event: asyncio.Event = asyncio.Event()
        self._last_message_ts: float | None = None
        # Cache OTel attribute dicts to avoid rebuilding on every message.
        self._last_msg_ts_attrs = {"agent": name}
        self._consumer_lag_attrs = {"agent_id": name}
        # NOTE: attribute is self.logger (not self.log) to match the 20+ call sites
        # in existing agents that use self.logger.
        # Logger is created AFTER setup_service_logging() when log_file is provided.
        self.logger: structlog.BoundLogger = structlog.get_logger().bind(agent=name)
        # Settings singleton — all agents inherit configuration access
        # Use provided settings if available (e.g., from BaseProviderAgent), otherwise get singleton
        self.settings = settings if settings is not None else get_settings()
        # OTel tracer — no-op when init_otel_providers() has not been called; safe before init.
        self.tracer = get_tracer(name)
        # OTel meter — provides instrument creation for subclasses
        self._meter = get_meter(name)

        # Cache OTel attribute dicts for crash/setup observability metrics
        self._agent_label = name.lower().replace(" ", "_")
        self._crash_attrs = {"agent": self._agent_label}
        self._setup_success_attrs = {"agent": self._agent_label}
        self._setup_latency_attrs = {"agent": self._agent_label}

    def __getattr__(self, name: str):
        """Fallback for attributes not set in __new__ test pattern (bypasses __init__).

        CLAUDE.md warning: tests using ServiceClass.__new__(ServiceClass) bypass __init__,
        so attributes set there are missing. This fallback provides safe defaults for the
        most common missing attributes without modifying all test instances.
        """
        if name == "tracer":
            from src.observability.otel import get_tracer

            return get_tracer("test-noop")
        if name == "_meter":
            from src.observability.otel import get_meter

            return get_meter("test-noop")
        if name == "_shadow_cache":
            return {}
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    @property
    def env_name(self) -> str:
        """Kafka topic environment prefix from settings. Empty string in dev/default."""
        return self.settings.env_name or ""

    def _register_signal_handlers(self) -> None:
        """Register SIGTERM and SIGINT handlers that set the stop event.

        Must be called from within a running event loop (i.e., from ``start()``).
        Uses ``asyncio.get_running_loop()`` — NOT the deprecated ``get_event_loop()``.
        """
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._stop_event.set)

    async def start(self) -> None:
        """Lifecycle entry point.

        Order (D-06):
        1. Register signal handlers.
        2. Initialize OTel MeterProvider + TracerProvider (idempotent — first call wins).
        3. Log agent.starting.
        4. Call _setup() — connect Kafka, seed history, etc.
        5. Launch lag reporter as background task.
        6. Await _run(). On Exception: log agent.run_failed and re-raise.
        7. finally: cancel lag task, await _teardown(), call stop().
        """
        self._register_signal_handlers()

        # Initialize OTel MeterProvider + TracerProvider (idempotent — first call wins)
        global _tracing_initialized
        if not _tracing_initialized:
            init_otel_providers(service_name=self.name)
            _tracing_initialized = True

        # Set up OTLP log bridge (additive to file logging)
        from src.observability.log_bridge import setup_otlp_logging

        setup_otlp_logging(service_name=self.name)

        self.logger.info("agent.starting", agent=self.name)

        # NEW: Track setup latency + success/failure
        try:
            setup_start = time.monotonic()
            await self._setup()
            setup_duration = time.monotonic() - setup_start
            AGENT_SETUP_LATENCY_SECONDS.record(setup_duration, self._setup_latency_attrs)
            AGENT_SETUP_SUCCESS_TOTAL.add(1, self._setup_success_attrs)
        except Exception as exc:
            # Log setup failure AND track metric
            self.logger.exception("agent.setup_failed")
            AGENT_SETUP_FAILURE_TOTAL.add(
                1, {"agent": self._agent_label, "error_type": type(exc).__name__}
            )
            raise

        lag_task = asyncio.create_task(self._report_consumer_lag())
        watchdog_task = asyncio.create_task(self._watchdog_notify())
        stall_task = asyncio.create_task(self._stall_watchdog())
        try:
            await self._run()
        except Exception:
            # Log run failure AND track crash metric
            self.logger.exception("agent.run_failed")
            AGENT_CRASH_TOTAL.add(1, self._crash_attrs)
            raise
        finally:
            lag_task.cancel()
            watchdog_task.cancel()
            stall_task.cancel()
            for t in (lag_task, watchdog_task, stall_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass
            await self._teardown()
            await self.stop()

    async def stop(self) -> None:
        """Lifecycle teardown. Override to add flush/drain logic."""
        self.logger.info("agent.stopped", agent=self.name)

    async def _setup(self) -> None:  # noqa: B027
        """Override to connect Kafka, seed history, etc. Called before _run().

        No-op by default — existing agents that don't override keep working.
        Not abstract: subclasses that omit _setup() are valid and common.
        """

    async def _teardown(self) -> None:  # noqa: B027
        """Override to drain/close Kafka/DB. Called after _run() exits.

        No-op by default — existing agents that don't override keep working.
        Not abstract: subclasses that omit _teardown() are valid and common.
        """

    @property
    def running(self) -> bool:
        """True while the stop event has not been set."""
        return not self._stop_event.is_set()

    @property
    def topics_consumed(self) -> list[str]:
        """Kafka topics this agent reads from. Override in concrete agents."""
        return []

    @property
    def topics_produced(self) -> list[str]:
        """Kafka topics this agent writes to. Override in concrete agents."""
        return []

    @property
    def lag_threshold_messages(self) -> int:
        """Consumer lag threshold before alerting. Override per agent."""
        return 1000

    async def _report_consumer_lag(self) -> None:
        """Report consumer lag until stop event.

        Default implementation: set gauge to 0 (stream processors have no buffer).
        Subclasses (e.g., BaseWriterAgent) override to report actual buffer depth.
        Loops until _stop_event is set.
        """
        while not self._stop_event.is_set():
            PERSISTENCE_CONSUMER_LAG.add(0, self._consumer_lag_attrs)
            await asyncio.sleep(15)

    def _record_message_consumed(self) -> None:
        """Call once per successfully consumed Kafka message.

        Updates the monotonic stall clock and the Prometheus liveness gauge.
        Required for _stall_watchdog() and _watchdog_notify() liveness gating to
        work. Agents that never call this behave as before (no stall detection).
        """
        # monotonic for stall detection (immune to clock skew); wall-clock for observability
        self._last_message_ts = time.monotonic()
        AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS.set(time.time(), self._last_msg_ts_attrs)

    async def _stall_watchdog(self) -> None:
        """Exit the process if no messages consumed for max_idle_seconds.

        Only active when max_idle_seconds > 0. Waits for the first message
        (startup grace) before the stall clock starts. On detection: logs and
        calls sys.exit(1) so systemd restarts the service.
        """
        if self.max_idle_seconds <= 0:
            return
        check_interval = max(10, min(60, self.max_idle_seconds // 5))
        while not self._stop_event.is_set():
            await asyncio.sleep(check_interval)
            if self._last_message_ts is None:
                continue  # startup grace — no messages received yet
            idle_secs = time.monotonic() - self._last_message_ts
            if idle_secs > self.max_idle_seconds:
                self.logger.error(
                    "agent.stall_detected",
                    agent=self.name,
                    idle_seconds=int(idle_secs),
                    max_idle_seconds=self.max_idle_seconds,
                )
                sys.exit(1)

    async def _watchdog_notify(self) -> None:
        """Notify systemd watchdog — gated on liveness when max_idle_seconds > 0.

        When max_idle_seconds is 0 (default): pings unconditionally (backward-compatible).
        When max_idle_seconds > 0: stops pinging once _last_message_ts goes stale,
        allowing systemd's WatchdogSec to fire as a secondary restart backstop.
        No-op when NOTIFY_SOCKET or WATCHDOG_USEC is not set (direct run / tests).
        Notifies at half WatchdogSec interval to stay well within the deadline.
        """
        socket_path = os.getenv("NOTIFY_SOCKET", "")
        usec = int(os.getenv("WATCHDOG_USEC", "0"))
        if not socket_path or usec <= 0:
            return
        import sdnotify

        notifier = sdnotify.SystemdNotifier()
        interval_s = usec / 2_000_000
        while self.running:
            should_notify = True
            if self.max_idle_seconds > 0 and self._last_message_ts is not None:
                should_notify = (time.monotonic() - self._last_message_ts) < interval_s * 2
            if should_notify:
                notifier.notify("WATCHDOG=1")
            await asyncio.sleep(interval_s)

    async def _send_to_dlq(self, payload: dict, error: Exception) -> None:
        """Route unprocessable payload to DLQ. Default: log and discard.

        If subclass overrides _dlq_topic() to return a topic name, routes to DLQ
        with structured DLQPayload and emits metrics.
        """
        from datetime import UTC, datetime

        from src.core.schemas.dlq_payload import DLQPayload
        from src.observability.metrics import DLQ_MESSAGES_TOTAL

        # Check if DLQ topic is configured
        dlq_topic = self._dlq_topic()

        if dlq_topic is None:
            # No DLQ configured — log and discard
            self.logger.error(
                "agent.dlq_discard",
                agent=self.name,
                error=str(error),
                payload_keys=list(payload.keys()) if isinstance(payload, dict) else None,
            )
            return

        # DLQ topic configured — route to DLQ
        dlq_payload = DLQPayload(
            agent=self.name,
            source_topic=self.topics_consumed[0] if self.topics_consumed else "unknown",
            error_type=type(error).__name__,
            error_message=str(error),
            payload=payload,
            timestamp=datetime.now(UTC),
            retry_count=0,
        )

        try:
            producer = self._get_producer()
            if producer is not None:
                await producer.publish(dlq_topic, dlq_payload.model_dump())
                DLQ_MESSAGES_TOTAL.add(
                    1,
                    {"agent": self.name, "topic": dlq_topic, "error_type": type(error).__name__},
                )
                self.logger.info(
                    "agent.dlq_routed",
                    agent=self.name,
                    topic=dlq_topic,
                    error_type=type(error).__name__,
                )
            else:
                # No producer available — log and discard
                self.logger.warning(
                    "agent.dlq_no_producer",
                    agent=self.name,
                    topic=dlq_topic,
                    error=str(error),
                )
        except Exception as exc:
            self.logger.error(
                "agent.dlq_route_failed",
                agent=self.name,
                topic=dlq_topic,
                error=str(exc),
            )

    def _get_producer(self):
        """Return the Kafka producer for this agent, or None if not available.

        Checks _kafka_producer first (used by most agents), then _producer
        (used by writer agents). Returns None if neither is set.
        """
        if hasattr(self, "_kafka_producer") and self._kafka_producer is not None:
            return self._kafka_producer
        if hasattr(self, "_producer") and self._producer is not None:
            return self._producer
        return None

    def _dlq_topic(self) -> str | None:
        """Override to return DLQ topic name. None = log-only (default)."""
        return None

    async def _send_alert(self, severity: str, message: str, context: dict | None = None) -> None:
        """Send alert to AlertingComputeAgent via Kafka.

        Args:
            severity: "CRITICAL" | "HIGH" | "MEDIUM"
            message: Human-readable alert message
            context: Optional structured context (symbol, tf, error details, etc.)

        No-op if producer not configured (agents without Kafka output).
        AlertingComputeAgent routes: CRITICAL → Telegram, HIGH/MEDIUM → Discord.
        """
        if not hasattr(self, "_producer") or self._producer is None:
            return

        from datetime import UTC, datetime

        from src.core.stream_keys import topic_alert_requests

        payload = {
            "severity": severity,
            "message": message,
            "source": self.name,
            "timestamp": datetime.now(UTC).isoformat(),
            **(context or {}),
        }

        try:
            env_name = self.settings.env_name or ""
            await self._producer.publish(topic_alert_requests(env_name), payload)
            self.logger.info("alert_published", severity=severity, message=message[:100])
        except Exception as exc:
            self.logger.error("alert_publish_failed", error=str(exc))

    async def _setup_with_retry(self) -> None:
        """Wrap _setup() with exponential backoff retry.

        Subclasses call this from start() instead of _setup() directly
        if they need bootstrap resilience. Default behavior is no retry.
        """
        _attempts = 3
        _backoff_base = 2.0  # seconds
        for attempt in range(_attempts):
            try:
                await self._setup()
                return
            except Exception as exc:
                if attempt == _attempts - 1:
                    raise
                backoff = _backoff_base**attempt
                self.logger.warning(
                    "agent.setup_retry",
                    attempt=attempt + 1,
                    max_attempts=_attempts,
                    backoff_seconds=backoff,
                    error=str(exc),
                )
                await asyncio.sleep(backoff)

    @abc.abstractmethod
    async def _run(self) -> None:
        """Main agent loop. Runs until ``_stop_event`` is set."""
        ...
