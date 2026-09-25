# Replay Optimization Design

**Date:** 2026-06-19
**Status:** Approved
**Scope:** Pre-Phase-133 corpus rebuild optimizations — DB-level and code-level

## Goal

Reduce Phase 133 corpus rebuild wall-clock time and eliminate code anti-patterns before running
the TRUNCATE + backfill + lifecycle replay sequence. All changes are safe to apply because the
corpus is being rebuilt from scratch after a full TRUNCATE.

## Changes

### 1. Pre/Post rebuild scripts

**`production/scripts/replay_prep.py`**

Run once before the D-03 rebuild sequence starts (before `reset_pipeline_data.py`).

- `ALTER SYSTEM SET max_wal_size = '4GB'; SELECT pg_reload_conf()` — reduces checkpoint stall
  frequency during bulk load. Currently 1GB; 4GB matches the scale of the rebuild.
- Drop all secondary (non-PK) indexes on `signal_events`, `trade_frames`, `trade_executions`,
  `intelligence_features`. PKs are kept — `ON CONFLICT` clauses in all replay scripts depend on them.
- Print the list of dropped indexes for reference.

Indexes to drop:

| Table | Index |
|-------|-------|
| signal_events | idx_signal_events_backfill |
| signal_events | idx_signal_events_ctf |
| signal_events | idx_signal_events_expires |
| signal_events | idx_signal_events_regime |
| signal_events | idx_signal_events_setup_plugin_ts |
| signal_events | idx_signal_events_shadow |
| signal_events | idx_signal_events_status_ts |
| signal_events | idx_signal_events_symbol_tf_ts |
| signal_events | idx_signal_events_symbol_ts |
| signal_events | signal_events_ts_idx |
| trade_frames | idx_trade_frames_labeled |
| trade_frames | idx_trade_frames_selected_pnl |
| trade_frames | idx_trade_frames_signal |
| trade_executions | idx_trade_executions_executed_at |
| trade_executions | idx_trade_executions_frame |
| trade_executions | idx_trade_executions_outcome |
| intelligence_features | idx_intel_features_sym_tf_ts |

**`production/scripts/replay_post.py`**

Run once after `_verify_replay` passes (D-03 step 4 complete).

- `CREATE INDEX CONCURRENTLY` for every dropped index above (non-blocking, no table lock).
  Each statement must execute outside any transaction block — asyncpg's `conn.execute()` in
  autocommit mode, or psycopg2 with `connection.autocommit = True`.
- `ALTER SYSTEM SET max_wal_size = '1GB'; SELECT pg_reload_conf()` — restore original setting.
- Run D-04 acceptance gate queries and print pass/fail:
  - signal_events count vs ~1,036,513 baseline (within 2%)
  - distinct setup_plugin count (must be 35)
  - context_features coverage (>=99%)
  - ctf_score distribution (>=85% of non-null rows > 0.05)
  - trade_frames hypertable confirmation

### 2. `feature_replay.py` — connection-per-bar fix + write batching

**Problem:** Lines 395-396 run `async with pool.acquire() as conn:` inside `for row in rows:`.
Every bar that fires signals opens, uses, and releases a DB connection. For the full corpus
this is hundreds of thousands of acquire/release cycles.

**Fix:**
- Acquire one connection per `(symbol, tf)` run at the top of `_replay_symbol_tf()`, release at
  the end.
- Set `synchronous_commit = off` immediately after acquiring (one call per connection).
- Accumulate `signal_events` and `trade_frames` parameter tuples across bars into two lists.
- Flush with `conn.executemany()` for both tables every `WRITE_BATCH_SIZE = 200` signals and at
  end of the `(symbol, tf)` run.
- Wrap each flush in `async with conn.transaction()`.

`executemany()` sends all rows in a single round-trip vs N round-trips for N `execute()` calls.

### 3. `lifecycle_replay.py` — executemany + synchronous_commit

**`_flush_writes()` batching:**

- **Activations (UPDATE signal_events):** all activations in a flush batch set the same status
  (`'active'`). Replace the per-signal loop with a single
  `UPDATE signal_events SET status = 'active' WHERE signal_id = ANY($1::uuid[])`.
- **Zone exits / market (INSERT trade_executions):** homogeneous INSERT shape — replace the
  per-signal `conn.execute()` loop with `conn.executemany()`.
- **Activation trade_frames UPDATE:** heterogeneous JSONB per signal — keep as individual
  executes (cannot be batched without a CTE unnest approach that adds complexity without
  meaningful gain since activations are sparse).

**Session setting:**

Add `SET synchronous_commit = off` alongside the existing
`SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0` on the connection acquired at
line 545. Applied once per `(symbol, tf)` worker connection.

### 4. `run_historical_pipeline.py` — subprocess worker session setting

The Stage 2 replay workers run in `ProcessPoolExecutor` subprocesses, each with its own psycopg2
connection. Add `cur.execute("SET synchronous_commit = off")` immediately after opening the
connection in the subprocess worker function. One call per worker process.

## D-03 Rebuild Sequence (updated)

```
0. python production/scripts/replay_prep.py          # drop indexes, set max_wal_size=4GB
1. python production/scripts/reset_pipeline_data.py  # TRUNCATE CASCADE (B4 fix)
2. python production/scripts/run_historical_pipeline.py --replay-only --include-rolled \
       --client-id 40 --workers 8
3. python production/scripts/lifecycle_replay.py --workers 8 --commit-every 500
4. _verify_replay must pass: stale_unresolved=0, target_no_pnl=0, orphan_signal_events=0
5. python production/scripts/replay_post.py          # rebuild indexes, restore max_wal_size
```

## What is NOT changed

- `ON CONFLICT` logic — PKs are not dropped, all idempotency guarantees preserved.
- Commit cadence in `lifecycle_replay.py` (`--commit-every 500`) — unchanged. Only the
  per-commit WAL flush wait is eliminated.
- The `B2` asyncpg transaction hygiene fix and other Phase 133 script fixes are separate
  concerns handled in the Phase 133 plans — this design does not duplicate them.
- `feature_replay.py` is the I7-only validation tool; `run_historical_pipeline.py` is the main
  backfill script. Both are touched, but for different reasons.

## Risk

- **Index drop window:** between `replay_prep.py` and `replay_post.py`, query plans that relied
  on secondary indexes fall back to seqscans. Acceptable — no live queries run against these
  tables during a corpus rebuild (services are stopped).
- **`synchronous_commit = off`:** session-scoped, so it only affects the replay connections.
  Crash during rebuild at worst requires re-running from the TRUNCATE. No data corruption risk.
- **`max_wal_size = 4GB`:** cluster-wide but transient. If the rebuild is interrupted, restore
  with `ALTER SYSTEM SET max_wal_size = '1GB'; SELECT pg_reload_conf()`.
