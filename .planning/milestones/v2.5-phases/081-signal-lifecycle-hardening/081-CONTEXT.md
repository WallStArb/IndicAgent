# Phase 81: Signal Lifecycle Hardening — Context

**Gathered:** 2026-05-08
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-05-08-signal-lifecycle-hardening-design.md)

<domain>
## Phase Boundary

This phase eliminates six structural defects in the signal lifecycle subsystem that cause wrong/missing outcome labels in `signal_ledger` and contaminated ML training data. Two new services are added (`BarReplayProviderAgent`, `SignalReplayAuditorAgent`), the publisher is fixed to stamp real timestamps, `SignalTrackerComputeAgent` is restored to a pure compute contract (zero DB writes), and a DB migration cleans the signal_ledger for a fresh start. After this phase: `signal_replay_unresolved_gauge=0` permanently; every v1 signal has a complete outcome.

</domain>

<decisions>
## Implementation Decisions

### D-01: Publisher Normalization (intelligence_pipeline_agent.py)
At publish time, before writing to `intelligence.i7.signals`, inject into each signal dict:
```python
tf_secs = TF_SECONDS.get(tf, 60)
is_backfill = (computed_at - bar_ts).total_seconds() > tf_secs
for sig in signals:
    sig["timestamp"] = bar_ts          # always bar_ts, never ""
    sig["is_backfill"] = is_backfill
```
`TF_SECONDS` dict maps timeframe string → seconds. `is_backfill` computed once at payload level. `ttl_bars` and `signal_schema_version` must already be present in signal dict from `make_signal_from_frame()`.

### D-02: `_load_signal(raw)` — Single Canonical Intake Function
Located in `signal_tracker_compute_agent.py`. Both bootstrap (DB SELECT) and Kafka paths route through it. Returns canonical dict or `None` (→ DLQ). Required fields:

| Field | Type | Reject if |
|---|---|---|
| `signal_id` | str | missing |
| `symbol`, `timeframe` | str | empty |
| `timestamp` | datetime UTC | None or "" → DLQ |
| `entry_price`, `stop_loss` | float | missing |
| `is_backfill` | bool | default False |
| `ttl_bars` | int | default 10 |
| `signal_schema_version` | str | default "v0" |
| `status` | str | default "pending" |
| `direction` | int | default 1 |
| `targets` | list[float] | default [] |
| `entry_zone_low/high` | float | default entry_price |
| `market_entry_price` | float\|None | optional |
| `activated_at` | datetime\|None | bootstrap only |
| `garch_sigma_at_fire`, `hmm_regime_at_fire` | optional | staleness tracking |

`timestamp=None` or `""` → hard reject → DLQ → counter increment. Publisher must provide it; consumer never infers it.

### D-03: Backfill Fast-Path in `_ingest_signal(canonical)`
```
signal arrives → _load_signal() → canonical dict or None (DLQ)
├─ already in _signal_ids → deduplicate, skip
├─ is_backfill=True AND bars_elapsed >= ttl_bars
│    → publish TTL-expired LifecycleTransition immediately
│    → increment backfill_fast_path counter
│    → never enters active index
├─ is_backfill=True AND bars_elapsed < ttl_bars
│    → active index (normal evaluation path)
└─ is_backfill=False
     → active index (normal evaluation path)
```
`bars_elapsed = int((now - signal.timestamp).total_seconds() / TF_SECONDS[timeframe])` — clock-based, no DB read.

### D-04: Bootstrap SELECT Gains
Bootstrap SELECT must include: `ttl_bars`, `signal_schema_version`, `garch_sigma_at_fire`, `hmm_regime_at_fire`, `is_backfill`. Bootstrap feeds `_load_signal()` same as Kafka path — zero divergence.

### D-05: Code Deleted from SignalTrackerComputeAgent
- `"timestamp": ""` in `intelligence_pipeline_agent.py` — fixed at publisher
- D-03 bootstrap DB sweep — architectural violation; replaced by `SignalReplayAuditorAgent`
- D-05 activation probability gate — discards training data; backfill fast-path makes unnecessary
- Consumer-side `bar_ts→timestamp` normalization — publisher owns this
- Consumer-side `symbol`/`tf` fallback — publisher guarantees these
- Separate bootstrap signal construction — replaced by `_load_signal()`
- D-02 compensating logic in `lifecycle_tracker.py` — keep violation **counter** as assertion, remove workaround
- Workaround-documenting comment blocks

