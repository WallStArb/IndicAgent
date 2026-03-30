# IntelligencePipelineComputeAgent — Unified I1-I7 Pipeline Design

**Status:** Design approved
**Date:** 2026-03-29
**Milestone:** v2.1
**Supersedes:** `feature_compute_agent.py` (I1-I6) + `signal_generator_agent.py` (I7)

---

## Problem

Three Renaissance violations in the current compute pipeline:

1. **Kafka as an inter-compute bus** — `feature_compute_agent` publishes `IntelligenceEvent` to the `intelligence` Kafka topic; `signal_generator_agent` subscribes to it as its input. I6→I7 is a single logical computation split across a Kafka serialization/deserialization round-trip. Kafka is for output sinks and fan-out, not for wiring compute stages together.

2. **Stateless compute forces replay on every restart** — plugin internal state (EMA accumulators, HMM posteriors, Kalman filter posterior, learned TOD priors) is ephemeral. On restart, `BarHistorySeeder` reloads raw bars from DB but cannot restore plugin state. The 15m pipeline requires 6.5 hours of live bars before it is genuinely warm. The dashboard is blind until warmup completes — a manual wait that repeats on every deploy or crash.

3. **Pipeline attribution data is unqueryable** — five `pipeline.*` Kafka topics capture intermediate confidence values per stage (quality_gate, regime_gate, tod_adjuster, calibrator, ranker) but have no consumer. Data expires after 7-day retention. The `signal_ledger` captures final state but not the per-stage confidence transformation chain — making "why did this signal's confidence drop from 0.7 to 0.4?" unanswerable.

---

## Renaissance Principles Applied

| Principle | Decision |
|---|---|
| Kafka and DB are sinks, not pipes | I1→I7 runs in-process; Kafka publish is fire-and-forget via async buffer |
| Stateful processes checkpoint their own state | Compacted Kafka topic `intelligence.pipeline.state` stores full plugin state per (symbol, tf) |
| No manual tasks on restart | State restore is automatic; fallback to DB seed is automatic; zero human steps |
| Never drop data that could contain signal | `pre_quality_confidence` + `pre_calibration_confidence` added to `signal_ledger` |
| Instrument everything | `output_buffer_depth`, `output_buffer_drops_total`, `state_checkpoint_fallback_total` metrics at birth |
| Degrade gracefully, adapt automatically | Missing checkpoint → automatic DB fallback; offset out of range → automatic reset to earliest |

---

## Architecture

```
                   ┌─────────────────────────────────────────────────────────────┐
market.bars ──────→│            IntelligencePipelineComputeAgent                  │
market.bars.htf ──→│   I1→I2→I3→I4→I5→SMC→I6→I7                                 │
system.events ────→│   quality_gate → regime_gate → tod_adjust                    │
cross_asset ──────→│   → calibrate → rank → select_winner                         │
                   │                                                               │
                   │   pure CPU — zero I/O blocking in hot path                    │
                   └──────────────────────┬────────────────────────────────────────┘
                                          │ queue.put_nowait() — non-blocking
                                          ▼
                                  asyncio.Queue(maxsize=500)
                                  output_buffer_depth gauge
                                          │
                               background drain task
                         ┌────────────────┼──────────────────────────┐
                         ▼                ▼                           ▼
                   intelligence        signals        intelligence.pipeline.state
                     topic           .aggregated          (compacted, ∞)
                         │                │               key: v1:ESM6:1m
                FeatureWriterAgent  SignalWriterAgent
                         │                │
                 intelligence_       signal_ledger
                   features (DB)        (DB)

── On restart ────────────────────────────────────────────────────────────────
1. Consume intelligence.pipeline.state (compacted) → restore plugin_state,
   kalman_state, tod_priors, bar_history, last_bar_offset  [~120 msgs, ms]
2. Seek bars consumer to last_bar_offset + 1
3. Catch up on missed bars → resume live processing
   Zero manual steps. Zero warmup window.
```

---

## What Changes

