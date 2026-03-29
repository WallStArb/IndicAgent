# Phase 57: IntelligencePipelineComputeAgent — Unified I1-I7 Pipeline - Research

**Researched:** 2026-03-29
**Domain:** Python asyncio agent architecture, Kafka compacted topics, msgpack state
checkpointing, pipeline attribution instrumentation
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Service Contract**
- File: `services/intelligence_pipeline_agent.py`
- Class: `IntelligencePipelineComputeAgent`
- Systemd unit: `indicagent-intelligence-pipeline`
- Log file: `logs/intelligence_pipeline_agent.log`
- Metrics port: `:9125` (inherited from `indicagent-feature-compute`; `:9112` from signal-generator retired)
- Inherits `BaseAgent` (Phase 52.6 lifecycle contract)

**Per-Bar Pipeline (pure CPU, no I/O)**
```
BarMessage → gap_detection → BarHistory.append
→ I1 → I2 → I3 → I4 → I5 → SMC → I6
→ I7 plugins (capture pre_quality_confidence here)
→ quality_gate (capture pre_calibration_confidence here)
→ regime_gate → tod_adjust → calibrate → rank → select_winner
→ enqueue(IntelligenceEvent, SignalResult, StateSnapshot)
```

**Attribution Capture Points**
- `pre_quality_confidence`: per-signal confidence captured immediately before `apply_quality_gate()`
- `pre_calibration_confidence`: per-signal confidence captured after `apply_quality_gate()`, immediately before `apply_calibration()`
- Invariant: `pre_quality_confidence >= pre_calibration_confidence >= calibrated_confidence`

**Async Output Buffer**
- `asyncio.Queue(maxsize=500)` inside the agent
- Hot path uses `queue.put_nowait()` — never blocks
- `QueueFull` increments `output_buffer_drops_total` counter, pipeline continues
- Background drain task batches by topic and publishes to Kafka

**State Checkpointing**
- Topic function: `topic_intelligence_pipeline_state()` in `stream_keys.py`
- Topic string: `development.intelligence.pipeline.state`
- Topic config: `cleanup.policy=compact`, `min.cleanable.dirty.ratio=0.1`, `segment.ms=3600000`
- Message key: `{agent_version}:{symbol}:{tf}` (e.g. `v1:ESM6:1m`)
- Message value: msgpack-encoded dict with all five state fields + `last_bar_offset`
- Published: once per processed bar per (symbol, tf), via async output buffer (fire-and-forget)

**State Fields (all checkpointed)**
- `_plugin_state: dict` — per `(plugin_name, symbol, tf)` indicator buffers
- `_kalman_state: dict` — per `(symbol, tf)` Kalman filter posterior
- `_tod_priors: dict` — per `(regime_type, tf, hour_et)` learned TOD multipliers
- `_bar_history: dict[str, deque]` — per `(symbol, tf)` rolling OHLCV deque
- `_last_bar_offset: dict[str, int]` — Kafka offset of last processed bar per `(symbol, tf)`

**State Restore on Startup**
1. Consume `intelligence.pipeline.state` from offset 0 until caught up → build `{key → state}` map
2. Restore all five state dicts from map
3. Seek bars consumer to `min(last_bar_offset.values()) + 1`
4. Version bump (new key prefix) → no map match → `state_checkpoint_fallback_total` increments → automatic `BarHistorySeeder` fallback

**Prometheus Metrics (all new)**
- `output_buffer_depth` — Gauge, current queue depth
- `output_buffer_drops_total` — Counter, QueueFull drops
- `output_publish_failures_total` — Counter, Kafka publish failures after retry
- `state_checkpoint_fallback_total` — Counter, checkpoint miss → DB fallback
- `state_checkpoint_failures_total` — Counter, non-fatal checkpoint publish failures
- `state_offset_reset_total` — Counter, offset out-of-range resets

**Database Migration**
```sql
ALTER TABLE signal_ledger
  ADD COLUMN pre_quality_confidence     FLOAT,
  ADD COLUMN pre_calibration_confidence FLOAT;
```
Migration file: `NNN_signal_ledger_attribution.sql`

**Files Removed**
- `services/feature_compute_agent.py` — replaced by `services/intelligence_pipeline_agent.py`
- `services/signal_generator_agent.py` — absorbed
- `services/intelligence_compute_agent.py` — confirmed dead (unit failed + disabled)
- `services/indicator_compute_agent.py` — legacy I1 predecessor, no active consumers
- Systemd units: `indicagent-feature-compute`, `indicagent-signal-generator`, `indicagent-intelligence-compute`
- Dead Kafka topics: `development.pipeline.quality_gated`, `.regime_gated`, `.tod_adjusted`, `.calibrated`, `.ranked`
- Dead stream_keys.py functions: `topic_quality_gated`, `topic_regime_gated`, `topic_tod_adjusted`, `topic_calibrated`, `topic_ranked`
- `topic_indicators()` — **verify first**: `src/api/main.py` and `src/api/routes/sse.py` reference it; remove only after confirming dead code paths

**BarHistorySeeder** — Kept as cold-start fallback only (checkpoint miss or version bump). NOT removed.

