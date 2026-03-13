#!/usr/bin/env python3
"""
Timeframe Builder Service - Continuous multi-timeframe bar building

A production-grade daemon that continuously consumes 1m bars from Redis Streams
and builds higher timeframes (5m, 15m, 1h, 4h, 1d) for technical analysis.

Features:
- Daemon-style background operation
- Consumes 1m bars from market:ESU5:1m, market:NQU5:1m, etc.
- Produces 5m, 15m, 1h, 4h, 1d bars to market:ESU5:5m, etc.
- Consumer group pattern for reliability
- Performance monitoring and metrics
- Graceful shutdown handling

Version: 1.0.0
Last Updated: 2025-08-06
Status: Production Ready ✅
"""

import asyncio
import json
import logging
import signal
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from logging.handlers import RotatingFileHandler

import redis.asyncio as redis
import structlog
from aiohttp import web, web_request

from src.config.settings import get_active_contracts

# Import our components
from src.core.redis_streams_manager import RedisStreamsManager
from src.core.timeframe_builder import TimeframeBuilder


@dataclass
class TimeframeBuilderMetrics:
    """Timeframe builder service metrics."""

    start_time: datetime
    uptime_seconds: int
    total_1m_bars_processed: int
    bars_5m_built: int
    bars_15m_built: int
    bars_1h_built: int
    bars_4h_built: int
    bars_1d_built: int
    active_symbols: set[str]
    health_status: str
    processing_rate_bars_per_min: float
    error_count: int
    last_processing_time: datetime | None


