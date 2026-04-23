---
created: 2026-04-23
title: Kafka→DB pipeline audit — deferred findings (H5, M2, M3, M5, M6, LOWs)
area: data-pipeline
source-audit: 2026-04-22 Kafka→DB pipeline review
phase-68-covers: H1, H2, H3, H4, H6 (68-02 acceptance criteria + 68-05), M1, M4, M7
files:
  - services/bar_aggregator_agent.py
  - services/bar_writer_agent.py
  - services/feature_writer_service.py
  - services/signal_writer_agent.py
  - src/core/bar_accumulator.py
---

## Background

Audit performed 2026-04-22. Phase 68 (68-02 + 68-05) addresses H1–H4, H6, M1, M4, M7.
The findings below were explicitly deferred as too large or cross-cutting for Phase 68.

---

## HIGH — Not addressed in Phase 68

### H5 · bar_aggregator_agent.py — Stale BarAccumulator on consumer restart

`_consumer_restart_needed` flag recreates the Kafka consumer but reuses the stale
`BarAccumulator` in memory. After restart the accumulator references offsets that may
already be aged out of retention. 68-05's AGG-EMIT-ONCE suppresses duplicate HTF bars
but does not fix the root cause (accumulator state is not reset or replayed coherently
on consumer restart).

**Fix direction:** On consumer restart, either reset the BarAccumulator to a clean state
and replay from `auto_offset_reset="earliest"` within the retention window, or persist
state to a compacted topic before restart (see M3).

---

## MEDIUM — Not addressed in Phase 68

### M2 · feature_writer_service.py — Replay storm on crash-restart

`auto_offset_reset="earliest"` means a crash-restart replays every historical record on
the `intelligence.*` topics. `ON CONFLICT DO NOTHING` handles idempotency but parse
overhead is wasteful and latency spikes during catch-up mask real lag.

**Fix direction:** Switch to a committed offset model (enable_auto_commit=False, commit
after flush — already the BaseWriterAgent pattern). On clean restart, pick up from last
committed offset, not "earliest". Ensure group ID is stable so offset is preserved.

### M3 · bar_aggregator_agent.py — BarAccumulator state not persisted

BarAccumulator is purely in-memory. An outage longer than the `_HTF_MS=3d` retention
window permanently loses partial bars for all in-progress HTF periods. StreamMerger
Convergence Gate is not wired here.

**Fix direction:** Checkpoint accumulator state to a compacted Kafka topic (same pattern
as `intelligence_pipeline_agent` `_checkpoint_state`). Restore on startup before
consuming new bars. This is the proper fix for H5 as well.

### M5 · Cross-cutting — DLQ is fire-and-forget with no replay

All writer agents and bar_aggregator now route bad payloads to DLQ topics, but no replay
agent or documented recovery procedure exists. Bad payloads accumulate silently. There is
no way to diagnose, retry, or purge DLQ contents operationally.

**Fix direction:** Design a `DLQReplayAgent` or at minimum:
- Grafana panel showing DLQ depth per topic
- `rpk topic consume` runbook in `docs/operations/`
- Script to replay DLQ → source topic after payload fix

### M6 · Cross-cutting — No early-warning on Kafka retention lag

If any writer falls behind topic retention, Redpanda deletes messages silently before
they are consumed. No metric or alert fires before data loss occurs. With `_BUFFER_MS=1d`
on intelligence topics, a writer pause of >24h loses data permanently.

**Fix direction:** Add a `retention_lag_warning` alert: compare consumer lag (messages
behind) against a threshold derived from retention window. Fire a Prometheus alert at
80% of retention window consumed (e.g., 20h for 1d retention). See Redpanda's
`kafka_consumer_group_lag` metric.

---

## LOW — Backlog

| Service | Finding |
|---------|---------|
| bar_writer_agent.py | Contract cache reload has no retry on DB failure at startup |
| feature_writer_service.py | `_build_expiry_map()` silently returns empty on Settings failure → all symbols get `days_to_expiry=0` |
| feature_writer_service.py | Health monitor and BaseWriterAgent both report consumer lag on different intervals → jagged metric spikes |
| signal_writer_agent.py | DLQ topic `signal.writer.dlq` missing `intelligence.` prefix (naming convention inconsistency) |
| signal_writer_agent.py | `LedgerEntry` fields `num_agreeing` / `resolution_method` hardcoded instead of read from payload |
| bar_accumulator.py | No TTL on partial bars — a delisted symbol's partial bar emits when trading resumes |
| bar_accumulator.py | `_validate_accumulator()` only runs with `__debug__` (disabled in production with `python -O`) |
| bar_aggregator_agent.py | Expensive per-call consumer lag check creates a new `AIOKafkaConsumer` instance every 15s |
| Cross-cutting | `MAX_BUFFER_SIZE=10k` overflow drops oldest entries silently (WARNING log only, no backpressure to producer) |
