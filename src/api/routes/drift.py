"""
Drift Monitor API Routes — QUAL-09/QUAL-10

Returns KS distribution drift and CUSUM performance drift state from
the drift_state DB table for all monitored symbols/TFs and setup plugins.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("")
async def get_drift_state(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Return current KS and CUSUM drift state from drift_state table."""
    ks_entries: list[dict[str, Any]] = []
    cusum_entries: list[dict[str, Any]] = []
    last_updated: str | None = None

    try:
        rows = await db_manager.fetch(
            "SELECT symbol, tf, ks_severity, cusum_severity, updated_at "
            "FROM drift_state ORDER BY updated_at DESC"
        )

        for row in rows:
            updated_at_iso = row["updated_at"].isoformat()
            if row["tf"] == "_cusum":
                cusum_entries.append(
                    {
                        "setup_plugin": row["symbol"],
                        "severity": row["cusum_severity"],
                        "updated_at": updated_at_iso,
                    }
                )
            else:
                ks_entries.append(
                    {
                        "symbol": row["symbol"],
                        "tf": row["tf"],
                        "ks_severity": row["ks_severity"],
                        "cusum_severity": row["cusum_severity"],
                        "updated_at": updated_at_iso,
                    }
                )
            if last_updated is None:
                last_updated = updated_at_iso

    except Exception as error:
        logger.warning("drift endpoint: DB query error", error=str(error))

    return {
        "ks": ks_entries,
        "cusum": cusum_entries,
        "last_updated": last_updated,
    }