class TimeframeBuilderService:
    """
    Production-grade timeframe builder service.

    Continuously consumes 1m bars and builds higher timeframes.
    """

    def __init__(self, config_file: str | None = None):
        """Initialize the timeframe builder service."""

        # Service state
        self.config = self._load_config(config_file)
        self._setup_logging()

        # Connection objects
        self.redis_client: redis.Redis | None = None
        self.streams_manager: RedisStreamsManager | None = None
        self.timeframe_builder: TimeframeBuilder | None = None

        # Service control
        self.running = False
        self.shutdown_requested = False

        # Metrics
        self.metrics = TimeframeBuilderMetrics(
            start_time=datetime.now(),
            uptime_seconds=0,
            total_1m_bars_processed=0,
            bars_5m_built=0,
            bars_15m_built=0,
            bars_1h_built=0,
            bars_4h_built=0,
            bars_1d_built=0,
            active_symbols=set(),
            health_status="starting",
            processing_rate_bars_per_min=0.0,
            error_count=0,
            last_processing_time=None,
        )

        # HTTP server for health endpoints
        self.http_app: web.Application | None = None
        self.http_server: web.TCPSite | None = None
        self.health_port = 9110  # Port for health endpoint

        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger = structlog.get_logger(__name__)

    def _load_config(self, config_file: str | None) -> dict[str, Any]:
        """Load service configuration."""
        default_config = {
            "redis": {"host": "localhost", "port": 6379, "db": 0},
            "service": {
                "symbols": get_active_contracts(),  # Use centralized symbol config
                "source_timeframe": "1m",
                "target_timeframes": ["5m", "15m", "1h", "4h", "1d"],
                "processing_interval": 1.0,
                "health_check_interval": 30,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/timeframe_builder.log",
                "max_size": "10MB",
                "backup_count": 5,
            },
        }

        if config_file and Path(config_file).exists():
            with open(config_file) as f:
                user_config = json.load(f)
                # Merge with defaults
                for key, value in user_config.items():
                    if isinstance(value, dict) and key in default_config:
                        default_config[key].update(value)
                    else:
                        default_config[key] = value

        return default_config

    def _setup_logging(self):
        """Setup structured logging with file rotation."""
        log_dir = Path(self.config["logging"]["file"]).parent
        log_dir.mkdir(exist_ok=True)

        # Setup rotating file handler
        file_handler = RotatingFileHandler(
            self.config["logging"]["file"], maxBytes=10 * 1024 * 1024, backupCount=5  # 10MB
        )

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
                structlog.processors.UnicodeDecoder(),
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

    async def start(self):
        """Start the timeframe builder service."""
        self.logger.info("🚀 Starting Timeframe Builder Service...", config=self.config["service"])

        try:
            # Connect to Redis
            await self._connect_redis()

            # Setup streams manager
            await self._setup_streams_manager()

            # Start timeframe builder
            await self._start_timeframe_builder()

            # Start HTTP server for health endpoints
            await self._start_http_server()

            # Start service tasks
            self.running = True
            tasks = [
                asyncio.create_task(self._monitor_builder()),
                asyncio.create_task(self._health_monitor_loop()),
                asyncio.create_task(self._metrics_update_loop()),
            ]

            self.logger.info("✅ Timeframe Builder Service started successfully")

            # Wait for all tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            self.logger.error("Failed to start timeframe builder service", error=str(e))
            raise
        finally:
            await self.stop()

    async def _connect_redis(self):
        """Connect to Redis."""
        try:
            self.redis_client = redis.Redis(
                host=self.config["redis"]["host"],
                port=self.config["redis"]["port"],
                db=self.config["redis"]["db"],
                decode_responses=False,
                max_connections=20,
            )
            await self.redis_client.ping()
            self.logger.info(
                "✅ Connected to Redis",
                host=self.config["redis"]["host"],
                port=self.config["redis"]["port"],
            )
        except Exception as e:
            self.logger.error("Redis connection failed", error=str(e))
            raise

    async def _setup_streams_manager(self):
        """Setup Redis streams manager."""
        try:
            self.streams_manager = RedisStreamsManager(self.redis_client)
            await self.streams_manager.start()
            self.logger.info("✅ Redis Streams Manager ready")
        except Exception as e:
            self.logger.error("Streams manager setup failed", error=str(e))
            raise

    async def _start_timeframe_builder(self):
        """Start the timeframe builder."""
        try:
            self.timeframe_builder = TimeframeBuilder(self.streams_manager)
            await self.timeframe_builder.start()

            # Subscribe to configured symbols
            symbols = self.config["service"]["symbols"]
            await self.timeframe_builder.subscribe_to_symbols(symbols)

            self.logger.info("✅ Timeframe Builder started", symbols=symbols)
        except Exception as e:
            self.logger.error("Timeframe builder start failed", error=str(e))
            raise

    async def _monitor_builder(self):
        """Monitor timeframe builder and update metrics."""
        self.logger.info("🔄 Starting builder monitoring loop")

        while self.running and not self.shutdown_requested:
            try:
                # Get builder metrics
                if self.timeframe_builder:
                    builder_metrics = self.timeframe_builder.get_metrics()

                    # Update service metrics
                    self.metrics.total_1m_bars_processed = builder_metrics.get(
                        "bars_1m_processed", 0
                    )
                    self.metrics.bars_5m_built = builder_metrics.get("bars_5m_built", 0)
                    self.metrics.bars_15m_built = builder_metrics.get("bars_15m_built", 0)
                    self.metrics.bars_1h_built = builder_metrics.get("bars_1h_built", 0)
                    self.metrics.bars_4h_built = builder_metrics.get("bars_4h_built", 0)
                    self.metrics.bars_1d_built = builder_metrics.get("bars_1d_built", 0)
                    self.metrics.active_symbols = builder_metrics.get("symbols_active", set())

                    # Calculate processing rate
                    uptime = (datetime.now() - self.metrics.start_time).total_seconds()
                    if uptime > 0:
                        self.metrics.processing_rate_bars_per_min = (
                            self.metrics.total_1m_bars_processed * 60.0 / uptime
                        )

                    self.metrics.last_processing_time = datetime.now()
                    self.metrics.health_status = "healthy"

                await asyncio.sleep(self.config["service"]["processing_interval"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in builder monitoring", error=str(e))
                self.metrics.error_count += 1
                await asyncio.sleep(1)

    async def _health_monitor_loop(self):
        """Health monitoring loop."""
        while self.running and not self.shutdown_requested:
            try:
                # Update uptime
                self.metrics.uptime_seconds = int(
                    (datetime.now() - self.metrics.start_time).total_seconds()
                )

                # Check health every 30 seconds
                if self.metrics.uptime_seconds > 0 and self.metrics.uptime_seconds % 30 == 0:
                    self.logger.info(
                        "Health check",
                        uptime=self.metrics.uptime_seconds,
                        bars_1m_processed=self.metrics.total_1m_bars_processed,
                        bars_5m_built=self.metrics.bars_5m_built,
                        bars_15m_built=self.metrics.bars_15m_built,
                        bars_1h_built=self.metrics.bars_1h_built,
                        processing_rate=self.metrics.processing_rate_bars_per_min,
                        health_status=self.metrics.health_status,
                    )

                await asyncio.sleep(self.config["service"]["health_check_interval"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in health monitoring", error=str(e))
                self.metrics.error_count += 1
                await asyncio.sleep(5)

    async def _metrics_update_loop(self):
        """Metrics update loop."""
        while self.running and not self.shutdown_requested:
            try:
                # Write metrics to status file
                status_file = Path("logs/timeframe_builder_status.json")
                status_file.parent.mkdir(exist_ok=True)

                status = {
                    "service": "timeframe_builder",
                    "status": self.metrics.health_status,
                    "uptime_seconds": self.metrics.uptime_seconds,
                    "bars_1m_processed": self.metrics.total_1m_bars_processed,
                    "bars_5m_built": self.metrics.bars_5m_built,
                    "bars_15m_built": self.metrics.bars_15m_built,
                    "bars_1h_built": self.metrics.bars_1h_built,
                    "bars_4h_built": self.metrics.bars_4h_built,
                    "bars_1d_built": self.metrics.bars_1d_built,
                    "processing_rate_bars_per_min": self.metrics.processing_rate_bars_per_min,
                    "active_symbols": list(self.metrics.active_symbols),
                    "error_count": self.metrics.error_count,
                    "last_update": datetime.now().isoformat(),
                }

                with open(status_file, "w") as f:
                    json.dump(status, f, indent=2)

                await asyncio.sleep(60)  # Update every minute

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error writing metrics", error=str(e))
                await asyncio.sleep(5)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info("Received shutdown signal", signal=signum)
        self.shutdown_requested = True

    async def stop(self):
        """Stop the service."""
        self.logger.info("⏹️  Stopping Timeframe Builder Service...")

        self.running = False
        self.shutdown_requested = True

        # Stop HTTP server
        await self._stop_http_server()

        # Stop timeframe builder
        if self.timeframe_builder:
            await self.timeframe_builder.stop()

        # Stop streams manager
        if self.streams_manager:
            await self.streams_manager.stop()

        # Close Redis connection
        if self.redis_client:
            await self.redis_client.aclose()

        self.logger.info("✅ Timeframe Builder Service stopped")

    async def _start_http_server(self):
        """Start HTTP server for health endpoints."""
        try:
            self.http_app = web.Application()

            # Add health endpoint
            self.http_app.router.add_get("/health", self._handle_health)
            self.http_app.router.add_get("/metrics", self._handle_metrics)

            # Start server
            runner = web.AppRunner(self.http_app)
            await runner.setup()

            self.http_server = web.TCPSite(runner, "localhost", self.health_port)
            await self.http_server.start()

            self.logger.info("HTTP health server started", port=self.health_port)

        except Exception as e:
            self.logger.error("Failed to start HTTP server", error=str(e))
            raise

    async def _stop_http_server(self):
        """Stop HTTP server."""
        try:
            if self.http_server:
                await self.http_server.stop()
                self.http_server = None
                self.logger.info("HTTP health server stopped")
        except Exception as e:
            self.logger.error("Error stopping HTTP server", error=str(e))

    async def _handle_health(self, request: web_request.Request) -> web.Response:
        """Handle health check endpoint."""
        try:
            health_data = {
                "status": self.metrics.health_status,
                "service": "timeframe_builder",
                "uptime_seconds": self.metrics.uptime_seconds,
                "bars_1m_processed": self.metrics.total_1m_bars_processed,
                "bars_5m_built": self.metrics.bars_5m_built,
                "bars_15m_built": self.metrics.bars_15m_built,
                "bars_1h_built": self.metrics.bars_1h_built,
                "bars_4h_built": self.metrics.bars_4h_built,
                "bars_1d_built": self.metrics.bars_1d_built,
                "active_symbols": list(self.metrics.active_symbols),
                "processing_rate": self.metrics.processing_rate_bars_per_min,
                "error_count": self.metrics.error_count,
                "last_processing": (
                    self.metrics.last_processing_time.isoformat()
                    if self.metrics.last_processing_time
                    else None
                ),
                "timestamp": datetime.now().isoformat(),
            }

            # Return appropriate HTTP status based on health
            if self.metrics.health_status == "healthy":
                status = 200
            elif self.metrics.health_status in ["degraded", "starting"]:
                status = 503  # Service Unavailable but recoverable
            else:
                status = 500  # Internal Server Error

            return web.json_response(health_data, status=status)

        except Exception as e:
            self.logger.error("Error in health endpoint", error=str(e))
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def _handle_metrics(self, request: web_request.Request) -> web.Response:
        """Handle metrics endpoint (Prometheus-style)."""
        try:
            metrics_text = f"""# HELP timeframe_1m_bars_processed_total Total 1m bars processed
# TYPE timeframe_1m_bars_processed_total counter
timeframe_1m_bars_processed_total {self.metrics.total_1m_bars_processed}

# HELP timeframe_5m_bars_built_total Total 5m bars built
# TYPE timeframe_5m_bars_built_total counter
timeframe_5m_bars_built_total {self.metrics.bars_5m_built}

# HELP timeframe_15m_bars_built_total Total 15m bars built
# TYPE timeframe_15m_bars_built_total counter
timeframe_15m_bars_built_total {self.metrics.bars_15m_built}

# HELP timeframe_1h_bars_built_total Total 1h bars built
# TYPE timeframe_1h_bars_built_total counter
timeframe_1h_bars_built_total {self.metrics.bars_1h_built}

# HELP timeframe_4h_bars_built_total Total 4h bars built
# TYPE timeframe_4h_bars_built_total counter
timeframe_4h_bars_built_total {self.metrics.bars_4h_built}

# HELP timeframe_1d_bars_built_total Total 1d bars built
# TYPE timeframe_1d_bars_built_total counter
timeframe_1d_bars_built_total {self.metrics.bars_1d_built}

# HELP timeframe_errors_total Total processing errors
# TYPE timeframe_errors_total counter
timeframe_errors_total {self.metrics.error_count}

# HELP timeframe_uptime_seconds Service uptime in seconds
# TYPE timeframe_uptime_seconds gauge
timeframe_uptime_seconds {self.metrics.uptime_seconds}

# HELP timeframe_processing_rate_bars_per_min Processing rate in bars per minute
# TYPE timeframe_processing_rate_bars_per_min gauge
timeframe_processing_rate_bars_per_min {self.metrics.processing_rate_bars_per_min}

# HELP timeframe_active_symbols Number of active symbols being processed
# TYPE timeframe_active_symbols gauge
timeframe_active_symbols {len(self.metrics.active_symbols)}
"""

            return web.Response(
                text=metrics_text, content_type="text/plain; version=0.0.4; charset=utf-8"
            )

        except Exception as e:
            self.logger.error("Error in metrics endpoint", error=str(e))
            return web.Response(text=f"# Error: {e}", status=500)


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Timeframe Builder Service")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground")

    args = parser.parse_args()

    service = TimeframeBuilderService(args.config)

    if args.foreground:
        print("🚀 Starting Timeframe Builder Service in foreground...")
        print("Press Ctrl+C to stop")

    try:
        await service.start()
    except KeyboardInterrupt:
        print("\n⏹️  Service stopped by user")
    except Exception as e:
        print(f"❌ Service failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
