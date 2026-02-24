"""
Signal History API Routes

Provides access to signal_ledger with optional JOIN to intelligence_features
for full feature context at signal time.
"""

import json
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)

router = APIRouter()


def _resolve_contract(symbol: str) -> str:
    """Map base symbol (ES) to active contract code (ESH6)."""
    if any(ch.isdigit() for ch in symbol):
        return symbol
    from ...config.settings import Settings

    settings = Settings()
    for c in settings.contracts:
        if c.base == symbol:
            return c.symbol
    return symbol


def _parse_jsonb(value: Any) -> Any:
    """Parse asyncpg JSONB string to dict. Returns None if value is None."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return value


def _build_signal_row(row: Any, include_features: bool) -> dict[str, Any]:
    """Build signal response dict from asyncpg row."""
    signal: dict[str, Any] = {
        "signal_id": str(row["signal_id"]),
        "timestamp": (
            row["timestamp"].isoformat()
            if hasattr(row["timestamp"], "isoformat")
            else str(row["timestamp"])
        ),
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "setup_plugin": row["setup_plugin"],
        "signal_type": row["signal_type"],
        "direction": row["direction"],
        "entry_price": float(row["entry_price"]) if row["entry_price"] is not None else None,
        "stop_loss": float(row["stop_loss"]) if row["stop_loss"] is not None else None,
        "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
        "status": row["status"],
        "feature_ts": (
            row["feature_ts"].isoformat()
            if row["feature_ts"] is not None and hasattr(row["feature_ts"], "isoformat")
            else None
        ),
        "feature_tf": row["feature_tf"],
    }
    if include_features:
        # feature_ts NULL → features=None (pre-Phase-2 signals without feature context)
        if row["feature_ts"] is None:
            signal["features"] = None
        else:
            signal["features"] = {
                "bar": _parse_jsonb(row["bar"]),
                "i1": _parse_jsonb(row["i1"]),
                "i3": _parse_jsonb(row["i3"]),
                "i4": _parse_jsonb(row["i4"]),
                "i5": _parse_jsonb(row["i5"]),
                "smc": _parse_jsonb(row["smc"]),
                "i6": _parse_jsonb(row["i6"]),
            }
    return signal


@router.get("/signals/{symbol}")
async def get_signals(
    symbol: str,
    include_features: bool = Query(
        False, description="Include full feature context from intelligence_features JOIN"
    ),
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000, description="Number of signals to return (max 1000)"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """
    Get signal history for a symbol from signal_ledger.

    Accepts both base symbols (ES) and contract codes (ESH6).

    With include_features=true, each signal includes the full intelligence_features
    row at signal time via LEFT JOIN on (symbol, feature_ts, feature_tf).
    Signals with NULL feature_ts (pre-Phase-2) return features: null.
    """
    contract = _resolve_contract(symbol)
    try:
        if include_features:
            query = """
                SELECT sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
                       sl.setup_plugin, sl.signal_type, sl.direction,
                       sl.entry_price, sl.stop_loss, sl.confidence, sl.status,
                       sl.feature_ts, sl.feature_tf,
                       f.bar, f.i1, f.i3, f.i4, f.i5, f.smc, f.i6
                FROM signal_ledger sl
                LEFT JOIN intelligence_features f
                  ON sl.symbol = f.symbol
                 AND sl.feature_ts = f.ts
                 AND sl.feature_tf = f.tf
                WHERE sl.symbol = $1
                  AND ($3::timestamptz IS NULL OR sl.timestamp >= $3)
                  AND ($4::timestamptz IS NULL OR sl.timestamp <= $4)
                ORDER BY sl.timestamp DESC
                LIMIT $2
            """
        else:
            query = """
                SELECT signal_id, timestamp, symbol, timeframe,
                       setup_plugin, signal_type, direction,
                       entry_price, stop_loss, confidence, status,
                       feature_ts, feature_tf
                FROM signal_ledger
                WHERE symbol = $1
                  AND ($3::timestamptz IS NULL OR timestamp >= $3)
                  AND ($4::timestamptz IS NULL OR timestamp <= $4)
                ORDER BY timestamp DESC
                LIMIT $2
            """

        rows = await db_manager.fetch(query, contract, limit, from_ts, to_ts)

        signals = [_build_signal_row(row, include_features) for row in rows]

        return {
            "symbol": contract,
            "count": len(signals),
            "signals": signals,
        }

    except Exception as e:
        logger.error("Error fetching signals", symbol=contract, error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching signals: {str(e)}") from e
