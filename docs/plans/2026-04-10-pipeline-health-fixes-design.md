---
title: Pipeline Health Fixes
status: Approved
priority: P0
scope: Signal tracker compute/persistence separation + operational unblocks
date: 2026-04-10
---

# Pipeline Health Fixes — Design

Fix the three critical blockers identified in the 2026-04-10 pipeline health audit by applying existing architectural patterns. No new patterns invented.

## Problem

The signal tracker is the only service in the system that interleaves compute and persistence. Every other data path follows:

```
ComputeAgent (DB-ignorant) → Kafka topic → WriterAgent (zero compute) → DB
```

The tracker reads from DB, evaluates lifecycle transitions, and writes to DB in the same process with `await` on every transition. This causes:

- 258K bar lag on signal_lifecycle consumer group
- 515K signals stuck at `pending` (zero activations for crypto)
- TimescaleDB decompression errors on every bar for 3 futures symbols
- 65K intelligence pipeline lag (separate issue, self-draining at 4.5 bars/sec)

## Solution

Two phases: unblock the system (P1), then fix the architectural violation (P2).

Pipeline throughput optimization (P3) is deferred. The pipeline catches up in ~5 hours at current 4.5 bars/sec vs 0.83 bars/sec real-time need. The 5000-symbol refactor will require a fundamentally different architecture — any plugin-level optimization now would be throwaway work.

---

## P1: Unblock (30 minutes)

### P1.1: Set TimescaleDB decompression limit to unlimited

The default `max_tuples_decompressed_per_dml_transaction = 100,000` (was previously 1,000, raised but not enough). The tracker's UPDATE queries on signal_ledger hit compressed chunks and exceed the limit on every bar for NQM6, RTYM6, ESM6.

```sql
ALTER SYSTEM SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;
SELECT pg_reload_conf();
```

### P1.2: Disable compression on signal_ledger

signal_ledger is write-heavy (frequent UPDATEs for status changes, chandelier state, MAE/MFE). Compression is designed for read-heavy hypertables. The compressed chunk causes decompression overhead on every write.

```sql
ALTER TABLE signal_ledger SET (
    timescaledb.compress = false
);

-- Decompress existing compressed chunks
SELECT decompress_chunk(chunk_schema || '.' || chunk_name)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'signal_ledger'
  AND is_compressed = true;
```

3.7M rows at ~104KB compressed — uncompressed size is still small. Storage cost is negligible.

### P1.3: Expire orphaned pre-restart pending signals

135K signals from before Apr 7 restart that sit outside topic retention (7 days). The tracker will never evaluate them.

```sql
UPDATE signal_ledger
SET status = 'expired',
    outcome = 'never_activated',
    exit_reason = 'orphaned_pre_restart',
    exit_ts = NOW()
WHERE status = 'pending'
  AND feature_ts < '2026-04-07 11:51:00+00';
```

### P1.4: Restart signal tracker

After config changes and orphan cleanup, restart to clear error state.

```bash
sudo systemctl restart indicagent-signal-tracker
```

**Verification:** Zero new decompression errors in tracker log. Lag starts decreasing within minutes.

---

## P2: Separate Compute from Persistence (2-3 days)

### Current Architecture (violates DAG)

```
market.bars → signal_tracker (compute + DB read + DB write) → signal_ledger
```

Single service that:
- Consumes bars one at a time from Kafka
- Queries DB for active signals every 60s (N queries for N symbols)
- Evaluates lifecycle transitions (pure compute)
- `await`s individual DB writes per transition (activation, resolution, chandelier)
- Commits Kafka after every bar

### Target Architecture (follows DAG)

```
market.bars ─────────────────────────────────────────────────────┐
market.bars.htf ─────────────────────────────────────────────────┤
                                                                 ↓
                                              signal_tracker_compute
                                              (DB-ignorant, in-memory)
                                                                 │
                                                                 ↓
                                                    lifecycle.transitions
                                                    (new Kafka topic)
                                                                 │
                                                                 ↓
                                                   lifecycle_writer_agent
                                                   (batch persist, zero compute)
                                                                 │
                                                                 ↓
                                                         signal_ledger
```

