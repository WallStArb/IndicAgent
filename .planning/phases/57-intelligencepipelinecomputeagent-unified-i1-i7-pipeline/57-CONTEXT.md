# Phase 57: IntelligencePipelineComputeAgent — Unified I1-I7 Pipeline — Context

**Gathered:** 2026-03-29
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-03-29-intelligence-agent-unified-pipeline-design.md)

<domain>
## Phase Boundary

Merge `feature_compute_agent.py` (I1-I6) and `signal_generator_agent.py` (I7) into a single `IntelligencePipelineComputeAgent`. This phase:

- Eliminates Kafka as an inter-compute bus (I6→I7 round-trip replaced by in-process call)
- Adds compacted-topic state checkpointing so agent restarts are zero-warmup (no manual replay)
- Adds `pre_quality_confidence` + `pre_calibration_confidence` to `signal_ledger` for full per-stage attribution
- Deletes five dead `pipeline.*` Kafka topics and their `stream_keys.py` functions
- Removes confirmed-dead legacy services: `intelligence_compute_agent.py`, `indicator_compute_agent.py`
- All I1-I7 plugin code in `src/intelligence/` is unchanged

</domain>

<decisions>
## Implementation Decisions

### Service Contract
- File: `services/intelligence_pipeline_agent.py`
- Class: `IntelligencePipelineComputeAgent`
- Systemd unit: `indicagent-intelligence-pipeline`
- Log file: `logs/intelligence_pipeline_agent.log`
- Metrics port: `:9125` (inherited from `indicagent-feature-compute`; `:9112` from signal-generator retired)
- Inherits `BaseAgent` (Phase 52.6 lifecycle contract)

### Per-Bar Pipeline (pure CPU, no I/O)
```
BarMessage → gap_detection → BarHistory.append
→ I1 → I2 → I3 → I4 → I5 → SMC → I6
→ I7 plugins (capture pre_quality_confidence here)
→ quality_gate (capture pre_calibration_confidence here)
→ regime_gate → tod_adjust → calibrate → rank → select_winner
→ enqueue(IntelligenceEvent, SignalResult, StateSnapshot)
```

### Attribution Capture Points
- `pre_quality_confidence`: per-signal confidence captured immediately before `apply_quality_gate()`
- `pre_calibration_confidence`: per-signal confidence captured after `apply_quality_gate()`, immediately before `apply_calibration()`
- Invariant: `pre_quality_confidence >= pre_calibration_confidence >= calibrated_confidence`

### Async Output Buffer
- `asyncio.Queue(maxsize=500)` inside the agent
- Hot path uses `queue.put_nowait()` — never blocks
- `QueueFull` increments `output_buffer_drops_total` counter, pipeline continues
- Background drain task batches by topic and publishes to Kafka

### State Checkpointing
- Topic function: `topic_intelligence_pipeline_state()` in `stream_keys.py`
- Topic string: `development.intelligence.pipeline.state`
- Topic config: `cleanup.policy=compact`, `min.cleanable.dirty.ratio=0.1`, `segment.ms=3600000`
- Message key: `{agent_version}:{symbol}:{tf}` (e.g. `v1:ESM6:1m`)
- Message value: msgpack-encoded dict with all five state fields + `last_bar_offset`
- Published: once per processed bar per (symbol, tf), via async output buffer (fire-and-forget)

### State Fields (all checkpointed)
- `_plugin_state: dict` — per `(plugin_name, symbol, tf)` indicator buffers
- `_kalman_state: dict` — per `(symbol, tf)` Kalman filter posterior
- `_tod_priors: dict` — per `(regime_type, tf, hour_et)` learned TOD multipliers
- `_bar_history: dict[str, deque]` — per `(symbol, tf)` rolling OHLCV deque
- `_last_bar_offset: dict[str, int]` — Kafka offset of last processed bar per `(symbol, tf)`

### State Restore on Startup
1. Consume `intelligence.pipeline.state` from offset 0 until caught up → build `{key → state}` map
2. Restore all five state dicts from map
3. Seek bars consumer to `min(last_bar_offset.values()) + 1`
4. Version bump (new key prefix) → no map match → `state_checkpoint_fallback_total` increments → automatic `BarHistorySeeder` fallback

### Prometheus Metrics (all new)
- `output_buffer_depth` — Gauge, current queue depth
- `output_buffer_drops_total` — Counter, QueueFull drops
- `output_publish_failures_total` — Counter, Kafka publish failures after retry
- `state_checkpoint_fallback_total` — Counter, checkpoint miss → DB fallback
- `state_checkpoint_failures_total` — Counter, non-fatal checkpoint publish failures
- `state_offset_reset_total` — Counter, offset out-of-range resets

### Database Migration
```sql
ALTER TABLE signal_ledger
  ADD COLUMN pre_quality_confidence     FLOAT,
  ADD COLUMN pre_calibration_confidence FLOAT;
```
Migration file: `NNN_signal_ledger_attribution.sql`