**Rollout Sequence (mandatory)**
1. Deploy in shadow mode publishing to `intelligence.shadow` topic (separate consumer group)
2. Compare shadow output vs canonical `intelligence` topic for N bars — assert field-level parity
3. Stop `indicagent-feature-compute` + `indicagent-signal-generator`
4. Start `indicagent-intelligence-pipeline` publishing to canonical `intelligence` topic
5. Apply `signal_ledger` migration
6. Delete dead `pipeline.*` Kafka topics
7. Remove dead `stream_keys.py` functions

**Tests Required**
Unit:
- `test_intelligence_pipeline_agent_pipeline.py` — mock bar in, assert IntelligenceEvent + SignalResult enqueued
- `test_async_output_buffer.py` — QueueFull increments counter, drain task publishes correctly
- `test_state_checkpoint_serde.py` — full state dict → msgpack → deserialize → round-trip fidelity
- `test_state_restore.py` — checkpoint payload → assert all five state fields restored + `_last_bar_offset`
- `test_pipeline_attribution.py` — assert `pre_quality >= pre_calibration >= calibrated` invariant

Integration:
- `test_intelligence_pipeline_agent_restart.py` — process N bars, checkpoint, restart, assert state restored and output identical to continuous-run baseline
- `test_signal_ledger_attribution.py` — `pre_quality_confidence` + `pre_calibration_confidence` non-null for every inserted row

### Claude's Discretion
- Plan decomposition (how many plans, task ordering within plans)
- Whether shadow rollout is a separate plan or part of the cutover plan
- Error handling details not specified (e.g., reconnect logic for state topic consumer)
- Whether to use `msgpack` directly or abstract behind a `StateSerializer` class

### Deferred Ideas (OUT OF SCOPE)
- `intelligence_compute_agent.py` retirement decision (confirmed dead this phase, deletion is in scope)
- Full shadow parity certification framework (the Phase 52.3/52.5 `SHADOW_PARITY_CERTIFIED` pattern could apply here but is out of scope — manual comparison for rollout validation is sufficient)
</user_constraints>

---

## Summary

Phase 57 merges two live agents (`FeatureComputeAgent` at I1-I6 and `SignalGeneratorAgent` at I7) into a
single `IntelligencePipelineComputeAgent` that runs I1-I7 in-process, adds compacted-topic state
checkpointing for zero-warmup restarts, and captures `pre_quality_confidence` /
`pre_calibration_confidence` attribution columns in `signal_ledger`.

Source investigation confirms all locked decisions are implementable without change. The two source
agents exist at `services/feature_compute_agent.py` (FeatureComputeAgent, consumer group
`feature_pipeline`) and `services/signal_generator_agent.py` (SignalGeneratorAgent inheriting
BaseAgent, consumer group `signal_generator_group`). Both are currently live on the system.

**Critical integration detail discovered:** The design document names state field `_tod_priors` but
the live `signal_generator_agent.py` uses `_tod_multipliers`. The planner must use `_tod_multipliers`
as the canonical name in the merged agent, matching the live code. Similarly, the design says
`_kalman_state` but live code uses `_cis_kalman_state`. The planner must decide which name to
canonicalize (recommendation: `_kalman_state` as the design specifies, since this is new code).

**Primary recommendation:** Implement in three plans: (1) core agent + unit tests, (2) state
checkpointing + serde tests, (3) shadow rollout + cutover + cleanup.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| msgpack | >=1.0.0 | Binary state serialization for checkpoint topic | Already in requirements.txt — confirmed present |
| asyncio | stdlib | Queue, create_task, put_nowait | Project standard; no external dep needed |
| structlog | project std | Structured logging with agent=name binding | All agents use structlog |

### Existing Imports (from source agents)
| Module | Source | Purpose |
|--------|--------|---------|
| `src.core.agent.base.BaseAgent` | Phase 52.6 | `_setup()`/`_teardown()`/`_run()` lifecycle contract |
| `src.intelligence.pipeline.*` | Existing | `apply_quality_gate`, `apply_regime_gate`, `apply_tod_adjustment`, `apply_calibration`, `rank_signals`, `select_winner` — pure functions |
| `src.core.bar_history.BarHistory` | Existing | Typed deque store for OHLCV per (symbol, tf) |
| `src.core.kafka_utils.KafkaConsumerClient` / `KafkaProducerClient` | Existing | Kafka I/O |
| `src.observability.metrics.counter` / `gauge` | Existing | Metric registration (prevents duplicate) |

**Version verification:** msgpack `>=1.0.0` confirmed in `requirements.txt`. No install step needed.

---

## Architecture Patterns

### Recommended Project Structure

```
services/
├── intelligence_pipeline_agent.py    # new — replaces FCA + SGA
├── feature_compute_agent.py          # to be deleted at cutover
├── signal_generator_agent.py         # to be deleted at cutover
├── intelligence_compute_agent.py     # to be deleted (dead)
├── indicator_compute_agent.py        # to be deleted (dead)
└── indicagent-intelligence-pipeline.service  # new systemd unit

src/core/stream_keys.py               # add topic_intelligence_pipeline_state(),
                                      # add topic_intelligence_shadow(),
                                      # delete 5 dead pipeline.* functions
production/migrations/
└── 052_signal_ledger_attribution.sql  # new — see Migration Numbering

tests/unit/
├── test_intelligence_pipeline_agent_pipeline.py  # new
├── test_async_output_buffer.py                   # new
├── test_state_checkpoint_serde.py                # new
├── test_state_restore.py                         # new
└── test_pipeline_attribution.py                  # new
tests/integration/
├── test_intelligence_pipeline_agent_restart.py   # new
└── test_signal_ledger_attribution.py             # new
```

