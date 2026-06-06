"""
MemoryClientFactory — startup wiring for the agent memory subsystem.

build_memory_client(settings, db_pool) -> MemoryClient | None
build_memory_writer(settings, db_pool) -> MemoryEpisodeWriter | None

Both functions are gated on settings.agent_memory_enabled (MEM-03).
When the flag is False, they return None immediately (no construction, no imports).
When True, they compose and return the live read/write paths.

Construction failures return None and log a WARNING — they never raise.
Services that call these functions can treat None as "memory subsystem disabled".

Call site pattern (e.g. alpha_swarm._setup()):

    self._memory_client = build_memory_client(self.settings, self._pool)
    self._memory_writer = build_memory_writer(self.settings, self._pool)

Then pass memory_client into WorkerContext at compute time:

    ctx = WorkerContext(
        signal_context=...,
        llm_chain=...,
        db_pool=self._pool,
        memory_client=self._memory_client,
    )

Phase: 097 (agent-memory)
Ring 0 — no Ring 1 imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg
import structlog

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.core.memory.client import MemoryClient
    from src.core.memory.writer import MemoryEpisodeWriter

log = structlog.get_logger(__name__)


def build_memory_client(
    settings: Settings,
    db_pool: asyncpg.Pool,
) -> MemoryClient | None:
    """Construct a MemoryClient from the four backends.

    Gated on settings.agent_memory_enabled. Returns None when the flag is
    False or when any construction step fails (graceful degradation).

    Args:
        settings: Application settings — reads agent_memory_enabled and ollama_base_url.
        db_pool: asyncpg connection pool used by the three pgvector backends.

    Returns:
        MemoryClient instance when memory is enabled and construction succeeds,
        None otherwise. Never raises.
    """
    if not settings.agent_memory_enabled:
        log.info("memory.disabled", reason="AGENT_MEMORY_ENABLED=False")
        return None

    try:
        from src.core.memory.backends.calibration import (  # noqa: PLC0415
            PgvectorCalibrationBackend,
        )
        from src.core.memory.backends.episodic import PgvectorEpisodicBackend  # noqa: PLC0415
        from src.core.memory.backends.mem0 import Mem0BackendImpl  # noqa: PLC0415
        from src.core.memory.backends.regime import PgvectorRegimeBackend  # noqa: PLC0415
        from src.core.memory.client import MemoryClient  # noqa: PLC0415
        from src.core.memory.embedding import EmbeddingService  # noqa: PLC0415

        embedding = EmbeddingService(ollama_base_url=settings.ollama_base_url)
        episodic = PgvectorEpisodicBackend(pool=db_pool)
        calibration = PgvectorCalibrationBackend(pool=db_pool)
        regime = PgvectorRegimeBackend(pool=db_pool)
        mem0 = Mem0BackendImpl(settings=settings)

        client = MemoryClient(
            episodic=episodic,
            calibration=calibration,
            regime=regime,
            mem0=mem0,
            embedding=embedding,
        )
        log.info("memory.client_built", agent_memory_enabled=True)
        return client

    except Exception as error:
        log.warning("memory.build_failed", error=str(error))
        return None


def build_memory_writer(
    settings: Settings,
    db_pool: asyncpg.Pool,
    queue_maxsize: int = 500,
    current_epoch_provider=None,
) -> MemoryEpisodeWriter | None:
    """Construct a MemoryEpisodeWriter for the signal pipeline write path.

    Gated on settings.agent_memory_enabled. Returns None when the flag is
    False or when construction fails.

    Args:
        settings: Application settings.
        db_pool: asyncpg connection pool.
        queue_maxsize: Bounded queue depth (default 500, D-13).
        current_epoch_provider: Callable () -> int for current regime epoch (C-01).
            When None, epoch defaults to 1.

    Returns:
        MemoryEpisodeWriter instance when memory is enabled, None otherwise.
        Never raises.
    """
    if not settings.agent_memory_enabled:
        return None

    try:
        from src.core.memory.embedding import EmbeddingService  # noqa: PLC0415
        from src.core.memory.writer import MemoryEpisodeWriter  # noqa: PLC0415

        embedding = EmbeddingService(ollama_base_url=settings.ollama_base_url)
        writer = MemoryEpisodeWriter(
            pool=db_pool,
            embedding=embedding,
            queue_maxsize=queue_maxsize,
            current_epoch_provider=current_epoch_provider,
        )
        log.info("memory.writer_built", queue_maxsize=queue_maxsize)
        return writer

    except Exception as error:
        log.warning("memory.writer_build_failed", error=str(error))
        return None
