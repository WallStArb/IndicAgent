---
title: Pipeline Health Fixes
status: Approved
priority: P0
scope: Signal tracker compute/persistence separation + operational unblocks
date: 2026-04-10
---

# Pipeline Health Fixes — Design

**Last Updated:** 2026-05-02

Fix the three critical blockers identified in the 2026-04-10 pipeline health audit by applying existing architectural patterns. No new patterns invented.

## Problem

The signal tracker violates the system's DAG architecture. Every other data path follows:

```
ComputeAgent (DB-ignorant) → Kafka topic → WriterAgent (zero compute) → DB
```

The tracker reads from DB, evaluates lifecycle transitions, and writes to DB in the same process with `await` on every transition. This causes:

- 258K bar lag on signal_lifecycle consumer group
- 515K signals stuck at `pending` (zero activations for crypto)
- TimescaleDB decompression errors on every bar for 3 futures symbols
- 65K intelligence pipeline lag (separate issue, self-draining at 4.5 bars/sec)

## Why the Tracker Stays Separate

Signal generation and signal lifecycle are different concerns:

| | Signal Generation | Signal Lifecycle |
|---|---|---|
| **Latency** | Milliseconds (per-bar) | Minutes to days |
| **Concern** | What patterns exist in this bar? | What happened to this business object? |
| **State** | Bounded (warmup windows) | Growing (accumulates with each new signal) |
| **Failure mode** | Miss a signal on this bar | Lose tracking of an active trade setup |
| **Scaling** | More symbols × more plugins | More signals × longer holding periods |

Lifecycle tracking is a TrackerAgent concern, not a ComputeAgent concern. It stays separate from the intelligence pipeline. But it follows the same DAG: compute in-memory, publish to Kafka, writer persists.

## Solution

Two phases: unblock the system (P1), then fix the architectural violation (P2).

Pipeline throughput optimization (P3) is deferred. The pipeline catches up in ~5 hours at current 4.5 bars/sec vs 0.83 bars/sec real-time need. The 5000-symbol refactor will require a fundamentally different architecture — any plugin-level optimization now would be throwaway work.

---

## P1: Unblock (30 minutes)

### P1.1: Set TimescaleDB decompression limit to unlimited

Current `max_tuples_decompressed_per_dml_transaction = 100,000` (was raised from 1,000 but not enough). Tracker UPDATE queries hit compressed chunks and exceed the limit for NQM6, RTYM6, ESM6.

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

SELECT decompress_chunk(chunk_schema || '.' || chunk_name)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'signal_ledger'
  AND is_compressed = true;
```

3.7M rows at ~104KB compressed — uncompressed size is still small. Storage cost is negligible.

### P1.3: Expire orphaned pre-restart signals

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

```bash
sudo systemctl restart indicagent-signal-tracker
```

**Verification:** Zero new decompression errors. Lag starts decreasing.

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
- `await`s individual DB writes per transition
- Commits Kafka after every bar
- Processes ALL bars even for symbols with zero active signals

### Target Architecture (follows DAG)

```
market.bars ──────────────────────────────┐
market.bars.htf ──────────────────────────┤
                                          ↓
                           signal_tracker_compute
                           (TrackerAgent, DB-ignorant)
                           ├─ symbol filter (skip ~70% of bars)
                           ├─ timeframe filter (1m signals ↔ 1m bars)
                           ├─ batch consume (getmany)
                           └─ transitions → Kafka
                                          │
                                          ↓
                             lifecycle.transitions
                             (Kafka topic, 7-day retention)
                                          │
                                          ↓
                          lifecycle_writer_agent
                          (WriterAgent, zero compute, batch persist)
                                          │
                                          ↓
                                  signal_ledger
```

Same DAG pattern as:
- `intelligence_pipeline` → `intelligence.journal` → `feature_writer` → `intelligence_features`
- `intelligence_pipeline` → `intelligence.i7.signals` → `signal_writer` → `signal_ledger`

---

### P2.1: Signal Tracker ComputeAgent

**File:** `services/signal_tracker_compute.py`
**Unit:** `indicagent-signal-tracker-compute`
**Consumer group:** `signal_tracker_compute` (new, starts fresh)
**Metrics port:** :9127

**Responsibilities:**
- Consume bars from `market.bars` + `market.bars.htf`
- Filter to symbols with active/pending signals (~70% of bars skipped)
- Evaluate lifecycle transitions via existing `evaluate_signal()` logic
- Publish transition events to `lifecycle.transitions` Kafka topic

**Compute layer design:**

```
getmany(max_records=100, timeout=1.0)
       ↓
for each bar:
    if symbol not in _active_signal_index: SKIP   ← ~70% of bars skipped here
    filter signals by timeframe matching bar        ← 1m signals only on 1m bars
    evaluate_signal() per signal (pure function, unchanged)
    collect transitions
       ↓
publish all transitions to lifecycle.transitions
       ↓
