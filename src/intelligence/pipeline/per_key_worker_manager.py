"""Per-(symbol, tf) worker manager for concurrent bar processing.

Each (symbol, tf) key gets a dedicated asyncio.Queue and a long-running asyncio.Task.
Independent keys run concurrently — ES:1m never blocks NQ:5m (D-01, D-03).
Worker lifecycle is owned by this class; the orchestrator calls start_per_key_workers()
once (D-16) and stop() on teardown.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from src.core.schemas.bar_message import BarMessage


class PerKeyWorkerManager:
    """Manages per-(symbol, tf) asyncio workers for concurrent bar processing.

    Workers are spawned lazily on first enqueue for a given key.
    Symbol filter (D-28): if set, only listed symbols get workers; bars for
    other symbols are silently dropped (shard ownership boundary).
    """

    def __init__(
        self,
        processor: Callable[[BarMessage], Awaitable[None]],
        symbol_filter: frozenset[str] | None = None,
        queue_maxsize: int = 100,
    ) -> None:
        self._processor = processor
        self._symbol_filter = symbol_filter
        self._queue_maxsize = queue_maxsize
        self._queues: dict[tuple[str, str], asyncio.Queue] = {}
        self._tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._stop_event = asyncio.Event()
        self._logger = structlog.get_logger(__name__)

    def start_per_key_workers(self) -> None:
        """No-op at startup — workers are lazily spawned on first enqueue per key.

        Exists for lifecycle symmetry with CacheManager.start_refresh_loops() and
        PluginStateManager.start_checkpoint_loop() (D-16).
        """

    async def enqueue(self, bar: BarMessage) -> None:
        """Fan a bar out to its per-key worker queue, blocking on back-pressure.

        Drops bars for symbols not owned by this shard (D-28 symbol filter).
        """
        if self._symbol_filter is not None and bar.symbol not in self._symbol_filter:
            return
        key = (bar.symbol, bar.tf)
        if key not in self._queues:
            self._spawn_worker(key)
        await self._queues[key].put(bar)

    def _spawn_worker(self, key: tuple[str, str]) -> None:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._queues[key] = queue
        task = asyncio.create_task(
            self._worker_loop(key),
            name=f"per_key_worker_{key[0]}_{key[1]}",
        )
        self._tasks[key] = task
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _worker_loop(self, key: tuple[str, str]) -> None:
        queue = self._queues[key]
        while not self._stop_event.is_set():
            try:
                bar = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await self._processor(bar)
            except TimeoutError:
                # enqueue_blocking timed out — _drops counter already incremented in output_queue
                self._logger.warning(
                    "per_key_worker.enqueue_timeout",
                    symbol=key[0],
                    tf=key[1],
                )
            except Exception as exc:
                self._logger.error(
                    "per_key_worker_error",
                    symbol=key[0],
                    tf=key[1],
                    error=str(exc),
                    exc_info=True,
                )
            finally:
                queue.task_done()

    async def stop(self) -> None:
        """Signal all workers to stop and await their completion."""
        self._stop_event.set()
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
