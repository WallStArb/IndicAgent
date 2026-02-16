#!/usr/bin/env python3
"""
Historical → Redis Publisher

Version: 1.0.0
Last Updated: 2025-08-09
Status: Current ✅

Reads historical OHLCV bars from TimescaleDB and publishes them to Redis Streams
using standardized stream keys and env prefix. Useful for backfilling Redis for
replay/testing when markets are closed.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from src.config.settings import Settings
from src.core.stream_keys import market as sk_market


async def fetch_bars(
    pool: asyncpg.Pool, symbol: str, timeframe: str, limit: int
) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT timestamp, open, high, low, close, volume
            FROM market_data_ohlcv
            WHERE symbol = $1 AND timeframe = $2
            ORDER BY timestamp ASC
            LIMIT $3
            """,
            symbol,
            timeframe,
            limit,
        )
    return [
        {
            "timestamp": (
                r["timestamp"].isoformat()
                if hasattr(r["timestamp"], "isoformat")
                else str(r["timestamp"])
            ),
            "symbol": symbol,
            "timeframe": timeframe,
            "open": str(r["open"]),
            "high": str(r["high"]),
            "low": str(r["low"]),
            "close": str(r["close"]),
            "volume": str(r["volume"]),
            "source": "historical_publisher",
        }
        for r in rows
    ]


async def publish_to_redis(
    r: aioredis.Redis, env_prefix: str, symbol: str, timeframe: str, bars: list[dict[str, Any]]
) -> int:
    if not bars:
        return 0
    stream = sk_market(env_prefix, symbol, timeframe)
    pipe = r.pipeline(transaction=False)
    for bar in bars:
        pipe.xadd(stream, bar, maxlen=2000 if timeframe == "1m" else 1000, approximate=True)
    await pipe.execute()
    return len(bars)


async def main_async(symbols: list[str], timeframes: list[str], limit: int) -> None:
    settings = Settings()
    env_prefix = f"{settings.env_name}:" if settings.env_name else ""

    pool = await asyncpg.create_pool(dsn=settings.database_url)
    r = aioredis.Redis(host=settings.redis_host, port=settings.redis_port, db=settings.redis_db)

    total = 0
    try:
        for symbol in symbols:
            for tf in timeframes:
                bars = await fetch_bars(pool, symbol, tf, limit)
                count = await publish_to_redis(r, env_prefix, symbol, tf, bars)
                print(f"Published {count} bars to {sk_market(env_prefix, symbol, tf)}")
                total += count
        print(f"Done. Total bars published: {total}")
    finally:
        await r.close()
        await pool.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Publish historical OHLCV to Redis Streams")
    p.add_argument("--symbols", default="ESU5", help="Comma-separated symbols, e.g., ESU5,NQU5")
    p.add_argument("--timeframes", default="1m", help="Comma-separated timeframes, e.g., 1m,5m,15m")
    p.add_argument("--limit", type=int, default=1000, help="Max bars per (symbol,timeframe)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    asyncio.run(main_async(symbols, timeframes, args.limit))


if __name__ == "__main__":
    main()
