from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_INSERT_FEATURE_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i2, i3, i4, i5, smc, i6, i7,
    bar_close_ts, i1_computed_at, computed_at,
    winner_plugin, winner_confidence, winner_direction,
    signals_evaluated, signals_after_quality, signals_after_regime,
    signals_after_tod, signals_after_calibration,
    ledger_written, pipeline_latency_ms,
    i7_computed_at, session_type, days_to_expiry
)
VALUES (
    $1, $2, $3, $4, $5, $6,
    $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb,
    $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb,
    $16, $17, $18,
    $19, $20, $21,
    $22, $23, $24,
    $25, $26,
    $27, $28,
    $29, $30, $31
)
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""

class FeatureRepository:
    """Repository for Feature storage operations."""

    def __init__(self, db_manager: Any):
        self._db_manager = db_manager

    async def insertBatch(self, feature_data: dict[str, Any]) -> None:
        """Perform high-efficiency batch insertion of feature vectors."""
        await self._db_manager.execute_command(_INSERT_FEATURE_SQL, *feature_data.values())
        logger.info("Batch persisted features to storage", count=1)
