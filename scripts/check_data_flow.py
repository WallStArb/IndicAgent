#!/usr/bin/env python3
"""
Check data flow: Redis streams (ticks, 1m bars) and database (market_data_ohlcv).

Version: 1.0.0
Last Updated: 2026-02-21
Status: Current

Usage:
    python scripts/check_data_flow.py
    python scripts/check_data_flow.py --env dev --symbols ESH6,NQH6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import redis

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings, get_active_contracts
from src.core.stream_keys import live_tick as sk_live_tick
from src.core.stream_keys import market as sk_market


def _env_prefix(env_name: str) -> str:
    return f"{env_name}:" if env_name else ""


def check_redis(settings: Settings, symbols: list[str], env: str) -> None:
    """Print Redis stream lengths and latest entry sample for ticks and 1m bars."""
    env_prefix = _env_prefix(env)
    r = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )
    print("\n--- Redis streams ---")
    print(f"Env prefix: {repr(env_prefix)}")
    for symbol in symbols:
        tick_stream = sk_live_tick(env_prefix, symbol)
        market_1m = sk_market(env_prefix, symbol, "1m")
        for name, key in [("ticks", tick_stream), ("1m bars", market_1m)]:
            try:
                length = r.xlen(key)
                latest = r.xrevrange(key, count=1)
                latest_str = ""
                if latest:
                    _id, fields = latest[0]
                    ts = fields.get("timestamp", fields.get("close", ""))
                    latest_str = f"  latest: {ts}"
                print(f"  {symbol} {name}: {key}  len={length}{latest_str}")
            except Exception as e:
                print(f"  {symbol} {name}: {key}  error={e}")
    # Optional: list any stream keys matching pattern (in case symbols != actual keys)
    try:
        pattern = f"{env_prefix}ticks:*:live"
        keys_ticks = r.keys(pattern)
        pattern_m = f"{env_prefix}market:*:1m"
        keys_market = r.keys(pattern_m)
        if keys_ticks or keys_market:
            print(f"  All tick streams (KEYS {pattern}): {len(keys_ticks)} keys")
            print(f"  All market:1m streams (KEYS {pattern_m}): {len(keys_market)} keys")
    except Exception as e:
        print(f"  KEYS scan error: {e}")


def check_database(settings: Settings) -> None:
    """Print market_data_ohlcv summary: counts and latest timestamp per symbol/timeframe."""
    try:
        import psycopg2
    except ImportError:
        print("\n--- Database ---")
        print("  psycopg2 not available; install psycopg2-binary to check DB.")
        return
    print("\n--- Database (market_data_ohlcv) ---")
    try:
        conn = psycopg2.connect(settings.database_url)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT symbol, timeframe, COUNT(*) AS cnt, MAX(timestamp) AS last_ts
            FROM market_data_ohlcv
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
            """
        )
        rows = cur.fetchall()
        if not rows:
            print("  No rows in market_data_ohlcv.")
        else:
            for symbol, tf, cnt, last_ts in rows:
                print(f"  {symbol} {tf}: count={cnt}  last={last_ts}")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"  DB error: {e}")


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(description="Check Redis and DB data flow")
    parser.add_argument("--env", default=settings.env_name or "dev", help="INDICAGENT_ENV value")
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols (default: from settings.contracts)",
    )
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        symbols = get_active_contracts(settings)
    if not symbols:
        print("No symbols to check. Set HF_CONTRACTS_JSON/IBKR_CONTRACTS_JSON or pass --symbols.")
        return
    print("Symbols:", symbols)
    check_redis(settings, symbols, args.env)
    check_database(settings)
    print()


if __name__ == "__main__":
    main()