### Removed
- `services/feature_compute_agent.py` — replaced by `services/intelligence_pipeline_agent.py`
- `services/signal_generator_agent.py` — absorbed into `IntelligencePipelineComputeAgent`
- `src/core/bar_history_seeder.py` — replaced by state checkpoint restore (kept as cold-start fallback only)
- Systemd unit `indicagent-feature-compute` — replaced by `indicagent-intelligence-pipeline`
- Systemd unit `indicagent-signal-generator` — removed
- Dead Kafka topic functions: `topic_quality_gated`, `topic_regime_gated`, `topic_tod_adjusted`, `topic_calibrated`, `topic_ranked` from `stream_keys.py`
- Dead Kafka topics from Redpanda: `development.pipeline.quality_gated`, `development.pipeline.regime_gated`, `development.pipeline.tod_adjusted`, `development.pipeline.calibrated`, `development.pipeline.ranked`
- `services/intelligence_compute_agent.py` — confirmed dead: `indicagent-intelligence-compute` is failed + disabled; superseded by `feature_compute_agent` in Phase 40 DAG refactor
- `services/indicator_compute_agent.py` — legacy I1 predecessor to `feature_compute_agent`; no active consumers
- Systemd unit `/etc/systemd/system/indicagent-intelligence-compute.service` — remove
- Kafka topic `development.indicators` — no active consumer groups; published by legacy `indicator_compute_agent` only
- `topic_indicators()` function from `stream_keys.py` — **verify first**: `src/api/main.py` and `src/api/routes/sse.py` reference it; confirm these are dead code paths before removing

### Added
- `services/intelligence_pipeline_agent.py` — `IntelligencePipelineComputeAgent` (I1-I7 unified)
- `topic_intelligence_pipeline_state()` in `stream_keys.py` → `development.intelligence.pipeline.state`
- `development.intelligence.pipeline.state` Kafka topic — `cleanup.policy=compact`, no retention limit
- `pre_quality_confidence FLOAT` column on `signal_ledger`
- `pre_calibration_confidence FLOAT` column on `signal_ledger`
- Migration: `052_signal_ledger_attribution.sql`

### Unchanged
- All I1-I7 plugin code — zero changes to `src/intelligence/`
- `src/intelligence/pipeline/` pure functions — unchanged, just called in-process
- `FeatureWriterAgent`, `SignalWriterAgent` — unchanged consumers
- `intelligence` topic, `signals.aggregated` topic — same names, same consumers
- `signal_ledger` schema except two new columns

---

## Component Contracts

### IntelligencePipelineComputeAgent

**File:** `services/intelligence_pipeline_agent.py`
**Class:** `IntelligencePipelineComputeAgent`
**Systemd unit:** `indicagent-intelligence-pipeline`
**Log file:** `logs/intelligence_pipeline_agent.log`
**Metrics port:** `:9125` (canonical — inherited from `indicagent-feature-compute`; `:9112` from `indicagent-signal-generator` is retired)

**State owned (fully checkpointed):**
- `_plugin_state: dict` — per `(plugin_name, symbol, tf)` indicator buffers
- `_kalman_state: dict` — per `(symbol, tf)` Kalman filter posterior
- `_tod_priors: dict` — per `(regime_type, tf, hour_et)` learned TOD multipliers
- `_bar_history: dict[str, deque]` — per `(symbol, tf)` rolling OHLCV deque
- `_last_bar_offset: dict[str, int]` — Kafka offset of last processed bar per `(symbol, tf)`

**Per-bar pipeline (pure CPU):**
```
BarMessage → gap_detection → BarHistory.append
→ I1 → I2 → I3 → I4 → I5 → SMC → I6
→ I7 plugins (capture pre_quality_confidence here)
→ quality_gate (capture pre_calibration_confidence here)
→ regime_gate → tod_adjust → calibrate → rank → select_winner
→ enqueue(IntelligenceEvent, SignalResult, StateSnapshot)
```

**Attribution capture points:**
- `pre_quality_confidence`: per-signal confidence value captured immediately before `apply_quality_gate()` runs — set on each signal dict in the pipeline loop
- `pre_calibration_confidence`: per-signal confidence value captured after `apply_quality_gate()`, immediately before `apply_calibration()` — set on each signal dict