### Pattern 1: BaseAgent Lifecycle Contract

**What:** All agents inherit `BaseAgent` from `src/core/agent/base.py`. Override `_setup()`,
`_run()`, `_teardown()`. Signal handlers are registered automatically in `start()`.

**Key facts verified from source:**
- `self.tracer = get_tracer(name)` — OTel tracer, no-op when tracing not initialized
- `self.logger: structlog.BoundLogger` — bound with `agent=name`
- `self.running` property → `not self._stop_event.is_set()`
- `start()` calls: `_register_signal_handlers()` → optionally `start_metrics_server(port)` → `_setup()` → `_report_consumer_lag()` task → `_run()` → finally `_teardown()` → `stop()`
- `_run()` is `@abc.abstractmethod` — must be implemented

**Example:**
```python
class IntelligencePipelineComputeAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="intelligence_pipeline_agent", metrics_port=9125)

    async def _setup(self) -> None:
        # connect kafka, restore state checkpoint, seed fallback if needed
        ...

    async def _run(self) -> None:
        # consume bars, run I1-I7, enqueue outputs
        ...

    async def _teardown(self) -> None:
        # stop kafka clients, flush output queue
        ...
```

### Pattern 2: Async Output Buffer

**What:** `asyncio.Queue(maxsize=500)` decouples hot-path compute from Kafka publish I/O. Hot
path calls `put_nowait()` — never blocks. Background task drains and publishes.

**Source of truth:** Identical pattern used in `SignalGeneratorAgent._audit_queue` (maxsize=1000)
with `_AUDIT_DROPS` counter for drops. Phase 57 uses a unified output buffer at maxsize=500 as
specified in CONTEXT.md.

```python
# Hot path (synchronous, called from pipeline loop)
try:
    self._output_queue.put_nowait(item)
except asyncio.QueueFull:
    self._output_buffer_drops_total.inc()

# Background drain task
async def _drain_output(self) -> None:
    while not self._stop_event.is_set():
        item = await self._output_queue.get()
        # publish to topic via _kafka_producer
        self._output_queue.task_done()
```

### Pattern 3: Compacted Topic State Checkpointing

**What:** msgpack-encode state dict, publish to compacted topic keyed by `{version}:{symbol}:{tf}`.
On restart, consume from offset 0 until caught up — last value per key wins (compaction
guarantees). Seek bars consumer to `min(last_bar_offset.values()) + 1`.

**msgpack usage (verified available):**
```python
import msgpack

# Serialize
payload = msgpack.packb(state_dict, use_bin_type=True)

# Deserialize
state = msgpack.unpackb(payload, raw=False)
```

**Key format:** `v1:ESM6:1m` — prefix `v1` is bumped on breaking state schema change.
This is the zero-config cache invalidation mechanism: all existing keys stop matching on version
bump → `state_checkpoint_fallback_total` increments → automatic DB fallback via BarHistorySeeder.

### Pattern 4: Attribution Capture in Pipeline Loop

**What:** Capture `pre_quality_confidence` and `pre_calibration_confidence` per signal dict before
passing to the respective pipeline stage functions. These must be captured before the stage mutates
confidence, then carried through to the `LedgerEntry` constructor.

**Attribution invariant:** `pre_quality_confidence >= pre_calibration_confidence >= calibrated_confidence`

```python
# Immediately before quality gate
for sig in signals:
    sig["pre_quality_confidence"] = sig.get("confidence", 0.0)

quality_gated = apply_quality_gate(signals, thresholds)

# Immediately before calibration (after regime gate + TOD adjust)
for sig in regime_gated_tod_adjusted:
    sig["pre_calibration_confidence"] = sig.get("confidence", 0.0)

calibrated = apply_calibration(regime_gated_tod_adjusted, ...)
```

### Pattern 5: LedgerEntry Extension (60 params after migration)

**What:** `LedgerEntry.to_insert_params()` currently returns a 58-element tuple. Adding
`pre_quality_confidence` ($59) and `pre_calibration_confidence` ($60) extends it to 60 elements.
The migration adds two FLOAT nullable columns. New fields default to `None` for backward
compatibility with pre-phase insertions.

### Anti-Patterns to Avoid

- **Sharing consumer groups with old agents during shadow phase:** Shadow agent must use a NEW
  consumer group (e.g., `intelligence_pipeline_shadow`) to avoid stealing messages from live
  `feature_pipeline` and `signal_generator_group`.
- **Blocking the hot path with queue.put():** Always use `put_nowait()` in the compute loop;
  `put()` (blocking) would deadlock if the drain task is behind.
- **Threading locks on plugin state in async context:** `FeatureComputeAgent` uses
  `threading.Lock()` + `asyncio.to_thread()` for GARCH/HMM. The new agent must preserve this
  pattern for CPU-bound plugins. Do not replace with `asyncio.Lock()` — it won't protect
  thread-safe CPU operations.