### D-06: SignalReplayAuditorAgent (NEW, L9)
**Concept:** `signal_replay` | **Class:** `SignalReplayAuditorAgent` | **File:** `services/signal_replay_auditor_agent.py` | **Unit:** `indicagent-signal-replay.service`

Runs every 5 minutes. Query:
```sql
SELECT * FROM signal_ledger
WHERE exit_at IS NULL
  AND signal_schema_version = 'v1'
  AND timestamp < NOW() - INTERVAL '2 minutes'
```
Per row: if `(NOW() - timestamp).total_seconds() <= ttl_bars * tf_seconds` → skip (live tracker may still hold it). Otherwise → replay.

Replay per signal:
1. Query `market_data_ohlcv` for `(symbol, timeframe)` bars in `[timestamp, timestamp + ttl_bars × tf_seconds]` ASC
2. If zero bars → increment `signal_replay_ohlcv_gap_total`, skip
3. Replay `evaluate_signal()` bar-by-bar (MAE/MFE, chandelier HH/LL accumulated)
4. Replay `evaluate_market_entry()` with same bars (independent track)
5. Publish `LifecycleTransition` events to `lifecycle.transitions`

**`LifecycleWriterAgent` idempotency:** all EXIT updates use `WHERE signal_id = $1 AND exit_at IS NULL`. First writer wins; second is no-op.

Staleness note: simplified replay — no per-bar HMM/GARCH from OHLCV; `condition_expired` exits not computed during replay; TTL covers these cases.

### D-07: BarReplayProviderAgent (NEW, L1)
**Concept:** `bar_replay` | **Class:** `BarReplayProviderAgent` | **File:** `services/bar_replay_provider_agent.py` | **Unit:** `indicagent-bar-replay.service`

Reads ALL timeframes from `market_data_ohlcv` in chronological order. Routes: `timeframe='1m'` → `market.bars`; HTF → `market.bars.htf`. Ordering: same-timestamp bars published smallest TF first (1m before 5m before 15m). Rate-limited (default ~10 bars/sec). Checkpoint: `cache/bar_replay_checkpoint.json`. Self-terminating at `last_replayed_ts >= NOW() - 5 minutes`. `ExecStopPost` restarts `ibkr-provider` + `bar-aggregator` on clean exit.

Query:
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

### D-08: DB Migration (Clean Start)
```sql
TRUNCATE TABLE signal_ledger;
ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS is_backfill BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS ttl_bars    INTEGER NOT NULL DEFAULT 10;
```
`signal_schema_version` already exists (Phase 79). No backward compatibility — v0 data is contaminated and not recoverable.

### D-09: Metrics (11 total)
| Metric | Type | Agent |
|---|---|---|
| `intelligence_pipeline_backfill_signals_total` | counter | intelligence_pipeline |
| `signal_tracker_backfill_fast_path_total` | counter | signal_tracker_compute |
| `signal_tracker_invalid_signal_total` | counter | signal_tracker_compute |
| `lifecycle_writer_idempotent_skip_total` | counter | lifecycle_writer |
| `signal_ledger_backfill_ratio` | gauge | signal_metrics_compute |
| `signal_replay_unresolved_gauge` | gauge | signal_replay_auditor |
| `signal_replay_attempted_total` | counter | signal_replay_auditor |
| `signal_replay_resolved_total` | counter | signal_replay_auditor |
| `signal_replay_ohlcv_gap_total` | counter | signal_replay_auditor |
| `bar_replay_provider_bars_published_total` | counter | bar_replay_provider |
| `bar_replay_provider_lag_seconds` | gauge | bar_replay_provider |

Alerts: `signal_tracker_invalid_signal_total > 0` sustained 5 min → page; `signal_replay_ohlcv_gap_total > 10` sustained → page; `signal_replay_unresolved_gauge` growing 2 consecutive cycles → page; `lifecycle_writer_idempotent_skip_total > 100/hour` → investigate.