### Files Removed
- `services/feature_compute_agent.py` — replaced by `services/intelligence_pipeline_agent.py`
- `services/signal_generator_agent.py` — absorbed
- `services/intelligence_compute_agent.py` — confirmed dead (unit failed + disabled)
- `services/indicator_compute_agent.py` — legacy I1 predecessor, no active consumers
- Systemd units: `indicagent-feature-compute`, `indicagent-signal-generator`, `indicagent-intelligence-compute`
- Dead Kafka topics: `development.pipeline.quality_gated`, `.regime_gated`, `.tod_adjusted`, `.calibrated`, `.ranked`
- Dead stream_keys.py functions: `topic_quality_gated`, `topic_regime_gated`, `topic_tod_adjusted`, `topic_calibrated`, `topic_ranked`
- `topic_indicators()` — **verify first**: `src/api/main.py` and `src/api/routes/sse.py` reference it; remove only after confirming dead code paths

### BarHistorySeeder
- Kept as cold-start fallback only (checkpoint miss or version bump)
- NOT removed: it's the graceful-degradation path

### Rollout Sequence (mandatory)
1. Deploy in shadow mode publishing to `intelligence.shadow` topic (separate consumer group)
2. Compare shadow output vs canonical `intelligence` topic for N bars — assert field-level parity
3. Stop `indicagent-feature-compute` + `indicagent-signal-generator`
4. Start `indicagent-intelligence-pipeline` publishing to canonical `intelligence` topic
5. Apply `signal_ledger` migration
6. Delete dead `pipeline.*` Kafka topics
7. Remove dead `stream_keys.py` functions

### Tests Required (from design doc)
**Unit:**
- `test_intelligence_pipeline_agent_pipeline.py` — mock bar in, assert IntelligenceEvent + SignalResult enqueued
- `test_async_output_buffer.py` — QueueFull increments counter, drain task publishes correctly
- `test_state_checkpoint_serde.py` — full state dict → msgpack → deserialize → round-trip fidelity
- `test_state_restore.py` — checkpoint payload → assert all five state fields restored + `_last_bar_offset`
- `test_pipeline_attribution.py` — assert `pre_quality >= pre_calibration >= calibrated` invariant

**Integration:**
- `test_intelligence_pipeline_agent_restart.py` — process N bars, checkpoint, restart, assert state restored and output identical to continuous-run baseline
- `test_signal_ledger_attribution.py` — `pre_quality_confidence` + `pre_calibration_confidence` non-null for every inserted row

### Claude's Discretion
- Plan decomposition (how many plans, task ordering within plans)
- Whether shadow rollout is a separate plan or part of the cutover plan
- Error handling details not specified (e.g., reconnect logic for state topic consumer)
- Whether to use `msgpack` directly or abstract behind a `StateSerializer` class

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design
- `docs/plans/2026-03-29-intelligence-agent-unified-pipeline-design.md` — Full design doc: architecture, component contracts, error handling, rollout sequence, test requirements

### Existing services being replaced
- `services/feature_compute_agent.py` — I1-I6 pipeline (to be replaced)
- `services/signal_generator_agent.py` — I7 pipeline (to be absorbed)
- `src/core/bar_history_seeder.py` — DB warm-up seeder (kept as fallback)

### Infrastructure contracts
- `src/core/stream_keys.py` — all Kafka topic functions (add `topic_intelligence_pipeline_state`, remove 5 dead pipeline functions)
- `src/core/agent/base_agent.py` — BaseAgent lifecycle contract (Phase 52.6)
- `src/intelligence/pipeline/` — pure pipeline functions (quality_gate, regime_gate, tod_adjust, calibrate, rank) — unchanged, called in-process
- `src/intelligence/schemas.py` — IntelligenceEvent, SignalResult schemas
- `src/observability/metrics.py` — create all metrics through this module

### Database
- `signal_ledger` table schema — migration adds two FLOAT columns
- `src/persistence/repository/signal_ledger.py` — `LedgerEntry.to_insert_params()` will gain two new positional params

### CLAUDE.md patterns
- Async output buffer pattern: `asyncio.Queue(maxsize=500)` + `put_nowait()` + background drain task
- BaseAgent pattern: `_setup()` / `_teardown()` / `self.tracer` / `self.running`
- Kafka compacted topics: `cleanup.policy=compact`
- msgpack: for binary state serialization (add `msgpack` to requirements.txt if not present)

</canonical_refs>

<specifics>
## Specific Ideas

### State key versioning
State key format `v1:ESM6:1m` — increment `v1` → `v2` on any breaking change to state schema. This is the zero-configuration cache invalidation mechanism.

### Shadow topic naming
Shadow topic: `development.intelligence.shadow` — add `topic_intelligence_shadow()` to `stream_keys.py` for the shadow rollout phase only. Remove after cutover.

### Kafka offset seek on restore
After restoring state, seek bars consumer to `min(last_bar_offset.values()) + 1` to replay missed bars since last checkpoint. This ensures zero gap in bar processing.

### `topic_indicators()` verification
Before removing `topic_indicators()` from `stream_keys.py`, grep `src/api/` for usage. If dead code, remove. If live, retain and document.

</specifics>

<deferred>
## Deferred Ideas

- `intelligence_compute_agent.py` retirement decision (confirmed dead this phase, deletion is in scope)
- Full shadow parity certification framework (the Phase 52.3/52.5 `SHADOW_PARITY_CERTIFIED` pattern could apply here but is out of scope — manual comparison for rollout validation is sufficient)

</deferred>

---

*Phase: 57-intelligencepipelinecomputeagent-unified-i1-i7-pipeline*
*Context gathered: 2026-03-29 via PRD Express Path (docs/plans/2026-03-29-intelligence-agent-unified-pipeline-design.md)*
