#!/usr/bin/env python3
"""Regime Gate Service — suppresses signals based on HMM regime."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.stages.regime_gate import RegimeGateService
from src.observability.metrics import start_metrics_server

logger = structlog.get_logger(__name__)

METRICS_PORT = 9120


async def main() -> None:
    """Main service entry point."""
    setup_service_logging("regime_gate")
    settings = Settings()
    logger.info("Starting Regime Gate Service", port=METRICS_PORT)
    start_metrics_server(METRICS_PORT)
    stage = RegimeGateService(settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(stage)))

    logger.info("Regime Gate Service running")
    await stage.run()


async def shutdown(stage: RegimeGateService) -> None:
    """Graceful shutdown."""
    logger.info("Shutting down Regime Gate Service")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