### Async Output Buffer

`asyncio.Queue(maxsize=500)` inside `IntelligencePipelineComputeAgent`. Hot path calls `queue.put_nowait()` — never blocks. `QueueFull` increments `output_buffer_drops_total` counter and continues.

Background drain task batches by topic and publishes to Kafka. Prometheus gauge `output_buffer_depth` tracks current queue depth.

### State Checkpoint Topic (`intelligence.pipeline.state`)

**Topic function:** `topic_intelligence_pipeline_state()` in `stream_keys.py`
**Topic string:** `development.intelligence.pipeline.state`

Compacted Kafka topic. Configuration:
```
cleanup.policy=compact
min.cleanable.dirty.ratio=0.1
segment.ms=3600000
```

**Message format:**
- Key: `{agent_version}:{symbol}:{tf}` — e.g. `v1:ESM6:1m`
- Value: msgpack-encoded dict containing all five state fields + `last_bar_offset`

**Published:** once per processed bar per (symbol, tf), via async output buffer (same fire-and-forget path as intelligence/signals outputs).

**Restore on startup:**
1. Consume topic from offset 0 until caught up — builds `{key → state}` map
2. Restore all five state dicts from map
3. Seek bars consumer to `min(last_bar_offset.values()) + 1`

**Agent version bump:** new key prefix → no match in map → `state_checkpoint_fallback_total` increments → automatic fallback to `BarHistorySeeder` DB path

### StateSerializer (`src/core/state_serializer.py`)

All five state fields are checkpointed including `_plugin_state`. Type conversion is explicit before msgpack encoding:

| Type | Encode | Decode |
|---|---|---|
| `numpy.ndarray` | `.tolist()` + tag `{"__ndarray__": true, "data": [...], "dtype": str}` | `numpy.array(d["data"], dtype=d["dtype"])` |
| Pydantic model | `.model_dump()` + tag `{"__pydantic__": "ClassName", "data": {...}}` | `ModelClass(**d["data"])` — registry keyed by class name |
| `deque` | `list(x)` + tag `{"__deque__": true, "data": [...], "maxlen": x.maxlen}` | `deque(d["data"], maxlen=d["maxlen"])` |
| Primitive (`int`, `float`, `str`, `bool`, `None`) | Pass-through | Pass-through |
| `dict` / `list` | Recurse | Recurse |

`StateSerializer.encode(state: dict) -> bytes` — walks the full state tree, applies type tags, returns msgpack bytes.
`StateSerializer.decode(payload: bytes) -> dict` — deserializes, reconstructs tagged types.

Pydantic model registry is populated at import time from `src/intelligence/schemas.py` and `src/intelligence/pipeline/` — any model used in plugin state must be registered. Unrecognised class name raises `StateDeserializationError` (non-fatal on startup → fallback to `BarHistorySeeder`).

---

## Error Handling

| Failure | Behaviour | Observable signal |
|---|---|---|
| Plugin throws | Isolated — null output for that tier, pipeline continues, circuit breaker tracks | `plugin_error_total` counter |
| `QueueFull` | Drop event, continue compute | `output_buffer_drops_total` counter |
| Kafka publish failure | Exponential backoff retry via `retry_utils`; log after final failure | `output_publish_failures_total` counter |
| State checkpoint publish failure | Non-fatal — previous checkpoint still valid; next restart replays from previous offset (idempotent) | `state_checkpoint_failures_total` counter |
| Checkpoint missing on restart | Automatic fallback to `BarHistorySeeder` DB seed | `state_checkpoint_fallback_total` counter |
| Kafka offset out of range (>7 day downtime) | Reset to earliest available offset; plugin state from checkpoint still valid | `state_offset_reset_total` counter + warning log |

---

## Signal Ledger Attribution

### Migration

```sql
ALTER TABLE signal_ledger
  ADD COLUMN pre_quality_confidence     FLOAT,
  ADD COLUMN pre_calibration_confidence FLOAT;
```

### Invariant

