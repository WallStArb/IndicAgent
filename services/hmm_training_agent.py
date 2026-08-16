"""HMM Training Agent — systemd oneshot entrypoint (Phase 082, Plan 03).

Invoked monthly by indicagent-hmm-training.timer.
Type=oneshot: runs once, exits.

Mirrors services/ml_training_agent.py main() pattern.
"""

from __future__ import annotations

import asyncio
import sys

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.settings import Settings
from src.core import timeframe_vocabulary
from src.core.database_manager import DatabaseManager
from src.core.service_utils import setup_service_logging
from src.intelligence.services.hmm_trainer import HMMTrainer


def main() -> None:
    """Create agent, run, exit.

    HMMTrainer.start() swallows all exceptions and logs them,
    so asyncio.run() always completes cleanly (systemd oneshot exit code 0).
    """
    setup_service_logging("logs/hmm_training_agent.log")
    settings = Settings()

    async def _run() -> None:
        db_manager = DatabaseManager(settings.database_url)
        await db_manager.initialize()
        try:
            await timeframe_vocabulary.prewarm(settings.database_url, db_manager.pool)
            agent = HMMTrainer(db_manager=db_manager, settings=settings)
            await agent.start()
        finally:
            if db_manager.pool is not None:
                await db_manager.pool.close()

    try:
        asyncio.run(_run())
    except Exception:
        import structlog

        structlog.get_logger(__name__).exception("hmm_training_agent.fatal_error")
        sys.exit(1)


if __name__ == "__main__":
    main()