commit Kafka offsets (per batch, not per bar)
```

**Symbol filtering:** Maintain an in-memory set `_active_symbols` populated from the signal index. On each bar, check `if bar.symbol not in _active_symbols: continue`. This is O(1) per bar and skips ~70% of processing.

**Timeframe filtering:** When processing a bar from `market.bars` (1m), only evaluate signals with `timeframe='1m'`. When processing from `market.bars.htf`, match the bar's timeframe to signal timeframes. Don't cross-evaluate.

**State management:**

Bootstrap: On startup, single DB query loads all active signals:
```sql
SELECT * FROM signal_ledger
WHERE status IN ('pending', 'active', 'regime_suppressed');
```

Signal ingestion: Subscribe to `intelligence.i7.signals` Kafka topic (second consumer group). New signals stream into the in-memory index as they're generated. No periodic DB polling.

No checkpointing. On restart: bootstrap from DB + resume Kafka offsets. Signal evaluation is idempotent — double-processing a bar produces the same result (status guards prevent double transitions).

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
- Batch bar consumption (`getmany`)
- Periodic Kafka commits
- Symbol filtering (skip irrelevant bars)
- Timeframe filtering (match bar TF to signal TF)

---

### P2.2: Lifecycle WriterAgent

**File:** `services/lifecycle_writer_agent.py`
**Unit:** `indicagent-lifecycle-writer`
**Consumer group:** `lifecycle_writer_group`
**Metrics port:** :9128

**Responsibilities:**
- Consume transition events from `lifecycle.transitions` topic
- Buffer transitions, batch-write to `signal_ledger` via `execute_batch()`
- Zero compute — pure persistence

**Pattern:** Same conventions as `signal_writer_agent.py`:

```python
BATCH_SIZE = 100
FLUSH_INTERVAL_SECS = 5.0
MAX_BUFFER_SIZE = 10_000
```

**Batch SQL by transition type:** Group buffered transitions by type before flushing. One `execute_batch()` call per type per flush cycle (5 types max), instead of one per signal.

**Transition types:**
- `activation` — signal pending → active
- `exit` — signal active → expired/stopped_out/target_hit
- `chandelier_update` — trailing stop state change
- `mae_mfe_update` — max adverse/favorable excursion update
- `shadow_outcome` — regime_suppressed signal outcome

**What stays the same:**
- Repository methods in `SignalLedgerRepository`
- All DB schema and column names

---

### P2.3: Kafka Topic

**Topic:** `lifecycle.transitions` via `topic_lifecycle_transitions()` in `stream_keys.py`
**Config:** Standard 7-day retention. No compaction needed — transitions are consumed within seconds and persisted to DB.

**Transition event schema:**

```json
{
  "transition_type": "activation|exit|chandelier_update|mae_mfe_update|shadow_outcome",
  "signal_id": "uuid",
  "symbol": "BTCUSD",
  "timeframe": "1m",
  "bar_ts": "2026-04-10T04:02:00Z",
  "data": { ... }
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

1. Create Kafka topic `lifecycle.transitions`
2. Create `services/signal_tracker_compute.py` — extract compute logic from `signal_tracker_agent.py`
3. Create `services/lifecycle_writer_agent.py` — new WriterAgent
4. Add `topic_lifecycle_transitions()` to `src/core/stream_keys.py`
5. Add transition type enum to `src/intelligence/trading/lifecycle_tracker.py`
6. Create systemd units for both new services
7. Deploy: start lifecycle_writer first, then signal_tracker_compute, then stop old signal_tracker
8. Archive `services/signal_tracker_agent.py` → `_archived_signal_tracker_agent.py`

**No data loss risk:** Old tracker drains pending transitions first. New ComputeAgent bootstraps from DB, picks up where old tracker left off. Signal evaluation is idempotent.

---

## Gains Summary

| Refinement | Phase | Gain |
|---|---|---|
| Decompression limit → 0 | P1 | Unblocks tracker for 3 futures symbols |
| Disable signal_ledger compression | P1 | Eliminates decompression overhead on all writes |
| Expire orphaned signals | P1 | Clears 135K unprocessable pending signals |
| Symbol filtering | P2 | Skip ~70% of bars (symbols with no active signals) |
| Timeframe filtering | P2 | No cross-TF evaluation (1m signals on 1m bars only) |
| Batch bar consumption (`getmany`) | P2 | Process N bars per iteration instead of 1 |
| Periodic Kafka commits | P2 | Removes per-bar commit round-trip |
| Compute/persistence separation | P2 | Compute never waits on DB writes |
| Chandelier through writer | P2 | Eliminates per-bar, per-signal DB writes |
| One bootstrap (not every 60s) | P2 | Eliminates N DB queries every 60 seconds |
| Streaming signal ingestion (i7.signals) | P2 | New signals enter tracker immediately via Kafka |
| No checkpointing | P2 | Simpler restart (DB bootstrap + Kafka offsets, idempotent) |
| Batch SQL by transition type | P2 | 5 batch calls per flush instead of N per signal |

## Out of Scope

- Intelligence pipeline throughput optimization (deferred — self-draining, big refactor needed for 5000 symbols)
- Historical backfill for equity/crypto feature gaps
- HMM fallback investigation (NC-1)
- IBKR provider log noise (NC-2)