For every row: `pre_quality_confidence >= pre_calibration_confidence >= calibrated_confidence`

Violations indicate a bug in the pipeline stage ordering and should be caught in tests.

### Example queries

```sql
-- Per-setup: how much does each stage compress confidence on average?
SELECT
  setup_plugin,
  AVG(pre_quality_confidence - pre_calibration_confidence) AS quality_gate_impact,
  AVG(pre_calibration_confidence - calibrated_confidence)  AS calibration_impact,
  COUNT(*) AS n
FROM signal_ledger
WHERE pre_quality_confidence IS NOT NULL
GROUP BY setup_plugin
ORDER BY quality_gate_impact DESC;

-- Signals where quality_gate was the primary kill
SELECT signal_id, symbol, timeframe, setup_plugin,
       pre_quality_confidence, calibrated_confidence
FROM signal_ledger
WHERE (pre_quality_confidence - calibrated_confidence) > 0.20
ORDER BY ts DESC LIMIT 50;
```

---

## Testing

### Unit tests (`tests/unit/`)

- `test_intelligence_pipeline_agent_pipeline.py` — mock bar in, assert `IntelligenceEvent` + `SignalResult` enqueued. Verifies I1→I7 wiring without Kafka or DB.
- `test_async_output_buffer.py` — verify `QueueFull` increments counter without raising. Verify drain task publishes to correct topics in correct order.
- `test_state_checkpoint_serde.py` — serialize full state dict → msgpack → deserialize → assert round-trip fidelity for each state type.
- `test_state_restore.py` — given a checkpoint payload, assert agent restores all five state fields correctly and `_last_bar_offset` matches.
- `test_pipeline_attribution.py` — assert `pre_quality_confidence >= pre_calibration_confidence >= calibrated_confidence` invariant holds across synthetic signal range.

### Integration tests (`tests/integration/`)

- `test_intelligence_pipeline_agent_restart.py` — run agent against live Kafka, process N bars, checkpoint to `intelligence.pipeline.state`, terminate, restart, assert state restored and next bar output is identical to continuous-run baseline.
- `test_signal_ledger_attribution.py` — assert `pre_quality_confidence` and `pre_calibration_confidence` are non-null for every row inserted by the agent.

---

## Rollout

Shadow validation is automated — not manual. The existing `ParityAuditorAgent` pattern (Phase 52.5) is extended for this cutover.

### Shadow Phase (automated parity gate)

1. Deploy `indicagent-intelligence-pipeline` in shadow mode publishing to `development.intelligence.shadow` topic — consumer group `intelligence_pipeline_shadow`, no WriterAgent consumption
2. `PipelineParityAuditorAgent` (new, lightweight — ~100 lines extending `ParityAuditorAgent`) compares shadow vs canonical `intelligence` topic per `(symbol, tf)` on a 5-minute timer
3. Certification gate — all must hold for `≥ 30` consecutive clean cycles:
   - Numeric field deviation `< 0.001` on all `i1`–`i6` JSONB sub-fields
   - Zero missing signals (every signal in canonical topic also present in shadow, matched by `(symbol, tf, ts)`)
   - Signal count delta `= 0` per cycle
4. On certification: `PipelineParityAuditorAgent` publishes `PIPELINE_PARITY_CERTIFIED` to `system.events` topic

### Cutover (triggered by `PIPELINE_PARITY_CERTIFIED`)

5. Stop `indicagent-feature-compute` + `indicagent-signal-generator`
6. Reconfigure `indicagent-intelligence-pipeline` to publish to canonical `intelligence` topic (remove shadow flag)
7. Apply `signal_ledger` migration (`052_signal_ledger_attribution.sql`)
8. Delete dead `pipeline.*` Kafka topics from Redpanda
9. Remove dead `topic_quality_gated`, `topic_regime_gated`, `topic_tod_adjusted`, `topic_calibrated`, `topic_ranked` functions from `stream_keys.py`
10. Remove dead service files and systemd units (feature_compute, signal_generator, intelligence_compute, indicator_compute)
11. Update CLAUDE.md active service table
