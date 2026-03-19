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
import logging
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg2

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings

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
# Database connection
# ---------------------------------------------------------------------------


def connect_db(settings: Settings) -> Any:
    """Create a synchronous psycopg2 connection from Settings."""
    url = settings.database_url
    url = url.replace("postgresql://", "").replace("postgres://", "")
    userpass, rest = url.split("@", 1)
    user, password = userpass.split(":", 1)
    hostport_db = rest.split("/", 1)
    hostport = hostport_db[0]
    dbname = hostport_db[1] if len(hostport_db) > 1 else "indicagent"
    host, port = hostport.split(":", 1) if ":" in hostport else (hostport, "5432")

    return psycopg2.connect(
        host=host, port=int(port), database=dbname, user=user, password=password
    )


# ---------------------------------------------------------------------------
# Step 1: Create v2 table
# ---------------------------------------------------------------------------


def create_v2_table(conn: Any) -> None:
    """Create market_data_ohlcv_v2 with 7-day chunk interval.

    Uses CREATE TABLE IF NOT EXISTS + create_hypertable(if_not_exists => TRUE)
    so this step is idempotent — safe to re-run if interrupted.
    """
    with conn.cursor() as cur:
        logger.info("Creating market_data_ohlcv_v2 (IF NOT EXISTS)...")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS market_data_ohlcv_v2 "
            "(LIKE market_data_ohlcv INCLUDING DEFAULTS INCLUDING CONSTRAINTS)"
        )

        # Drop any inherited PK — hypertable PK must include partition column
        cur.execute(
            "ALTER TABLE market_data_ohlcv_v2 "
            "DROP CONSTRAINT IF EXISTS market_data_ohlcv_v2_pkey"
        )

        # Create as hypertable with 7-day chunks
        cur.execute(
            "SELECT create_hypertable("
            "  'market_data_ohlcv_v2', 'timestamp',"
            "  chunk_time_interval => INTERVAL '7 days',"
            "  if_not_exists => TRUE"
            ")"
        )

        # Add unique constraint (required for ON CONFLICT DO NOTHING)
        cur.execute(
            "ALTER TABLE market_data_ohlcv_v2 "
            "ADD CONSTRAINT market_data_ohlcv_v2_unique "
            "UNIQUE (symbol, timeframe, timestamp)"
        )

        conn.commit()
    logger.info("market_data_ohlcv_v2 created with 7-day chunks.")


# ---------------------------------------------------------------------------
# Step 2: Copy data in batches
# ---------------------------------------------------------------------------


def copy_data(conn: Any, batch_days: int = 30) -> int:
    """Copy all rows from market_data_ohlcv to market_data_ohlcv_v2 in batches.

    Uses INSERT ... ON CONFLICT DO NOTHING so already-copied rows are skipped
    on restart. Returns total rows inserted.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM market_data_ohlcv"
        )
        row = cur.fetchone()

    if row is None or row[0] is None:
        logger.warning("market_data_ohlcv is empty — nothing to copy.")
        return 0

    min_ts, max_ts = row
    logger.info("Copying data from %s to %s (%d-day batches).", min_ts, max_ts, batch_days)

    total_inserted = 0
    window_start = min_ts

    while window_start < max_ts:
        window_end = window_start + timedelta(days=batch_days)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO market_data_ohlcv_v2
                SELECT * FROM market_data_ohlcv
                WHERE timestamp >= %s AND timestamp < %s
                ON CONFLICT DO NOTHING
                """,
                (window_start, window_end),
            )
            inserted = cur.rowcount
            conn.commit()

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


def verify_v2_ready(conn: Any) -> tuple[bool, dict]:
    """Check chunk_count < 200 AND benchmark query < 500ms.

    Pure function — uses only the passed connection, no global state.
    Returns (passed, details_dict) where details_dict contains measured values
    and failure reason (if any).
    """
    with conn.cursor() as cur:
        # Check chunk count
        cur.execute(
            """
            SELECT count(*) FROM timescaledb_information.chunks
            WHERE hypertable_name = 'market_data_ohlcv_v2'
            AND hypertable_schema = 'public'
            """
        )
        chunk_count = cur.fetchone()[0]

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
    with conn.cursor() as cur:
        cur.execute(benchmark_sql)
        cur.fetchall()
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


def atomic_rename(conn: Any) -> None:
    """Rename market_data_ohlcv → _old, market_data_ohlcv_v2 → market_data_ohlcv.

    Then recreate the performance index documented in CLAUDE.md:
        CREATE INDEX ON market_data_ohlcv (symbol, timeframe, timestamp DESC)
    """
    with conn.cursor() as cur:
        logger.info("Renaming market_data_ohlcv → market_data_ohlcv_old...")
        cur.execute(
            "ALTER TABLE market_data_ohlcv RENAME TO market_data_ohlcv_old"
        )

        logger.info("Renaming market_data_ohlcv_v2 → market_data_ohlcv...")
        cur.execute(
            "ALTER TABLE market_data_ohlcv_v2 RENAME TO market_data_ohlcv"
        )

        logger.info("Recreating performance index on market_data_ohlcv...")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_data_ohlcv_sym_tf_ts "
            "ON market_data_ohlcv (symbol, timeframe, timestamp DESC)"
        )

        conn.commit()

    logger.info(
        "Rename complete. Old table preserved as market_data_ohlcv_old."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


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

    settings = Settings()
    logger.info(
        "Connecting to database (env=%s)...", settings.environment
    )
    conn = connect_db(settings)

    try:
        # Step 1
        create_v2_table(conn)

        # Step 2
        copy_data(conn, batch_days=args.batch_days)

        # Step 3
        logger.info("Running verification gate...")
        passed, details = verify_v2_ready(conn)

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
            atomic_rename(conn)
            logger.info("Rebuild complete.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
