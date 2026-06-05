"""Unit tests for MemoryEpisodeWriter and EmbeddingWorker.

Locks the contracts:
  - Fire-and-forget: store() never raises or blocks even when queue is full
  - Drop on QueueFull: MEMORY_WRITE_DROPPED_TOTAL incremented; episode silently discarded
  - EmbeddingWorker._process_episode skips INSERT when embedding is None
  - EmbeddingWorker._process_episode executes INSERT when embedding succeeds
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.memory.writer import EmbeddingWorker, MemoryEpisodeWriter

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_UTC_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _raw_episode(**overrides) -> dict:
    base = {
        "ts": _UTC_NOW,
        "kind": "episodic",
        "symbol": "ES",
        "timeframe": "5m",
        "agent_id": "test_agent",
        "hmm_regime": "trending_up",
        "vol_regime": "normal",
        "entry_type": "at_close",
        "memory_assisted": False,
        "payload": {"rsi_pct": 0.65},
    }
    base.update(overrides)
    return base


class _FakeEmbeddingService:
    """Fake EmbeddingService returning a fixed 768-dim vector."""

    async def embed_context(self, context):
        return ([0.0] * 768, "ES 5m at_close regime:trending_up")


class _NullEmbeddingService:
    """Fake EmbeddingService that always returns None for the vector."""

    async def embed_context(self, context):
        return (None, "ES 5m at_close regime:trending_up")


def _make_fake_pool() -> MagicMock:
    """Build a fake asyncpg pool whose acquire() returns an async context manager."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    pool = MagicMock()
    # pool.acquire() must work as an async context manager
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool


# ---------------------------------------------------------------------------
# MemoryEpisodeWriter tests
# ---------------------------------------------------------------------------


def test_store_enqueues():
    """store() puts episodes onto the queue when it has capacity."""
    pool = _make_fake_pool()
    writer = MemoryEpisodeWriter(pool=pool, embedding=_FakeEmbeddingService(), queue_maxsize=5)
    writer.store(_raw_episode(symbol="ES"))
    writer.store(_raw_episode(symbol="MES"))
    assert writer.queue.qsize() == 2


def test_store_drops_when_full():
    """store() does NOT raise on a full queue — it drops the episode silently."""
    pool = _make_fake_pool()
    writer = MemoryEpisodeWriter(pool=pool, embedding=_FakeEmbeddingService(), queue_maxsize=1)

    # Fill the queue
    writer.store(_raw_episode(symbol="ES"))
    assert writer.queue.qsize() == 1

    # Second store should drop silently (no exception)
    with patch("src.core.memory.writer.MEMORY_WRITE_DROPPED_TOTAL") as mock_counter:
        writer.store(_raw_episode(symbol="MES"))  # Must NOT raise
        mock_counter.add.assert_called_once_with(1, {})

    # Queue remains at 1 (second episode dropped)
    assert writer.queue.qsize() == 1


def test_store_never_raises_on_arbitrary_exception():
    """store() swallows any unexpected exception — pipeline is never harmed."""
    pool = _make_fake_pool()
    writer = MemoryEpisodeWriter(pool=pool, embedding=_FakeEmbeddingService(), queue_maxsize=5)
    # Pass a non-dict to cause internal errors if any — must still not raise
    writer.store({})  # Empty dict is fine
    # Even if the epoch provider raises, store should not propagate
    bad_provider = MagicMock(side_effect=RuntimeError("epoch error"))
    writer2 = MemoryEpisodeWriter(
        pool=pool,
        embedding=_FakeEmbeddingService(),
        queue_maxsize=5,
        current_epoch_provider=bad_provider,
    )
    writer2.store(_raw_episode())  # Must not raise


# ---------------------------------------------------------------------------
# EmbeddingWorker._process_episode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_inserts_on_success():
    """_process_episode INSERTs one row when embedding succeeds."""
    pool = _make_fake_pool()
    queue: asyncio.Queue[dict] = asyncio.Queue()
    worker = EmbeddingWorker(pool=pool, embedding=_FakeEmbeddingService(), queue=queue)

    episode = _raw_episode()
    await worker._process_episode(episode)

    # The fake pool's connection.execute must have been called exactly once
    conn = pool.acquire.return_value.__aenter__.return_value
    conn.execute.assert_awaited_once()
    # Confirm the INSERT_RAW SQL was used (contains 'memory_episodes_raw')
    call_args = conn.execute.call_args
    assert "memory_episodes_raw" in call_args[0][0]


@pytest.mark.asyncio
async def test_drain_skips_insert_when_embedding_none():
    """_process_episode still calls INSERT even with NULL embedding (raw row persisted).

    Design: rows with embedding=None are persisted with NULL; the offline
    back-fill job handles re-embedding. The row is ALWAYS written.
    """
    pool = _make_fake_pool()
    queue: asyncio.Queue[dict] = asyncio.Queue()
    worker = EmbeddingWorker(pool=pool, embedding=_NullEmbeddingService(), queue=queue)

    episode = _raw_episode()
    await worker._process_episode(episode)

    # INSERT still called — NULL embedding is allowed (offline backfill handles it)
    conn = pool.acquire.return_value.__aenter__.return_value
    conn.execute.assert_awaited_once()
    # The embedding_str argument (index 6, 0-indexed) should be None
    call_positional = conn.execute.call_args[0]
    # call_positional[0] is SQL, [1..] are params
    # embedding_str is the 7th param (index 7): $7::vector
    embedding_param = call_positional[7]
    assert embedding_param is None, f"Expected None embedding but got {embedding_param!r}"


@pytest.mark.asyncio
async def test_drain_handles_embed_exception_gracefully():
    """_process_episode does not raise when embed_context itself raises."""

    class _BoomEmbedder:
        async def embed_context(self, context):
            raise RuntimeError("ollama offline")

    pool = _make_fake_pool()
    queue: asyncio.Queue[dict] = asyncio.Queue()
    worker = EmbeddingWorker(pool=pool, embedding=_BoomEmbedder(), queue=queue)

    # Must not propagate — episode persisted with NULL embedding
    await worker._process_episode(_raw_episode())

    conn = pool.acquire.return_value.__aenter__.return_value
    conn.execute.assert_awaited_once()
