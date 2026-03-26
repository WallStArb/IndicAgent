"""BaseAgent — abstract base class for all IndicAgent pipeline agents.

Provides the Renaissance Agentic DAG standard lifecycle:
- SIGTERM/SIGINT drain via asyncio event (asyncio.get_running_loop, not deprecated get_event_loop)
- Structured logging via structlog bound with agent name
- Consumer lag reporting scaffolding (override in concrete agents)
- start/stop/run contract enforced via abc.ABC
"""

from __future__ import annotations

import abc
import asyncio
import signal

import structlog


class BaseAgent(abc.ABC):
    """Abstract base for all pipeline agents.

    Subclasses must implement ``_run()``. The lifecycle is:
    1. ``start()`` — registers signal handlers, starts lag reporter, calls ``_run()``.
    2. ``_run()`` — main loop; runs until ``_stop_event`` is set.
    3. ``stop()`` — called in ``start()`` finally block; override to add flush logic.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._stop_event: asyncio.Event = asyncio.Event()
        # NOTE: attribute is self.logger (not self.log) to match the 20+ call sites
        # in existing agents that use self.logger.
        self.logger: structlog.BoundLogger = structlog.get_logger().bind(agent=name)

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

        Registers signal handlers, launches the lag reporter as a background task,
        awaits ``_run()``, cancels the lag task in the finally block, then calls
        ``stop()`` for any flush logic.
        """
        self._register_signal_handlers()
        self.logger.info("agent.starting", agent=self.name)
        lag_task = asyncio.create_task(self._report_consumer_lag())
        try:
            await self._run()
        finally:
            lag_task.cancel()
            try:
                await lag_task
            except asyncio.CancelledError:
                pass
            await self.stop()

    async def stop(self) -> None:
        """Lifecycle teardown. Override to add flush/drain logic."""
        self.logger.info("agent.stopped", agent=self.name)

    async def _report_consumer_lag(self) -> None:
        """No-op consumer lag reporter.

        Override in concrete agents to emit PERSISTENCE_CONSUMER_LAG metrics.
        Loops until ``_stop_event`` is set.
        """
        while not self._stop_event.is_set():
            await asyncio.sleep(15)

    @abc.abstractmethod
    async def _run(self) -> None:
        """Main agent loop. Runs until ``_stop_event`` is set."""
        ...
