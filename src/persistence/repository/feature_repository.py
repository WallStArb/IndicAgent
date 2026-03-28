"""FeatureRepository — write-side persistence for intelligence feature vectors.

Accepts a configurable table_name so the same SQL template is reused by both
FeatureWriterService (-> intelligence_features) and FeatureSnapshotWriterAgent
(-> feature_snapshots_shadow). Never duplicate the 31-column INSERT.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Security: only these two tables are valid destinations — no f-string injection possible.
_ALLOWED_TABLES: frozenset[str] = frozenset({"intelligence_features", "feature_snapshots_shadow"})

_INSERT_SQL_TEMPLATE = """
INSERT INTO {table} (
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
    """Write-side repository for intelligence_features (or shadow table).

    Args:
        db_manager: Open DatabaseManager instance.
        table_name: Target table. Defaults to 'intelligence_features'.
                    Pass 'feature_snapshots_shadow' for shadow writes.
                    Must be in the allow-list — raises ValueError otherwise.
    """

    def __init__(self, db_manager: Any, table_name: str = "intelligence_features") -> None:
        if table_name not in _ALLOWED_TABLES:
            raise ValueError(
                f"table_name '{table_name}' not in allowed table list: {_ALLOWED_TABLES}"
            )
        self._db_manager = db_manager
        self.table_name = table_name
        self._insert_sql = _INSERT_SQL_TEMPLATE.format(table=table_name)

    async def insert(self, params: tuple) -> None:
        """Insert one 31-element params tuple. Skips on conflict (ts, symbol, tf)."""
        await self._db_manager.execute_command(self._insert_sql, *params)
        logger.debug("feature_row_written", table=self.table_name)

    # Legacy compat — callers passing a dict get a clear error instead of a silent noop.
    async def insertBatch(self, feature_data: Any) -> None:
        raise TypeError(
            "FeatureRepository.insertBatch() removed — use insert(params_tuple). "
            "Build params via feature_writer_agent._record_to_insert_params()."
        )
