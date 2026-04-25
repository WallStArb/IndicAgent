"""TransformRecorder — async batch writer for signal_transform_log.

Called by each pipeline transform stage (quality_gate, regime_gate, tod_adjuster,
calibrator, ranker) and swarm agents (skeptic, correlation, volume).
Zero per-transform boilerplate: just call await recorder.record(...).
Batched writes with configurable size + flush interval via asyncio.

Mirrors ShadowRecorder pattern exactly (src/core/ml/shadow.py).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)

_INSERT_SQL = """
INSERT INTO signal_transform_log
    (ts, signal_id, transform_id, transform_version, dag_order,
     segment_key, multiplier, metadata, is_shadow)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""


class TransformRecorder:
    """Batch writes to signal_transform_log."""

    def __init__(self, pool: Any, batch_size: int = 100, flush_interval_s: float = 2.0) -> None:
        self._pool = pool
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._pending: list[tuple] = []
        self._flush_task: asyncio.Task | None = None

    async def record(
        self,
        signal_id: str | UUID,
        transform_id: str,
        dag_order: int,
        multiplier: float,
        segment_key: str = "__global__",
        metadata: dict[str, Any] | None = None,
        transform_version: str = "v1",
        is_shadow: bool = True,
    ) -> None:
        """Queue one transform row. Auto-flushes when batch_size is reached."""
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.ensure_future(self._flush_loop())

        row = (
            datetime.now(UTC),
            str(signal_id),
            transform_id,
            transform_version,
            int(dag_order),
            segment_key,
            float(multiplier),
            json.dumps(metadata) if metadata else None,
            bool(is_shadow),
        )
        self._pending.append(row)
        if len(self._pending) >= self._batch_size:
            await self._flush()

    async def _flush_loop(self) -> None:
        """Periodic background flush so low-volume periods don't stall writes."""
        while True:
            await asyncio.sleep(self._flush_interval_s)
            await self._flush()

    async def _flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(_INSERT_SQL, batch)
            logger.debug("transform_recorder.flushed", count=len(batch))
        except Exception as exc:
            logger.exception("transform_recorder.flush_error", error=str(exc), count=len(batch))

    async def flush(self) -> None:
        """Force flush remaining pending rows (called at SIGTERM)."""
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()
