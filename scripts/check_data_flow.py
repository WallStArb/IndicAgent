#!/usr/bin/env python3
"""
Check data flow: Redis streams (ticks, 1m bars) and database (market_data_ohlcv).

Version: 1.1.0
Last Updated: 2026-02-28
Status: Current

Usage:
    python scripts/check_data_flow.py
    python scripts/check_data_flow.py --env dev --symbols ESH6,NQH6
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

import redis

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings, get_active_contracts
from src.core.stream_keys import live_tick as sk_live_tick
from src.core.stream_keys import market as sk_market
from src.core.stream_keys import prefix as sk_prefix
from src.core.stream_keys import ticks_pattern as sk_ticks_pattern


def check_redis(settings: Settings, symbols: list[str], env: str) -> None:
    """Print Redis stream lengths and latest entry sample for ticks and 1m bars."""
    env_prefix = sk_prefix(env)
    r = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )
    print("\n--- Redis streams ---")
    print(f"Env prefix: {repr(env_prefix)}")
    try:
        # Build key list and pipeline all xlen + xrevrange calls in one round-trip
        key_meta: list[tuple[str, str, str]] = []  # (symbol, label, stream_key)
        pipe = r.pipeline()
        for symbol in symbols:
            for label, key in [
                ("ticks", sk_live_tick(env_prefix, symbol)),
                ("1m bars", sk_market(env_prefix, symbol, "1m")),
            ]:
                key_meta.append((symbol, label, key))
                pipe.xlen(key)
                pipe.xrevrange(key, count=1)
        results = pipe.execute(raise_on_error=False)

        for i, (symbol, label, key) in enumerate(key_meta):
            length = results[i * 2]
            latest = results[i * 2 + 1]
            if isinstance(length, Exception):
                print(f"  {symbol} {label}: {key}  error={length}")
                continue
            latest_str = ""
            if latest:
                _id, fields = latest[0]
                ts = fields.get("timestamp", fields.get("close", ""))
                latest_str = f"  latest: {ts}"
            print(f"  {symbol} {label}: {key}  len={length}{latest_str}")

        # Discovery scan: find streams beyond the known symbol list
        tick_pat = sk_ticks_pattern(env_prefix)
        market_pat = f"{env_prefix}market:*:1m"
        try:
            discovered_ticks = list(r.scan_iter(tick_pat))
            discovered_market = list(r.scan_iter(market_pat))
            if discovered_ticks or discovered_market:
                print(f"  All tick streams ({tick_pat}): {len(discovered_ticks)} keys")
                print(f"  All market:1m streams ({market_pat}): {len(discovered_market)} keys")
        except Exception as e:
            print(f"  Scan error: {e}")
    finally:
        r.close()


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
        with contextlib.closing(psycopg2.connect(settings.database_url)) as conn:
            with conn.cursor() as cur:
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
    except Exception as e:
        print(f"  DB error: {e}")


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(description="Check Redis and DB data flow")
    parser.add_argument("--env", default=settings.env_name, help="INDICAGENT_ENV value")
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols (default: from settings.contracts)",
    )
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        symbols = get_active_contracts(settings)
    print("Symbols:", symbols)
    check_redis(settings, symbols, args.env)
    check_database(settings)
    print()


if __name__ == "__main__":
    main()
