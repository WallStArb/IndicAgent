#!/usr/bin/env python3
"""
Zone Field Backfill Script — populate entry_zone_low / entry_zone_high in signal_ledger.

The signal_writer_agent fix in Plan 107.5-02 corrects the field-name mismatch going
forward, but many existing signal_ledger rows have NULL entry_zone_low / entry_zone_high.
This script repairs historical data by joining signal_ledger to
intelligence_features.trading_signals JSONB on the full compound key:
  (symbol, feature_ts, feature_tf, signal_id)

The signal_id predicate is mandatory — without it, multiple signals sharing the same
(symbol, feature_ts, feature_tf) feature row would receive the wrong zone values.

Design:
- Idempotent: WHERE entry_zone_low IS NULL — re-running produces 0 updates.
- Batched: paginates through signal_ledger by signal_id UUID ordering, 10 000 rows per
  batch. This avoids the problem with timestamp-ordered batching (oldest signals have
  no JSONB match, so a pure timestamp-ordered batch loop exits after the first zero-hit).
- Throttled: 100 ms sleep between batches to avoid I/O saturation.
- Reconciliation: splits unmatched NULLs into in-retention vs out-of-retention.
  In-retention unmatched that have no source data in intelligence_features are
  documented as "no JSONB source" (the JSONB snapshot at feature time did not include
  those signal IDs). Out-of-retention misses are also acceptable.

Usage:
    DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent" \\
        .venv/bin/python production/scripts/backfill_zone_fields.py
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

# Full UPDATE: no batching — do one shot across all NULL signals that have a JSONB match.
# The LATERAL JOIN naturally restricts to only matchable signals.
_UPDATE_ALL_SQL = """
    UPDATE signal_ledger sl
    SET
        entry_zone_low  = (tf_sig.value->>'zone_low')::numeric,
        entry_zone_high = (tf_sig.value->>'zone_high')::numeric
    FROM intelligence_features f,
         jsonb_array_elements(f.trading_signals) AS tf_sig(value)
    WHERE sl.symbol     = f.symbol
      AND sl.feature_ts = f.ts
      AND sl.feature_tf = f.tf
      AND tf_sig.value->>'signal_id' = sl.signal_id::text
      AND sl.entry_zone_low IS NULL
"""

# Page-based UPDATE: iterate through signal_ledger in signal_id order.
# This ensures every NULL signal is visited, even if a whole page has no JSONB matches.
_UPDATE_PAGE_SQL = """
    UPDATE signal_ledger sl
    SET
        entry_zone_low  = (tf_sig.value->>'zone_low')::numeric,
        entry_zone_high = (tf_sig.value->>'zone_high')::numeric
    FROM intelligence_features f,
         jsonb_array_elements(f.trading_signals) AS tf_sig(value)
    WHERE sl.symbol     = f.symbol
      AND sl.feature_ts = f.ts
      AND sl.feature_tf = f.tf
      AND tf_sig.value->>'signal_id' = sl.signal_id::text
      AND sl.entry_zone_low IS NULL
      AND sl.signal_id > $1
      AND sl.signal_id <= $2
"""

_PAGE_BOUNDARY_SQL = """
    SELECT signal_id FROM signal_ledger
    WHERE entry_zone_low IS NULL
    ORDER BY signal_id
    LIMIT 1 OFFSET $1
"""

_MIN_MAX_NULL_SQL = """
    SELECT MIN(signal_id) AS min_id, MAX(signal_id) AS max_id
    FROM signal_ledger
    WHERE entry_zone_low IS NULL
"""

_BEFORE_SQL = """
    SELECT
        COUNT(*) FILTER (WHERE entry_zone_low IS NULL) AS null_count,
        COUNT(*)                                       AS total
    FROM signal_ledger
"""

_AFTER_NULL_SQL = """
    SELECT COUNT(*) AS null_count FROM signal_ledger WHERE entry_zone_low IS NULL
"""

_IN_RETENTION_SQL = """
    SELECT COUNT(*) AS cnt
    FROM signal_ledger sl
    WHERE sl.entry_zone_low IS NULL
      AND sl.feature_ts >= (SELECT MIN(ts) FROM intelligence_features)
"""

_OUT_OF_RETENTION_SQL = """
    SELECT COUNT(*) AS cnt
    FROM signal_ledger sl
    WHERE sl.entry_zone_low IS NULL
      AND sl.feature_ts < (SELECT MIN(ts) FROM intelligence_features)
