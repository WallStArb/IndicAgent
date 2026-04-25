"""TransformGraduationRepository — UPSERT helper for transform_graduation table.

Phase 72. Used by GraduationWriterAgent.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.core.database_manager import DatabaseManager
from src.core.service_utils import parse_iso_ts

logger = structlog.get_logger(__name__)

_UPSERT_SQL = """
INSERT INTO transform_graduation (
    transform_id, transform_version, segment_key, n,
    spearman_rho, spearman_p, calibration_max_error, cvar_bottom_decile,
    mde, val_rho, overfitting_risk, sharpe_delta,
    is_graduated, evaluated_at, expires_at
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
ON CONFLICT (transform_id, transform_version, segment_key) DO UPDATE SET
    n = EXCLUDED.n,
    spearman_rho = EXCLUDED.spearman_rho,
    spearman_p = EXCLUDED.spearman_p,
    calibration_max_error = EXCLUDED.calibration_max_error,
    cvar_bottom_decile = EXCLUDED.cvar_bottom_decile,
    mde = EXCLUDED.mde,
    val_rho = EXCLUDED.val_rho,
    overfitting_risk = EXCLUDED.overfitting_risk,
    sharpe_delta = EXCLUDED.sharpe_delta,
    is_graduated = EXCLUDED.is_graduated,
    evaluated_at = EXCLUDED.evaluated_at,
    expires_at = EXCLUDED.expires_at
"""


def _row_to_tuple(row: dict[str, Any]) -> tuple:
    evaluated_at = row["evaluated_at"]
    expires_at = row["expires_at"]
    return (
        row["transform_id"],
        row["transform_version"],
        row["segment_key"],
        int(row["n"]) if row.get("n") is not None else 0,
        row.get("spearman_rho"),
        row.get("spearman_p"),
        row.get("calibration_max_error"),
        row.get("cvar_bottom_decile"),
        row.get("mde"),
        row.get("val_rho"),
        bool(row.get("overfitting_risk", False)),
        row.get("sharpe_delta"),
        bool(row["is_graduated"]),
        parse_iso_ts(evaluated_at) if isinstance(evaluated_at, str) else evaluated_at,
        parse_iso_ts(expires_at) if isinstance(expires_at, str) else expires_at,
    )


class TransformGraduationRepository:
    """Repository for transform_graduation table UPSERT operations."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def batch_upsert(self, rows: list[dict[str, Any]]) -> None:
        """Batch-upsert graduation evaluation rows into transform_graduation.

        Empty list is a no-op. ISO-8601 timestamp strings are converted to
        datetime objects for asyncpg timestamptz compatibility.
        """
        if not rows:
            return
        tuples = [_row_to_tuple(r) for r in rows]
        await self._db.execute_batch(_UPSERT_SQL, tuples)
        logger.debug("transform_graduation.upserted", count=len(tuples))
