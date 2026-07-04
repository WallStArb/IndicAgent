# Signal Lifecycle Hardening — Design Spec

**Date:** 2026-05-08  
**Status:** Approved for planning  
**Branch:** feat/signal-lifecycle-hardening

---

## Problem Statement

The signal lifecycle subsystem has accumulated six structural defects over months of patched fixes. The compounding effect: incomplete outcome labels in `signal_ledger`, contaminated ML training data, and a tracker that violates its own ComputeAgent contract. The symptoms (zombie signals, pipeline catch-up floods, bootstrap gaps) are all downstream of the same root causes.

**Root causes:**
1. Publisher ships `timestamp=""` — all timestamp inference is consumer-side guesswork
2. Three divergent signal loading paths (Kafka, DB bootstrap, D-02 restore) with different field sets — edge cases guaranteed
3. `SignalTrackerComputeAgent` writes to DB on startup (D-03 sweep) — architectural contract violation
4. D-05 gate discards training data based on a heuristic
5. No `is_backfill` provenance — tracker cannot distinguish live from catch-up signals
6. `signal_ledger` missing `ttl_bars` and `is_backfill` columns — replay cannot compute correct evaluation windows

**Consequence:** signals fired during pipeline catch-up get wrong outcome labels or no labels at all. The training set is not trustworthy.

---

## Design Principles Applied

- **Never drop data that could contain signal** — D-05 deleted, replay auditor recovers all outcomes
- **Data quality over model complexity** — clean training labels beat a smarter model on dirty data
- **Instrument everything** — every component has Prometheus counters; `signal_replay_unresolved_gauge` is the north star
- **Let the system run** — no manual intervention after initial replay trigger; self-healing by design
- **Separation of concerns** — ComputeAgent computes, AuditorAgent audits, WriterAgent writes; no exceptions

---

## Architecture: What Changes

```
BEFORE
intelligence_pipeline_agent
  → intelligence.i7.signals  { timestamp="", no is_backfill, ttl_bars missing }

signal_tracker_compute_agent
  D-03 sweep  →  DB write on startup (CONTRACT VIOLATION)
  bootstrap   →  SELECT missing ttl_bars, signal_schema_version, garch_sigma_at_fire, hmm_regime_at_fire
  kafka path  →  consumer-side timestamp/tf/symbol normalization (compensating for publisher)
  D-05 gate   →  discards training data

signal_ledger  (no is_backfill, no ttl_bars columns)
No recovery mechanism for missed outcomes.


AFTER
intelligence_pipeline_agent
  → intelligence.i7.signals  { timestamp=bar_ts, is_backfill computed, ttl_bars, signal_schema_version }

signal_tracker_compute_agent  (zero DB writes — contract restored)
  _load_signal(raw)  ←  single canonical function, both sources
  bootstrap path  →  full SELECT → _load_signal()
  kafka path      →  _ingest_i7_payload() → _load_signal()
  is_backfill fast-path: TTL elapsed at ingest → TTL-expired transition, never enters active index

signal_replay_auditor_agent  (NEW, L9)
  every 5 min: signals where exit_at IS NULL AND TTL elapsed AND signal_schema_version='v1'
  → market_data_ohlcv bars → evaluate_signal() + evaluate_market_entry() bar-by-bar
  → lifecycle.transitions → lifecycle_writer (idempotent write)

bar_replay_provider_agent  (NEW, L1)
  one-shot: reads market_data_ohlcv → publishes to market.bars + market.bars.htf
  rate-limited to pipeline throughput; checkpoint-based; self-terminating at NOW()

signal_ledger  (+ is_backfill BOOLEAN NOT NULL DEFAULT FALSE)
               (+ ttl_bars INTEGER NOT NULL DEFAULT 10)
```

**DAG additions:**
- L1: `bar_replay_provider` (one-shot, alongside `ibkr-provider`)
- L9: `signal_replay_auditor` (periodic, alongside `signal_auditor`)

---

## Section 1 — Canonical `SignalRecord`: `_load_signal()`

Single function in `signal_tracker_compute_agent.py`. All sources route through it. Returns canonical dict or `None` (→ DLQ). No source-specific branching downstream.

**Required fields enforced:**

| Field | Type | Reject if |
|---|---|---|
| `signal_id` | `str` | missing |
| `symbol`, `timeframe` | `str` | empty |
| `timestamp` | `datetime` UTC | `None` or `""` → DLQ |
| `entry_price`, `stop_loss` | `float` | missing |
| `is_backfill` | `bool` | default `False` |
| `ttl_bars` | `int` | default `10` |
| `signal_schema_version` | `str` | default `"v0"` |
| `status` | `str` | default `"pending"` |
| `direction` | `int` | default `1` |
| `targets` | `list[float]` | default `[]` |
| `entry_zone_low/high` | `float` | default `entry_price` |
| `market_entry_price` | `float\|None` | optional |
| `activated_at` | `datetime\|None` | bootstrap only |
| `garch_sigma_at_fire`, `hmm_regime_at_fire` | optional | staleness tracking |