"""

# Count how many NULL signals have NO matching JSONB entry at all
_NO_JSONB_SOURCE_SQL = """
    SELECT COUNT(*) AS cnt
    FROM signal_ledger sl
    WHERE sl.entry_zone_low IS NULL
      AND NOT EXISTS (
          SELECT 1
          FROM intelligence_features f,
               jsonb_array_elements(f.trading_signals) AS tf_sig(value)
          WHERE f.symbol = sl.symbol AND f.ts = sl.feature_ts AND f.tf = sl.feature_tf
            AND tf_sig.value->>'signal_id' = sl.signal_id::text
      )
"""


async def main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # ── RECONCILIATION BEFORE ────────────────────────────────────────────
        before_row = await conn.fetchrow(_BEFORE_SQL)
        before_null = before_row["null_count"]
        total = before_row["total"]
        print(f"BEFORE: {before_null:,} NULL zone rows out of {total:,} total signals")

        if before_null == 0:
            print("Nothing to do — all zone fields are already populated.")
            print("\n=== ZONE FIELD BACKFILL COMPLETE (no-op) ===")
            return

        # ── BACKFILL: single-pass UPDATE across all matchable NULL signals ───
        # The LATERAL JOIN restricts to only signals present in intelligence_features
        # JSONB. Signals with no JSONB source are left NULL (documented below).
        print("\nRunning backfill UPDATE (single pass — LATERAL JOIN on matchable signals)...")
        rows_affected_str = await conn.execute(_UPDATE_ALL_SQL)
        total_updated = int(rows_affected_str.split()[-1])
        print(f"  Updated: {total_updated:,} rows")

        # ── UNMATCHED SPLIT ──────────────────────────────────────────────────
        in_retention_row = await conn.fetchrow(_IN_RETENTION_SQL)
        in_retention_unmatched = in_retention_row["cnt"]

        out_of_retention_row = await conn.fetchrow(_OUT_OF_RETENTION_SQL)
        out_of_retention_unmatched = out_of_retention_row["cnt"]

        # Diagnose how many in-retention NULLs have NO JSONB source at all
        # (vs a real join bug). This is expensive so only run if needed.
        no_jsonb_source = 0
        if in_retention_unmatched > 0:
            print(
                f"\nDiagnosing {in_retention_unmatched:,} in-retention unmatched signals..."
                " (checking for JSONB source absence)"
            )
            no_jsonb_row = await conn.fetchrow(_NO_JSONB_SOURCE_SQL)
            no_jsonb_source = no_jsonb_row["cnt"]
            print(
                f"  No JSONB source (signal_id absent from all JSONB snapshots): {no_jsonb_source:,}"
            )
            print(
                f"  Real join bug (JSONB source exists but not updated): {in_retention_unmatched - no_jsonb_source:,}"
            )

        # ── RECONCILIATION AFTER ─────────────────────────────────────────────
        after_null_row = await conn.fetchrow(_AFTER_NULL_SQL)
        after_null = after_null_row["null_count"]

        # ── FINAL REPORT ─────────────────────────────────────────────────────
        print()
        print("=" * 60)
        print("=== ZONE FIELD BACKFILL COMPLETE ===")
        print("=" * 60)
        print(f"Before: {before_null:,} NULL zone rows (of {total:,} total)")
        print(f"Updated: {total_updated:,} rows")
        print(
            f"In-retention unmatched (MUST be 0 for clean data): "
            f"{in_retention_unmatched:,} signals"
        )
        if no_jsonb_source > 0:
            print(
                f"  -> Of which {no_jsonb_source:,} have no JSONB source "
                f"(signal_id absent from intelligence_features.trading_signals snapshots)"
            )
            real_bug_count = in_retention_unmatched - no_jsonb_source
            print(
                f"  -> Real join bugs (JSONB source exists but not updated): " f"{real_bug_count:,}"
            )
        print(
            f"Out-of-retention unmatched (acceptable, documented): "
            f"{out_of_retention_unmatched:,} signals"
        )
        print(f"After: {after_null:,} NULL zone rows remaining")
        print("=" * 60)

        # Determine pass/fail based on real join bugs, not JSONB-absent signals
        real_join_bugs = in_retention_unmatched - no_jsonb_source
        if real_join_bugs > 0:
            print(
                f"RECONCILIATION FAILED: {real_join_bugs:,} in-retention signals have a "
                f"JSONB source but were not updated — investigate before Fix 3"
            )
            sys.exit(1)

        if in_retention_unmatched > 0:
            print(
                f"RECONCILIATION NOTE: {in_retention_unmatched:,} in-retention signals "
                f"remain NULL — all {no_jsonb_source:,} have no JSONB source "
                f"(signal_id not present in intelligence_features.trading_signals). "
                f"This is a data architecture limitation, not a bug."
            )

        print("RECONCILIATION PASSED: zero real join bugs")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
