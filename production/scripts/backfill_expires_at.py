#!/usr/bin/env python3
"""
Expires-At Backfill Script -- populate expires_at in signal_ledger.

expires_at = timestamp + ttl_bars * tf_seconds (wall-clock TTL unification, Fix 3).

Design:
- Self-contained within signal_ledger -- no JOIN to other tables.
- CASE expression has NO ELSE default -- unknown timeframes are excluded from the WHERE
  clause so they are never silently coerced to 60s (D-03 fail-loud).
- Idempotent: WHERE expires_at IS NULL -- re-running produces 0 updates.
- Batched: 10 000 rows per batch using a subquery to page through NULL rows.
- Throttled: 100 ms sleep between batches to prevent lock contention on the hypertable.
- Reconciliation: classifies remaining NULLs into data-quality vs unknown-timeframe vs
  unexpected, and exits with code 1 if any unknown-tf or unexpected NULLs remain.

Usage:
    DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent" \\
        .venv/bin/python production/scripts/backfill_expires_at.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/indicagent"
)

BATCH_SIZE = 10_000
THROTTLE_SECONDS = 0.1

_KNOWN_TFS = ("'1m'", "'5m'", "'15m'", "'1h'", "'4h'", "'1d'")
_KNOWN_TFS_LIST = ",".join(_KNOWN_TFS)

# Batched UPDATE: update up to BATCH_SIZE rows per call.
# CASE has NO ELSE default -- unknown TFs are excluded by the WHERE clause.
_UPDATE_BATCH_SQL = f"""
    UPDATE signal_ledger
    SET expires_at = timestamp + (ttl_bars * CASE feature_tf
        WHEN '1m'  THEN  60
        WHEN '5m'  THEN  300
        WHEN '15m' THEN  900
        WHEN '1h'  THEN  3600
        WHEN '4h'  THEN  14400
        WHEN '1d'  THEN  86400
        END) * INTERVAL '1 second'
    WHERE expires_at IS NULL
      AND ttl_bars IS NOT NULL
      AND feature_tf IN ({_KNOWN_TFS_LIST})
      AND signal_id IN (
          SELECT signal_id FROM signal_ledger
          WHERE expires_at IS NULL
            AND ttl_bars IS NOT NULL
            AND feature_tf IN ({_KNOWN_TFS_LIST})
          LIMIT {BATCH_SIZE}
      )
"""

_BEFORE_SQL = """
    SELECT
        COUNT(*) FILTER (WHERE expires_at IS NULL) AS null_count,
        COUNT(*) AS total
    FROM signal_ledger
"""

_RECONCILE_SQL = f"""
    SELECT
        COUNT(*) FILTER (
            WHERE expires_at IS NULL
              AND (ttl_bars IS NULL OR feature_tf IS NULL)
        ) AS dq_null,
        COUNT(*) FILTER (
            WHERE expires_at IS NULL
              AND ttl_bars IS NOT NULL
              AND feature_tf IS NOT NULL
              AND feature_tf NOT IN ({_KNOWN_TFS_LIST})
        ) AS unknown_tf_null,
        COUNT(*) FILTER (
            WHERE expires_at IS NULL
              AND ttl_bars IS NOT NULL
              AND feature_tf IN ({_KNOWN_TFS_LIST})
        ) AS unexpected_null,
        COUNT(*) FILTER (WHERE expires_at IS NULL) AS after_null,
        COUNT(*) AS total
    FROM signal_ledger
"""

_UNKNOWN_TF_SAMPLE_SQL = f"""
    SELECT DISTINCT feature_tf
    FROM signal_ledger
    WHERE expires_at IS NULL
      AND ttl_bars IS NOT NULL
      AND feature_tf IS NOT NULL
      AND feature_tf NOT IN ({_KNOWN_TFS_LIST})
    LIMIT 10
"""


async def main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # -- RECONCILIATION BEFORE -------------------------------------------------
        before_row = await conn.fetchrow(_BEFORE_SQL)
        before_null_count = before_row["null_count"]
        total = before_row["total"]
        print(f"BEFORE: {before_null_count:,} NULL expires_at rows out of {total:,} total signals")

        if before_null_count == 0:
            print("Nothing to do -- all expires_at fields are already populated.")
            print("\n=== EXPIRES_AT BACKFILL COMPLETE (no-op) ===")
            return

        # -- BATCHED UPDATE --------------------------------------------------------
        total_updated = 0
        batch_count = 0

        while True:
            result = await conn.execute(_UPDATE_BATCH_SQL)
            rows_affected = int(result.split()[-1])
            total_updated += rows_affected
            batch_count += 1

            if rows_affected > 0:
                print(
                    f"  Batch {batch_count}: updated {rows_affected:,} rows (total: {total_updated:,})"
                )
            else:
                print(f"  Batch {batch_count}: 0 rows -- backfill complete")
                break

            await asyncio.sleep(THROTTLE_SECONDS)

        # -- RECONCILIATION AFTER --------------------------------------------------
        rec_row = await conn.fetchrow(_RECONCILE_SQL)
        dq_null = rec_row["dq_null"]
        unknown_tf_null = rec_row["unknown_tf_null"]
        unexpected_null = rec_row["unexpected_null"]
        after_null_count = rec_row["after_null"]

        # Fetch offending TF values if any unknown-TF rows remain
        unknown_tf_values: list[str] = []
        if unknown_tf_null > 0:
            rows = await conn.fetch(_UNKNOWN_TF_SAMPLE_SQL)
            unknown_tf_values = [r["feature_tf"] for r in rows]

        # -- FINAL REPORT ----------------------------------------------------------
        print()
        print("=" * 60)
        print("=== EXPIRES_AT BACKFILL COMPLETE ===")
        print("=" * 60)
        print(f"Before: {before_null_count:,} NULL expires_at rows (of {total:,} total)")
        print(f"Updated: {total_updated:,} rows in {batch_count} batches")
        print(f"Data-quality NULL (missing ttl_bars or feature_tf): {dq_null:,} rows")
        print(f"Unknown-timeframe NULL (MUST be 0): {unknown_tf_null:,} rows")
        print(f"Unexpected NULL (MUST be 0): {unexpected_null:,} rows")
        print(f"After: {after_null_count:,} NULL expires_at rows remaining")
        print("=" * 60)

        failed = False

        if unknown_tf_null > 0:
            print(
                f"\nRECONCILIATION FAILED: {unknown_tf_null:,} rows have an unknown feature_tf "
                f"with non-NULL ttl_bars -- expires_at was NOT set (fail-loud, no silent coercion)."
            )
            if unknown_tf_values:
                print(f"  Offending feature_tf values (sample): {unknown_tf_values}")
            failed = True

        if unexpected_null > 0:
            print(
                f"\nRECONCILIATION FAILED: {unexpected_null:,} rows with known feature_tf and "
                f"non-NULL ttl_bars still have NULL expires_at -- backfill may be incomplete."
            )
            failed = True

        if failed:
            sys.exit(1)

        print("\nRECONCILIATION PASSED: unknown_tf_null=0, unexpected_null=0")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
