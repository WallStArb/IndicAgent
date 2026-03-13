#!/usr/bin/env python3
"""
Reset CUSUM baseline for a named setup plugin.

Usage:
    python reset_cusum.py --plugin trad_TrendFollowing

Deletes the Redis drift:cusum:{plugin} key, resetting the CUSUM state to "none".
Inserts an audit record into the drift_monitor hypertable.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
import redis.asyncio as redis

from src.config.settings import Settings
from src.core.stream_keys import drift_cusum


async def reset_cusum(plugin: str) -> None:
    """Delete CUSUM Redis key and insert audit record for a setup plugin."""
    settings = Settings()
    env_prefix = f"{settings.env_name}:" if settings.env_name else ""
    cusum_key = drift_cusum(env_prefix, plugin)

    # Connect to Redis
    redis_client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )

    # Connect to database
    db_conn = await asyncpg.connect(settings.database_url)

    try:
        # Delete CUSUM Redis key
        deleted = await redis_client.delete(cusum_key)
        if deleted:
            print(f"Deleted Redis key: {cusum_key}")
        else:
            print(f"Key not found (already clear): {cusum_key}")

        # Insert audit record into drift_monitor
        await db_conn.execute(
            """
            INSERT INTO drift_monitor
                (check_type, symbol, setup_plugin, checked_at,
                 alert_triggered, alert_severity, alert_message)
            VALUES ('cusum', 'RESET', $1, $2, FALSE, 'none', $3)
            """,
            plugin,
            datetime.now(UTC),
            f"Manual CUSUM reset for {plugin}",
        )
        print(f"Audit record written to drift_monitor for {plugin}")
        print(f"CUSUM state reset to 'none' for setup: {plugin}")

    finally:
        await redis_client.aclose()
        await db_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset CUSUM baseline for a setup plugin")
    parser.add_argument(
        "--plugin",
        required=True,
        help="Setup plugin name to reset (e.g. trad_TrendFollowing)",
    )
    args = parser.parse_args()
    asyncio.run(reset_cusum(args.plugin))


if __name__ == "__main__":
    main()
