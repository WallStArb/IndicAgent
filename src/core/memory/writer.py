"""
MemoryEpisodeWriter + EmbeddingWorker — write path for agent memory episodes.

Design contract (D-13, MEM-01):
    MemoryEpisodeWriter.store() is fire-and-forget: put_nowait to a bounded
    asyncio.Queue(maxsize=500). Full queue drops the episode and increments
    MEMORY_WRITE_DROPPED_TOTAL. The live signal pipeline is NEVER blocked or
    errored by memory write saturation.

    EmbeddingWorker drains the queue in a background coroutine:
    - Calls EmbeddingService.embed_context() to produce (vector, embedding_text)
    - INSERTs the raw episode into memory_episodes_raw via asyncpg
    - Rows with embedding=None are inserted with NULL embedding — the offline
      back-fill job filters WHERE embedding IS NOT NULL before labeling.
      The raw row is ALWAYS persisted regardless of embedding availability.

Observability (D-21, F1):
    MEMORY_WRITE_QUEUE_DEPTH    — set after every enqueue/drain iteration
    MEMORY_WRITE_DROPPED_TOTAL  — incremented on asyncio.QueueFull
    MEMORY_EMBED_STALL_SECONDS  — time since last successful drain; alert on > 30s

Phase: 097 (agent-memory)
Ring 0 — no Ring 1 imports.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import asyncpg
import structlog

from src.observability.metrics import (
    MEMORY_EMBED_STALL_SECONDS,
    MEMORY_WRITE_DROPPED_TOTAL,
    MEMORY_WRITE_QUEUE_DEPTH,
)

if TYPE_CHECKING:
    from src.core.memory.embedding import EmbeddingService

log = structlog.get_logger(__name__)

# Grafana alert thresholds (documented, not enforced here):
#   queue_depth > 200 (40% of maxsize=500) -> warning
#   stall_seconds > 30                     -> warning
_QUEUE_WARN_DEPTH = 200
_STALL_WARN_SECONDS = 30.0

# INSERT statement for memory_episodes_raw (D-13 / migration 118)
_INSERT_RAW = """
    INSERT INTO memory_episodes_raw (
        ts, kind, signal_id, symbol, timeframe, agent_id,
        embedding, embedding_text,
        hmm_regime, vol_regime, entry_type,
        regime_epoch, n_eligible, memory_assisted,
        outcome, pnl_r, payload
    ) VALUES (
        $1, $2, $3, $4, $5, $6,
        $7::vector, $8,
        $9, $10, $11,
        $12, NULL, $13,
        NULL, NULL, $14
    )
"""


def _format_embedding(vector: list[float]) -> str:
    """Format a Python float list as a pgvector literal string.

    asyncpg sends this as a text parameter; the ::vector cast in the SQL
    instructs pgvector to parse it (same pattern as PgvectorEpisodicBackend).
    """
    return "[" + ",".join(str(v) for v in vector) + "]"


class MemoryEpisodeWriter:
    """Write-only episode queue for the live signal pipeline.

    Holds a bounded asyncio.Queue. store() enqueues raw episode dicts
    without blocking. EmbeddingWorker drains asynchronously.

    This class is write-only — agents and the pipeline never read from it.
    Agents receive MemoryClient (read-only) via WorkerContext.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        embedding: EmbeddingService,
        queue_maxsize: int = 500,
        current_epoch_provider: Any = None,
    ) -> None:
        """Initialize the writer.

        Args:
            pool: asyncpg connection pool — shared with the rest of the service.
            embedding: EmbeddingService for embed_context() calls.
            queue_maxsize: Bounded queue depth (default 500, D-13).
            current_epoch_provider: Callable () -> int returning the current
                memory regime epoch from memory_system_state. When None, epoch
                defaults to 1 (no epoch decay applied — safe for cold-start).
        """
        self._pool = pool
        self._embedding = embedding
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=queue_maxsize)
        self._current_epoch_provider = current_epoch_provider
        self._worker: EmbeddingWorker | None = None

    def store(self, raw_episode: dict) -> None:
        """Enqueue a raw episode for async embedding and persistence.

        Non-blocking. On asyncio.QueueFull, increments MEMORY_WRITE_DROPPED_TOTAL
        and drops the episode. Never raises.

        Args:
            raw_episode: Dict with episode fields. Required keys:
                ts, kind, symbol, timeframe, agent_id, hmm_regime, vol_regime,
                entry_type, memory_assisted, payload.
                Optional: signal_id, pnl_r.
                regime_epoch is stamped here from current_epoch_provider (C-01).
        """
        try:
            # Stamp regime_epoch from provider (C-01)
            if self._current_epoch_provider is not None:
                try:
                    raw_episode["regime_epoch"] = int(self._current_epoch_provider())
                except Exception:
                    raw_episode.setdefault("regime_epoch", 1)
            else:
                raw_episode.setdefault("regime_epoch", 1)

            self._queue.put_nowait(raw_episode)
        except asyncio.QueueFull:
            MEMORY_WRITE_DROPPED_TOTAL.add(1, {})
            log.warning(
                "memory_writer.queue_full",
                qsize=self._queue.qsize(),
                symbol=raw_episode.get("symbol", ""),
            )
        except Exception as error:
            # Defensive — never propagate to signal pipeline
            log.warning("memory_writer.store_error", error=str(error))
        finally:
            # Update queue depth gauge regardless of success/failure
            try:
                MEMORY_WRITE_QUEUE_DEPTH.set(self._queue.qsize(), {})
            except Exception:
                pass

    def attach_worker(self, worker: EmbeddingWorker) -> None:
        """Attach the EmbeddingWorker that drains this queue."""
        self._worker = worker

    @property
    def queue(self) -> asyncio.Queue[dict]:
        """Expose queue for EmbeddingWorker (same-process only)."""
        return self._queue


