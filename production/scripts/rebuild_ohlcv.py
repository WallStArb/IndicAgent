#!/usr/bin/env python3
"""
Rebuild market_data_ohlcv hypertable with 7-day chunk interval.

Strategy:
1. Create market_data_ohlcv_v2 with 7-day chunks
2. Copy all data in batches (INSERT SELECT ON CONFLICT DO NOTHING for restartability)
3. Verify: chunk_count < 200 AND benchmark query < 500ms
4. Atomic rename: old -> _old, v2 -> current
5. Recreate indexes on the renamed table

Idempotent: safe to restart if interrupted. ON CONFLICT skips already-copied rows.

Context:
  market_data_ohlcv currently has ~15,740 chunks (1-day interval) causing
  4-5 second timeouts on aggregate queries. Rebuilding with 7-day chunks
  reduces chunk count to < 200 and query latency to < 500ms.

Usage:
    INDICAGENT_ENV=development .venv/bin/python production/scripts/rebuild_ohlcv.py --dry-run
    INDICAGENT_ENV=development .venv/bin/python production/scripts/rebuild_ohlcv.py
    INDICAGENT_ENV=development .venv/bin/python production/scripts/rebuild_ohlcv.py --batch-days 7

Design rationale (Renaissance principles):
- Instrument everything: progress logged per batch window
- Never drop data: old table renamed to _old, not dropped
- Let the system run: ON CONFLICT DO NOTHING makes restarts safe
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.core.script_utils import get_script_db

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1: Create v2 table
# ---------------------------------------------------------------------------


async def create_v2_table(db: DatabaseManager) -> None:
    """Create market_data_ohlcv_v2 with 7-day chunk interval.

    Uses CREATE TABLE IF NOT EXISTS + create_hypertable(if_not_exists => TRUE)
    so this step is idempotent — safe to re-run if interrupted.
    """
    logger.info("Creating market_data_ohlcv_v2 (IF NOT EXISTS)...")

    async with db.get_connection() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS market_data_ohlcv_v2 "
            "(LIKE market_data_ohlcv INCLUDING DEFAULTS INCLUDING CONSTRAINTS)"
        )

        # Drop any inherited PK — hypertable PK must include partition column
        await conn.execute(
            "ALTER TABLE market_data_ohlcv_v2 "
            "DROP CONSTRAINT IF EXISTS market_data_ohlcv_v2_pkey"
        )

        # Create as hypertable with 7-day chunks
        await conn.execute(
            "SELECT create_hypertable("
            "  'market_data_ohlcv_v2', 'timestamp',"
            "  chunk_time_interval => INTERVAL '7 days',"
            "  if_not_exists => TRUE"
            ")"
        )

        # Add unique constraint (required for ON CONFLICT DO NOTHING)
        await conn.execute(
            "ALTER TABLE market_data_ohlcv_v2 "
            "ADD CONSTRAINT market_data_ohlcv_v2_unique "
            "UNIQUE (symbol, timeframe, timestamp)"
        )

    logger.info("market_data_ohlcv_v2 created with 7-day chunks.")


# ---------------------------------------------------------------------------
# Step 2: Copy data in batches
# ---------------------------------------------------------------------------


async def copy_data(db: DatabaseManager, batch_days: int = 30) -> int:
    """Copy all rows from market_data_ohlcv to market_data_ohlcv_v2 in batches.

    Uses INSERT ... ON CONFLICT DO NOTHING so already-copied rows are skipped
    on restart. Returns total rows inserted.
    """
    async with db.get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT MIN(timestamp), MAX(timestamp) FROM market_data_ohlcv"
        )

        if row is None or row[0] is None:
            logger.warning("market_data_ohlcv is empty — nothing to copy.")
            return 0

        min_ts, max_ts = row
        logger.info("Copying data from %s to %s (%d-day batches).", min_ts, max_ts, batch_days)

        total_inserted = 0
        window_start = min_ts

        while window_start < max_ts:
            window_end = window_start + timedelta(days=batch_days)

            result = await conn.execute(
                """
                INSERT INTO market_data_ohlcv_v2
                SELECT * FROM market_data_ohlcv
                WHERE timestamp >= $1 AND timestamp < $2
                ON CONFLICT DO NOTHING
                """,
                window_start,
                window_end,
            )

            # asyncpg returns "INSERT 0 N" string
            inserted = int(result.split()[-1]) if result else 0
            total_inserted += inserted

            logger.info(
                "  [%s → %s] %d rows inserted (cumulative: %d).",
                window_start.date(),
                window_end.date(),
                inserted,
                total_inserted,
            )
            window_start = window_end

        logger.info("Copy complete — %d total rows inserted.", total_inserted)
        return total_inserted


# ---------------------------------------------------------------------------
# Step 3: Verify v2 is ready
# ---------------------------------------------------------------------------


async def verify_v2_ready(db: DatabaseManager) -> tuple[bool, dict]:
    """Check chunk_count < 200 AND benchmark query < 500ms.

    Pure function — uses only the passed connection, no global state.
    Returns (passed, details_dict) where details_dict contains measured values
    and failure reason (if any).
    """
    async with db.get_connection() as conn:
        # Check chunk count
        chunk_count = await conn.fetchval(
            """
            SELECT count(*) FROM timescaledb_information.chunks
            WHERE hypertable_name = 'market_data_ohlcv_v2'
            AND hypertable_schema = 'public'
            """
        )

        if chunk_count >= 200:
            return False, {
                "chunk_count": chunk_count,
                "reason": "chunk_count >= 200",
            }

        # Benchmark aggregate query
        benchmark_sql = """
            SELECT symbol, timeframe, date_trunc('day', timestamp) AS day,
                   max(high), min(low), sum(volume)
            FROM market_data_ohlcv_v2
            WHERE timestamp >= NOW() - INTERVAL '30 days'
            GROUP BY 1, 2, 3
            LIMIT 100
        """
        start = time.monotonic()
        await conn.fetch(benchmark_sql)
        elapsed_ms = (time.monotonic() - start) * 1000

        if elapsed_ms >= 500:
            return False, {
                "chunk_count": chunk_count,
                "elapsed_ms": round(elapsed_ms, 1),
                "reason": "latency >= 500ms",
            }

        return True, {
            "chunk_count": chunk_count,
            "elapsed_ms": round(elapsed_ms, 1),
        }


# ---------------------------------------------------------------------------
# Step 4: Atomic rename
# ---------------------------------------------------------------------------


async def atomic_rename(db: DatabaseManager) -> None:
    """Rename market_data_ohlcv → _old, market_data_ohlcv_v2 → market_data_ohlcv.

    Then recreate the performance index documented in CLAUDE.md:
        CREATE INDEX ON market_data_ohlcv (symbol, timeframe, timestamp DESC)
    """
    async with db.get_connection() as conn:
        logger.info("Renaming market_data_ohlcv → market_data_ohlcv_old...")
        await conn.execute(
            "ALTER TABLE market_data_ohlcv RENAME TO market_data_ohlcv_old"
        )

        logger.info("Renaming market_data_ohlcv_v2 → market_data_ohlcv...")
        await conn.execute(
            "ALTER TABLE market_data_ohlcv_v2 RENAME TO market_data_ohlcv"
        )

        logger.info("Recreating performance index on market_data_ohlcv...")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_data_ohlcv_sym_tf_ts "
            "ON market_data_ohlcv (symbol, timeframe, timestamp DESC)"
        )

    logger.info(
        "Rename complete. Old table preserved as market_data_ohlcv_old."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _amain(args: argparse.Namespace) -> None:
    """Async main entry point."""
    settings = Settings()
    logger.info(
        "Connecting to database (env=%s)...", settings.environment
    )

    db = await get_script_db(settings)

    try:
        # Step 1
        await create_v2_table(db)

        # Step 2
        await copy_data(db, batch_days=args.batch_days)

        # Step 3
        logger.info("Running verification gate...")
        passed, details = await verify_v2_ready(db)

        if not passed:
            logger.error(
                "Verification gate FAILED: %s (details: %s)",
                details.get("reason"),
                details,
            )
            sys.exit(1)

        logger.info("Verification gate PASSED: %s", details)

        # Step 4
        if args.dry_run:
            logger.info(
                "--dry-run: skipping atomic rename. "
                "market_data_ohlcv_v2 is ready and verified."
            )
        else:
            await atomic_rename(db)
            logger.info("Rebuild complete.")

    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild market_data_ohlcv with 7-day chunks"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Create v2 table and verify only — skip atomic rename.",
    )
    parser.add_argument(
        "--batch-days",
        type=int,
        default=30,
        help="Days per INSERT batch (default: 30).",
    )
    args = parser.parse_args()

    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
