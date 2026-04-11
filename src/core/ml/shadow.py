"""ShadowRecorder — async batch writer for alpha_multiplier_shadow.

Called automatically by AIBaseAgent (Plan 56-04 SwarmBaseAgent via compute()).
Zero per-agent boilerplate: just call await recorder.record(...).
Batched writes with configurable size + flush interval via asyncio.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)

_INSERT_SQL = """
INSERT INTO alpha_multiplier_shadow
    (ts, signal_id, agent_id, symbol, tf,
     hmm_regime, path, predicted_multiplier, confidence, features)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (signal_id, agent_id) DO NOTHING
"""


class ShadowRecorder:
    """Batch shadow prediction writes to alpha_multiplier_shadow."""

    def __init__(self, pool: Any, batch_size: int = 100, flush_interval_s: float = 2.0) -> None:
        self._pool = pool
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s
        self._pending: list[tuple] = []

    async def record(
        self,
        signal_id: UUID,
        agent_id: str,
        multiplier: float,
        confidence: float,
        symbol: str,
        tf: str,
        regime: int | None,
        path: str,
        features: dict[str, Any] | None,
    ) -> None:
        """Queue one shadow prediction row."""
        row = (
            datetime.now(UTC),
            str(signal_id),
            agent_id,
            symbol,
            tf,
            regime,
            path,
            multiplier,
            confidence,
            json.dumps(features) if features else None,
        )
        self._pending.append(row)
        if len(self._pending) >= self._batch_size:
            await self._flush()

    async def _flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(_INSERT_SQL, batch)
            logger.debug("shadow_recorder.flushed", count=len(batch))
        except Exception as exc:
            logger.exception("shadow_recorder.flush_error", error=str(exc), count=len(batch))

    async def flush(self) -> None:
        """Force flush remaining pending rows (called at SIGTERM)."""
        await self._flush()
