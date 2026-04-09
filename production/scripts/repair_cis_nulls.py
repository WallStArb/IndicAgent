#!/usr/bin/env python3
"""Chunked back-fill of raw_cis_score / filtered_cis_score / calibrated_confidence
in signal_ledger from the i7 JSONB field in intelligence_features.

Run ONCE as a pre-v2.3 data repair. Safe to re-run — rows already populated
are skipped by the WHERE clause.

Usage:
    .venv/bin/python production/scripts/repair_cis_nulls.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncpg

from src.config.settings import Settings, get_active_contracts

# Chunk size: one (symbol, timeframe, date) combination at a time.
# This keeps JOIN size manageable (a few thousand rows per batch).
_TFS = ("1m", "5m", "15m", "1h", "4h", "1d")


async def _repair_chunk(
    conn: asyncpg.Connection,
    symbol: str,
    tf: str,
    day: date,
    dry_run: bool,
) -> int:
    """Back-fill one (symbol, tf, date) chunk. Returns rows updated."""
    day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    # Tune memory per session to allow the JOIN to fit
    await conn.execute("SET work_mem = '256MB'")

    if dry_run:
        count = await conn.fetchval(
            """
            SELECT count(*)
            FROM signal_ledger sl
            WHERE sl.symbol = $1
              AND sl.feature_tf = $2
              AND sl.feature_ts >= $3 AND sl.feature_ts < $4
              AND sl.raw_cis_score IS NULL
            """,
            symbol, tf, day_start, day_end,
        )
        return count or 0

    result = await conn.execute(
        """
        UPDATE signal_ledger sl
        SET
            raw_cis_score         = (inff.i7->>'raw_cis_score')::float,
            filtered_cis_score    = (inff.i7->>'filtered_cis_score')::float,
            calibrated_confidence = (inff.i7->>'calibrated_confidence')::float
        FROM intelligence_features inff
        WHERE sl.symbol     = inff.symbol
          AND sl.feature_ts = inff.ts
          AND sl.feature_tf = inff.tf
          AND sl.symbol     = $1
          AND sl.feature_tf = $2
          AND sl.feature_ts >= $3 AND sl.feature_ts < $4
          AND sl.raw_cis_score IS NULL
          AND inff.i7 IS NOT NULL
          AND inff.i7 ? 'raw_cis_score'
        """,
        symbol, tf, day_start, day_end,
    )
    # asyncpg returns "UPDATE N" — parse the integer
    if not result:
        return 0
    parts = result.split()
    return int(parts[-1]) if parts else 0


async def _amain(args: argparse.Namespace) -> None:
    settings = Settings()
    contracts = get_active_contracts(settings)
    symbols = [c.symbol for c in contracts]

    conn = await asyncpg.connect(settings.database_url)
    try:
        # Determine date range from earliest signal_ledger row
        first_ts = await conn.fetchval(
            "SELECT min(feature_ts) FROM signal_ledger WHERE raw_cis_score IS NULL"
        )
        if first_ts is None:
            print("No NULL rows found — already clean.")
            return

        start_date = first_ts.date()
        end_date = datetime.now(UTC).date()

        total_updated = 0
        current = start_date
        while current <= end_date:
            for symbol in symbols:
                for tf in _TFS:
                    n = await _repair_chunk(conn, symbol, tf, current, args.dry_run)
                    if n > 0:
                        mode = "would update" if args.dry_run else "updated"
                        print(f"  {current} {symbol} {tf}: {mode} {n} rows")
                        total_updated += n
            current += timedelta(days=1)

        mode = "Would update" if args.dry_run else "Updated"
        print(f"\nDone. {mode} {total_updated} rows total.")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back-fill CIS null scores in signal_ledger"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Count rows without updating"
    )
    args = parser.parse_args()
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
