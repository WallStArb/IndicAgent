#!/usr/bin/env python3
"""Quality Gate Service — applies Hurst x Entropy and drift penalty multipliers."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

# Ensure project root is on the path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.stages.quality_gate import QualityGateService
from src.observability.metrics import start_metrics_server

logger = structlog.get_logger(__name__)

# Metrics port — increments from :9118 (cross-asset)
METRICS_PORT = 9119

_main_task: asyncio.Task | None = None


async def main() -> None:
    """Main service entry point."""
    global _main_task
    setup_service_logging("logs/quality_gate_service.log")

    settings = Settings()

    logger.info("Starting Quality Gate Service", port=METRICS_PORT)

    start_metrics_server(METRICS_PORT)

    stage = QualityGateService(settings)

    _main_task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(stage)))

    logger.info("Quality Gate Service running")
    await stage.run()


async def shutdown(stage: QualityGateService) -> None:
    """Graceful shutdown."""
    logger.info("Shutting down Quality Gate Service")
    if _main_task:
        _main_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
