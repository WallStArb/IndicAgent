#!/usr/bin/env python3
"""Calibrator Service — applies isotonic regression confidence calibration."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.stages.calibrator import CalibratorService
from src.observability.metrics import start_metrics_server

logger = structlog.get_logger(__name__)

_main_task: asyncio.Task | None = None

METRICS_PORT = 9122


async def main() -> None:
    """Main service entry point."""
    global _main_task
    setup_service_logging("logs/calibrator_service.log")
    settings = Settings()
    logger.info("Starting Calibrator Service", port=METRICS_PORT)
    start_metrics_server(METRICS_PORT)
    stage = CalibratorService(settings)

    _main_task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(stage)))

    logger.info("Calibrator Service running")
    await stage.run()


async def shutdown(stage: CalibratorService) -> None:
    """Graceful shutdown."""
    logger.info("Shutting down Calibrator Service")
    if _main_task:
        _main_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
