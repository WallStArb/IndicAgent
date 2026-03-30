# Phase 57: IntelligencePipelineComputeAgent — Unified I1-I7 Pipeline — Context

**Gathered:** 2026-03-29
**Status:** Ready for planning (refined)
**Source:** PRD Express Path + design review session

<domain>
## Phase Boundary

Merge `feature_compute_agent.py` (I1-I6) and `signal_generator_agent.py` (I7) into a single `IntelligencePipelineComputeAgent`. This phase:

- Eliminates Kafka as an inter-compute bus (I6→I7 round-trip → in-process call chain)
- Adds full state checkpointing via `StateSerializer` — all five state fields including `_plugin_state` (EMA buffers, HMM posteriors). Zero-warmup restarts.
- Adds `pre_quality_confidence` + `pre_calibration_confidence` to `signal_ledger` for per-stage attribution
- Automated shadow parity gate via `PipelineParityAuditorAgent` before cutover
- Deletes five dead `pipeline.*` Kafka topics + functions, four dead service files, three dead systemd units

Nothing is live in production — clean cutover, no elaborate rollback path needed.

</domain>

<decisions>
## Implementation Decisions

### Service Contract
- File: `services/intelligence_pipeline_agent.py`
- Class: `IntelligencePipelineComputeAgent`
- Systemd unit: `indicagent-intelligence-pipeline`
- Log file: `logs/intelligence_pipeline_agent.log`
- Metrics port: `:9125` (inherited from `indicagent-feature-compute`; `:9112` from signal-generator retired)
- Inherits `BaseAgent` (Phase 52.6 lifecycle: `_setup()`, `_teardown()`, `self.tracer`, `self.running`, `metrics_port`)
- Consumer group: `intelligence_pipeline_group` (new — avoids offset conflict during shadow period)

### Per-Bar Pipeline (pure CPU, no I/O in hot path)
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

### `_setup()` DB calls (preserved from SignalGeneratorAgent)
`_setup()` makes 5 DB calls (calibration curves, TOD multipliers, CIS weights, perf weights, drift penalties). Hot path remains DB-free. These are seeded once at startup, same as current signal_generator behaviour.

### Async Output Buffer
- `asyncio.Queue(maxsize=500)` — hot path uses `queue.put_nowait()`, never blocks
- `QueueFull` → increments `output_buffer_drops_total`, pipeline continues
- Background drain task batches by topic, publishes IntelligenceEvent + SignalResult + StateSnapshot

### State Checkpointing — Full (all five fields)

**Topic:** `topic_intelligence_pipeline_state()` → `development.intelligence.pipeline.state`
**Config:** `cleanup.policy=compact`, `min.cleanable.dirty.ratio=0.1`, `segment.ms=3600000`
**Key:** `{agent_version}:{symbol}:{tf}` — version bump auto-invalidates stale checkpoints
**Value:** `StateSerializer.encode(state_dict)` — msgpack bytes

**StateSerializer (`src/core/state_serializer.py`)** — explicit type tagging:
| Type | Encode | Decode |
|---|---|---|
| `numpy.ndarray` | `{"__ndarray__": true, "data": .tolist(), "dtype": str}` | `numpy.array(data, dtype=dtype)` |
| Pydantic model | `{"__pydantic__": "ClassName", "data": .model_dump()}` | `Registry[name](**data)` |
| `deque` | `{"__deque__": true, "data": list(x), "maxlen": x.maxlen}` | `deque(data, maxlen=maxlen)` |
| primitives / dict / list | pass-through | pass-through |

`StateDeserializationError` on unknown class → non-fatal → fallback to `BarHistorySeeder`

**Five checkpointed fields:**
- `_plugin_state` — per `(plugin_name, symbol, tf)` indicator buffers (EMA, HMM, etc.)
- `_kalman_state` — per `(symbol, tf)` Kalman filter posterior
- `_tod_priors` — per `(regime_type, tf, hour_et)` learned TOD multipliers
- `_bar_history` — per `(symbol, tf)` rolling OHLCV deque
- `_last_bar_offset` — Kafka offset of last processed bar per `(symbol, tf)`

**Restore on startup:**
1. Consume `intelligence.pipeline.state` from offset 0 → build `{key → state}` map
2. Restore all five dicts via `StateSerializer.decode()`
3. Seek bars consumer to `min(last_bar_offset.values()) + 1`
4. Checkpoint miss / version mismatch → `state_checkpoint_fallback_total` increments → `BarHistorySeeder` fallback

### Prometheus Metrics (all new, registered via `src/observability/metrics.py`)
- `output_buffer_depth` — Gauge
- `output_buffer_drops_total` — Counter
- `output_publish_failures_total` — Counter
- `state_checkpoint_fallback_total` — Counter
- `state_checkpoint_failures_total` — Counter
- `state_offset_reset_total` — Counter

