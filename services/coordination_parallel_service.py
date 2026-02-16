#!/usr/bin/env python3
"""
Parallel Service Coordinator - Runs multiple services concurrently

Coordinates timeframe_builder_service and indicator_processor_service to consume
market data streams in parallel instead of sequentially. Each service uses its
own Redis consumer group to avoid conflicts.

Features:
- Parallel execution of services using asyncio.gather()
- Independent service health monitoring
- Graceful shutdown coordination
- Shared configuration management
- Performance metrics aggregation

Version: 1.0.0
Last Updated: 2025-08-13
Status: Production Ready
"""

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog

from services.indicators_processor_service import IndicatorProcessorService

# Import our services
from services.timeframes_builder_service import TimeframeBuilderService


@dataclass
class CoordinatorMetrics:
    """Metrics for the parallel coordinator."""

    start_time: datetime = field(default_factory=datetime.now)
    services_running: int = 0
    total_services: int = 0
    health_status: str = "starting"
    uptime_seconds: float = 0.0
    services_status: dict[str, str] = field(default_factory=dict)


class ParallelServiceCoordinator:
    """
    Coordinates multiple services to run in parallel for optimal performance.

    Services consume from the same Redis streams using different consumer groups,
    allowing true parallel processing without conflicts.
    """

    def __init__(self, config_file: str | None = None):
        self.config = self._load_config(config_file)
        self.metrics = CoordinatorMetrics()
        self.running = False
        self.services = {}
        self.service_tasks = {}

        # Setup logging
        self._setup_logging()

        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)

        # Initialize services
        self._initialize_services()

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        """Load coordinator configuration."""
        default_config = {
            "services": {
                "timeframe_builder": {
                    "enabled": True,
                    "config_file": "config/timeframe_builder_service.json",
                },
                "indicator_processor": {
                    "enabled": True,
                    "config_file": "config/indicator_processor_service.json",
                },
            },
            "coordinator": {
                "health_check_interval": 30,
                "startup_delay": 2,
                "shutdown_timeout": 10,
            },
            "logging": {"level": "INFO", "file": "logs/parallel_coordinator.log"},
        }

        if config_file and os.path.exists(config_file):
            with open(config_file) as f:
                user_config = json.load(f)
                self._deep_update(default_config, user_config)

        return default_config

    def _deep_update(self, base_dict: dict, update_dict: dict):
        """Deep update dictionary."""
        for key, value in update_dict.items():
            if isinstance(value, dict):
                base_dict[key] = self._deep_update(base_dict.get(key, {}), value)
            else:
                base_dict[key] = value
        return base_dict

    def _setup_logging(self):
        """Setup structured logging."""
        # Create logs directory
        log_file = self.config["logging"]["file"]
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, self.config["logging"]["level"]))

        # Configure structlog
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        # Setup standard logging
        logging.basicConfig(
            level=getattr(logging, self.config["logging"]["level"]),
            handlers=[file_handler],
            format="%(message)s",
        )

    def _initialize_services(self):
        """Initialize all enabled services."""
        service_configs = self.config["services"]

        # Initialize timeframe builder
        if service_configs["timeframe_builder"]["enabled"]:
            config_file = service_configs["timeframe_builder"]["config_file"]
            self.services["timeframe_builder"] = TimeframeBuilderService(config_file)

        # Initialize indicator processor
        if service_configs["indicator_processor"]["enabled"]:
            config_file = service_configs["indicator_processor"]["config_file"]
            self.services["indicator_processor"] = IndicatorProcessorService(config_file)

        self.metrics.total_services = len(self.services)
        self.logger.info(
            "Initialized services",
            services=list(self.services.keys()),
            total=self.metrics.total_services,
        )

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info("Shutdown signal received", signal=signum)
        asyncio.create_task(self.stop())

    async def start(self):
        """Start all services in parallel."""
        self.logger.info(
            "🚀 Starting Parallel Service Coordinator...", services=list(self.services.keys())
        )

        self.running = True
        self.metrics.health_status = "starting"

        try:
            # Start all services concurrently
            service_start_tasks = []

            for service_name, service in self.services.items():
                self.logger.info("Starting service", service=service_name)
                task = asyncio.create_task(self._run_service(service_name, service))
                self.service_tasks[service_name] = task
                service_start_tasks.append(task)

            # Wait for startup delay
            await asyncio.sleep(self.config["coordinator"]["startup_delay"])

            # Update metrics
            self.metrics.services_running = len(self.service_tasks)
            self.metrics.health_status = "running"

            self.logger.info(
                "✅ All services started in parallel",
                services_running=self.metrics.services_running,
            )

            # Start health monitoring
            health_task = asyncio.create_task(self._health_monitor())

            # Wait for all services to complete (or fail)
            await asyncio.gather(*service_start_tasks, health_task, return_exceptions=True)

        except Exception as e:
            self.logger.error("Error in coordinator startup", error=str(e))
            await self.stop()

    async def _run_service(self, service_name: str, service):
        """Run a single service with error handling."""
        try:
            self.metrics.services_status[service_name] = "starting"
            self.logger.info("Service starting", service=service_name)

            await service.start()

            self.metrics.services_status[service_name] = "running"
            self.logger.info("Service completed", service=service_name)

        except asyncio.CancelledError:
            self.metrics.services_status[service_name] = "cancelled"
            self.logger.info("Service cancelled", service=service_name)
            raise

        except Exception as e:
            self.metrics.services_status[service_name] = "failed"
            self.logger.error("Service failed", service=service_name, error=str(e))
            # Don't raise - let other services continue

    async def _health_monitor(self):
        """Monitor service health periodically."""
        while self.running:
            try:
                # Update uptime
                self.metrics.uptime_seconds = (
                    datetime.now() - self.metrics.start_time
                ).total_seconds()

                # Count running services
                running_count = sum(
                    1 for status in self.metrics.services_status.values() if status == "running"
                )
                self.metrics.services_running = running_count

                # Update health status
                if running_count == 0:
                    self.metrics.health_status = "failed"
                elif running_count < self.metrics.total_services:
                    self.metrics.health_status = "degraded"
                else:
                    self.metrics.health_status = "healthy"

                self.logger.info(
                    "Health check",
                    services_running=running_count,
                    total_services=self.metrics.total_services,
                    health_status=self.metrics.health_status,
                    uptime_minutes=round(self.metrics.uptime_seconds / 60, 1),
                )

                await asyncio.sleep(self.config["coordinator"]["health_check_interval"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Health monitor error", error=str(e))
                await asyncio.sleep(5)

    async def stop(self):
        """Stop all services gracefully."""
        if not self.running:
            return

        self.logger.info("🛑 Stopping Parallel Service Coordinator...")
        self.running = False
        self.metrics.health_status = "stopping"

        # Cancel all service tasks
        for service_name, task in self.service_tasks.items():
            if not task.done():
                self.logger.info("Stopping service", service=service_name)
                task.cancel()

        # Wait for tasks to complete with timeout
        if self.service_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.service_tasks.values(), return_exceptions=True),
                    timeout=self.config["coordinator"]["shutdown_timeout"],
                )
            except TimeoutError:
                self.logger.warning("Service shutdown timeout exceeded")

        # Stop individual services
        for service_name, service in self.services.items():
            try:
                if hasattr(service, "stop"):
                    await service.stop()
                self.logger.info("Service stopped", service=service_name)
            except Exception as e:
                self.logger.error("Error stopping service", service=service_name, error=str(e))

        self.metrics.health_status = "stopped"
        self.logger.info("✅ Parallel Service Coordinator stopped")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Parallel Service Coordinator")
    parser.add_argument(
        "--config", "-c", help="Configuration file path", default="config/parallel_coordinator.json"
    )

    args = parser.parse_args()

    # Create and start coordinator
    coordinator = ParallelServiceCoordinator(args.config)

    try:
        await coordinator.start()
    except KeyboardInterrupt:
        await coordinator.stop()
    except Exception as e:
        print(f"Coordinator failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