`timestamp=None` or `""` is a hard reject routed to DLQ with counter increment. The publisher must provide it; the consumer never infers it.

---

## Section 2 — Publisher Normalization (`intelligence_pipeline_agent.py`)

At publish time, before writing to `intelligence.i7.signals`, inject into each signal dict:

```python
tf_secs = TF_SECONDS.get(tf, 60)
is_backfill = (computed_at - bar_ts).total_seconds() > tf_secs

for sig in signals:
    sig["timestamp"] = bar_ts          # always bar_ts, never ""
    sig["is_backfill"] = is_backfill   # computed once at payload level
```

`is_backfill=True` when signal is published more than one full bar period after the bar closed. Normal live processing (sub-second): `False`. Pipeline catch-up on backlog: `True`.

`ttl_bars` and `signal_schema_version` must be present in each signal dict from `make_signal_from_frame()`. If absent, `_load_signal()` applies defaults and increments the invalid counter.

---

## Section 3 — Tracker: Unified Intake + Backfill Fast-Path

**New intake decision tree in `_ingest_signal(canonical)`:**

```
signal arrives → _load_signal() → canonical dict or None (DLQ)
│
├─ already in _signal_ids → deduplicate, skip
│
├─ is_backfill=True AND bars_elapsed >= ttl_bars
│    → publish TTL-expired LifecycleTransition immediately
│    → increment backfill_fast_path counter
│    → never enters active index
│
├─ is_backfill=True AND bars_elapsed < ttl_bars
│    → still has valid window, may activate on live bars
│    → active index (normal evaluation path)
│
└─ is_backfill=False
     → active index (normal evaluation path)
```

**Bootstrap SELECT gains:** `ttl_bars`, `signal_schema_version`, `garch_sigma_at_fire`, `hmm_regime_at_fire`, `is_backfill`.

Bootstrap feeds `_load_signal()` same as Kafka path. Zero divergence.

---

## Section 4 — Two-Path Outcome Guarantee

**Path 1: Live tracker** — real-time, bar-by-bar. Correct for live signals. May miss signals during catch-up or restart.

**Path 2: `SignalReplayAuditorAgent`** — runs every 5 minutes. Catches everything the live path missed.

**Query (replay auditor each cycle):**
```sql
SELECT * FROM signal_ledger
WHERE exit_at IS NULL
  AND signal_schema_version = 'v1'
  AND timestamp < NOW() - INTERVAL '2 minutes'
```
Then per row: if `(NOW() - timestamp).total_seconds() <= ttl_bars * tf_seconds` → skip (live tracker may still hold it). Otherwise → replay.

**Replay per signal:**
1. Query `market_data_ohlcv` for `(symbol, timeframe)` bars in `[timestamp, timestamp + ttl_bars × tf_seconds]` ordered `ASC`
2. If zero bars found → increment `signal_replay_ohlcv_gap_total`, skip
3. Replay `evaluate_signal()` bar-by-bar with full state (MAE/MFE, chandelier HH/LL accumulated)
4. Replay `evaluate_market_entry()` with same bars (independent track)
5. Publish `LifecycleTransition` events to `lifecycle.transitions`

**`LifecycleWriterAgent` idempotency:** all EXIT updates use `WHERE signal_id = $1 AND exit_at IS NULL`. First writer wins; second is no-op. This is the safety contract enabling both paths to run without coordination.

**Staleness tracking in replay:** simplified — no per-bar HMM/GARCH from OHLCV. `condition_expired` exits not computed during replay; TTL covers these cases. Future phase can add `intelligence_features` JOIN for full staleness replay.

**What replay recovers:**

| Signal state | Zone track | Market entry track |
|---|---|---|
| `is_backfill=True`, TTL elapsed at ingest | TTL-expired (fast-path) | Replayed from OHLCV |
| `is_backfill=True`, TTL remaining | Live bars going forward | Live bars going forward |
| Live tracker missed (restart) | Replayed from OHLCV | Replayed from OHLCV |
| Live (normal) | Correct real-time | Correct real-time |

After this phase: every `signal_schema_version='v1'` signal has `exit_at` and `outcome` populated. `signal_replay_unresolved_gauge = 0` is the health invariant.

---

## Section 5 — `BarReplayProviderAgent` + DB Migration

### `BarReplayProviderAgent`

**Purpose:** feed historical OHLCV bars through the existing pipeline to regenerate signals after truncation.

