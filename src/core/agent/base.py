"""BaseAgent — abstract base class for all IndicAgent pipeline agents.

Provides the Renaissance Agentic DAG standard lifecycle:
- SIGTERM/SIGINT drain via asyncio event (asyncio.get_running_loop, not deprecated get_event_loop)
- Structured logging via structlog bound with agent name
- Consumer lag reporting scaffolding (override in concrete agents)
- OTel tracer via get_tracer(name) — no-op when init_tracing() not called
- Optional Prometheus metrics auto-start via metrics_port parameter
- _setup()/_teardown() lifecycle hooks (no-op by default, override in subclasses)
- running property derived from stop_event state
- topics_consumed/topics_produced/lag_threshold_messages for ProcessManifest (Plan 03)
- _send_to_dlq() stub — logs and discards; override when DLQ topics are provisioned
- start/stop/run contract enforced via abc.ABC
"""

from __future__ import annotations

import abc
import asyncio
import signal

import structlog

from src.observability.metrics import start_metrics_server
from src.observability.otel import get_tracer


class BaseAgent(abc.ABC):
    """Abstract base for all pipeline agents.

    Subclasses must implement ``_run()``. The lifecycle is:
    1. ``start()`` — registers signal handlers, optionally starts metrics server,
       calls ``_setup()``, starts lag reporter, calls ``_run()``.
    2. ``_run()`` — main loop; runs until ``_stop_event`` is set.
    3. ``_teardown()`` — called in finally block after ``_run()`` exits (or raises).
    4. ``stop()`` — called after ``_teardown()``; override to add flush logic.
    """

    def __init__(self, name: str, metrics_port: int | None = None) -> None:
        self.name = name
        self._metrics_port = metrics_port
        self._stop_event: asyncio.Event = asyncio.Event()
        # NOTE: attribute is self.logger (not self.log) to match the 20+ call sites
        # in existing agents that use self.logger.
        self.logger: structlog.BoundLogger = structlog.get_logger().bind(agent=name)
        # OTel tracer — no-op when init_tracing() has not been called; safe before init.
        self.tracer = get_tracer(name)

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
        3. Log agent.starting.
        4. Call _setup() — connect Kafka, seed history, etc.
        5. Launch lag reporter as background task.
        6. Await _run(). On Exception: log agent.run_failed and re-raise.
        7. finally: cancel lag task, await _teardown(), call stop().
        """
        self._register_signal_handlers()
        if self._metrics_port is not None:
            start_metrics_server(port=self._metrics_port)
        self.logger.info("agent.starting", agent=self.name)
        await self._setup()
        lag_task = asyncio.create_task(self._report_consumer_lag())
        try:
            await self._run()
        except Exception:
            self.logger.exception("agent.run_failed", agent=self.name)
            raise
        finally:
            lag_task.cancel()
            try:
                await lag_task
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
        """No-op consumer lag reporter.

        Override in concrete agents to emit PERSISTENCE_CONSUMER_LAG metrics.
        Loops until ``_stop_event`` is set.
        """
        while not self._stop_event.is_set():
            await asyncio.sleep(15)

    async def _send_to_dlq(self, payload: dict, error: Exception) -> None:
        """Route unprocessable payload to DLQ. Default: log and discard.

        Override when DLQ topics are provisioned:
            await self._kafka_producer.produce(topic_dlq(...), payload)
        """
        self.logger.error(
            "agent.dlq_discard",
            agent=self.name,
            error=str(error),
            payload_keys=list(payload.keys()) if isinstance(payload, dict) else None,
        )

    @abc.abstractmethod
    async def _run(self) -> None:
        """Main agent loop. Runs until ``_stop_event`` is set."""
        ...
