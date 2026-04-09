#!/usr/bin/env python3
"""One-shot migration: fix market_data_ohlcv.base from contract codes to base symbols.

Root cause: BarWriterAgent queried instruments table (base symbols only),
so IBKR contract codes (ESM6) fell back to base=symbol (base="ESM6").

Fix: JOIN contract_metadata to get correct base_symbol for all futures rows.

Safe to run while live — UPDATE with WHERE guard is idempotent:
  - Rows already correct (base=base_symbol) are skipped by WHERE clause
  - ON CONFLICT logic in INSERT is unaffected
  - TimescaleDB hypertable: UPDATE touches all relevant chunks

Usage:
    .venv/bin/python production/scripts/fix_bar_base_symbols.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncpg

from src.config.settings import Settings


async def _amain(dry_run: bool) -> None:
    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)

    try:
        # Step 1: Count scope
        count_sql = """
            SELECT COUNT(*)
            FROM market_data_ohlcv m
            JOIN contract_metadata cm ON m.symbol = cm.symbol
            WHERE m.base != cm.base_symbol;
        """
        affected = await conn.fetchval(count_sql)
        print(f"Rows with incorrect base: {affected:,}")

        if affected == 0:
            print("Nothing to fix — all rows already have correct base symbols.")
            return

        # Step 2: Show sample before
        sample_sql = """
            SELECT m.symbol, m.base AS base_current, cm.base_symbol AS base_correct, COUNT(*) AS rows
            FROM market_data_ohlcv m
            JOIN contract_metadata cm ON m.symbol = cm.symbol
            WHERE m.base != cm.base_symbol
            GROUP BY m.symbol, m.base, cm.base_symbol
            ORDER BY rows DESC
            LIMIT 10;
        """
        rows = await conn.fetch(sample_sql)
        print("\nTop affected symbols (before):")
        print(f"  {'symbol':<12} {'base_current':<14} {'base_correct':<14} {'rows':>8}")
        for r in rows:
            print(f"  {r['symbol']:<12} {r['base_current']:<14} {r['base_correct']:<14} {r['rows']:>8,}")

        if dry_run:
            print(f"\nDRY RUN — would update {affected:,} rows. Re-run without --dry-run to apply.")
            return

        # Step 3: Apply fix
        print(f"\nUpdating {affected:,} rows...")
        update_sql = """
            UPDATE market_data_ohlcv m
            SET base = cm.base_symbol
            FROM contract_metadata cm
            WHERE m.symbol = cm.symbol
              AND m.base != cm.base_symbol;
        """
        result = await conn.execute(update_sql)
        try:
            updated = int(result.split()[-1])
        except (ValueError, IndexError):
            print(f"WARNING: could not parse update count from '{result}' — assuming 0")
            updated = 0
        print(f"Updated: {updated:,} rows")

        # Step 4: Verify
        remaining = await conn.fetchval(count_sql)
        print(f"Remaining incorrect rows: {remaining}")
        if remaining == 0:
            print("SUCCESS — all base symbols corrected.")
        else:
            print(f"WARNING — {remaining} rows still incorrect. Check contract_metadata coverage.")
            sys.exit(1)

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix market_data_ohlcv.base symbols")
    parser.add_argument("--dry-run", action="store_true", help="Count affected rows without modifying data")
    args = parser.parse_args()
    asyncio.run(_amain(dry_run=args.dry_run))
