"""
Instruments API Routes

Serves instrument/contract configuration from the database.
"""

import json
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/instruments")
async def list_instruments(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> list[dict[str, Any]]:
    """Return all active instruments."""
    rows = await db_manager.execute_query(
        "SELECT symbol, contract_details, is_active "
        "FROM instruments WHERE is_active = TRUE ORDER BY symbol"
    )
    return [
        {
            "symbol": r["symbol"],
            "is_active": r["is_active"],
            **(r["contract_details"] if isinstance(r["contract_details"], dict) else json.loads(r["contract_details"])),
        }
        for r in rows
    ]


@router.get("/instruments/{symbol}")
async def get_instrument(
    symbol: str,
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Return a single instrument by base symbol."""
    rows = await db_manager.execute_query(
        "SELECT symbol, contract_details, is_active FROM instruments WHERE symbol = $1",
        symbol.upper(),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol}' not found")
    r = rows[0]
    cd = r["contract_details"]
    return {"symbol": r["symbol"], "is_active": r["is_active"], **(cd if isinstance(cd, dict) else json.loads(cd))}