- **Mutating signal dicts before attribution capture:** `apply_quality_gate()` returns new copies
  (confirmed from source — `result = []` with `{**sig, ...}` construction), but attribution
  capture must happen on the list BEFORE passing to the function.
- **Confusing `_tod_multipliers` vs `_tod_priors`:** Live `SignalGeneratorAgent` uses
  `_tod_multipliers`. Design doc uses `_tod_priors`. New agent should use `_tod_priors` per design
  (new code, no legacy callers), but planner must document this rename explicitly.
- **Confusing `_cis_kalman_state` vs `_kalman_state`:** Live SGA uses `_cis_kalman_state`. Design
  uses `_kalman_state`. New agent uses `_kalman_state` per design.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Binary serialization | Custom JSON encoder for numpy/deque | `msgpack` + convert to lists pre-encode | msgpack handles bytes natively; already in requirements.txt |
| Plugin state isolation | Per-bar state dict copy | Existing `_plugin_states[(plugin, symbol, tf)]` pattern from FCA | Already battle-tested across 27 I1 + 121 total plugins |
| Kafka seek on restore | Manual offset arithmetic | `KafkaConsumerClient.seek()` (check if supported) or seek via raw consumer | Check KafkaConsumerClient API for seek() before implementing |
| Metrics dedup | Direct prometheus_client | `src/observability/metrics.py` `counter()` / `gauge()` helpers | Prevents duplicate registration crash on service restart |
| Pipeline pure functions | Re-implementing quality/regime/TOD/calibration/rank/winner | `src/intelligence/pipeline.*` — all verified pure functions | Already battle-tested; no Kafka or DB I/O |
| DB seed on fallback | New seed logic | `BarHistorySeeder` from `src/core/bar_history_seeder.py` | Standalone utility, no agent-specific state, kept exactly for this purpose |

---

## Runtime State Inventory

> This phase renames/replaces two live services. Runtime state audit required.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | signal_ledger rows lack `pre_quality_confidence` / `pre_calibration_confidence` — columns don't exist yet | DB migration `052_signal_ledger_attribution.sql` — ALTER TABLE adds nullable FLOAT columns; existing rows remain NULL |
| Live service config | `indicagent-feature-compute.service` and `indicagent-signal-generator.service` installed in `/etc/systemd/system/` — both currently active (confirmed `systemctl is-active` = active) | Stop both services, disable units, delete unit files at cutover step |
| Live service config | `indicagent-intelligence-compute.service` installed in `/etc/systemd/system/` — currently failed + disabled | Delete unit file (dead service) |
| Live service config | `indicagent-indicator-compute.service` NOT installed in `/etc/systemd/system/` — absent from installed units | No unit action needed; only the service file in `services/` needs deletion |
| OS-registered state | Kafka consumer groups `feature_pipeline`, `feature_pipeline_ticks`, `signal_generator_group`, `signal_generator_resolution` — all Stable in Redpanda (verified) | New agent uses new consumer group name (e.g., `intelligence_pipeline`); old groups expire naturally after 7 days of inactivity |
| Secrets/env vars | No env var changes — new agent inherits same `INDICAGENT_ENV`, `DATABASE_URL`, `IBKR_HOST`, etc. | None |
| Build artifacts | `services/feature_pipeline_service.py` is a backward-compat shim re-exporting `FeatureComputeAgent` — will break when FCA is deleted | Delete shim at cutover alongside `feature_compute_agent.py` |
| Dead Kafka topics | `development.pipeline.quality_gated`, `.regime_gated`, `.tod_adjusted`, `.calibrated`, `.ranked` — confirmed present in Redpanda, no active consumers | Delete via `rpk topic delete` in cleanup step |

**`topic_indicators()` status (VERIFIED — DO NOT REMOVE YET):**
`src/api/main.py` and `src/api/routes/sse.py` both import and subscribe to `topic_indicators()`.
It is passed to `KafkaConsumerClient` in the SSE broadcaster startup and appended to the topic list
in `_get_sse_topics()`. This is LIVE code — the SSE API subscribes to `development.indicators`.
The planner must include: (1) verify if any producer still publishes to `development.indicators`,
(2) if no producer exists, the SSE subscription is harmless but wasted. Do NOT remove
`topic_indicators()` from stream_keys.py unless confirmed the SSE subscription is also removed.
This is out of scope for Phase 57 unless the planner confirms the full removal path.

---

## Common Pitfalls

### Pitfall 1: State Dict Contains Non-Serializable Types

**What goes wrong:** Plugin state dicts may contain `numpy.ndarray`, `deque`, `pandas.DataFrame`,
`datetime`, or custom Pydantic models. `msgpack.packb()` will raise `TypeError` on these.

**Why it happens:** I1 plugins (GARCH, HMM, Kalman) store numpy arrays in `_state`. The design
assumes "all five state fields" are checkpoint-serializable, but this requires explicit conversion.

**How to avoid:** Before msgpack encode, walk state dict recursively and convert: `np.ndarray` →
`list`, `deque` → `list`, `datetime` → ISO string, Pydantic models → `.model_dump()`. Write a
`_serialize_state()` helper. Write a `_deserialize_state()` companion that reverses conversions
where needed (e.g., restore deque from list using `deque(data, maxlen=200)`).

