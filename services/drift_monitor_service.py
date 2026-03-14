#!/usr/bin/env python3
"""
Drift Monitor Service — QUAL-09 KS distribution drift detection.

Runs KSDriftMonitor.run_forever() for all active contracts × timeframes.
Writes KS penalty severity to the drift_state DB table so signal_generator
can automatically reduce confidence on features whose distributions have
shifted from baseline. signal_generator reads drift_state at startup and
every 4h via _refresh_drift_penalties_from_db().

Phase 30: Redis dependency removed. All drift state written to drift_state table.

Prometheus metrics on :9118.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog

from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.monitoring.cusum_monitor import CUSUMMonitor
from src.monitoring.ks_drift_monitor import KSDriftMonitor
from src.observability.metrics import counter, gauge, start_metrics_server


class DriftMonitorService:
    """Orchestrates KS drift checks for all active symbol/TF pairs."""

    def __init__(self, config_file: str | None = None):
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(tz=UTC)
        self.config = self._load_config(config_file)
        self._setup_logging()

        self.db_manager: DatabaseManager | None = None

        settings = Settings()
        self.env_prefix = f"{settings.env_name}:" if settings.env_name else ""

        # Prometheus metrics
        self.checks_cycle_total = counter(
            "drift_monitor_cycles_total",
            "Total drift monitor check cycles completed",
        )
        self.service_uptime_seconds = gauge(
            "drift_monitor_uptime_seconds",
            "Drift monitor service uptime in seconds",
        )
        self.error_count_total = counter(
            "drift_monitor_errors_total",
            "Total errors in drift monitor service",
        )

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        try:
            _settings = Settings()
        except Exception:
            _settings = None

        default: dict[str, Any] = {
            "database": {
                "url": (
                    _settings.database_url
                    if _settings and getattr(_settings, "database_url", None)
                    else "postgresql://postgres:postgres@localhost:5432/indicagent"
                )
            },
            "service": {
                "symbols": get_active_contracts(),
                "timeframes": ["1m", "5m", "15m", "1h"],
                "ks_interval_seconds": 4 * 3600,  # 4 hours
                "cusum_interval_seconds": 3600,  # 1 hour
            },
            "metrics_port": 9118,
            "logging": {
                "level": "INFO",
                "file": "logs/drift_monitor_service.log",
            },
        }
        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
            for k, v in user_config.items():
                if isinstance(v, dict) and k in default:
                    default[k].update(v)
                else:
                    default[k] = v
        return default

    def _setup_logging(self) -> None:
        from src.core.service_utils import setup_service_logging

        setup_service_logging(
            self.config["logging"]["file"],
            level=self.config["logging"].get("level", "INFO"),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True
        self.running = False

    async def _connect_database(self) -> None:
        try:
            self.db_manager = DatabaseManager(self.config["database"]["url"])
            await self.db_manager.initialize()
        except Exception as e:
            self.logger.warning("Database unavailable", error=str(e))
            self.db_manager = None

    async def _health_monitor_loop(self) -> None:
        while self.running and not self.shutdown_requested:
            try:
                uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())
                self.service_uptime_seconds.set(uptime)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def _ks_task(self) -> None:
        """Run KSDriftMonitor.run_forever() until shutdown."""
        if not self.db_manager:
            self.logger.warning("KS task: DB unavailable — skipping")
            return

        symbols = self.config["service"]["symbols"]
        timeframes = self.config["service"]["timeframes"]
        interval = self.config["service"]["ks_interval_seconds"]

        monitor = KSDriftMonitor(
            db_pool=self.db_manager.pool,
            env_prefix=self.env_prefix,
            timeframes=timeframes,
        )

        try:
            await monitor.run_forever(symbols=symbols, interval_seconds=interval)
        except asyncio.CancelledError:
            self.logger.info("KS monitor task cancelled")
        except Exception as exc:
            self.error_count_total.inc()
            self.logger.error("KS monitor task failed", error=str(exc))
            raise

    async def _cusum_task(self) -> None:
        """Run CUSUMMonitor.run_forever() until shutdown."""
        if not self.db_manager:
            self.logger.warning("CUSUM task: DB unavailable — skipping")
            return

        interval = self.config["service"]["cusum_interval_seconds"]

        monitor = CUSUMMonitor(
            db_pool=self.db_manager.pool,
            env_prefix=self.env_prefix,
        )

        try:
            await monitor.run_forever(interval_seconds=interval)
        except asyncio.CancelledError:
            self.logger.info("CUSUM monitor task cancelled")
        except Exception as exc:
            self.error_count_total.inc()
            self.logger.error("CUSUM monitor task failed", error=str(exc))
            raise

    async def start(self) -> None:
        self.logger.info(
            "Starting Drift Monitor Service",
            symbols=self.config["service"]["symbols"],
            timeframes=self.config["service"]["timeframes"],
        )
        try:
            await self._connect_database()
            start_metrics_server(port=self.config.get("metrics_port", 9118))
            self.running = True
            tasks = [
                asyncio.create_task(self._ks_task()),
                asyncio.create_task(self._cusum_task()),
                asyncio.create_task(self._health_monitor_loop()),
            ]
            self.logger.info("Drift Monitor Service started", service="drift_monitor")
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error("Failed to start drift monitor", error=str(e))
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("Stopping Drift Monitor Service")
        self.running = False
        self.shutdown_requested = True
        if self.db_manager:
            await self.db_manager.close()


def main() -> None:
    svc = DriftMonitorService()
    asyncio.run(svc.start())


if __name__ == "__main__":
    main()
