"""
Intelligence Features API Routes

Provides paginated query and Parquet export for intelligence_features hypertable.

Route ordering is critical: /features/export MUST be registered before
/features/{symbol}/{timeframe} to prevent FastAPI from matching "export"
as a {symbol} path parameter.
"""

import io
import json
from datetime import datetime
from typing import Any

import pandas as pd
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)

router = APIRouter()

MAX_EXPORT_ROWS = 100_000


def _resolve_contract(symbol: str) -> str:
    """Map base symbol (ES) to active contract code (ESH6), same as sse.py."""
    if any(ch.isdigit() for ch in symbol):
        return symbol
    from ...config.settings import Settings

    settings = Settings()
    for c in settings.contracts:
        if c.base == symbol:
            return c.symbol
    return symbol


def _parse_jsonb(value: Any) -> Any:
    """Parse asyncpg JSONB string to dict. Returns {} on None or parse failure."""
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return {}
    return value  # already dict (asyncpg may parse in future)


# IMPORTANT: /features/export must be registered BEFORE /features/{symbol}/{timeframe}
# to prevent FastAPI matching "export" as a {symbol} path parameter.


@router.get("/features/export")
async def export_features(
    symbol: str = Query(..., description="Contract or base symbol, e.g. ESH6 or ES"),
    timeframe: str = Query(..., description="Timeframe, e.g. 1m, 5m, 15m, 1h, 1d"),
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> Response:
    """
    Export intelligence_features as Parquet file.

    Returns a Parquet binary with JSONB tier columns expanded into flat columns
    prefixed by tier name (e.g., i4_garch_sigma, i1_rsi_14).

    Constraints: symbol and timeframe are required; result capped at 100,000 rows.
    """
    contract = _resolve_contract(symbol)
    try:
        query = """
            SELECT ts, symbol, tf, platform, source, schema_version,
                   bar, i1, i3, i4, i5, smc, i6
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ($3::timestamptz IS NULL OR ts >= $3)
              AND ($4::timestamptz IS NULL OR ts <= $4)
            ORDER BY ts DESC
            LIMIT $5
        """
        rows = await db_manager.fetch(query, contract, timeframe, from_ts, to_ts, MAX_EXPORT_ROWS)

        records = []
        for row in rows:
            record = {
                "ts": row["ts"].isoformat() if hasattr(row["ts"], "isoformat") else str(row["ts"]),
                "symbol": row["symbol"],
                "tf": row["tf"],
                "source": row["source"],
                "schema_version": row["schema_version"],
            }
            for tier in ["bar", "i1", "i3", "i4", "i5", "smc", "i6"]:
                tier_data = _parse_jsonb(row[tier])
                for k, v in tier_data.items():
                    record[f"{tier}_{k}"] = v
            records.append(record)

        df = pd.DataFrame(records)
        buf = io.BytesIO()
        df.to_parquet(buf, engine="pyarrow", index=False)
        buf.seek(0)

        filename = f"features_{contract}_{timeframe}.parquet"
        return Response(
            content=buf.read(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as e:
        logger.error("Error exporting features", symbol=contract, timeframe=timeframe, error=str(e))
        raise HTTPException(status_code=500, detail=f"Error exporting features: {str(e)}") from e


@router.get("/features/{symbol}/{timeframe}")
async def get_features(
    symbol: str,
    timeframe: str,
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000, description="Number of rows to return (max 1000)"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """
    Get paginated intelligence_features rows for a symbol and timeframe.

    Accepts both base symbols (ES) and contract codes (ESH6).
    JSONB tier columns (bar, i1, i3, i4, i5, smc, i6) are returned as dicts.
    Use from/to query params (ISO 8601) for date range filtering.
    """
    contract = _resolve_contract(symbol)
    try:
        query = """
            SELECT ts, symbol, tf, platform, source, schema_version,
                   bar, i1, i3, i4, i5, smc, i6
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ($3::timestamptz IS NULL OR ts >= $3)
              AND ($4::timestamptz IS NULL OR ts <= $4)
            ORDER BY ts DESC
            LIMIT $5
        """
        rows = await db_manager.fetch(query, contract, timeframe, from_ts, to_ts, limit)

        result_rows = []
        for row in rows:
            result_rows.append(
                {
                    "ts": (
                        row["ts"].isoformat()
                        if hasattr(row["ts"], "isoformat")
                        else str(row["ts"])
                    ),
                    "symbol": row["symbol"],
                    "tf": row["tf"],
                    "platform": row["platform"],
                    "source": row["source"],
                    "schema_version": row["schema_version"],
                    "bar": _parse_jsonb(row["bar"]),
                    "i1": _parse_jsonb(row["i1"]),
                    "i3": _parse_jsonb(row["i3"]),
                    "i4": _parse_jsonb(row["i4"]),
                    "i5": _parse_jsonb(row["i5"]),
                    "smc": _parse_jsonb(row["smc"]),
                    "i6": _parse_jsonb(row["i6"]),
                }
            )

        return {
            "symbol": contract,
            "timeframe": timeframe,
            "count": len(result_rows),
            "rows": result_rows,
        }

    except Exception as e:
        logger.error(
            "Error fetching features", symbol=contract, timeframe=timeframe, error=str(e)
        )
        raise HTTPException(
            status_code=500, detail=f"Error fetching features: {str(e)}"
        ) from e
