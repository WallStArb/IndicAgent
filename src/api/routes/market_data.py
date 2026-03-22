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
            ORDER BY timestamp DESC
            LIMIT $3
        """

        rows = await db_manager.fetch(query, symbol, timeframe, limit)

        if not rows:
            raise HTTPException(
                status_code=404, detail=f"No market data found for {symbol} {timeframe}"
            )

        bars = []
        for row in rows:
            bars.append(
                {
                    "timestamp": row[0].isoformat(),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": int(row[5]),
                    "source": row[6],
                }
            )

        bars.reverse()

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": bars,
            "count": len(bars),
            "last_updated": bars[-1]["timestamp"] if bars else None,
        }

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

        symbols = []
        for row in rows:
            symbols.append(
                {
                    "symbol": row[0],
                    "total_bars": row[1],
                    "timeframes_count": row[2],
                    "first_data": row[3].isoformat() if row[3] else None,
                    "last_data": row[4].isoformat() if row[4] else None,
                    "available_timeframes": row[5] if row[5] else [],
                }
            )

        return {"symbols": symbols, "total_symbols": len(symbols)}

    except Exception as e:
        logger.error("Error fetching active symbols", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching symbols: {str(e)}") from e