**Warning signs:** `TypeError: Unknown type: <class 'numpy.ndarray'>` on first checkpoint publish
after the agent processes a bar with warm plugin state.

### Pitfall 2: Compacted Topic Requires Manual Creation

**What goes wrong:** Redpanda topics default to `cleanup.policy=delete`. A compacted topic must
be created explicitly with `cleanup.policy=compact`. Creating it via the producer (auto-create)
will use broker defaults and compaction will never run.

**How to avoid:** Create topic explicitly as a Wave 0 or `_setup()` step:
```bash
docker exec redpanda rpk topic create development.intelligence.pipeline.state \
  --topic-config cleanup.policy=compact \
  --topic-config min.cleanable.dirty.ratio=0.1 \
  --topic-config segment.ms=3600000
```

**Warning signs:** State topic exists but old keys never get cleaned up, causing unbounded growth.

### Pitfall 3: KafkaConsumerClient Seek API Availability

**What goes wrong:** The state restore step requires seeking the bars consumer to
`min(last_bar_offset.values()) + 1`. If `KafkaConsumerClient` does not expose a `seek()` method,
the restore logic cannot replay missed bars.

**How to avoid:** Check `src/core/kafka_utils.py` for `seek()` / `seek_to_beginning()` methods
before implementation. `KafkaConsumerClient` already has `seek_to_beginning()` (used in
`src/api/main.py`). The planner should verify if per-offset seek is also available. If not, a
`seek_to_beginning()` + replay from earliest is the fallback (with deduplication via
`_last_bar_offset`).

**Warning signs:** `AttributeError: 'KafkaConsumerClient' object has no attribute 'seek'` at
state restore time.

### Pitfall 4: Threading Lock Pattern Must Be Preserved for CPU-Bound Plugins

**What goes wrong:** `FeatureComputeAgent` uses `threading.Lock()` per `(plugin, symbol, tf)` state
key, combined with `asyncio.to_thread()` for CPU-bound plugin execution (GARCH, HMM). If the new
agent drops the lock pattern (simplifying to pure asyncio), GARCH/HMM state will have race
conditions when multiple bars arrive concurrently.

**How to avoid:** Copy `_plugin_states_locks: dict[tuple, threading.Lock]` and `_get_state_lock()`
from `FeatureComputeAgent`. Use `asyncio.to_thread()` + lock for any plugin in
`PRICE_SENSITIVE_PLUGINS` or that manages numpy state.

**Warning signs:** GARCH sigma values drift implausibly, or KeyError on `_plugin_states` under
concurrent bar processing.

### Pitfall 5: `feature_pipeline_service.py` Shim Will Break at Cutover

**What goes wrong:** `services/feature_pipeline_service.py` re-exports `FeatureComputeAgent as
FeaturePipelineService` for backward compatibility with tests. When `feature_compute_agent.py` is
deleted, the shim import will fail, breaking any test that imports `FeaturePipelineService`.

**How to avoid:** Identify which tests import from `feature_pipeline_service.py` and update them
to import from `intelligence_pipeline_agent.py` (or just delete the shim and fix the imports). Do
this as part of the cutover plan, not after.

**Warning signs:** `ModuleNotFoundError: No module named 'services.feature_compute_agent'` in
test suite after cutover.

### Pitfall 6: Signal Generator Uses DB (SignalGeneratorAgent is NOT DB-ignorant)

**What goes wrong:** The new agent is designed to be DB-ignorant in the hot path. However,
`SignalGeneratorAgent._setup()` makes DB connections for: calibration curves, TOD multipliers,
CIS weights, perf weights, drift penalties. These must be handled by the new agent either via
DB calls in `_setup()` or via Kafka-based distribution.

**How to avoid:** The new `IntelligencePipelineComputeAgent` must preserve the DB calls from
`SignalGeneratorAgent._setup()`:
- `_load_calibration_curves_from_db()`
- `_load_tod_multipliers_from_db()`
- `_load_cis_weights_from_db()`
- `_load_perf_weights()`
- `_refresh_drift_penalties_from_db()`

These are startup-only reads with periodic refresh (14400s / 30min refresh loops). The hot path
compute loop itself never touches DB. The agent is "DB-ignorant in the hot path" — not fully
DB-free. This is consistent with the design's description of `DatabaseManager` being used only
in `_setup()` and refresh loops.

**Warning signs:** Calibration curves are empty dictionaries at startup → all `calibrated_confidence`
values are NULL in signal_ledger.

### Pitfall 7: Migration Numbering Collision

**What goes wrong:** The next migration number is not obvious — `production/migrations/` contains
both `050_drop_unused_tables.sql` and `050_intelligence_metrics.sql` (duplicate 050). The last
numerically unique prefix is 051.

**How to avoid:** Use `052_signal_ledger_attribution.sql` as the migration file name. Verify by
listing migrations sorted and taking the highest prefix + 1.

**Warning signs:** `psql` applies migrations in filesystem order — duplicate prefix means
non-deterministic application order.

---

## Code Examples

Verified patterns from official sources:

### BaseAgent Inheritance (from `src/core/agent/base.py`)
```python
# Source: src/core/agent/base.py (verified)
class IntelligencePipelineComputeAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="intelligence_pipeline_agent", metrics_port=9125)
        self._output_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        # Five checkpointed state fields (use names from design doc, not SGA legacy names)
        self._plugin_state: dict = {}          # (plugin, symbol, tf) → state dict
        self._kalman_state: dict = {}          # (symbol, tf) → {x_est, P_est}
        self._tod_priors: dict = {}            # (regime_type, tf, hour_et) → float
        self._bar_history = BarHistory(maxlen=200)
        self._last_bar_offset: dict[str, int] = {}  # "symbol:tf" → Kafka offset

    async def _setup(self) -> None:
        # 1. Attempt state restore from compacted topic
        restored = await self._restore_state_from_checkpoint()
        if not restored:
            self._state_checkpoint_fallback_total.inc()
            # 2. Fall back to BarHistorySeeder DB warm-up
            await self._seed_via_db()
        # 3. Start Kafka clients
        await self._start_kafka()
        if restored:
            await self._seek_bars_consumer()

    @abc.abstractmethod
    async def _run(self) -> None:
        ...  # main bar consumption loop
```

### Output Queue Usage (from `signal_generator_agent.py` _audit_queue pattern)
```python
# Source: services/signal_generator_agent.py lines ~499-503 (adapted)
_AUDIT_DROPS = _PrometheusCounter(...)  # FYI: Phase 57 uses metrics.counter() instead

try:
    self._output_queue.put_nowait({"topic": ..., "payload": ...})
except asyncio.QueueFull:
    self._output_buffer_drops_total.inc()
```

### msgpack State Checkpoint (new pattern)
```python
# Source: Design doc + requirements.txt verification
import msgpack

def _serialize_checkpoint(self, symbol: str, tf: str) -> bytes:
    state = {
        "plugin_state": {
            str(k): v for k, v in self._plugin_state.items()
            if k[1] == symbol and k[2] == tf
        },
        "kalman_state": self._kalman_state.get(f"{symbol}:{tf}", {}),
        "tod_priors": {str(k): v for k, v in self._tod_priors.items()},
        "bar_history": [b.model_dump() for b in self._bar_history.get(symbol, tf)],
        "last_bar_offset": self._last_bar_offset.get(f"{symbol}:{tf}", -1),
    }
    return msgpack.packb(_convert_for_msgpack(state), use_bin_type=True)

def _restore_checkpoint(self, payload: bytes) -> dict:
    return msgpack.unpackb(payload, raw=False)
```

### Attribution Capture Points (new pattern, verified against pipeline signatures)
```python
# Source: src/intelligence/pipeline/quality_gate.py (verified — returns copies, not mutates)
# Capture pre_quality_confidence BEFORE quality gate
for sig in signals:
    sig["pre_quality_confidence"] = float(sig.get("confidence", 0.0))

quality_gated = apply_quality_gate(signals, thresholds)

# ... regime gate, TOD adjust ...

# Capture pre_calibration_confidence AFTER quality gate and TOD, BEFORE calibration
for sig in regime_tod_signals:
    sig["pre_calibration_confidence"] = float(sig.get("confidence", 0.0))

calibrated = apply_calibration(regime_tod_signals, ...)
```