class EmbeddingWorker:
    """Background drain coroutine: embeds and persists raw memory episodes.

    Drains MemoryEpisodeWriter.queue, calls EmbeddingService.embed_context(),
    and INSERTs into memory_episodes_raw. Write failures are caught and logged
    per-row — a single failure never stops the drain loop.

    Stall detection (F1): tracks time since last successful INSERT and emits
    MEMORY_EMBED_STALL_SECONDS every drain iteration. Alert on > 30s.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        embedding: EmbeddingService,
        queue: asyncio.Queue[dict],
    ) -> None:
        self._pool = pool
        self._embedding = embedding
        self._queue = queue
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_drain_completed_at: float = time.monotonic()

    async def start(self) -> None:
        """Launch the background drain task."""
        self._running = True
        self._task = asyncio.create_task(self._drain(), name="memory.embedding_worker")

    async def stop(self) -> None:
        """Graceful shutdown: cancel the drain task and wait for completion."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _drain(self) -> None:
        """Long-lived drain loop. Runs until stop() is called."""
        while self._running:
            try:
                # Block until an item is available (graceful wake-up on stop via cancel)
                episode = await self._queue.get()
                try:
                    await self._process_episode(episode)
                except Exception as error:
                    log.warning("memory_worker.process_error", error=str(error))
                finally:
                    self._queue.task_done()

                # Update queue depth and stall gauge after each drain
                MEMORY_WRITE_QUEUE_DEPTH.set(self._queue.qsize(), {})
                MEMORY_EMBED_STALL_SECONDS.set(time.monotonic() - self._last_drain_completed_at, {})

            except asyncio.CancelledError:
                break
            except Exception as error:
                # Unexpected drain loop error — log and continue, never crash
                log.error("memory_worker.drain_loop_error", error=str(error))

    async def _process_episode(self, episode: dict) -> None:
        """Embed one episode and INSERT into memory_episodes_raw.

        Embedding failure does NOT prevent INSERT — the row is persisted with
        embedding=NULL and the offline back-fill job handles re-embedding later.
        """
        # Build a duck-typed context-like object from the episode dict
        # so EmbeddingService.embed_context() can serialize it (Ring 0 duck-typing)
        context_proxy = _EpisodeContextProxy(episode)

        try:
            vector, embedding_text = await self._embedding.embed_context(context_proxy)
        except Exception as error:
            log.warning("memory_worker.embed_error", error=str(error))
            vector = None
            embedding_text = episode.get("embedding_text", "")

        # Prepare INSERT values
        ts = episode.get("ts")
        kind = episode.get("kind", "episodic")
        signal_id = episode.get("signal_id")  # may be None
        symbol = str(episode.get("symbol", ""))
        timeframe = str(episode.get("timeframe", ""))
        agent_id = episode.get("agent_id")
        hmm_regime = episode.get("hmm_regime")
        vol_regime = episode.get("vol_regime")
        entry_type = episode.get("entry_type")
        regime_epoch = int(episode.get("regime_epoch", 1))
        memory_assisted = bool(episode.get("memory_assisted", False))
        payload = episode.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        # Format embedding as pgvector literal string, or None for NULL
        embedding_str: str | None = _format_embedding(vector) if vector is not None else None

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    _INSERT_RAW,
                    ts,
                    kind,
                    signal_id,
                    symbol,
                    timeframe,
                    agent_id,
                    embedding_str,
                    embedding_text or None,
                    hmm_regime,
                    vol_regime,
                    entry_type,
                    regime_epoch,
                    memory_assisted,
                    payload,  # asyncpg sends JSONB dict directly (no json.dumps)
                )
            self._last_drain_completed_at = time.monotonic()

        except Exception as error:
            log.warning(
                "memory_worker.insert_failed",
                symbol=symbol,
                signal_id=str(signal_id) if signal_id else None,
                error=str(error),
            )
            # Do not re-raise — episode loss is acceptable; pipeline integrity is not


class _EpisodeContextProxy:
    """Duck-typed proxy so EmbeddingService can serialize an episode dict.

    EmbeddingService.serialize() uses getattr() on any object (Ring 0 duck-typing).
    This proxy exposes the episode dict fields as attributes so serialize() works
    without importing any Ring 1 types.
    """

    __slots__ = (
        "symbol",
        "timeframe",
        "entry_type",
        "hmm_regime",
        "vol_regime",
        "hmm_prob",
        "trend",
        "ctf",
        "rsi_pct",
        "atr_pct",
        "swing",
        "vol_pct",
        "mom_pct",
    )

    def __init__(self, episode: dict) -> None:
        self.symbol = episode.get("symbol", "")
        self.timeframe = episode.get("timeframe", "")
        self.entry_type = episode.get("entry_type", "")
        self.hmm_regime = episode.get("hmm_regime", "")
        self.vol_regime = episode.get("vol_regime", "")
        # Optional percentile fields — None if absent (EmbeddingService skips None)
        payload = episode.get("payload", {}) or {}
        self.hmm_prob = payload.get("hmm_prob")
        self.trend = payload.get("trend")
        self.ctf = payload.get("ctf")
        self.rsi_pct = payload.get("rsi_pct")
        self.atr_pct = payload.get("atr_pct")
        self.swing = payload.get("swing")
        self.vol_pct = payload.get("vol_pct")
        self.mom_pct = payload.get("mom_pct")