### Database Migration
File: `production/migrations/052_signal_ledger_attribution.sql`
```sql
ALTER TABLE signal_ledger
  ADD COLUMN pre_quality_confidence     FLOAT,
  ADD COLUMN pre_calibration_confidence FLOAT;
```

### Shadow Rollout — Automated Parity Gate

**Shadow topic:** `topic_intelligence_shadow()` → `development.intelligence.shadow`
**Shadow consumer group:** `intelligence_pipeline_shadow`

**PipelineParityAuditorAgent** (new, `services/pipeline_parity_auditor_agent.py`, ~100 lines):
- Extends `ParityAuditorAgent` pattern (Phase 52.5)
- 5-minute timer: compares shadow vs canonical `intelligence` topic per `(symbol, tf)`
- Certification gate (all must hold for ≥ 30 consecutive clean cycles):
  - Numeric field deviation `< 0.001` on all `i1`–`i6` JSONB sub-fields
  - Zero missing signals (matched by `(symbol, tf, ts)`)
  - Signal count delta `= 0` per cycle
- On certification: publishes `PIPELINE_PARITY_CERTIFIED` to `system.events`

### Cutover (after `PIPELINE_PARITY_CERTIFIED`)
1. Stop `indicagent-feature-compute` + `indicagent-signal-generator`
2. Reconfigure `indicagent-intelligence-pipeline` → canonical `intelligence` topic
3. Apply `052_signal_ledger_attribution.sql`
4. Delete dead `pipeline.*` Kafka topics
5. Remove dead `stream_keys.py` functions: `topic_quality_gated`, `topic_regime_gated`, `topic_tod_adjusted`, `topic_calibrated`, `topic_ranked`
6. Remove dead files: `feature_compute_agent.py`, `signal_generator_agent.py`, `intelligence_compute_agent.py`, `indicator_compute_agent.py`
7. Remove dead systemd units: `indicagent-feature-compute`, `indicagent-signal-generator`, `indicagent-intelligence-compute`
8. Update CLAUDE.md active service table

### DO NOT remove
- `topic_indicators()` — live in `src/api/main.py` + `src/api/routes/sse.py`
- `BarHistorySeeder` — kept as cold-start fallback
- `src/intelligence/` plugins — zero changes

### Claude's Discretion
- Plan decomposition (number of plans, task ordering)
- Whether `PipelineParityAuditorAgent` is its own plan or part of shadow/cutover plan
- Internal structure of `StateSerializer` (single class vs module-level functions)
- Whether shadow flag is an env var or hardcoded constructor param

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design
- `docs/plans/2026-03-29-intelligence-agent-unified-pipeline-design.md` — Full design: architecture, component contracts, StateSerializer, error handling, automated rollout

### Source services (being replaced/absorbed)
- `services/feature_compute_agent.py` — I1-I6 pipeline implementation
- `services/signal_generator_agent.py` — I7 pipeline, DB setup calls, state fields
- `src/core/bar_history_seeder.py` — DB warm-up seeder (kept as fallback)

### Infrastructure
- `src/core/stream_keys.py` — add `topic_intelligence_pipeline_state()`, `topic_intelligence_shadow()`; remove 5 dead pipeline functions (NOT `topic_indicators()`)
- `src/core/agent/base_agent.py` — BaseAgent lifecycle contract (Phase 52.6)
- `src/intelligence/pipeline/` — pure pipeline functions (unchanged, called in-process)
- `src/intelligence/schemas.py` — IntelligenceEvent, SignalResult
- `src/observability/metrics.py` — all metrics registered here
- `services/parity_auditor_agent.py` — Phase 52.5 pattern to extend for `PipelineParityAuditorAgent`

### Database
- `signal_ledger` schema — migration adds two FLOAT columns
- `src/persistence/repository/signal_ledger.py` — `LedgerEntry.to_insert_params()` gains two params

</canonical_refs>

<specifics>
## Specific Ideas

- State key format `v1:ESM6:1m` — bump `v1` → `v2` on any breaking state schema change
- Pydantic model registry populated at import from `src/intelligence/schemas.py` — any model in plugin state must be in this registry
- `msgpack` already in `requirements.txt` (≥1.0.0) — no install step
- Consumer group `intelligence_pipeline_group` chosen specifically to not conflict with `feature_pipeline` or `signal_generator_group` during shadow period

</specifics>

<deferred>
## Deferred

- `topic_indicators()` removal — requires companion API change, out of scope for Phase 57
- Full Phase 52.5-style `SHADOW_PARITY_CERTIFIED` ceremony — 30-cycle gate is sufficient given nothing is truly live

</deferred>

---

*Phase: 57-intelligencepipelinecomputeagent-unified-i1-i7-pipeline*
*Context gathered: 2026-03-29, refined via design review*