Two services, following the exact same pattern as:
- `intelligence_pipeline` → `intelligence.journal` → `feature_writer` → `intelligence_features`
- `intelligence_pipeline` → `intelligence.i7.signals` → `signal_writer` → `signal_ledger`

---

### P2.1: Signal Tracker ComputeAgent

**File:** `services/signal_tracker_compute.py`
**Unit:** `indicagent-signal-tracker-compute`
**Consumer group:** `signal_tracker_compute` (new group, starts fresh)
**Metrics port:** :9127

**Responsibilities:**
- Consume bars from `market.bars` + `market.bars.htf`
- Maintain active signals in-memory
- Evaluate lifecycle transitions via existing `evaluate_signal()` logic
- Publish transition events to `lifecycle.transitions` Kafka topic
- Checkpoint state to compacted topic for restart recovery

**Compute layer design:**

```
getmany() batch of bars
       ↓
for each bar:
    filter active signals by symbol + timeframe
    evaluate_signal() per signal (pure function, unchanged)
    collect transitions (activations, exits, chandelier updates, MAE/MFE)
       ↓
publish all transitions to lifecycle.transitions topic
       ↓
commit Kafka offsets (every batch, not every bar)
```

**Key changes from current tracker:**
- `getmany(max_records=100, timeout=1.0)` instead of single-message iteration
- Zero `await` on DB writes — transitions are Kafka publishes only
- Kafka commits per batch, not per bar
- Chandelier state updates published as transitions (not direct DB writes)

**State management:**

Bootstrap: On startup, query DB once for all active signals:
```sql
SELECT * FROM signal_ledger WHERE status IN ('pending', 'active', 'regime_suppressed');
```

Checkpoint: Periodically serialize in-memory state to a compacted Kafka topic `lifecycle.checkpoint` (same pattern as `intelligence_pipeline` state checkpointing).

Signal ingestion: The ComputeAgent subscribes to `intelligence.i7.signals` Kafka topic (same topic `signal_writer_agent` consumes). New signals are added to the in-memory index as they arrive. This replaces the current reseed-from-DB-every-60s pattern with a streaming update. The ComputeAgent is a second consumer on the same topic (different consumer group `signal_tracker_compute`), which Kafka supports natively.

**What stays the same:**
- `evaluate_signal()` pure function (untouched)
- Signal lifecycle logic: pending → active → expired
- 8-class outcome taxonomy
- Shadow tracking for regime_suppressed signals
- Market-entry parallel track
- Chandelier trailing stop computation

**What changes:**
- No DB reads after initial bootstrap
- No DB writes at all
- All transitions published to Kafka
- Batch bar consumption
- Periodic Kafka commits

---

### P2.2: Lifecycle WriterAgent

**File:** `services/lifecycle_writer_agent.py`
**Unit:** `indicagent-lifecycle-writer`
**Consumer group:** `lifecycle_writer_group`
**Metrics port:** :9128

**Responsibilities:**
- Consume transition events from `lifecycle.transitions` topic
- Buffer transitions in memory
- Batch-write to `signal_ledger` via `execute_batch()`
- Standard writer metrics (batch latency, buffer depth, consumer lag)

**Pattern:** Exact copy of `signal_writer_agent.py` conventions:

```python
BATCH_SIZE = 100          # flush after this many transitions
FLUSH_INTERVAL_SECS = 5.0 # or after this many seconds
MAX_BUFFER_SIZE = 10_000   # memory safety cap
```

**Transition types to persist:**
- `activation` — signal status pending → active
- `exit` — signal status active → expired/stopped_out/target_hit
- `chandelier_update` — trailing stop state change
- `mae_mfe_update` — max adverse/favorable excursion update
- `shadow_outcome` — regime_suppressed signal outcome recording

