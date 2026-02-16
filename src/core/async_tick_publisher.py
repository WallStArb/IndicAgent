"""
AsyncTickPublisher - decouple IBKR tick callback from Redis I/O.

Version: 1.0.0
Last Updated: 2025-08-09
Status: Current ✅

Provides:
- Per-symbol deduplication (consecutive duplicate signature suppression)
- Priority handling under pressure (favor price/last changes)
- Adaptive batching based on queue depth
- Async Redis pipeline publishing (xadd + latest price cache)
"""

from __future__ import annotations

import asyncio
from typing import Any

import redis.asyncio as redis
from prometheus_client import Gauge

from src.core.stream_keys import live_tick as sk_live_tick


class AsyncTickPublisher:
    """Async tick publisher with deduplication and adaptive batching.

    This component accepts ticks enqueued from external producers (e.g., an IBKR
    event callback running in a different thread) and flushes them to Redis
    Streams using an async pipeline. It maintains a small amount of per-symbol
    state for deduplication and exposes an optional Prometheus gauge for queue
    depth visibility.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        env_prefix: str,
        queue_maxsize: int = 5000,
        max_batch: int = 250,
        max_delay: float = 0.03,
        queue_gauge: Gauge | None = None,
    ) -> None:
        self.redis: redis.Redis = redis_client
        self.env_prefix: str = env_prefix
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=queue_maxsize)
        self.max_batch: int = max_batch
        self.max_delay: float = max_delay
        self._last_signature_by_symbol: dict[str, tuple[Any, ...]] = {}
        self.queue_gauge = queue_gauge

    @staticmethod
    def _signature(tick: dict[str, Any]) -> tuple[Any, ...]:
        """Create a deduplication signature for a tick."""
        return (
            tick.get("price"),
            tick.get("bid"),
            tick.get("ask"),
            tick.get("bid_size"),
            tick.get("ask_size"),
            tick.get("volume"),
            tick.get("last"),
            tick.get("last_size"),
        )

    async def publish_tick(self, symbol: str, tick: dict[str, Any]) -> None:
        """Deduplicate and enqueue a tick for async publishing.

        If the queue is full, prefer keeping price/last updates and drop pure
        volume-only updates.
        """
        signature = self._signature(tick)
        if self._last_signature_by_symbol.get(symbol) == signature:
            return
        self._last_signature_by_symbol[symbol] = signature

        try:
            self.queue.put_nowait((symbol, tick))
        except asyncio.QueueFull:
            # Prioritize price/last changes under pressure
            if "price" in tick or "last" in tick:
                await self.queue.put((symbol, tick))
            # Else drop silently

        if self.queue_gauge is not None:
            self.queue_gauge.set(self.queue.qsize())

    def _adaptive_target(self) -> int:
        """Determine batch size target based on current queue depth."""
        depth = self.queue.qsize()
        if depth > 3000:
            return min(800, self.max_batch)
        if depth > 1000:
            return min(400, self.max_batch)
        if depth > 200:
            return min(150, self.max_batch)
        if depth > 50:
            return min(75, self.max_batch)
        return min(30, self.max_batch)

    async def _flush(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        """Flush a prepared batch to Redis using a pipeline."""
        pipe = self.redis.pipeline(transaction=False)
        for symbol, tick in batch:
            live_stream = sk_live_tick(self.env_prefix, symbol)
            pipe.xadd(live_stream, tick, maxlen=20000, approximate=True)

            # Keep a hot latest price cache for fast lookups
            price_key = f"{self.env_prefix}price:{symbol}:latest"
            pipe.hset(
                price_key,
                mapping={
                    "price": tick.get("price", ""),
                    "bid": tick.get("bid", ""),
                    "ask": tick.get("ask", ""),
                    "timestamp": tick.get("timestamp", ""),
                },
            )
            pipe.expire(price_key, 120)

        await pipe.execute()

    async def run(self) -> None:
        """Main worker loop: coalesce queue items and publish in batches."""
        while True:
            # Always block for the first item
            symbol, tick = await self.queue.get()
            batch: list[tuple[str, dict[str, Any]]] = [(symbol, tick)]
            target = self._adaptive_target()

            # Opportunistically collect more items up to the target size
            while len(batch) < target:
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=self.max_delay)
                except TimeoutError:
                    break
                else:
                    batch.append(item)

            try:
                await self._flush(batch)
            finally:
                # Mark all items done even if flush failed (upstream tracks drops)
                for _ in batch:
                    self.queue.task_done()
                if self.queue_gauge is not None:
                    self.queue_gauge.set(self.queue.qsize())

    async def drain(self, timeout: float | None = None) -> None:
        """Wait for the internal queue to drain.

        Args:
            timeout: Optional timeout in seconds for the drain. If provided,
                     raises asyncio.TimeoutError on expiry.
        """
        if timeout is None:
            await self.queue.join()
        else:
            await asyncio.wait_for(self.queue.join(), timeout=timeout)

    def size(self) -> int:
        """Return current queue size."""
        return self.queue.qsize()
