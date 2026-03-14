#!/usr/bin/env python3
"""Validate that equity backfill contains no off-hours bars.

Usage:
    python production/scripts/validate_equity_backfill.py --symbol SPY [--symbol QQQ ...]

Exits non-zero if any off-hours rows found for any symbol.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager

_OFF_HOURS_SQL = """
SELECT COUNT(*) AS count FROM intelligence_features
WHERE symbol = $1
  AND tf = '1m'
  AND (
    EXTRACT(HOUR FROM ts AT TIME ZONE 'America/New_York') < 9
    OR EXTRACT(HOUR FROM ts AT TIME ZONE 'America/New_York') >= 16
    OR (
      EXTRACT(HOUR FROM ts AT TIME ZONE 'America/New_York') = 9
      AND EXTRACT(MINUTE FROM ts AT TIME ZONE 'America/New_York') < 30
    )
  )
"""


async def validate_symbol(db: DatabaseManager, symbol: str) -> int:
    """Return count of off-hours rows for symbol. 0 = pass."""
    rows = await db.fetch(_OFF_HOURS_SQL, symbol)
    return int(rows[0]["count"]) if rows else 0


async def main(symbols: list[str]) -> int:
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    total_bad = 0
    try:
        for symbol in symbols:
            count = await validate_symbol(db, symbol)
            if count > 0:
                print(
                    f"FAIL: {symbol} has {count} off-hours rows in intelligence_features",
                    file=sys.stderr,
                )
                total_bad += count
            else:
                print(f"OK:   {symbol} — 0 off-hours rows")
    finally:
        await db.close()
    return 1 if total_bad > 0 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate equity backfill off-hours rows")
    parser.add_argument("--symbol", action="append", required=True, dest="symbols")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.symbols)))
