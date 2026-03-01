"""Health monitoring mixin for services.

Provides a generic health monitoring loop that accepts a callback for
service-specific metrics logging. Eliminates ~60 lines of duplicated code
across 5 services (indicator, market_analysis, signal_generator, feature_writer, ai_narrative).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class HealthMonitoringMixin:
    """Mixin providing health monitoring capabilities for services.

    Services inherit from this mixin and call `_start_health_monitor()` during startup.
    The mixin runs a background task that logs health status at the configured interval.
    """

    def _start_health_monitor(self) -> asyncio.Task[None]:
        """Start the health monitoring background task.

        Returns:
            asyncio.Task: The monitoring loop task, or None if already running
        """
        if (
            hasattr(self, "_health_monitor_task")
            and self._health_monitor_task
            and not self._health_monitor_task.done()
        ):
            return None  # Already running

        async def _health_monitor_loop() -> None:
            """Health monitoring loop that calls service-specific metrics callback.

            The service must override `_get_health_metrics()` to return a dict of
            metrics to log (e.g., uptime, bars_processed, signals_generated, errors).
            """
            interval = self.config.get("service", {}).get("health_check_interval", 30)

            while self.running and not self.shutdown_requested:
                try:
                    uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())

                    # Get service-specific health metrics from callback
                    metrics = await self._get_health_metrics()

                    # Log health check
                    self.logger.info(
                        "Health check",
                        uptime=uptime,
                        **metrics,
                    )

                    await asyncio.sleep(interval)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error("Error in health monitor", error=str(e))
                    await asyncio.sleep(5)  # Backoff before retry

        # Create and store task reference
        self._health_monitor_task = asyncio.create_task(_health_monitor_loop())

        return self._health_monitor_task

    def _get_health_metrics(self) -> dict[str, Any]:
        """Override in subclass to return service-specific health metrics.

        Returns:
            dict[str, Any]: Key-value pairs of metrics to log

        Default implementation returns empty dict. Subclasses should override this.
        """
        return {}

    async def stop_health_monitor(self) -> None:
        """Stop the health monitoring background task."""
        if hasattr(self, "_health_monitor_task") and self._health_monitor_task:
            self._health_monitor_task.cancel()
            self._health_monitor_task = None
