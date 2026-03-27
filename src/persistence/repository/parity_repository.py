"""ParityRepository — read/write side persistence for parity audit.

Phase 52.5: ParityAuditorAgent

Provides:
  - fetch_window(table_name, since, until) -> list[dict]
  - insert_violations(violations, run_id) -> None
  - fetch_clean_cycles(symbol, tf, threshold) -> int
        Derives certification state from feature_parity_violations query.
        NO fetch_certification_state / update_certification_state (D-09).

Security: table_name validated against _ALLOWED_TABLES allow-list (same pattern
as FeatureRepository) — no f-string injection possible.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

# Security: only these two tables are valid read targets.
_ALLOWED_TABLES: frozenset[str] = frozenset(
    {"intelligence_features", "feature_snapshots_shadow"}
)

_FETCH_WINDOW_SQL = "SELECT * FROM {table} WHERE ts >= $1 AND ts < $2 ORDER BY ts, symbol, tf"

_INSERT_VIOLATIONS_SQL = """
INSERT INTO feature_parity_violations
    (ts, symbol, tf, field, legacy_val, shadow_val, run_id)
VALUES ($1, $2, $3, $4, $5, $6, $7)
"""

# D-01/D-09: Certification derived from violations query, not a state table.
# Uses the (symbol, tf, detected_at DESC) composite index:
#   - equality filters on symbol + tf reduce scan to one pair
#   - range filter on detected_at selects the last threshold windows
# COUNT(DISTINCT date_trunc) = number of dirty windows in the period.
# Result = threshold - dirty_window_count = clean windows in period.
_FETCH_CLEAN_CYCLES_SQL = """
SELECT $3::int - COUNT(DISTINCT date_trunc('5 minutes', detected_at))::int
FROM feature_parity_violations
WHERE symbol = $1
  AND tf = $2
  AND detected_at >= NOW() - ($3 * INTERVAL '5 minutes')
"""


class ParityRepository:
    """Read/write repository for parity audit operations.

    Args:
        pool: An asyncpg connection pool.

    Note: certification state is DERIVED from feature_parity_violations, not stored
    separately. This makes certification restart-safe with no additional infrastructure.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def fetch_window(
        self, table_name: str, since: datetime, until: datetime
    ) -> list[dict]:
        """Fetch rows in [since, until) time window from the specified table.

        Args:
            table_name: Must be in _ALLOWED_TABLES (raises ValueError otherwise).
            since: Window start (inclusive).
            until: Window end (exclusive).

        Returns:
            List of rows as dicts.

        Raises:
            ValueError: If table_name is not in the allow-list.
        """
        if table_name not in _ALLOWED_TABLES:
            raise ValueError(
                f"table_name '{table_name}' not in allowed table list: {_ALLOWED_TABLES}"
            )
        sql = _FETCH_WINDOW_SQL.format(table=table_name)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, since, until)
        return [dict(row) for row in rows]

    async def insert_violations(
        self, violations: list[Any], run_id: uuid.UUID
    ) -> None:
        """Batch-insert FieldViolation objects into feature_parity_violations.

        Uses executemany for performance. detected_at uses DEFAULT NOW() in DB schema.

        Column mapping:
            FieldViolation.primary_value -> legacy_val (column name unchanged from DDL)
            FieldViolation.shadow_value  -> shadow_val
            FieldViolation.field_name    -> field
        """
        if not violations:
            return
        records = [
            (
                v.ts,
                v.symbol,
                v.tf,
                v.field_name,     # -> field column
                v.primary_value,  # -> legacy_val column
                v.shadow_value,   # -> shadow_val column
                run_id,
            )
            for v in violations
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(_INSERT_VIOLATIONS_SQL, records)
        logger.debug("parity_violations_inserted", count=len(records), run_id=str(run_id))

    async def fetch_clean_cycles(self, symbol: str, tf: str, threshold: int) -> int:
        """Return number of consecutive clean 5-min windows in the last threshold windows.

        Derives certification state from feature_parity_violations — no state table (D-01/D-09).

        Uses COUNT(DISTINCT date_trunc) pattern, not generate_series + LEFT JOIN, for
        index efficiency. One scan via (symbol, tf, detected_at DESC) composite index.

        Args:
            symbol: Instrument symbol.
            tf: Timeframe.
            threshold: Number of 5-min windows to look back (CERTIFICATION_THRESHOLD).

        Returns:
            Number of clean windows (threshold - dirty_window_count).
            Returns threshold if no violations in the period (fully certified).
        """
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(_FETCH_CLEAN_CYCLES_SQL, symbol, tf, threshold)
        # fetchval returns None if no rows (shouldn't happen with $3 - COUNT, but guard)
        return int(result) if result is not None else threshold
