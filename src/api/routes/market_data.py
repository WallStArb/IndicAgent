"""
Market Data API Routes

Provides access to real-time and historical market data from Redis streams and database.
"""

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from ...config.settings import Settings
from ...core.database_manager import DatabaseManager
from ...core.redis_streams_manager import RedisStreamsManager
from ...core.stream_keys import market as sk_market
from ..dependencies import get_db_manager, get_redis_manager

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
        # Query database for historical data
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

        # Convert to API response format
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

        # Reverse to get chronological order (oldest first)
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


@router.get("/market-data/{symbol}/{timeframe}/latest")
async def get_latest_bar(
    symbol: str, timeframe: str, redis_manager: RedisStreamsManager = Depends(get_redis_manager)
) -> dict[str, Any]:
    """
    Get the latest market data bar from Redis streams.

    Args:
        symbol: Trading symbol
        timeframe: Timeframe

    Returns:
        Latest market data bar
    """
    try:
        # Read latest from Redis stream using standardized keys with env prefix
        settings = Settings()
        env_prefix = f"{settings.env_name}:" if settings.env_name else ""
        stream_name = sk_market(env_prefix, symbol, timeframe)
        messages = await redis_manager.read_from_stream(stream_name, count=1)

        if not messages:
            raise HTTPException(
                status_code=404, detail=f"No live data found for {symbol} {timeframe}"
            )

        # Get the latest message
        message = messages[0]
        data = message.data

        # Handle both string and bytes keys
        def get_value(key):
            if key in data:
                return data[key]
            elif key.encode() in data:
                val = data[key.encode()]
                return val.decode() if isinstance(val, bytes) else val
            else:
                return None

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": get_value("timestamp"),
            "open": float(get_value("open")),
            "high": float(get_value("high")),
            "low": float(get_value("low")),
            "close": float(get_value("close")),
            "volume": int(float(get_value("volume"))),
            "source": get_value("source"),
            "stream_id": message.stream_id,
        }

    except Exception as e:
        logger.error(f"Error fetching latest bar for {symbol} {timeframe}", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching latest bar: {str(e)}") from e


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


@router.get("/market-data/{symbol}/status")
async def get_symbol_status(
    symbol: str,
    db_manager: DatabaseManager = Depends(get_db_manager),
    redis_manager: RedisStreamsManager = Depends(get_redis_manager),
) -> dict[str, Any]:
    """
    Get detailed status for a specific symbol including both database and stream data.

    Args:
        symbol: Trading symbol

    Returns:
        Detailed status information
    """
    try:
        # Database stats
        db_query = """
            SELECT
                timeframe,
                COUNT(*) as bar_count,
                MIN(timestamp) as first_bar,
                MAX(timestamp) as last_bar
            FROM market_data_ohlcv
            WHERE symbol = $1
            GROUP BY timeframe
            ORDER BY timeframe
        """

        db_rows = await db_manager.fetch(db_query, symbol)

        # Redis stream stats
        timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]
        stream_stats = {}

        settings = Settings()
        env_prefix = f"{settings.env_name}:" if settings.env_name else ""
        for tf in timeframes:
            try:
                stream_name = sk_market(env_prefix, symbol, tf)
                # Get stream length
                length = await redis_manager.redis_client.xlen(stream_name)

                # Get latest message if stream exists
                latest = None
                if length > 0:
                    messages = await redis_manager.read_from_stream(stream_name, count=1)
                    if messages:
                        data = messages[0].data
                        latest = {
                            "timestamp": data.get("timestamp")
                            or data.get(b"timestamp", b"").decode(),
                            "close": data.get("close") or data.get(b"close", b"").decode(),
                        }

                stream_stats[tf] = {"length": length, "latest": latest}

            except Exception:
                stream_stats[tf] = {"length": 0, "latest": None}

        # Database timeframe stats
        db_stats = {}
        for row in db_rows:
            tf, count, first, last = row
            db_stats[tf] = {
                "bar_count": count,
                "first_bar": first.isoformat() if first else None,
                "last_bar": last.isoformat() if last else None,
            }

        return {
            "symbol": symbol,
            "database": db_stats,
            "redis_streams": stream_stats,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error fetching status for {symbol}", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching status: {str(e)}") from e
