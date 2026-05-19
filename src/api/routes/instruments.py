"""
Instruments API Routes

Serves instrument/contract configuration from the database.
Provides CRUD endpoints to add, update, and deactivate instruments
without a code deploy. Writes trigger pg_notify via DB trigger (091-01),
which propagates changes to the running pipeline within 1 second.
"""

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class InstrumentUpsert(BaseModel):
    """Request model for creating or replacing an instrument."""

    symbol: str
    base: str
    name: str = ""
    asset_class: Literal["equity", "futures", "fx", "crypto"]
    exchange: str = ""
    sector: str = ""
    tick_size: float = 0.0
    point_value: float = 0.0
    session_id: str = "futures_24_5"
    provider_meta: dict = {}
    expiry: str | None = None


class InstrumentUpdate(BaseModel):
    """Partial-update model for PUT /instruments/{symbol}.

    Only non-None fields are merged into the DB record.
    Numeric fields declared as float | None so FastAPI rejects string values with 422.
    """

    name: str | None = None
    asset_class: Literal["equity", "futures", "fx", "crypto"] | None = None
    exchange: str | None = None
    sector: str | None = None
    tick_size: float | None = None
    point_value: float | None = None
    session_id: str | None = None
    provider_meta: dict | None = None
    expiry: str | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


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
            **r["contract_details"],
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
    return {"symbol": r["symbol"], "is_active": r["is_active"], **r["contract_details"]}


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------


@router.post("/instruments", status_code=201)
async def create_instrument(
    payload: InstrumentUpsert,
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, str]:
    """Insert or upsert an instrument.

    Uses ON CONFLICT (symbol) DO UPDATE so concurrent POSTs for the same symbol
    are idempotent (last write wins). The DB trigger fires pg_notify automatically
    on INSERT or UPDATE - no explicit notify call is needed here.
    """
    symbol = payload.symbol.upper()
    contract_details = payload.model_dump(exclude={"symbol", "base"})
    # Include symbol and base inside contract_details for completeness
    contract_details["symbol"] = symbol
    contract_details["base"] = payload.base.upper()

    await db_manager.execute_command(
        """
        INSERT INTO instruments (symbol, base, contract_details, is_active)
        VALUES ($1, $2, $3::jsonb, true)
        ON CONFLICT (symbol) DO UPDATE
            SET contract_details = EXCLUDED.contract_details,
                is_active = true,
                updated_at = NOW()
        """,
        symbol,
        payload.base.upper(),
        contract_details,
    )

    logger.info("api.instruments.created", symbol=symbol)
    return {"status": "created", "symbol": symbol}


@router.put("/instruments/{symbol}")
async def update_instrument(
    symbol: str,
    payload: InstrumentUpdate,
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, str]:
    """Update contract_details fields or is_active for an existing instrument.

    Only non-None fields in the payload are applied. Returns 404 if the symbol
    does not exist. The DB trigger fires pg_notify on UPDATE automatically.
    """
    symbol = symbol.upper()

    # Check the symbol exists first
    rows = await db_manager.execute_query(
        "SELECT symbol FROM instruments WHERE symbol = $1", symbol
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol}' not found")

    # Handle is_active toggle separately (it's a top-level column, not inside JSONB)
    if payload.is_active is not None:
        status = await db_manager.execute_command(
            "UPDATE instruments SET is_active = $2, updated_at = NOW() WHERE symbol = $1",
            symbol,
            payload.is_active,
        )
        # If is_active was the only field, return early
        contract_fields = payload.model_dump(exclude={"is_active"}, exclude_none=True)
        if not contract_fields:
            logger.info("api.instruments.updated", symbol=symbol)
            return {"status": "updated", "symbol": symbol}
    else:
        contract_fields = payload.model_dump(exclude={"is_active"}, exclude_none=True)

    # Merge any contract_details fields via JSONB concatenation
    if contract_fields:
        await db_manager.execute_command(
            "UPDATE instruments SET contract_details = contract_details || $2::jsonb, "
            "updated_at = NOW() WHERE symbol = $1",
            symbol,
            contract_fields,
        )

    logger.info("api.instruments.updated", symbol=symbol)
    return {"status": "updated", "symbol": symbol}


@router.delete("/instruments/{symbol}")
async def delete_instrument(
    symbol: str,
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, str]:
    """Soft-delete an instrument by setting is_active=false.

    This is NOT a hard DELETE - audit history is preserved. The DB trigger fires
    pg_notify on UPDATE so the pipeline listener invalidates its cache within 1 second.
    Returns 404 if the symbol does not exist.
    """
    symbol = symbol.upper()

    status = await db_manager.execute_command(
        "UPDATE instruments SET is_active = false, updated_at = NOW() WHERE symbol = $1",
        symbol,
    )

    # asyncpg execute() returns a tag like "UPDATE 0" or "UPDATE 1"
    rows_affected = int(status.split()[-1]) if status else 0
    if rows_affected == 0:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol}' not found")

    logger.info("api.instruments.deactivated", symbol=symbol)
    return {"status": "deactivated", "symbol": symbol}