- **Concept:** `bar_replay` | **Class:** `BarReplayProviderAgent` | **File:** `services/bar_replay_provider_agent.py` | **Unit:** `indicagent-bar-replay.service`
- Reads ALL timeframes from `market_data_ohlcv` in chronological order
- Routes: `timeframe='1m'` → `market.bars`; HTF → `market.bars.htf` (no recompute — data already correct in DB)
- Ordering: same-timestamp bars published smallest TF first (1m before 5m before 15m) so pipeline indicator state is current before HTF bar arrives
- Rate-limited to pipeline throughput (configurable, default ~10 bars/sec)
- Checkpoint: persists `last_replayed_ts` to `cache/bar_replay_checkpoint.json` — survives restart, auto-resumes
- Self-terminating: exits cleanly when `last_replayed_ts >= NOW() - 5 minutes`
- `ExecStopPost`: restarts `ibkr-provider` and `bar-aggregator` automatically on clean exit

```sql
SELECT symbol, timeframe, timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE timestamp > $last_checkpoint
ORDER BY timestamp ASC,
  CASE timeframe
    WHEN '1m' THEN 1 WHEN '5m' THEN 5 WHEN '15m' THEN 15
    WHEN '1h' THEN 60 WHEN '4h' THEN 240 WHEN '1d' THEN 1440
  END ASC
LIMIT 1000
```

Kafka 1-day retention handles cleanup — bars are consumed by the pipeline almost immediately at replay rate; no accumulation.

### DB Migration (clean start — no backward compatibility)

```sql
-- Wipe contaminated v0 history
TRUNCATE TABLE signal_ledger;

-- Add missing columns
ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS is_backfill BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS ttl_bars    INTEGER NOT NULL DEFAULT 10;
-- signal_schema_version already exists (Phase-79)
```

### Operational replay procedure

```bash
# Stop live ingestion and HTF recompute (not needed during replay)
sudo systemctl stop indicagent-ibkr-provider indicagent-bar-aggregator

# Apply migration
docker exec timescaledb psql -U postgres -d indicagent -f migration.sql

# Start replay — pipeline regenerates signals automatically
sudo systemctl start indicagent-bar-replay
# bar-replay exits when caught up → ExecStopPost restarts ibkr-provider + bar-aggregator
```

Zero manual steps after trigger. `SignalReplayAuditorAgent` (already running) fills in outcomes as signals accumulate.

---

## Section 6 — Metrics & Alerting (DAG-correct placement)

| Metric | Type | Layer | Agent | Meaning |
|---|---|---|---|---|
| `intelligence_pipeline_backfill_signals_total` | counter | L5 | intelligence_pipeline | Signals published with `is_backfill=True`; 0 in normal ops |
| `signal_tracker_backfill_fast_path_total` | counter | L6 | signal_tracker_compute | Expired backfill signals fast-pathed at ingest |
| `signal_tracker_invalid_signal_total` | counter | L6 | signal_tracker_compute | Signals rejected by `_load_signal()` → DLQ |
| `lifecycle_writer_idempotent_skip_total` | counter | L6 | lifecycle_writer | Second EXIT blocked by idempotency guard; validates two-path safety |
| `signal_ledger_backfill_ratio` | gauge | L8 | signal_metrics_compute | `is_backfill=TRUE / total` last 24h; training set quality KPI |
| `signal_replay_unresolved_gauge` | gauge | L9 | signal_replay_auditor | **North star:** signals with `exit_at IS NULL` past TTL; target = 0 |
| `signal_replay_attempted_total` | counter | L9 | signal_replay_auditor | Signals queried for replay each cycle |
| `signal_replay_resolved_total` | counter | L9 | signal_replay_auditor | Outcomes successfully computed |
| `signal_replay_ohlcv_gap_total` | counter | L9 | signal_replay_auditor | OHLCV data missing for signal window |
| `bar_replay_provider_bars_published_total` | counter | L1 | bar_replay_provider | Progress tracking |
| `bar_replay_provider_lag_seconds` | gauge | L1 | bar_replay_provider | Distance from NOW(); drops to 0 on completion |

**Alerts:**
- `signal_tracker_invalid_signal_total > 0` sustained 5 min → publisher bug → page
- `signal_replay_ohlcv_gap_total > 10` sustained → data integrity issue in `market_data_ohlcv`
- `signal_replay_unresolved_gauge` growing for 2 consecutive cycles → replay auditor stuck → page
- `lifecycle_writer_idempotent_skip_total > 100/hour` → investigate two-path collision rate

---

## Section 7 — Code Deleted

`SignalTrackerComputeAgent` becomes a true ComputeAgent: zero DB writes, zero DB reads after bootstrap.