Each transition type maps to a specific UPDATE statement on signal_ledger. The writer batches transitions of the same type together for efficient `execute_batch()` calls.

**What stays the same:**
- Repository methods in `SignalLedgerRepository` for DB interaction
- All DB schema and column names

**What's new:**
- Kafka topic `lifecycle.transitions` (via `stream_keys.py`)
- The writer service itself
- Systemd unit

---

### P2.3: Kafka Topic

**Topic:** `lifecycle.transitions` (constructed via `topic_lifecycle_transitions()` in `stream_keys.py`)
**Config:** compacted (for checkpoint recovery), 7-day retention

**Transition event schema:**

```json
{
  "transition_type": "activation|exit|chandelier_update|mae_mfe_update|shadow_outcome",
  "signal_id": "uuid",
  "symbol": "BTCUSD",
  "timeframe": "1m",
  "bar_ts": "2026-04-10T04:02:00Z",
  "data": { ... }  // type-specific payload
}
```

**Transition data payloads:**

`activation`:
```json
{
  "activation_ts": "...",
  "activation_price": 67234.50,
  "bars_pending": 5
}
```

`exit`:
```json
{
  "exit_ts": "...",
  "exit_price": 67100.00,
  "exit_reason": "target_hit",
  "outcome": "target_1_hit",
  "pnl_r": 2.3,
  "mae": -0.5,
  "mfe": 2.5,
  "bars_held": 12
}
```

`chandelier_update`:
```json
{
  "trailing_stop": 66800.00,
  "chandelier_history": [...]
}
```

`mae_mfe_update`:
```json
{
  "mae": -0.3,
  "mfe": 1.8,
  "current_price": 67200.00
}
```

`shadow_outcome`:
```json
{
  "shadow_outcome": "would_have_stopped_out",
  "shadow_mae": -1.2,
  "shadow_mfe": 0.3
}
```

---

### P2.4: Migration Plan

1. Create new Kafka topic `lifecycle.transitions`
2. Create `services/signal_tracker_compute.py` — extract compute logic from `signal_tracker_agent.py`
3. Create `services/lifecycle_writer_agent.py` — new WriterAgent consuming transitions
4. Add `topic_lifecycle_transitions()` to `src/core/stream_keys.py`
5. Add transition type enum to `src/intelligence/trading/lifecycle_tracker.py`
6. Create systemd units for both new services
7. Deploy: start lifecycle_writer first (consumer ready), then signal_tracker_compute, then stop old signal_tracker
8. Archive `services/signal_tracker_agent.py` as `_archived_signal_tracker_agent.py`

**No data loss risk:** During switchover, the old tracker's pending transitions drain first. The new ComputeAgent bootstraps from DB, picking up where the old tracker left off.

---

## Gains Summary

| Refinement | Phase | Gain |
|---|---|---|
| Decompression limit → 0 | P1 | Unblocks tracker for 3 futures symbols |
| Disable signal_ledger compression | P1 | Eliminates decompression overhead on all writes |
| Expire orphaned signals | P1 | Clears 135K unprocessable pending signals |
| Batch bar consumption (`getmany`) | P2 | Process N bars per iteration instead of 1 |
| Periodic Kafka commits | P2 | Removes per-bar commit round-trip |
| Compute/persistence separation | P2 | Compute never waits on DB writes |
| Chandelier through writer | P2 | Eliminates per-bar, per-signal DB writes |
| Bootstrap once (not every 60s) | P2 | Eliminates N DB queries every 60 seconds |
| Checkpoint to Kafka | P2 | Restart recovery without DB queries |

## Out of Scope

- Intelligence pipeline throughput optimization (deferred — self-draining at 4.5 bars/sec, big refactor needed for 5000 symbols)
- Historical backfill for equity/crypto feature gaps
- HMM fallback investigation (NC-1)
- IBKR provider log noise (NC-2)
