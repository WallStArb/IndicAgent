#!/usr/bin/env python3
"""
debug_replay_prep.py — pre-rebuild database preparation: drop indexes and tune WAL

Drops secondary indexes on signal_events/trade_frames/trade_executions to eliminate
write amplification during corpus rebuild; increases max_wal_size to reduce checkpoint stalls.
Run as step 0 of the D-03 rebuild sequence before bulk data operations; replay_post.py restores indexes.
Requires PostgreSQL superuser access for index operations and config changes.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncpg

from src.config.settings import Settings

_SECONDARY_INDEXES = [
    # signal_events (10 secondary indexes)
    "idx_signal_events_backfill",
    "idx_signal_events_ctf",
    "idx_signal_events_expires",
    "idx_signal_events_regime",
    "idx_signal_events_setup_plugin_ts",
    "idx_signal_events_shadow",
    "idx_signal_events_status_ts",
    "idx_signal_events_symbol_tf_ts",
    "idx_signal_events_symbol_ts",
    "signal_events_ts_idx",
    # trade_frames (3 secondary indexes)
    "idx_trade_frames_labeled",
    "idx_trade_frames_selected_pnl",
    "idx_trade_frames_signal",
    # trade_executions (3 secondary indexes)
    "idx_trade_executions_executed_at",
    "idx_trade_executions_frame",
    "idx_trade_executions_outcome",
    # intelligence_features (1 secondary index)
    "idx_intel_features_sym_tf_ts",
]


async def main() -> None:
    settings = Settings()
    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        await conn.execute("ALTER SYSTEM SET max_wal_size = '4GB'")
        await conn.execute("SELECT pg_reload_conf()")
        print("[replay_prep] max_wal_size set to 4GB")

        dropped, skipped = [], []
        for idx in _SECONDARY_INDEXES:
            exists = await conn.fetchval("SELECT 1 FROM pg_indexes WHERE indexname = $1", idx)
            if exists:
                await conn.execute(f"DROP INDEX IF EXISTS {idx}")
                dropped.append(idx)
                print(f"[replay_prep] dropped: {idx}")
            else:
                skipped.append(idx)
                print(f"[replay_prep] skipped (not found): {idx}")

        print(f"\n[replay_prep] Done. Dropped {len(dropped)} indexes, skipped {len(skipped)}.")
        print(
            "Run scripts/debug/replay/debug_replay_post.py after _verify_replay passes to rebuild indexes."
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