### D-10: DAG Registration
Both new services added to `_DAG_ORDER` in `service_auditor_agent.py`:
- L1: `bar-replay` (one-shot, alongside `ibkr-provider`)
- L9: `signal-replay` (periodic, alongside `signal-auditor`)

### Claude's Discretion
- Exact systemd unit file structure (follow existing service unit patterns)
- `evaluate_signal()` and `evaluate_market_entry()` — reuse existing implementations from `lifecycle_tracker.py`; do not duplicate
- `LifecycleTransition` schema — reuse existing schema; replay path produces identical event structure to live path
- Exact batch size and rate-limit knobs for `BarReplayProviderAgent`
- Where `TF_SECONDS` dict lives (likely `src/core/stream_keys.py` or inline in each file)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Spec (primary reference)
- `docs/plans/2026-05-08-signal-lifecycle-hardening-design.md` — Full architectural spec with all sections

### Files to Modify
- `services/signal_tracker_compute_agent.py` — Primary target: add `_load_signal()`, remove D-03/D-05, backfill fast-path
- `src/api/routes/sse.py` — Likely no change; reference for LifecycleTransition consumption
- `services/lifecycle_tracker.py` — Remove D-02 compensating logic, keep violation counter
- `services/lifecycle_writer_agent.py` — Verify idempotency guard (`WHERE exit_at IS NULL`) exists
- `services/intelligence_pipeline_agent.py` — Publisher normalization (D-01)
- `services/service_auditor_agent.py` — Add both new services to `_DAG_ORDER`

### New Files to Create
- `services/signal_replay_auditor_agent.py` — SignalReplayAuditorAgent (L9)
- `services/bar_replay_provider_agent.py` — BarReplayProviderAgent (L1)
- `/etc/systemd/system/indicagent-signal-replay.service` — systemd unit
- `/etc/systemd/system/indicagent-bar-replay.service` — systemd unit

### Key Patterns (read before implementing)
- `services/signal_auditor_agent.py` — Closest analog to SignalReplayAuditorAgent (L9 periodic auditor)
- `services/ibkr_provider_agent.py` or `services/bar_aggregator_compute_agent.py` — Closest analog to BarReplayProviderAgent (L1 provider)
- `src/core/service_utils.py` — `setup_service_logging()`, timer patterns
- `src/core/stream_keys.py` — All topic constants
- `src/observability/metrics.py` — Metric registration pattern

### Test Patterns
- `tests/unit/` — Existing unit test patterns
- `tests/integration/` — Existing integration test patterns

</canonical_refs>

<specifics>
## Specific Ideas

**North star health invariant:** `signal_replay_unresolved_gauge = 0` — after each replay cycle, zero v1 signals should have `exit_at IS NULL` past TTL.

**Two-path guarantee table:**
| Signal state | Zone track | Market entry track |
|---|---|---|
| `is_backfill=True`, TTL elapsed at ingest | TTL-expired (fast-path) | Replayed from OHLCV |
| `is_backfill=True`, TTL remaining | Live bars going forward | Live bars going forward |
| Live tracker missed (restart) | Replayed from OHLCV | Replayed from OHLCV |
| Live (normal) | Correct real-time | Correct real-time |

**ML training filter after this phase:**
- Clean set: `WHERE signal_schema_version='v1' AND is_backfill=FALSE`
- All recoverable: `WHERE signal_schema_version='v1'`

**Operational replay procedure (post-migration):**
```bash
sudo systemctl stop indicagent-ibkr-provider indicagent-bar-aggregator
docker exec timescaledb psql -U postgres -d indicagent -f migration.sql
sudo systemctl start indicagent-bar-replay
# bar-replay exits when caught up → ExecStopPost restarts ibkr-provider + bar-aggregator
```

</specifics>

<deferred>
## Deferred Ideas

- Full staleness replay (per-bar HMM/GARCH from `intelligence_features` JOIN) — future phase; TTL covers these cases for now
- `bar_replay_provider` rate-limit auto-tuning based on pipeline lag — manual knob sufficient for now

</deferred>

---

*Phase: 081-signal-lifecycle-hardening*
*Context gathered: 2026-05-08 via PRD Express Path*
