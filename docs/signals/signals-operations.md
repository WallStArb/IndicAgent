# Signals Operations — Debugging lifecycle services and signal health

**Version:** 2.8.0 | **Status:** stale (v2.x, see banner) | **Last Updated:** 2026-05-29

---

> **Staleness note (2026-08-01):** This doc covers operating `SignalTracker`,
> `SignalReplayAuditor`, and `SignalMetricsAnalyzer` — all part of the ARCHIVED v2.x signal
> lifecycle system, with no live consumer as of 2026-07-02 per CLAUDE.md. Not yet rewritten for
> v3.0 -- tracked for a future doc pass, not fixed here.

## Purpose

This document covers how to operate and debug the three signal lifecycle services: `SignalTracker`, `SignalReplayAuditor`, and `SignalMetricsAnalyzer`. A new engineer should be able to diagnose orphaned signals, investigate metric anomalies, and understand what is happening during a live debugging session using only this doc.

**Who reads this doc:** Engineers debugging live signal behavior (why didn't this signal activate?), investigating why metrics are stale, or diagnosing mismatches between signals fired and outcomes recorded.

---

## Design Principles

### Why three separate services?

Each service owns a different part of the signal lifecycle problem:

| Service | Owns | Why separate |
|---------|------|-------------|
| `SignalTracker` | Real-time lifecycle evaluation | Must be in the hot bar-processing loop. DB-ignorant — cannot tolerate DB latency. Publishes transitions to Kafka. |
| `SignalReplayAuditor` | Recovering missed outcomes | Runs periodically (every 5 min), reads `market_data_ohlcv`, replays bar-by-bar. DB-aware. Only handles signals the live tracker missed. |
| `SignalMetricsAnalyzer` | Performance metrics computation | Timer-triggered every 15 min. Reads resolved signals, computes per-setup stats. Not in the hot path at all. |

Separating these ensures that a slow metrics computation cycle never delays real-time signal tracking, and a replay auditor query never blocks new transitions from being written.

### Why does signal replay exist?

The live tracker (`SignalTracker`) processes bars in real time. If the service restarts, it bootstraps from `signal_ledger` and picks up pending/active signals. But there is a gap: bars that arrived during the service's downtime are not replayed. Any signal that should have activated or exited during that window will be stuck as `pending`/`active` forever.

`SignalReplayAuditor` solves this by querying all `v1` signals where `exit_at IS NULL` and `expires_at < NOW()`, then replaying each one bar-by-bar against `market_data_ohlcv`. It uses the same `evaluate_signal()` function as the live tracker — identical evaluation logic, no divergence.

North-star health metric: `signal_replay_unresolved_gauge == 0`.

### Two-path safety

Both the live tracker and the replay auditor publish `LifecycleTransition(type=EXIT)` events to the same `lifecycle.transitions` Kafka topic. `LifecycleWriter` uses `WHERE exit_at IS NULL` on all exit writes — the second writer is always a safe no-op. First writer wins. This means there is no risk of double-counting outcomes or corrupting state if both services resolve the same signal.

---

## Architecture: The Service Trio

### SignalTracker

- **Systemd unit:** `indicagent-signal-tracker-compute`
- **Log file:** `logs/signal_tracker_compute_agent.log`
- **Consumes:** `market.bars` (1m), `market.bars.htf` (HTF), `intelligence.i7.signals`
- **Consumer groups:** `signal_tracker_compute` (bars), `signal_tracker_compute_signals` (i7.signals)
- **Produces:** `lifecycle.transitions`
- **State:** All active signal state in memory. Bootstrapped from `signal_ledger_full` at startup.
- **DB access:** Bootstrap read only. Never writes to DB.

The service maintains three data structures per signal:
- `_active_index`: `{(symbol, timeframe): [signal_dict, ...]}` — the signals being tracked
- `_signal_states`: `{signal_id: SignalState}` — per-signal in-memory tracking (MAE/MFE/chandelier/staleness)
- `_active_symbols`: `set[str]` — fast filter to skip bars for symbols with no active signals

On startup, the bootstrap query loads all `pending`/`active` signals from the last 7 days with `exit_at IS NULL`. After bootstrap, new signals are ingested via the `intelligence.i7.signals` consumer in real time — no periodic DB re-seeding.

Bootstrap failure (3 retries with 2/4/8s backoff) publishes a `bootstrap_failed` health event to `health.events` and proceeds with empty state. The replay auditor will recover any signals that were missed.

### SignalReplayAuditor

- **Systemd unit:** `indicagent-signal-replay`
- **Log file:** `logs/signal_replay_auditor_agent.log`
- **Consumes:** DB only (no Kafka input)
- **Produces:** `lifecycle.transitions`
- **Cycle:** Runs every `replay_interval_seconds` (default 300s / 5 min)

Each cycle:
1. Fetches a bounded batch of unresolved signals (expired TTL but `exit_at IS NULL`, `signal_schema_version = 'v1'`).
2. For each signal: fetches the bar window from `market_data_ohlcv`, runs `evaluate_signal()` bar-by-bar.
3. Publishes `EXIT` or `NEVER_ACTIVATED` transition.
4. Also handles a parallel market-entry track if `market_entry_price` was set.
5. Updates `signal_replay_unresolved_gauge`.

Signals with NULL `entry_zone_low` or `entry_zone_high` are skipped (logged as `replay_null_zone_skip`, metric `SIGNAL_REPLAY_NULL_ZONE_TOTAL`). These are DLQ candidates — they should never have reached `signal_ledger` without zone fields.

Signals with no bar data in `market_data_ohlcv` for the signal window emit `SIGNAL_REPLAY_OHLCV_GAP_TOTAL` and are skipped — they remain unresolved until bar data arrives (or indefinitely if data was never collected for that window).

### SignalMetricsAnalyzer

- **Systemd unit:** `indicagent-signal-metrics-compute`
- **Log file:** `logs/signal_metrics_compute_agent.log`
- **Consumes:** DB (`signal_ledger_full` where `outcome IS NOT NULL` and `was_selected = true`)
- **Produces:** `intelligence.signal_metrics` (consumed by `SignalMetricsWriter` → `setup_performance` table)
- **Cycle:** Every 900 seconds (15 minutes)
- **Lookback window:** 90 days of resolved signals

Each cycle:
1. Fetches all resolved signals with `outcome IS NOT NULL`, `exit_at` within 90 days, `was_selected = true`.
2. Runs `validate_signal_row()` for data quality — publishes `metrics_dq_failure` events for new failures (deduped in memory, bootstrapped from `signal_metrics_dq_failures` table).
3. Computes metrics for each (track, setup, timeframe, regime, window_days) group. Windows: 7d, 14d, 30d, 60d, 90d.
4. Publishes `metrics_computed` and `ic_computed` events.
5. Updates `SIGNAL_LEDGER_BACKFILL_RATIO` gauge (fraction of last-24h signals that are backfill).

---

## Data Contracts

### What each service reads and writes

**SignalTracker:**
- Reads: `market_data_ohlcv` (indirectly via Kafka bars), `signal_ledger_full` (bootstrap only)
- Writes: `lifecycle.transitions` Kafka topic (consumed by `LifecycleWriter`)
- Never writes to DB directly

**SignalReplayAuditor:**
- Reads: `signal_ledger_full`, `market_data_ohlcv`
- Writes: `lifecycle.transitions` Kafka topic

**LifecycleWriter (the actual DB writer — shared by both above):**
- Reads: `lifecycle.transitions` Kafka topic
- Writes: `signal_outcomes` table (activation and exit fields)

**SignalMetricsAnalyzer:**
- Reads: `signal_ledger_full` (resolved signals), `instruments` (tick sizes), `signal_metrics_dq_failures` (DQ dedup bootstrap)
- Writes: `intelligence.signal_metrics` Kafka topic (consumed by `SignalMetricsWriter`)
- `SignalMetricsWriter` writes: `setup_performance`, `signal_metrics_dq_failures` tables

### Kafka topics involved

| Topic | Producer | Consumer |
|-------|---------|---------|
| `intelligence.i7.signals` | `IntelligencePipelineAgent` | `SignalWriter`, `SignalTracker` |
| `lifecycle.transitions` | `SignalTracker`, `SignalReplayAuditor` | `LifecycleWriter` |
| `intelligence.signal_metrics` | `SignalMetricsAnalyzer` | `SignalMetricsWriter` |

---

## How To Extend

### Adding a new lifecycle metric

1. Add the metric column to `signal_outcomes` via migration.
2. Update the `Transition` dataclass in `lifecycle_tracker.py` to carry the new field.
3. Populate it in `evaluate_signal()` or in `SignalTracker._enrich_exit_transition()`.
4. Update `_transition_to_lifecycle()` in `signal_tracker_compute_agent.py` to include it in the EXIT data dict.
5. Update `_BATCH_EXIT_SQL` and `batch_execute("exit", ...)` in `signal_ledger_repository.py`.
6. Update `_build_exit_transition()` in `signal_replay_auditor_agent.py` to handle the new field (replay path must stay in sync with live path).
7. If the metric should appear in `setup_performance`, add it to `compute_signal_metrics()` in `src/intelligence/metrics/compute.py` and update the `SignalMetricsWriter` write logic.

### Adding a new exit condition

1. Add the check to `evaluate_signal()` in `lifecycle_tracker.py`, following the priority order (stop → target → chandelier → staleness → TTL). Return a `Transition` with appropriate `exit_reason` and `outcome`.
2. If the condition requires per-signal state (like staleness's consecutive bar counter), add the field to `SignalState` in `signal_tracker_compute_agent.py` and pass it to `evaluate_signal()`.
3. The replay auditor uses the same `evaluate_signal()` call — no changes needed there unless the new condition requires features not available in the bar window query (e.g., external data).
4. Update the outcome taxonomy table in `signals-lifecycle.md`.

---

## Failure Modes & Operations

### Orphaned signals: stuck in pending too long

**Symptom:** `signal_replay_unresolved_gauge > 0` in Grafana, or manual query shows pending signals with `expires_at` in the past.

**Diagnostic query:**
```sql
-- Signals past TTL but not resolved
SELECT signal_id, symbol, timeframe, setup_plugin, timestamp, expires_at, status,
       entry_zone_low, entry_zone_high
FROM signal_ledger_full
WHERE status IN ('pending', 'active')
  AND exit_at IS NULL
  AND expires_at < NOW()
  AND signal_schema_version = 'v1'
ORDER BY expires_at ASC
LIMIT 20;
```

**Common causes:**
1. `SignalReplayAuditor` is down — check `systemctl status indicagent-signal-replay`.
2. `LifecycleWriter` is down — transitions are being published but not persisted. Check `systemctl status indicagent-lifecycle-writer`.
3. No bar data for the signal window in `market_data_ohlcv` — check `signal_replay_ohlcv_gap_total` metric.
4. Signal has NULL zone fields — check `signal_replay_null_zone_total`. These will never be resolved by replay.

**Resolution:** Restart the replay auditor. It will find the unresolved signals on the next cycle. If the issue is missing OHLCV data, backfill first via `historical_backfill.py`.

### Active signals with no exit

**Symptom:** `status = 'active'` but `exit_at IS NULL` and `expires_at` is in the past.

```sql
-- Active signals whose TTL is overdue
SELECT signal_id, symbol, timeframe, activated_at, expires_at, mae, mfe, bars_in_trade
FROM signal_ledger_full
WHERE status = 'active'
  AND exit_at IS NULL
  AND expires_at IS NOT NULL
  AND expires_at < NOW()
ORDER BY expires_at ASC;
```

These should be resolved by the replay auditor within 5 minutes. If they persist:
1. Check replay auditor logs: `tail -50 logs/signal_replay_auditor_agent.log`
2. Check `signal_replay_unresolved_gauge` in Grafana
3. Check whether `LifecycleWriter` consumer lag is elevated: `docker exec redpanda rpk group describe lifecycle_writer_group -t`

### Metrics compute lag

**Symptom:** `setup_performance` table data is stale (metrics not updated in > 15 min).

```bash
# Check when metrics were last computed
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT setup_plugin, timeframe, window_days, computed_at \
   FROM setup_performance \
   ORDER BY computed_at DESC LIMIT 5;"

# Check service health
systemctl status indicagent-signal-metrics-compute

# Check consumer lag for signal metrics writer
docker exec redpanda rpk group describe signal_metrics_writer -t

# Check consumer lag for signal tracker (bars consumer group)
docker exec redpanda rpk group describe signal_tracker_compute -t
# Check consumer lag for signal tracker (i7 signals consumer group)
docker exec redpanda rpk group describe signal_tracker_compute_signals -t
```

If `SignalMetricsAnalyzer` is running but metrics are still stale, check the log for DQ failures or cycle errors: `tail -50 logs/signal_metrics_compute_agent.log`. A DQ failure in `validate_signal_row()` does NOT stop metric computation — it only publishes a `metrics_dq_failure` event. Cycle errors (exceptions) are logged at ERROR level and increment `signal_metrics_compute_cycle_errors_total`.

### Signals not activating that should be

**Step 1:** Confirm the signal exists and its zone:
```sql
SELECT signal_id, timestamp, status, entry_zone_low, entry_zone_high,
       direction, expires_at
FROM signal_ledger_full
WHERE symbol = 'ESM6' AND timeframe = '1m'
  AND status = 'pending' AND exit_at IS NULL
ORDER BY timestamp DESC LIMIT 5;
```

**Step 2:** Check whether any bars overlapped the zone:
```sql
-- Check if any bar touched the zone
SELECT timestamp, high, low, close
FROM market_data_ohlcv
WHERE symbol = 'ESM6' AND timeframe = '1m'
  AND timestamp >= '2026-05-29 14:00:00+00'
  AND timestamp <= '2026-05-29 15:00:00+00'
  AND low <= <zone_high> AND high >= <zone_low>
ORDER BY timestamp ASC;
```

**Step 3:** If no bars touched the zone, activation is correct (signal is waiting). If bars did overlap and the signal is still pending, check whether `SignalTracker` has the signal in its active index — it may have missed it if the service was down when the signal arrived. Check: `tail -100 logs/signal_tracker_compute_agent.log | grep <signal_id>`.

**Step 4:** If the signal was not in the tracker's index, it can be recovered by the replay auditor once `expires_at` is reached. If you want to force immediate recovery, restart the replay auditor cycle: `sudo systemctl restart indicagent-signal-replay`.

### Bootstrap failure (SignalTracker)

If the tracker fails to bootstrap from DB (after 3 retries), it starts with empty state and publishes a `bootstrap_failed` health event to `health.events`. The tracker is still running and will ingest new signals from Kafka — it just missed the pre-existing pending signals.

```bash
# Check for bootstrap failures
grep "bootstrap_failed" logs/signal_tracker_compute_agent.log | tail -5

# Count signals that are active but tracker doesn't know about them
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT COUNT(*) FROM signal_ledger_full \
   WHERE status IN ('pending', 'active') AND exit_at IS NULL \
   AND timestamp > NOW() - INTERVAL '7 days';"
```

If bootstrap failed, the replay auditor will recover outcomes for signals that expire while the tracker is unaware. Pending signals that are still within their TTL window will not be tracked in real-time until the tracker restarts and bootstraps them.

### Key OTel metrics for signal health

| Metric | Meaning |
|--------|---------|
| `signal_replay_unresolved_gauge` | Signals past TTL with no outcome — should be 0 |
| `signal_tracker_compute_active_signals` | Signals currently in the tracker's active index |
| `signal_tracker_compute_transitions_total` | Total lifecycle transitions published |
| `signal_replay_resolved_total` | Total outcomes recovered by replay |
| `signal_replay_ohlcv_gap_total` | Signals skipped due to missing bar data |
| `signal_replay_null_zone_total` | Signals skipped due to NULL zone fields |
| `signal_metrics_compute_cycles_total` | Metrics compute cycles completed |
| `signal_metrics_dq_failures_total` | Data quality gate failures (by reason) |
| `signal_lifecycle_null_expires_at_total` | Bars processed where signal had NULL expires_at |
| `signal_tracker_labeling_violations_total` | Signals with activated_at set but status=PENDING at TTL time |

### Common debug flow: "why did outcome X not get recorded?"

1. Find the signal: `SELECT * FROM signal_ledger_full WHERE signal_id = '<uuid>';`
2. Check `exit_at IS NULL` — if null, outcome was never recorded.
3. Check `expires_at` — if in the past, replay auditor should have resolved it.
4. Check replay auditor logs for the signal_id: `grep <uuid> logs/signal_replay_auditor_agent.log`
5. Check whether there are bars in `market_data_ohlcv` for the signal's symbol/timeframe/window.
6. Check `LifecycleWriter` lag and logs — transitions may have been published but not consumed.
7. If all else fails, check the `lifecycle.transitions` Kafka topic for the signal_id: `docker exec redpanda rpk topic consume {env}.lifecycle.transitions --from-beginning | grep <uuid>` (replace `{env}.` with your env prefix, e.g. `dev.lifecycle.transitions`; production uses no prefix: `lifecycle.transitions`)

---

## See Also

- `docs/signals/signals-foundation.md` — schema reference, signal_ledger design rationale
- `docs/signals/signals-lifecycle.md` — state machine, activation logic, exit conditions
- `docs/intelligence/intelligence-foundation.md` — I7 signal generation (upstream of this)
- `docs/data/data-streaming.md` — Signal Kafka topics — see Data Streaming
- `services/signal_tracker_compute_agent.py` — live tracker source
- `services/signal_replay_auditor_agent.py` — replay auditor source
- `services/signal_metrics_compute_agent.py` — metrics compute source
- `services/lifecycle_writer_agent.py` — the DB writer consumed by both tracker and replay
- `src/persistence/repository/signal_ledger_repository.py` — all SQL and the `batch_execute()` contract
