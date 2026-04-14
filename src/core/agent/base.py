"""BaseAgent — abstract base class for all IndicAgent pipeline agents.

Provides the Renaissance Agentic DAG standard lifecycle:
- SIGTERM/SIGINT drain via asyncio event (asyncio.get_running_loop, not deprecated get_event_loop)
- Structured logging via structlog bound with agent name (configured before logger creation)
- Consumer lag reporting scaffolding (override in concrete agents)
- OTel tracer via get_tracer(name) — no-op when init_tracing() not called
- Optional Prometheus metrics auto-start via metrics_port parameter
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
from prometheus_client import Counter as _Counter
from prometheus_client import Histogram as _Histogram

from src.config.settings import Settings, get_settings
from src.core.service_utils import setup_service_logging
from src.observability.metrics import (
    AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS,
    PERSISTENCE_CONSUMER_LAG,
    start_metrics_server,
)
from src.observability.otel import get_tracer, init_tracing

# ---------------------------------------------------------------------------
# BaseAgent Observability Metrics (Phase 67)
# ---------------------------------------------------------------------------

AGENT_CRASH_TOTAL = _Counter(
    "agent_crash_total",
    "Agent crashes (uncaught exceptions) from BaseAgent._run()",
    ["agent"]
)

AGENT_SETUP_SUCCESS_TOTAL = _Counter(
    "agent_setup_success_total",
    "Successful BaseAgent._setup() completions",
    ["agent"]
)

AGENT_SETUP_FAILURE_TOTAL = _Counter(
    "agent_setup_failure_total",
    "Failed BaseAgent._setup() completions",
    ["agent", "error_type"]
)

AGENT_SETUP_LATENCY_SECONDS = _Histogram(
    "agent_setup_latency_seconds",
    "BaseAgent._setup() execution time in seconds",
    ["agent"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0]
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
        metrics_port: int | None = None,
        max_idle_seconds: int = 0,
        settings: Settings | None = None,
    ) -> None:
        # Configure logging BEFORE creating logger using convention-over-configuration
        # Convert PascalCase agent names to snake_case for log files
        import re
        log_name = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        log_path = f"logs/{log_name}.log"
        setup_service_logging(log_path)

        self.name = name
        self._metrics_port = metrics_port
        self.max_idle_seconds = max_idle_seconds
        self._stop_event: asyncio.Event = asyncio.Event()
        self._last_message_ts: float | None = None
        # Cache labeled Prometheus child once — avoids dict lookup on every message.
        self._last_msg_ts_gauge = AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS.labels(agent=name)
        # Cache labeled Prometheus child for consumer lag — avoids dict lookup on every report
        self._consumer_lag_gauge = PERSISTENCE_CONSUMER_LAG.labels(agent_id=name)
        # NOTE: attribute is self.logger (not self.log) to match the 20+ call sites
        # in existing agents that use self.logger.
        # Logger is created AFTER setup_service_logging() when log_file is provided.
        self.logger: structlog.BoundLogger = structlog.get_logger().bind(agent=name)
        # Settings singleton — all agents inherit configuration access
        # Use provided settings if available (e.g., from BaseProviderAgent), otherwise get singleton
        self.settings = settings if settings is not None else get_settings()
        # OTel tracer — no-op when init_tracing() has not been called; safe before init.
        self.tracer = get_tracer(name)

        # NEW: Cache crash/setup observability metrics at init (minimal runtime overhead)
        self._agent_label = name.lower().replace(" ", "_")
        self._crash_total = AGENT_CRASH_TOTAL.labels(agent=self._agent_label)
        self._setup_success_total = AGENT_SETUP_SUCCESS_TOTAL.labels(agent=self._agent_label)
        # NOTE: _setup_failure_total not cached here - needs error_type label at exception time
        self._setup_latency = AGENT_SETUP_LATENCY_SECONDS.labels(agent=self._agent_label)

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
        2. Start Prometheus metrics server if metrics_port is set.
        3. Initialize OTel tracing (idempotent — first call wins).
        4. Log agent.starting.
        5. Call _setup() — connect Kafka, seed history, etc.
        6. Launch lag reporter as background task.
        7. Await _run(). On Exception: log agent.run_failed and re-raise.
        8. finally: cancel lag task, await _teardown(), call stop().
        """
        self._register_signal_handlers()
        if self._metrics_port is not None:
            start_metrics_server(port=self._metrics_port)

        # Initialize OTel tracing (idempotent — first call wins)
        global _tracing_initialized
        if not _tracing_initialized:
            init_tracing(service_name=self.name)
            _tracing_initialized = True

        self.logger.info("agent.starting", agent=self.name)

        # NEW: Track setup latency + success/failure
        try:
            setup_start = time.monotonic()
            await self._setup()
            setup_duration = time.monotonic() - setup_start
            self._setup_latency.observe(setup_duration)
            self._setup_success_total.inc()
        except Exception as exc:
            # Log setup failure AND track metric
            self.logger.exception("agent.setup_failed")
            AGENT_SETUP_FAILURE_TOTAL.labels(agent=self._agent_label, error_type=type(exc).__name__).inc()
            raise

        lag_task = asyncio.create_task(self._report_consumer_lag())
        watchdog_task = asyncio.create_task(self._watchdog_notify())
        stall_task = asyncio.create_task(self._stall_watchdog())
        try:
            await self._run()
        except Exception:
            # Log run failure AND track crash metric
            self.logger.exception("agent.run_failed")
            self._crash_total.inc()
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
            self._consumer_lag_gauge.set(0)
            await asyncio.sleep(15)

    def _record_message_consumed(self) -> None:
        """Call once per successfully consumed Kafka message.

        Updates the monotonic stall clock and the Prometheus liveness gauge.
        Required for _stall_watchdog() and _watchdog_notify() liveness gating to
        work. Agents that never call this behave as before (no stall detection).
        """
        # monotonic for stall detection (immune to clock skew); wall-clock for observability
        self._last_message_ts = time.monotonic()
        self._last_msg_ts_gauge.set(time.time())

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
        from src.observability.metrics import DLQ_DEPTH, DLQ_MESSAGES_TOTAL

        # Check if DLQ topic is configured
        dlq_topic = self._dlq_topic() if hasattr(self, "_dlq_topic") else None

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
            # Check if agent has a Kafka producer
            if hasattr(self, "_kafka_producer") and self._kafka_producer is not None:
                await self._kafka_producer.publish(dlq_topic, dlq_payload.model_dump())
                # Emit metrics
                DLQ_DEPTH.labels(agent=self.name, topic=dlq_topic).inc()
                DLQ_MESSAGES_TOTAL.labels(agent=self.name, topic=dlq_topic, error_type=type(error).__name__).inc()
                self.logger.info(
                    "agent.dlq_routed",
                    agent=self.name,
                    topic=dlq_topic,
                    error_type=type(error).__name__,
                )
            elif hasattr(self, "_producer") and self._producer is not None:
                # Some agents use self._producer instead of self._kafka_producer
                await self._producer.publish(dlq_topic, dlq_payload.model_dump())
                DLQ_DEPTH.labels(agent=self.name, topic=dlq_topic).inc()
                DLQ_MESSAGES_TOTAL.labels(agent=self.name, topic=dlq_topic, error_type=type(error).__name__).inc()
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

    def _dlq_topic(self) -> str | None:
        """Override to return DLQ topic name. None = log-only (default)."""
        return None

    async def _send_alert(self, severity: str, message: str, context: dict | None = None) -> None:
        """Send alert to AlertingAgent via Kafka.

        Args:
            severity: "CRITICAL" | "HIGH" | "MEDIUM"
            message: Human-readable alert message
            context: Optional structured context (symbol, tf, error details, etc.)

        No-op if producer not configured (agents without Kafka output).
        AlertingAgent routes: CRITICAL → Telegram, HIGH/MEDIUM → Discord.
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
            env = getattr(self, "_settings", None)
            env_name = env.env_name if env and hasattr(env, "env_name") else ""
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
                backoff = _backoff_base ** attempt
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
