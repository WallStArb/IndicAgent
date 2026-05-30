"""
Drift Monitor API Routes — QUAL-09/QUAL-10

Returns KS distribution drift and CUSUM performance drift state from
the drift_state DB table for all monitored symbols/TFs and setup plugins.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("")
async def get_drift_state() -> dict[str, Any]:
    """Return current KS and CUSUM drift state from drift_state table."""
    from src.core.database_manager import get_connection

    ks_entries: list[dict[str, Any]] = []
    cusum_entries: list[dict[str, Any]] = []
    last_updated: str | None = None

    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                "SELECT symbol, tf, ks_severity, cusum_severity, updated_at "
                "FROM drift_state ORDER BY updated_at DESC"
            )

        for row in rows:
            entry = {
                "symbol": row["symbol"],
                "tf": row["tf"],
                "ks_severity": row["ks_severity"],
                "cusum_severity": row["cusum_severity"],
                "updated_at": row["updated_at"].isoformat(),
            }
            if row["tf"] == "_cusum":
                cusum_entries.append(
                    {
                        "setup_plugin": row["symbol"],
                        "severity": row["cusum_severity"],
                        "updated_at": row["updated_at"].isoformat(),
                    }
                )
            else:
                ks_entries.append(entry)
            if last_updated is None:
                last_updated = row["updated_at"].isoformat()

    except Exception as error:
        logger.warning("drift endpoint: DB query error", error=str(error))

    return {
        "ks": ks_entries,
        "cusum": cusum_entries,
        "last_updated": last_updated,
    }
