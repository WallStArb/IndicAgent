#!/usr/bin/env python3
"""
Post-Rebuild Index Restoration and D-04 Acceptance Gate Checks.

Version: 1.0
Status: current
Last Updated: 2026-06-19

Rebuilds all secondary indexes dropped by replay_prep.py using CREATE INDEX CONCURRENTLY
(non-blocking — no table lock). Restores max_wal_size to 1GB. Then runs the Phase 133
D-04 acceptance gate queries and exits non-zero if any gate fails.

Run once as step 5 of the D-03 rebuild sequence, after lifecycle_replay.py completes
and _verify_replay passes.

D-04 gates checked:
    - signal_events count within 2% of baseline (~1,036,513)
    - distinct setup_plugin count == 35
    - context_features coverage >= 99%
    - ctf_score > 0.05 for >= 85% of non-null rows
    - trade_frames confirmed as hypertable

Usage:
    python production/scripts/replay_post.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncpg

from src.config.settings import Settings

# Exact DDL for each dropped index — CONCURRENTLY added, schema-qualified removed.
# Each statement runs outside any transaction (required for CONCURRENTLY).
_INDEX_CREATES = [
    # signal_events
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_backfill ON signal_events USING btree (ts DESC) WHERE (is_backfill = true)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_ctf ON signal_events USING btree (ctf_confirmed, ts DESC)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_expires ON signal_events USING btree (expires_at) WHERE (expires_at IS NOT NULL)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_regime ON signal_events USING btree (hmm_regime_at_fire, ts DESC)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_setup_plugin_ts ON signal_events USING btree (setup_plugin, ts DESC)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_shadow ON signal_events USING btree (ts DESC) WHERE (is_shadow = true)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_status_ts ON signal_events USING btree (status, ts DESC)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_symbol_tf_ts ON signal_events USING btree (symbol, tf, ts DESC)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_symbol_ts ON signal_events USING btree (symbol, ts DESC)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS signal_events_ts_idx ON signal_events USING btree (ts DESC)",
    # trade_frames
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trade_frames_labeled ON trade_frames USING btree (signal_ts DESC, counterfactual_pnl_r) WHERE (counterfactual_pnl_r IS NOT NULL)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trade_frames_selected_pnl ON trade_frames USING btree (was_selected, counterfactual_pnl_r)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trade_frames_signal ON trade_frames USING btree (signal_id, signal_ts)",
    # trade_executions
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trade_executions_executed_at ON trade_executions USING btree (executed_at)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trade_executions_frame ON trade_executions USING btree (frame_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trade_executions_outcome ON trade_executions USING btree (outcome) WHERE (outcome IS NOT NULL)",
    # intelligence_features
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_intel_features_sym_tf_ts ON intelligence_features USING btree (symbol, tf, ts DESC)",
]

_BASELINE_SIGNAL_COUNT = 1_036_513
_BASELINE_TOLERANCE = 0.02  # 2%


async def _run_acceptance_gates(conn: asyncpg.Connection) -> list[str]:
    """Run D-04 acceptance gate queries. Returns list of failure messages (empty = pass)."""
    failures = []

    # Gate 1: signal_events count within 2% of baseline
    count = await conn.fetchval("SELECT COUNT(*) FROM signal_events")
    lo = int(_BASELINE_SIGNAL_COUNT * (1 - _BASELINE_TOLERANCE))
    hi = int(_BASELINE_SIGNAL_COUNT * (1 + _BASELINE_TOLERANCE))
    status = "PASS" if lo <= count <= hi else "FAIL"
    print(
        f"  [D-04] signal_events count: {count:,} (baseline ~{_BASELINE_SIGNAL_COUNT:,}, range [{lo:,}, {hi:,}]) — {status}"
    )
    if status == "FAIL":
        failures.append(
            f"signal_events count {count:,} outside 2% tolerance of baseline {_BASELINE_SIGNAL_COUNT:,}"
        )

    # Gate 2: distinct setup_plugin count must be 35
    plugin_count = await conn.fetchval("SELECT COUNT(DISTINCT setup_plugin) FROM signal_events")
    status = "PASS" if plugin_count == 35 else "FAIL"
    print(f"  [D-04] distinct plugins firing: {plugin_count} (expected 35) — {status}")
    if status == "FAIL":
        failures.append(f"distinct plugins: {plugin_count} != 35")
        # Print which plugins fired
        rows = await conn.fetch(
            "SELECT setup_plugin, COUNT(*) as cnt FROM signal_events GROUP BY 1 ORDER BY 2 DESC"
        )
        for r in rows:
            print(f"         {r['setup_plugin']}: {r['cnt']:,}")

    # Gate 3: context_features coverage >= 99%
    cf_row = await conn.fetchrow(
        "SELECT COUNT(*) as total, COUNT(context_features) as with_cf FROM signal_events"
    )
    total = cf_row["total"]
    with_cf = cf_row["with_cf"]
    cf_pct = with_cf / total if total > 0 else 0.0
    status = "PASS" if cf_pct >= 0.99 else "FAIL"
    print(f"  [D-04] context_features coverage: {cf_pct:.1%} (required >=99%) — {status}")
    if status == "FAIL":
        failures.append(f"context_features coverage {cf_pct:.1%} < 99%")

    # Gate 4: ctf_score distribution — >=85% of non-null rows > 0.05
    ctf_row = await conn.fetchrow("""SELECT
            COUNT(*) FILTER (WHERE ctf_score IS NOT NULL) as non_null,
            COUNT(*) FILTER (WHERE ctf_score > 0.05) as above_threshold
           FROM signal_events""")
    non_null = ctf_row["non_null"]
    above = ctf_row["above_threshold"]
    ctf_pct = above / non_null if non_null > 0 else 0.0
    status = "PASS" if ctf_pct >= 0.85 else "FAIL"
    print(
        f"  [D-04] ctf_score >0.05 rate: {ctf_pct:.1%} of {non_null:,} non-null rows (required >=85%) — {status}"
    )
    if status == "FAIL":
        failures.append(f"ctf_score distribution {ctf_pct:.1%} < 85%")

    # Gate 5: trade_frames confirmed as hypertable
    ht_row = await conn.fetchrow(
        "SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_name = 'trade_frames'"
    )
    status = "PASS" if ht_row else "FAIL"
    print(f"  [D-04] trade_frames hypertable: {'confirmed' if ht_row else 'NOT FOUND'} — {status}")
    if status == "FAIL":
        failures.append("trade_frames is not a hypertable")

    return failures


async def main() -> None:
    settings = Settings()
    # CONCURRENTLY requires autocommit — asyncpg runs each execute() in autocommit by default.
    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        print(
            f"[replay_post] Rebuilding {len(_INDEX_CREATES)} indexes (CONCURRENTLY — non-blocking)..."
        )
        for ddl in _INDEX_CREATES:
            name = ddl.split("IF NOT EXISTS ")[1].split(" ON ")[0]
            print(f"  building: {name} ...")
            await conn.execute(ddl)
            print(f"  done:     {name}")

        await conn.execute("ALTER SYSTEM SET max_wal_size = '1GB'")
        await conn.execute("SELECT pg_reload_conf()")
        print("\n[replay_post] max_wal_size restored to 1GB")

        print("\n[replay_post] Running D-04 acceptance gates...")
        failures = await _run_acceptance_gates(conn)

        if failures:
            print(f"\n[replay_post] FAILED — {len(failures)} gate(s) did not pass:")
            for f in failures:
                print(f"  - {f}")
            sys.exit(1)
        else:
            print("\n[replay_post] All D-04 gates PASSED — corpus is clean.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
