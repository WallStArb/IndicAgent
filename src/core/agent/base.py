"""BaseDaemon — abstract base class for all IndicAgent pipeline agents.

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
  BaseDaemon auto-configures logging before creating the logger using convention-over-configuration:
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
import re
import signal
import sys
import time
from datetime import UTC, datetime
from typing import Any

import structlog
from opentelemetry import metrics as _otel_metrics

from src.config.config_consumer import (
    ConfigConsumerMixin,  # ring0-ok: settings is Ring 0 infrastructure
)
from src.config.settings import (  # ring0-ok: all daemons need configuration access
    Settings,
    get_settings,
)
from src.core.service_utils import setup_service_logging
from src.observability.metrics import (
    AGENT_CIRCUIT_BREAKER_STATE,
    AGENT_DLQ_TOTAL,
    AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS,
    AGENT_SETUP_RETRIES_TOTAL,
)
from src.observability.otel import OTelInitError, get_meter, get_tracer, init_otel_providers

# ---------------------------------------------------------------------------
# BaseDaemon Observability Metrics (Phase 67)
# ---------------------------------------------------------------------------

_base_meter = _otel_metrics.get_meter("indicagent")

AGENT_CRASH_TOTAL = _base_meter.create_counter(
    "agent_crash_total",
    description="Agent crashes (uncaught exceptions) from BaseDaemon._run()",
)

WATCHDOG_NOTIFY_TOTAL = _base_meter.create_counter(
    "watchdog_notify_total",
    description="Successful sd_notify WATCHDOG=1 pings per agent",
)

WATCHDOG_NOTIFY_SUPPRESSED_TOTAL = _base_meter.create_counter(
    "watchdog_notify_suppressed_total",
    description="Suppressed watchdog pings (agent alive but idle/stalled) per agent",
)

AGENT_SETUP_SUCCESS_TOTAL = _base_meter.create_counter(
    "agent_setup_success_total",
    description="Successful BaseDaemon._setup() completions",
)

AGENT_SETUP_FAILURE_TOTAL = _base_meter.create_counter(
    "agent_setup_failure_total",
    description="Failed BaseDaemon._setup() completions",
)

AGENT_SETUP_LATENCY_SECONDS = _base_meter.create_histogram(
    "agent_setup_latency_seconds",
    description="BaseDaemon._setup() execution time in seconds",
    unit="s",
)

# Module-level flag to ensure init_tracing() is called only once per process
_tracing_initialized: bool = False


def _to_snake_case(name: str) -> str:
    """Convert PascalCase/CamelCase to snake_case.

    Examples:
        BarAggregator -> bar_aggregator
        MLDiscoveryAnalyzer -> ml_discovery_analyzer
        SignalTracker -> signal_tracker
    """
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.lower()


class BaseDaemon(abc.ABC, ConfigConsumerMixin):
    """Abstract base for all pipeline agents.

    Subclasses must implement ``_run()``. The lifecycle is:
    1. ``start()`` — registers signal handlers, optionally starts metrics server,
       calls ``_setup()``, starts lag reporter, calls ``_run()``.
    2. ``_run()`` — main loop; runs until ``_stop_event`` is set.
    3. ``_teardown()`` — called in finally block after ``_run()`` exits (or raises).
    4. ``stop()`` — called after ``_teardown()``; override to add flush logic.

    Config integration (Phase 109):
    - _pre_setup_config_load() loads OPS snapshot BEFORE _setup() (Codex HIGH fix)
    - _setup_config_consumer() subscribes Kafka AFTER _setup() completes
    - Both phases are NON-FATAL; service starts with defaults if DB/Kafka unavailable
    - Subclasses may override _config_layer = "INFRA" to skip Kafka subscription
    - Subclasses may override _config_prefixes = ("regime.",) to filter reloads
    """

    # ---------------------------------------------------------------------------
    # Class-attribute configuration — subclasses override to tune behavior.
    # ---------------------------------------------------------------------------
    SETUP_RETRY_ATTEMPTS: int = 3
    SETUP_RETRY_BACKOFF_S: float = 2.0
    circuit_breaker: bool = False

    def __init__(
        self,
        name: str | None = None,
        max_idle_seconds: int = 0,
        settings: Settings | None = None,
    ) -> None:
        if name is None:
            name = _to_snake_case(self.__class__.__name__)
        # Configure logging BEFORE creating logger using convention-over-configuration
        # Convert PascalCase agent names to snake_case for log files
        log_path = f"logs/{name}.log"
        # Guard: only configure if this exact path has not already been set up.
        # Multiple agent instantiations (e.g., in tests) would otherwise redirect
        # all logging to the most recently instantiated agent's log file.
        if getattr(BaseDaemon, "_log_configured_path", None) != log_path:
            setup_service_logging(log_path)
            BaseDaemon._log_configured_path = log_path

        self.name = name
        self.max_idle_seconds = max_idle_seconds
        self._stop_event: asyncio.Event = asyncio.Event()
        self._last_message_ts: float | None = None
        # Cache OTel attribute dicts to avoid rebuilding on every message.
        self._last_msg_ts_attrs = {"agent_id": name}
        self._consumer_lag_attrs = {"agent_id": name}
        # NOTE: attribute is self.logger (not self.log) to match the 20+ call sites
        # in existing agents that use self.logger.
        # Logger is created AFTER setup_service_logging() when log_file is provided.
        self.logger: structlog.BoundLogger = structlog.get_logger().bind(agent=name)
        # Settings singleton — all agents inherit configuration access
        # Use provided settings if available (e.g., from BaseProvider), otherwise get singleton
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
        # D-09: per-agent DLQ counter attrs (label key is agent_id per spec)
        self._dlq_attrs = {"agent_id": self._agent_label}
        self._cb_attrs = {"agent_id": self._agent_label}
        self._cb_open: bool = False
        # Phase 109: config consumer state — initialized here so mixin methods work.
        # Subclasses MAY override _config_layer = "INFRA"/"STRUCT" to skip Kafka subscription.
        # Subclasses MAY override _config_prefixes = ("regime.", "swarm.") to filter reloads.
        self._config_cache: dict[str, Any] = {}
        self._config_consumer = None
        self._config_reload_task = None
        self._config_loaded = False

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
        if name == "_active_signal_count":
            return 0
        if name in ("_active_signals_gauge", "_transitions_total"):
            from src.observability.otel import get_meter

            m = get_meter("test-noop")
            return m.create_up_down_counter(name.lstrip("_"))
        if name == "_plugin_circuit_breakers":
            return {}
        # Phase 111: _agent_label derived from class name when tests bypass __init__.
        if name == "_agent_label":
            return _to_snake_case(type(self).__name__)
        # Phase 109: config consumer attrs — tests that bypass __init__ via __new__ need these.
        if name == "_config_cache":
            return {}
        if name in ("_config_consumer", "_config_reload_task"):
            return None
        if name == "_config_loaded":
            return False
        if name == "_bar_e2e_latency":
            from src.observability.otel import get_meter

            return get_meter("test-noop").create_histogram("bar_e2e_latency_ms")
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

        Order (D-06, updated Phase 109):
        1. Register signal handlers.
        2. Initialize OTel MeterProvider + TracerProvider (idempotent — first call wins).
        3. Log agent.starting.
        4. [NEW] _pre_setup_config_load() — load OPS config snapshot NON-FATALLY.
           Config snapshot loads BEFORE _setup() so service-specific setup can read OPS
           config values (Codex HIGH finding). Kafka subscription comes AFTER _setup()
           because hot-reload is not required for service initialization.
        5. Call _setup() — connect Kafka, seed history, etc. CAN now read OPS config.
        6. [NEW] _setup_config_consumer() — subscribe to Kafka for hot-reload NON-FATALLY.
        7. Launch lag reporter as background task.
        8. Await _run(). On Exception: log agent.run_failed and re-raise.
        9. finally: cancel lag task, await _teardown(), call stop().
        """
        self._register_signal_handlers()

        # Initialize OTel MeterProvider + TracerProvider (idempotent — first call wins)
        # Metrics export is NOT optional — crash the service if the collector is
        # unreachable so systemd restarts with visible failure, not silent degradation.
        global _tracing_initialized
        if not _tracing_initialized:
            try:
                init_otel_providers(service_name=self.name)
            except OTelInitError as error:
                self.logger.critical("daemon.otel_init_failed", error=str(error))
                raise
            _tracing_initialized = True

        # Set up OTLP log bridge (additive to file logging)
        from src.observability.log_bridge import setup_otlp_logging

        setup_otlp_logging(service_name=self.name)

        # Base-class infra events use the "daemon." role prefix (not a per-service agent_id) — intentional exception to the {derived_agent_id}.action convention.
        self.logger.info("daemon.starting", agent=self.name)

        try:
            setup_start = time.monotonic()

            # Phase 109: config snapshot loads BEFORE _setup() so service-specific setup can
            # read OPS config (Codex review finding). Kafka subscription comes AFTER _setup()
            # because hot-reload is not required for service initialization.
            try:
                await self._pre_setup_config_load()
            except Exception:
                self.logger.warning("daemon.config_pre_load_unexpected_error", agent=self.name)

            if self.circuit_breaker:
                try:
                    await self._setup_with_retry()
                except Exception:
                    self._cb_open = True
                    AGENT_CIRCUIT_BREAKER_STATE.set(2, self._cb_attrs)
                    raise
            else:
                await self._setup()

            # Phase 109: subscribe to Kafka config updates AFTER _setup() completes.
            try:
                await self._setup_config_consumer()
            except Exception:
                self.logger.warning("daemon.config_consumer_unexpected_error", agent=self.name)

            setup_duration = time.monotonic() - setup_start
            AGENT_SETUP_LATENCY_SECONDS.record(setup_duration, self._setup_latency_attrs)
            AGENT_SETUP_SUCCESS_TOTAL.add(1, self._setup_success_attrs)
        except Exception as error:
            # Log setup failure AND track metric
            self.logger.exception("daemon.setup_failed")
            AGENT_SETUP_FAILURE_TOTAL.add(
                1, {"agent": self._agent_label, "error_type": type(error).__name__}
            )
            raise

        lag_task = asyncio.create_task(self._report_consumer_lag())
        watchdog_task = asyncio.create_task(self._watchdog_notify())
        stall_task = asyncio.create_task(self._stall_watchdog())
        try:
            await self._run()
        except Exception:
            # Log run failure AND track crash metric
            self.logger.exception("daemon.run_failed")
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
            await self._teardown_config_consumer()
            await self.stop()

    async def stop(self) -> None:
        """Lifecycle teardown. Override to add flush/drain logic."""
        self.logger.info("daemon.stopped", agent=self.name)

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

    def get_config(self, key: str, default: Any = None) -> Any:
        """Return cached OPS config value for key, or default if not present.

        Reads from in-memory _config_cache populated by _pre_setup_config_load()
        and updated by _reload_config_loop(). Safe to call at any time; returns
        default when config not loaded (DB down) or key not in OPS config.
        """
        return self._config_cache.get(key, default)

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
        """No-op for stream processors — they have no buffer lag to report.

        BaseWriter overrides this to report actual buffer depth via
        PERSISTENCE_CONSUMER_LAG.set(). Loops with a longer sleep so the
        stop event check still works without burning 4 OTel submissions/min.
        """
        while not self._stop_event.is_set():
            await asyncio.sleep(60)

    def _record_message_consumed(self) -> None:
        """Call once per successfully consumed Kafka message.

        Updates the monotonic stall clock and the OTel liveness gauge
        (`agent_last_message_timestamp_seconds`). Required for _stall_watchdog()
        and _watchdog_notify() liveness gating to work. Agents that never call
        this behave as before (no stall detection).
        """
        # monotonic for stall detection (immune to clock skew)
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
                    "daemon.stall_detected",
                    agent=self.name,
                    idle_seconds=int(idle_secs),
                    max_idle_seconds=self.max_idle_seconds,
                )
                sys.exit(1)

    async def _watchdog_notify(self) -> None:
        """Notify systemd watchdog — gated on liveness when max_idle_seconds > 0.

        When max_idle_seconds is 0 (default): pings unconditionally (backward-compatible).
        When max_idle_seconds > 0: suppresses pings only after max_idle_seconds of idle,
        allowing _stall_watchdog to fire sys.exit(1) first; systemd WatchdogSec is the
        secondary backstop if stall detection fails.
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
        # Suppress threshold must be >= max_idle_seconds so _stall_watchdog fires first.
        # Using interval_s * 2 caused services with max_idle_seconds=300 to be killed by
        # systemd after only 120s of idle (60s suppress + 60s WatchdogSec), defeating the
        # 5-minute stall budget entirely.
        stale_threshold = max(self.max_idle_seconds, interval_s * 2)
        while self.running:
            should_notify = True
            if self.max_idle_seconds > 0 and self._last_message_ts is not None:
                should_notify = (time.monotonic() - self._last_message_ts) < stale_threshold
            if should_notify:
                notifier.notify("WATCHDOG=1")
                WATCHDOG_NOTIFY_TOTAL.add(1, self._last_msg_ts_attrs)
            else:
                WATCHDOG_NOTIFY_SUPPRESSED_TOTAL.add(1, self._last_msg_ts_attrs)
            await asyncio.sleep(interval_s)

    async def _send_to_dlq(self, payload: dict, error: Exception) -> None:
        """Route unprocessable payload to DLQ. Default: log and discard.

        If subclass overrides _dlq_topic() to return a topic name, routes to DLQ
        with structured DLQPayload and emits metrics.
        """
        # Per-agent DLQ rollup counter — fires unconditionally on every DLQ path
        # (including log-only discard). agent_id label matches D-09 spec.
        AGENT_DLQ_TOTAL.add(1, self._dlq_attrs)

        from src.core.schemas.dlq_payload import DLQPayload
        from src.observability.metrics import DLQ_MESSAGES_TOTAL

        # Check if DLQ topic is configured
        dlq_topic = self._dlq_topic()

        if dlq_topic is None:
            # No DLQ configured — log and discard
            self.logger.error(
                "daemon.dlq_discard",
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
                    "daemon.dlq_routed",
                    agent=self.name,
                    topic=dlq_topic,
                    error_type=type(error).__name__,
                )
            else:
                # No producer available — log and discard
                self.logger.warning(
                    "daemon.dlq_no_producer",
                    agent=self.name,
                    topic=dlq_topic,
                    error=str(error),
                )
        except Exception as error:
            self.logger.error(
                "daemon.dlq_route_failed",
                agent=self.name,
                topic=dlq_topic,
                error=str(error),
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
        """Send alert to AlertMonitor via Kafka.

        Args:
            severity: "CRITICAL" | "HIGH" | "MEDIUM"
            message: Human-readable alert message
            context: Optional structured context (symbol, tf, error details, etc.)

        No-op if producer not configured (agents without Kafka output).
        AlertMonitor routes: CRITICAL → Telegram, HIGH/MEDIUM → Discord.
        """
        if not hasattr(self, "_producer") or self._producer is None:
            return

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
        except Exception as error:
            self.logger.error("alert_publish_failed", error=str(error))

    async def _setup_with_retry(self) -> None:
        """Wrap _setup() with exponential backoff retry.

        Reads attempt count and backoff base from class attributes
        SETUP_RETRY_ATTEMPTS and SETUP_RETRY_BACKOFF_S — subclasses
        override those to tune retry behavior without subclassing this method.
        """
        for attempt in range(self.SETUP_RETRY_ATTEMPTS):
            try:
                await self._setup()
                return
            except Exception as error:
                if attempt == self.SETUP_RETRY_ATTEMPTS - 1:
                    raise
                backoff = self.SETUP_RETRY_BACKOFF_S * (2**attempt)
                AGENT_SETUP_RETRIES_TOTAL.add(1, self._cb_attrs)
                self.logger.warning(
                    "daemon.setup_retry",
                    attempt=attempt + 1,
                    max_attempts=self.SETUP_RETRY_ATTEMPTS,
                    backoff_seconds=backoff,
                    error=str(error),
                )
                await asyncio.sleep(backoff)

    @abc.abstractmethod
    async def _run(self) -> None:
        """Main agent loop. Runs until ``_stop_event`` is set."""
        ...
