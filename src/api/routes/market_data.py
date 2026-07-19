"""
Market Data API Routes

Provides access to historical market data from the database.
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/market-data/{symbol}/{timeframe}")
async def get_market_data(
    symbol: str,
    timeframe: str,
    limit: int = Query(100, ge=1, le=1000, description="Number of bars to return"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """
    Get historical market data for a symbol and timeframe.

    Args:
        symbol: Trading symbol (e.g., ESU5, NQU5)
        timeframe: Timeframe (1m, 5m, 15m, 1h, 4h, 1d)
        limit: Number of bars to return (max 1000)

    Returns:
        Dictionary with market data bars
    """
    try:
        query = """
            SELECT timestamp, open, high, low, close, volume, source
            FROM market_data_ohlcv
            WHERE symbol = $1 AND timeframe = $2
            ORDER BY timestamp ASC
            LIMIT $3
        """

        rows = await db_manager.fetch(query, symbol, timeframe, limit)

        if not rows:
            raise HTTPException(
                status_code=404, detail=f"No market data found for {symbol} {timeframe}"
            )

        bars = [
            {
                "timestamp": row["timestamp"].isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "source": row["source"],
            }
            for row in rows
        ]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": bars,
            "count": len(bars),
            "last_updated": bars[-1]["timestamp"] if bars else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching market data for {symbol} {timeframe}", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching market data: {str(e)}") from e


@router.get("/symbols")
async def get_active_symbols(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """
    Get list of active symbols with data.

    Returns:
        List of active symbols with metadata
    """
    try:
        query = """
            SELECT
                symbol,
                COUNT(*) as total_bars,
                COUNT(DISTINCT timeframe) as timeframes,
                MIN(timestamp) as first_data,
                MAX(timestamp) as last_data,
                array_agg(DISTINCT timeframe ORDER BY timeframe) as available_timeframes
            FROM market_data_ohlcv
            GROUP BY symbol
            ORDER BY symbol
        """

        rows = await db_manager.fetch(query)

        symbols = [
            {
                "symbol": row["symbol"],
                "total_bars": row["total_bars"],
                "timeframes_count": row["timeframes"],
                "first_data": row["first_data"].isoformat() if row["first_data"] else None,
                "last_data": row["last_data"].isoformat() if row["last_data"] else None,
                "available_timeframes": row["available_timeframes"] or [],
            }
            for row in rows
        ]

        return {"symbols": symbols, "total_symbols": len(symbols)}

    except Exception as e:
        logger.error("Error fetching active symbols", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching symbols: {str(e)}") from e
