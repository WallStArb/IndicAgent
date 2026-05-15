#!/usr/bin/env python3
"""Backfill 1d OHLCV bars for all active contracts.

Fetches named-contract 1d bars in 364-day chunks, iterating backward
to cover up to 7 years. Uses ON CONFLICT DO NOTHING — safe to re-run.

Usage:
    python production/scripts/backfill_1d.py                  # 7 years
    python production/scripts/backfill_1d.py --years 2        # 2 years
    python production/scripts/backfill_1d.py --symbols SPY,QQQ --years 1
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import psycopg2

from src.config.settings import Settings, get_active_contracts
from src.providers import IBKRProvider

_CHUNK_DAYS = 364
_INSERT_SQL = """
INSERT INTO market_data_ohlcv (timestamp, symbol, timeframe, open, high, low, close, volume, source)
VALUES %s
ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING
"""


def _store_bars(conn, bars: list[dict]) -> int:
    if not bars:
        return 0
    from psycopg2.extras import execute_values

    rows = [
        (
            b["timestamp"],
            b["symbol"],
            "1d",
            b["open"],
            b["high"],
            b["low"],
            b["close"],
            b["volume"],
            b["source"],
        )
        for b in bars
    ]
    with conn.cursor() as cur:
        execute_values(cur, _INSERT_SQL, rows, page_size=1000)
    conn.commit()
    return len(rows)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=7)
    parser.add_argument("--symbols", type=str, default=None)
    parser.add_argument("--client-id", type=int, default=40)
    args = parser.parse_args()

    settings = Settings()
    contracts = get_active_contracts(settings)
    if args.symbols:
        sym_set = set(args.symbols.split(","))
        contracts = [c for c in contracts if c.symbol in sym_set]

    print(f"1d Backfill — {len(contracts)} contracts, {args.years} years, {_CHUNK_DAYS}d chunks")
    print(f"  Symbols: {[c.symbol for c in contracts][:10]}{'...' if len(contracts) > 10 else ''}")

    # Connect to IBKR
    provider = IBKRProvider(
        host=settings.ib_host,
        port=settings.ib_port,
        client_id=args.client_id,
    )
    if not await provider.connect():
        print("Cannot connect to IBKR — aborting")
        sys.exit(1)
    print("  IBKR connected")

    # Qualify contracts
    for inst in contracts:
        await provider.qualify_instrument(inst)
    qualified = [c for c in contracts if c.symbol in provider._qualified_contracts]
    print(f"  Qualified: {len(qualified)}/{len(contracts)}")

    # Connect to DB
    db_conn = psycopg2.connect(dsn=settings.database_url)

    end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total_chunks = args.years * 365 // _CHUNK_DAYS + 1
    total_inserted = 0

    for chunk_idx in range(total_chunks):
        chunk_end = end - timedelta(days=chunk_idx * _CHUNK_DAYS)
        chunk_start = chunk_end - timedelta(days=_CHUNK_DAYS - 1)
        print(
            f"\n--- Chunk {chunk_idx + 1}/{total_chunks}: {chunk_start.date()} → {chunk_end.date()} ---"
        )

        for inst in qualified:
            try:
                bars = await provider.fetch_historical_bars(
                    symbol=inst.symbol,
                    timeframe="1d",
                    start=chunk_start,
                    end=chunk_end,
                    continuous=False,
                )
            except Exception as e:
                print(f"  {inst.symbol}: error — {e}")
                continue

            if not bars:
                continue

            bar_dicts = [
                {
                    "timestamp": b.timestamp,
                    "symbol": inst.symbol,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "source": getattr(b, "source", "backfill_1d"),
                }
                for b in bars
            ]
            n = _store_bars(db_conn, bar_dicts)
            total_inserted += n
            print(f"  {inst.symbol}: {len(bars)} fetched, {n} inserted")

            time.sleep(1)  # IBKR pacing

    print(f"\nDone. Total inserted: {total_inserted}")

    # Check result
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COUNT(DISTINCT symbol) FROM market_data_ohlcv WHERE timeframe = '1d'"
        )
        row = cur.fetchone()
        print(f"  DB now has {row[0]} 1d bars across {row[1]} symbols")

    await provider.disconnect()
    db_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
