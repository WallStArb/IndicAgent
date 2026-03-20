#!/usr/bin/env python3
"""Winner Selector Service — selects winning signal using CIS or priority/majority."""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.stages.winner_selector import WinnerSelectorService
from src.observability.metrics import start_metrics_server

logger = structlog.get_logger(__name__)

_main_task: asyncio.Task | None = None

METRICS_PORT = 9124


async def main() -> None:
    """Main service entry point."""
    global _main_task
    setup_service_logging("logs/winner_selector_service.log")
    settings = Settings()
    logger.info("Starting Winner Selector Service", port=METRICS_PORT)
    start_metrics_server(METRICS_PORT)
    stage = WinnerSelectorService(settings)

    _main_task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(stage)))

    logger.info("Winner Selector Service running")
    await stage.run()


async def shutdown(stage: WinnerSelectorService) -> None:
    """Graceful shutdown."""
    logger.info("Shutting down Winner Selector Service")
    if _main_task:
        _main_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
