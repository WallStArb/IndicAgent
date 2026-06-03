"""Managed asyncpg pool wrapper supporting graceful flush + recreate.

Flush semantics (Renaissance standard):
  1. Snapshot current pool reference (old_pool)
  2. Create NEW pool via create_pool() with SAME url + pool_name + kwargs
  3. Health-check new pool with SELECT 1 (lightweight, sub-ms)
  4. If health check fails -> close new pool, KEEP old_pool active, raise.
     (Never leave the system without a working pool.)
  5. Atomic swap: self._pool = new_pool
  6. Drain old_pool: await asyncio.wait_for(old_pool.close(), timeout=drain_timeout)
     asyncpg's pool.close() blocks until all checked-out connections are released
     (graceful drain). On timeout, fall back to terminate() to force-close.
"""

import asyncio
import time

import asyncpg
import structlog

from src.core.database_manager import create_pool

logger = structlog.get_logger(__name__)


class ManagedPool:
    """Owns an asyncpg.Pool and supports graceful flush + recreate.

    Constructor injection: callers pass url + kwargs; ManagedPool owns the pool lifecycle.
    Thread-safety: flush() acquires an asyncio.Lock to serialize concurrent flushes.
    """

    def __init__(
        self,
        database_url: str,
        pool_name: str = "self_healing",
        drain_timeout_seconds: float = 10.0,
        **pool_kwargs,
    ) -> None:
        self._url = database_url
        self._pool_name = pool_name
        self._drain_timeout = drain_timeout_seconds
        self._pool_kwargs = pool_kwargs
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()  # serialize concurrent flushes

    async def initialize(self) -> None:
        """Create the initial pool. Idempotent: no-op if already initialized."""
        if self._pool is None:
            self._pool = await create_pool(
                self._url, pool_name=self._pool_name, **self._pool_kwargs
            )

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("ManagedPool not initialized — call initialize() first")
        return self._pool

    async def close(self) -> None:
        """Gracefully close the pool and clear the reference."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def flush(self) -> dict:
        """Graceful flush: create new pool, health-check, atomic swap, drain old.

        Returns a dict with timing breakdown:
          {"create_ms": int, "verify_ms": int, "drain_ms": int, "drain_forced": bool}

        Raises:
          RuntimeError if not initialized.
          Exception from create_pool / SELECT 1 if new pool is unhealthy.
            Old pool is preserved in this case; the system continues to function.
        """
        if self._pool is None:
            raise RuntimeError("ManagedPool.flush called before initialize()")

        async with self._lock:
            old_pool = self._pool

            # Step 1: Create new pool
            t0 = time.monotonic()
            try:
                new_pool = await create_pool(
                    self._url, pool_name=self._pool_name, **self._pool_kwargs
                )
            except Exception as error:
                logger.error("managed_pool.create_failed", error=str(error))
                # old_pool untouched; system remains functional
                raise

            create_ms = int((time.monotonic() - t0) * 1000)

            # Step 2: Health-check new pool BEFORE atomic swap (rollback path)
            t1 = time.monotonic()
            try:
                async with new_pool.acquire() as conn:
                    result = await conn.fetchval("SELECT 1")
                if result != 1:
                    raise RuntimeError(f"SELECT 1 returned unexpected value: {result!r}")
            except Exception as error:
                logger.error("managed_pool.verify_failed", error=str(error))
                # CRITICAL rollback path: close the failed new pool, keep old_pool active.
                # self._pool has NOT been swapped yet — system continues working on old_pool.
                try:
                    await asyncio.wait_for(new_pool.close(), timeout=2.0)
                except Exception:
                    new_pool.terminate()
                raise

            verify_ms = int((time.monotonic() - t1) * 1000)

            # Step 3: Atomic swap (only after new pool proven healthy)
            self._pool = new_pool

            # Step 4: Graceful drain of old pool with timeout fallback
            t2 = time.monotonic()
            drain_forced = False
            try:
                await asyncio.wait_for(old_pool.close(), timeout=self._drain_timeout)
            except TimeoutError:
                logger.warning(
                    "managed_pool.drain_timeout",
                    timeout_s=self._drain_timeout,
                    action="terminate_forced",
                )
                old_pool.terminate()  # force-close stuck connections
                drain_forced = True
            except Exception as error:
                # Swap already succeeded -> system is healthy on new pool. Log and continue.
                logger.warning("managed_pool.drain_error", error=str(error))

            drain_ms = int((time.monotonic() - t2) * 1000)

            logger.info(
                "managed_pool.flush_complete",
                create_ms=create_ms,
                verify_ms=verify_ms,
                drain_ms=drain_ms,
                drain_forced=drain_forced,
            )

            return {
                "create_ms": create_ms,
                "verify_ms": verify_ms,
                "drain_ms": drain_ms,
                "drain_forced": drain_forced,
            }