### LedgerEntry Extension (from `signal_ledger_repository.py`)
```python
# Current: 58-element tuple ending at $58 = regime_type_at_fire
# New: 60-element tuple adding $59 and $60
@dataclass
class LedgerEntry:
    # ... existing 58 fields ...
    pre_quality_confidence: float | None = None      # $59 — captured before quality_gate
    pre_calibration_confidence: float | None = None  # $60 — captured after quality_gate, before calibration

def to_insert_params(self) -> tuple:
    return (
        # ... existing 58 values ...
        self.pre_quality_confidence,      # $59
        self.pre_calibration_confidence,  # $60
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| IndicatorComputeAgent (I1) + IntelligenceComputeAgent (I2-I6) + SignalGeneratorService (I7) | FeatureComputeAgent (I1-I6) + SignalGeneratorAgent (I7) | Phase 40 DAG refactor | Two services instead of three |
| Redis state, no warmup | In-memory plugin state + BarHistorySeeder DB warm-up | Phase 48 | Reduced warmup but still requires DB replay |
| Pipeline stages published to 5 Kafka topics (pipeline.*) | In-process pipeline stages; 5 topics are write-only audit snapshots with no consumers | Phase 40+ | Topics exist but are unconsummated data |
| SignalGeneratorAgent consumes `intelligence` Kafka topic | **Phase 57:** I7 runs in-process on raw BarMessage | Phase 57 | Eliminates I6→I7 serialization round-trip |
| Full warmup on every restart (15m = 6.5h wait) | **Phase 57:** Compacted topic state restore (~ms) | Phase 57 | Zero-warmup restarts |

**Deprecated/outdated after Phase 57:**
- `services/intelligence_compute_agent.py`: already failed+disabled; deleted in this phase
- `services/indicator_compute_agent.py`: inactive, no unit installed; deleted in this phase
- 5 `pipeline.*` Kafka topics: no consumers; deleted after cutover
- 5 `stream_keys.py` `topic_pipeline_*` functions: removed after cutover
- Consumer groups `feature_pipeline`, `feature_pipeline_ticks`, `signal_generator_group`,
  `signal_generator_resolution`: orphaned after cutover; Redpanda auto-expires in 7 days

---

## Open Questions

1. **`topic_indicators()` / `development.indicators` — is there still a producer?**
   - What we know: SSE API (main.py + sse.py) subscribes to `development.indicators`. `indicator_compute_agent.py` produced to it (now dead/inactive). No indicator_compute unit installed.
   - What's unclear: Does any other live service publish to `development.indicators`?
   - Recommendation: Run `docker exec redpanda rpk topic describe development.indicators` to check if there are active producers. If no producers, the topic is an empty subscription. Safe to leave `topic_indicators()` in stream_keys.py for Phase 57; flag as tech debt for a dedicated API cleanup phase.

2. **KafkaConsumerClient seek API for offset-based restore**
   - What we know: `seek_to_beginning()` exists (used in SSE api). `seek()` per-partition + offset is needed for state restore.
   - What's unclear: Whether `KafkaConsumerClient` wraps the underlying `seek()` call from aiokafka/confluent-kafka.
   - Recommendation: Planner should include a Wave 0 task to verify `KafkaConsumerClient.seek()` API and add it if absent (it is a single-line wrapper around the underlying consumer).

3. **`_plugin_state` serialization complexity**
   - What we know: I1 plugin state dicts contain `numpy.ndarray`, Pydantic model instances (from GARCH/HMM), and nested dicts. `FeatureComputeAgent` has 27 I1 plugins each with per-(symbol, tf) state.
   - What's unclear: Whether all plugin state can be reduced to msgpack-serializable primitives losslessly, or whether some state (e.g., HMM fitted model) would need to be recomputed after restore anyway.
   - Recommendation: For Phase 57, checkpoint only `_kalman_state`, `_tod_priors`, `_bar_history`, and `_last_bar_offset`. Exclude `_plugin_state` from the checkpoint (mark it as "partial checkpoint"). On restore, plugins still warm up from bar replay from the checkpointed offset — but the Kalman and TOD state (slow to converge) are restored immediately. Document this as a known limitation. Full `_plugin_state` serialization can be a Phase 57.1 enhancement.

4. **Pattern reliability weights — DB call in FCA hot path**
   - What we know: `FeatureComputeAgent` calls `_load_pattern_reliability_weights(db_manager)` which uses a 15-min TTL cache from `pattern_reliability` table. `self._db = None` in FCA — it never initializes a DB connection, so the call always returns `{}` or the cached value. Effectively dead code.
   - What's unclear: Whether the new agent should wire up DB access for pattern reliability weights (which `SignalGeneratorAgent` doesn't use directly).
   - Recommendation: Preserve the same behavior — initialize `_db = None` in the new agent. The refresh loop from SignalGeneratorAgent handles CIS weights, calibration, and TOD via DB. Pattern reliability weights remain a no-op until a dedicated phase wires them properly.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Redpanda | Kafka compacted topic for state checkpoint | ✓ | Running | — |
| msgpack | State serialization | ✓ | >=1.0.0 (requirements.txt) | — |
| TimescaleDB | BarHistorySeeder DB fallback | ✓ | Running | Skip seed, live warmup |
| `indicagent-feature-compute` | Currently live — must be stopped at cutover | ✓ active | — | — |
| `indicagent-signal-generator` | Currently live — must be stopped at cutover | ✓ active | — | — |
| `indicagent-intelligence-compute` | Dead — failed+disabled, to be deleted | ✓ (failed) | — | N/A |

**Missing dependencies:** None blocking.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | `pytest.ini` in project root |
| Quick run command | `.venv/bin/pytest tests/unit/test_intelligence_pipeline_agent_pipeline.py -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PIPE-01 | BarMessage in → IntelligenceEvent + SignalResult enqueued | unit | `pytest tests/unit/test_intelligence_pipeline_agent_pipeline.py -x` | ❌ Wave 0 |
| PIPE-02 | QueueFull increments counter, pipeline continues | unit | `pytest tests/unit/test_async_output_buffer.py -x` | ❌ Wave 0 |
| PIPE-03 | State dict → msgpack → deserialize round-trip | unit | `pytest tests/unit/test_state_checkpoint_serde.py -x` | ❌ Wave 0 |
| PIPE-04 | Checkpoint payload restores all 5 state fields | unit | `pytest tests/unit/test_state_restore.py -x` | ❌ Wave 0 |
| PIPE-05 | `pre_quality >= pre_calibration >= calibrated` invariant | unit | `pytest tests/unit/test_pipeline_attribution.py -x` | ❌ Wave 0 |
| PIPE-06 | State restored after restart, output identical to continuous run | integration | `pytest tests/integration/test_intelligence_pipeline_agent_restart.py -x` | ❌ Wave 0 |
| PIPE-07 | `pre_quality_confidence` + `pre_calibration_confidence` non-null in signal_ledger | integration | `pytest tests/integration/test_signal_ledger_attribution.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/ -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full unit suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_intelligence_pipeline_agent_pipeline.py` — PIPE-01
- [ ] `tests/unit/test_async_output_buffer.py` — PIPE-02
- [ ] `tests/unit/test_state_checkpoint_serde.py` — PIPE-03
- [ ] `tests/unit/test_state_restore.py` — PIPE-04
- [ ] `tests/unit/test_pipeline_attribution.py` — PIPE-05
- [ ] `tests/integration/test_intelligence_pipeline_agent_restart.py` — PIPE-06
- [ ] `tests/integration/test_signal_ledger_attribution.py` — PIPE-07