| Code | Location | Reason |
|---|---|---|
| `"timestamp": ""` | `intelligence_pipeline_agent.py` | Root cause fixed at publisher |
| **D-03 bootstrap DB sweep** | `signal_tracker_compute_agent.py` | **Architectural violation:** ComputeAgent writing DB; writes wrong outcomes (no OHLCV lookup); replaced by `SignalReplayAuditorAgent` |
| **D-05 activation probability gate** | `signal_tracker_compute_agent.py` | Discards training data based on heuristic; backfill fast-path makes it unnecessary |
| Consumer-side `bar_ts→timestamp` normalization | `signal_tracker_compute_agent.py` | Publisher owns this |
| Consumer-side `symbol`/`tf` fallback | `signal_tracker_compute_agent.py` | Publisher guarantees these fields |
| Separate bootstrap signal construction | `signal_tracker_compute_agent.py` | Replaced by `_load_signal()` |
| D-02 compensating logic | `lifecycle_tracker.py` | Bootstrap now correct; keep violation **counter** as assertion |
| Workaround-documenting comment blocks | throughout | Root causes gone; comments become lies |

---

## Section 8 — Testing

### Unit tests (`tests/unit/`)

| Test | Verifies |
|---|---|
| `test__load_signal_canonical` | all fields normalized from both source shapes |
| `test__load_signal_rejects_empty_timestamp` | `timestamp=""` → `None` → DLQ counter |
| `test__load_signal_bootstrap_kafka_identical` | bootstrap row and Kafka payload → byte-identical canonical dict (three-path regression) |
| `test_backfill_fast_path_expired` | `is_backfill=True` + TTL elapsed → transition published, no active index entry |
| `test_backfill_carried_forward` | `is_backfill=True` + TTL remaining → active index |
| `test_publisher_is_backfill_computed` | within/outside `tf_seconds` window → correct flag |
| `test_replay_outcome_parametric` | **all 8 outcome types × long/short** — known bar sequence → correct outcome + pnl_r |
| `test_replay_both_tracks_independent` | `never_activated` zone track + market entry resolves correctly with pnl_r |
| `test_replay_skips_v0_signals` | v0 signal with `exit_at IS NULL` → skipped, stays unresolved |
| `test_replay_skips_ttl_not_elapsed` | signal within TTL window → not touched this cycle |
| `test_replay_ohlcv_gap_counter` | no OHLCV bars found → counter increments, signal skipped |
| `test_bar_replay_topic_routing` | `1m` → `market.bars`; `15m` → `market.bars.htf` |
| `test_bar_replay_ordering` | same timestamp: 1m published before 5m before 1h |
| `test_bar_replay_checkpoint_resume` | interrupt mid-replay, restart → continues from checkpoint |
| `test_d02_violation_counter` | `activated_at` + `status=PENDING` → counter increments |
| `test_compute_agent_no_db_writes` | `SignalTrackerComputeAgent` has no reachable DB write path |

### Integration tests (`tests/integration/`)

| Test | Verifies |
|---|---|
| `test_lifecycle_writer_idempotency_counter` | second EXIT transition → skip counter increments, DB row unchanged |
| `test_is_backfill_roundtrip` | published `is_backfill=True` → written to DB → ML filter `WHERE is_backfill=FALSE` excludes it |
| `test_all_signals_resolved` | N signals + known OHLCV bars → replay auditor cycle → `COUNT(*) WHERE exit_at IS NULL = 0` |
| `test_market_entry_completeness` | every signal with `market_entry_price` gets `market_entry_outcome` after replay |

`test_all_signals_resolved` and `test_replay_outcome_parametric` are the north star tests. If both pass, the training set is correct.

---

## New Services Summary

| Service | Concept | Class | Unit | DAG Layer | Role |
|---|---|---|---|---|---|
| `bar_replay_provider_agent.py` | `bar_replay` | `BarReplayProviderAgent` | `indicagent-bar-replay.service` | L1 | One-shot OHLCV→Kafka replay |
| `signal_replay_auditor_agent.py` | `signal_replay` | `SignalReplayAuditorAgent` | `indicagent-signal-replay.service` | L9 | Periodic outcome recovery |

Both must be added to `_DAG_ORDER` in `service_auditor_agent.py`.

---

## What Simons Gets

After this phase ships and the replay completes:
- `signal_replay_unresolved_gauge = 0` — every v1 signal has a complete, correct outcome
- `WHERE signal_schema_version='v1' AND is_backfill=FALSE` — clean training set, provably correct
- `WHERE signal_schema_version='v1'` — all recoverable outcomes including catch-up signals
- Zero manual intervention going forward — self-healing by design
- `SignalTrackerComputeAgent` contract restored — pure compute, zero DB side effects