---

## Project Constraints (from CLAUDE.md)

The following CLAUDE.md directives apply to this phase and must be enforced by the planner:

1. **Naming:** File `intelligence_pipeline_agent.py`, class `IntelligencePipelineComputeAgent`,
   systemd unit `indicagent-intelligence-pipeline`, log `logs/intelligence_pipeline_agent.log`.
   Per naming convention table: agent file = `<concept>_agent.py`, class = `PascalCase` + `ComputeAgent`.

2. **BaseAgent pattern:** `_setup()` / `_teardown()` / `self.tracer` / `self.running`. Confirmed
   interface from `src/core/agent/base.py`.

3. **Metrics:** All via `src/observability/metrics.py` `counter()` / `gauge()` helpers to prevent
   duplicate registration. Exception: labeled counters (e.g., per-stage counters with `["stage"]`
   label) must use `prometheus_client.Counter` directly — `metrics.counter()` has no label support.

4. **Stream keys:** All Kafka topics via `src/core/stream_keys.py`. Never hardcode topic strings.

5. **Timestamps:** All datetimes must be timezone-aware UTC. `datetime.now(UTC)` not `datetime.now()`.

6. **Kafka topic naming:** `development.intelligence.pipeline.state` — dots only, never colons.
   Shadow topic: `development.intelligence.shadow`.

7. **asyncpg batch inserts:** `to_insert_params()` returns Python `datetime` objects for
   `timestamptz` — do NOT use ISO strings. New FLOAT columns (`pre_quality_confidence`,
   `pre_calibration_confidence`) pass `float | None` directly.

8. **Pre-commit:** `/simplify` then `/coderabbit:code-review` before every commit.

9. **PYTHONUNBUFFERED=1:** Required in the new systemd unit file.

10. **Async mock gotcha (for tests):** `AsyncMock` with instance-level `__aiter__` yields 0
    iterations — define `__aiter__` at class level in a real class for async iterables.

11. **Consumer group names:** New agent uses `intelligence_pipeline` (bars) and
    `intelligence_pipeline_ticks` (ticks). Do NOT reuse `feature_pipeline` — it's still active
    until cutover.

---

## Sources

### Primary (HIGH confidence)
- `services/feature_compute_agent.py` — verified directly: consumer group `feature_pipeline`,
  BarHistory pattern, plugin state structure, DB seed logic, Kafka topics consumed
- `services/signal_generator_agent.py` — verified directly: consumer group `signal_generator_group`,
  BaseAgent inheritance, _tod_multipliers / _cis_kalman_state naming, DB calls in _setup(),
  pipeline.* audit topic publishing, LedgerEntry usage
- `src/core/agent/base.py` — verified: full BaseAgent interface, `_setup()/_teardown()/_run()`,
  `self.tracer`, `self.running`, `_register_signal_handlers()`, `start()` lifecycle
- `src/core/stream_keys.py` — verified: `topic_quality_gated`, `topic_regime_gated`,
  `topic_tod_adjusted`, `topic_calibrated`, `topic_ranked` all exist; `topic_indicators` exists
  and is live in SSE API
- `src/persistence/repository/signal_ledger_repository.py` — verified: 58-element
  `to_insert_params()` tuple, field positions $55-$58 = calibration fields
- `src/intelligence/pipeline/__init__.py` — verified: all 6 pure function exports, no I/O
- `requirements.txt` — verified: `msgpack>=1.0.0` present
- `systemctl is-active` — verified: feature-compute active, signal-generator active,
  intelligence-compute failed+disabled, indicator-compute inactive (no unit installed)
- `production/migrations/` — verified: highest migration prefix is 051; next is 052
- Redpanda consumer groups — verified: `feature_pipeline`, `signal_generator_group`, and
  `pipeline.*` topics all confirmed via `rpk group list` + `rpk topic list`
- `src/api/main.py` + `src/api/routes/sse.py` — verified: `topic_indicators()` is live in SSE
  broadcaster; NOT safe to remove without API change

### Secondary (MEDIUM confidence)
- Design doc `docs/plans/2026-03-29-intelligence-agent-unified-pipeline-design.md` — authoritative
  design; all locked decisions traced back to source code and confirmed implementable

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified in requirements.txt and source imports
- Architecture: HIGH — both source agents read and verified; BaseAgent interface confirmed
- Pitfalls: HIGH — each pitfall traced to specific line numbers in live source code
- State naming discrepancy (`_tod_priors` vs `_tod_multipliers`): HIGH — confirmed by reading both design doc and live SGA source

**Research date:** 2026-03-29
**Valid until:** 2026-04-28 (stable codebase; re-verify if SGA or FCA are modified before this phase executes)
