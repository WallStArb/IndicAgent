# Phase 089: Compute Performance Optimization - Research

**Researched:** 2026-05-18
**Domain:** Python asyncio pipeline architecture, plugin execution, per-bar allocation optimization
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**PERF-07 (Per-Key Concurrency Model):**
- D-01: Per-key Queue + worker tasks. Each `(symbol, tf)` key gets a dedicated `asyncio.Queue` and a long-running `asyncio.Task`. Orchestrator fans out bars to per-key queues. Sequential within key, concurrent across keys.
- D-02: Plan 06 (wave 3), after PERF-03 state threading. PERF-03 is prerequisite.
- D-03: Architecture mirrors service DAG: each `(symbol, tf)` is a DAG node with own input buffer.

**PERF-10:** Already delivered by Phase 088. Do NOT re-implement.

**PERF-04 (O(N) Plugin Targets):**
- D-05: 12 plugins with p95 > 20ms (from live OBS-01 data queried 2026-05-18)
- D-06: For `supports_incremental=True`: profile after PERF-03 first. If still slow, optimize algorithm.
- D-07: For `supports_incremental=False` (MarketProfile, SessionLevels): implement `compute_next()`, set flag True.

**Plan Structure (6 plans, 4 waves):**
- D-08: Wave 0 = Plan 01 (standalone prerequisite), Wave 1 = Plans 02+03 (parallel), Wave 2 = Plans 04→05 (sequential), Wave 3 = Plan 06
- D-09: Plans 02 and 03 can execute in parallel (different files)
- D-10: Plans 04 and 05 sequential

**Measurement:**
- D-11: OBS-01 histogram, query: `histogram_quantile(0.95, rate(intelligence_pipeline_plugin_duration_ms_milliseconds_bucket[10m]))`
- D-12: Each plan must include "before" Prometheus snapshot in success criteria
- D-13: Per-bar latency gauge `intelligence_pipeline_pipeline_latency_ms` for allocation wins (plans 02, 03)

**Renaissance Design Principles:**
- D-14: Drain N configurable (default 10), via Settings
- D-15: Plugin state flows as parameter, PluginExecutor never holds PluginStateManager reference
- D-16: Per-key workers self-managing, lifecycle owned by worker manager
- D-17: No manual profiling steps; measurement via existing Prometheus only

**FeaturePipelineExecutor (6th DAG Node):**
- D-18: Extracts `_run_i1_to_i6` (lines 628–745). Returns `FeaturePipelineResult`. File: `src/intelligence/pipeline/feature_pipeline_executor.py`
- D-25: HMM regime update via `FeaturePipelineResult.hmm_regime`; orchestrator calls `self._cache_mgr.update_hmm_regime(result.hmm_regime)`
- D-26: `to_dataframe()` dedup absorbed into D-18; FPE owns all dataframe construction

**CacheManager Stream Cache Migration:**
- D-19: Three orchestrator dicts (`_cross_asset_cache`, `_macro_cache`, `_htf_intel_cache`) migrate to CacheManager. Add `update_cross_asset()`, `update_macro()`, `update_htf_intel()` methods. Extend CacheSnapshot.

**PluginExecutor I7 Completion:**
- D-20: Add `PluginExecutor.run_i7_complete(intel_event, bar, cache_snapshot, state_mgr) -> list[dict]`

**Alpha Decay Ownership:**
- D-21: Move `_apply_alpha_decay` execution into `SignalProcessor.process()` as pre-processing step

**SignalProcessorResult Metrics:**
- D-22: 5 new OTel counters: `signal_processor_cis_null_total`, `signal_processor_dlq_total` (with `reason` label), `signal_processor_gate_rejections_total` (with `gate` label), `signal_processor_winner_total` (with `entry_type` label), `signal_processor_signals_evaluated_total`

**Cleanup (Plan 01):**
- D-24: Delete `self._df_cache` (line 162), move deferred imports (lines 485–487, 517–519), delete redundant `_plugin_cache` (lines 146–150)

**Thread Pool Saturation Check:**
- D-27: Plan 06 success criteria must measure thread pool saturation. Document finding — determines Phase 090 scope.

**Symbol Filter Foundation:**
- D-28: Add `intelligence_pipeline_symbol_filter: list[str] = []` to `Settings`
- D-29: Remove `min(12, ...)` cap from thread pool formula; new formula: `max(4, cpu_count // 2)` with Settings override
- D-30: Add `symbols: frozenset[str] | None = None` to `CacheManager.__init__`

### Claude's Discretion
- Exact `compute_next()` algorithm for MarketProfile (volume bucket structure, data type)
- Exact `compute_next()` algorithm for SessionLevels (rolling session high/low tracking)
- Whether BOCPD incremental is O(N) or O(K²) — profile first
- Whether PerKeyWorkerManager is a new class or inline (prefer new class if >50 lines)
- Exact batch size N for `_drain_output` (10 default, configurable via Settings)
- Whether `FeaturePipelineResult` carries `main_df` as DataFrame or bar_history ref

### Deferred Ideas (OUT OF SCOPE)
- Phase 090: thread pool sizing after PERF-07 saturation measurement
- Phase 090: wave-level parallelism within single bar
- HMM/BOCPD deep algorithm optimization (GPU, approximation)
- CacheSnapshot versioning with version stamp
</user_constraints>

---

## Summary

Phase 089 continues the Phase 088 god-class decomposition to completion, then adds performance wins on top of the clean architecture. The phase is well-scoped: all changes are inside `IntelligencePipelineComputeAgent` and its 5 extracted pipeline classes. Zero behavior change to signal logic, schema, or DB writes.

The post-088 orchestrator is 763 lines (down from 1928 pre-088). The current `_process_bar_inner` runs I1-I6 via `_run_i1_to_i6` (628–745) then assembles a 52-line I7 setup block before delegating to `SignalProcessor.process()`. Plan 01 extracts both remaining compute blocks into named DAG nodes (`FeaturePipelineExecutor` and an expanded `PluginExecutor.run_i7_complete()`), reducing `_process_bar_inner` to ~20 lines of pure routing.

The key correctness issue to fix (PERF-03): `plugin._state = plugin_states.get(plugin_name, {})` is assigned at line 298 (I1), 360 (tier), and 508 (I7) in `executor.py` — this is a shared mutable write before `loop.run_in_executor()` dispatch. With per-key workers (Plan 06), the same plugin instance could have `_state` overwritten by a concurrent bar before the thread-pool call fires. Plan 04 (PERF-03) must fix this before Plan 06 (PERF-07) is safe to enable.

**Primary recommendation:** Execute plans in strict wave order. Plan 01 is a prerequisite for all others. Plans 02+03 can parallelize after Plan 01. Plans 04→05→06 must be sequential due to the state threading dependency chain.

---

## Verified File State (post-088 actual line numbers)

### Orchestrator: `services/intelligence_pipeline_agent.py` (763 lines)

| Symbol | Actual Line | CONTEXT.md Reference | Match |
|--------|-------------|---------------------|-------|
| `_process_bar_inner` | 441 | 441 | EXACT |
| `_run_i1_to_i6` | 628 | 628 | EXACT |
| `_df_cache: dict = {}` | 162 | 162 | EXACT |
| `self._cross_asset_cache` | 158 | 158 | EXACT |
| `self._macro_cache` | 159 | 159 | EXACT |
| `self._htf_intel_cache` | 160 | 160 | EXACT |
| `_plugin_cache` block | 146–150 | 146–150 | EXACT |
| deferred import `_build_features_from_event` | 485–487 | 485–487 | EXACT |
| deferred import `_apply_alpha_decay` | 517–519 | 517–519 | EXACT |
| `self._executor._plugin_cache.get(task.plugin_name)` | 529–530 | 529–530 | EXACT |
| `_apply_alpha_decay(sig, tf, self._sig_proc._setup_last_fire.get(fire_key))` | 532 | 532 | EXACT |
| `bar = bar.model_copy(update={"gap_preceding": True})` | 451 | ~451 | CONFIRMED |
| `BarMessage(**msg)` | 430 | 430 | CONFIRMED |
| thread pool sizing formula with `min(12, ...)` | 169 | 169 | EXACT |
| `intelligence_thread_pool_workers` setting | 168 | EXISTS | CONFIRMED |
| `await self._process_bar(bar)` | 412 | 412 | CONFIRMED |
| `IntelligenceEvent` construction 7× comprehensions | 716–727 | 716–727 | EXACT |

All CONTEXT.md line references verified accurate against post-088 codebase.

### `src/intelligence/pipeline/executor.py`

- `plugin._state = plugin_states.get(plugin_name, {})` assignment confirmed at lines 298 (run_i1), 360 (run_tier), 508 (run_i7_plugins)
- `_timed_plugin_call` at line 76 reads `plugin._state` directly: `if getattr(plugin, "supports_incremental", False) and plugin._state`
- No `run_i7_complete()` method exists yet — confirmed (Plan 01 adds it)
- Flat `features` dual-write in `run_tiers()` confirmed at line 457: `features.update(tier_output)` into `frames.setdefault("features", {})`
- `PLUGIN_DURATION_MS` histogram already wired in `_collect_plugin_results()`

### `src/intelligence/pipeline/signal_processor.py`

- `_build_features_from_event` is a module-level function at line 79
- `_apply_alpha_decay` is a module-level function at line 58
- `CacheSnapshot` is defined in `signal_processor.py` (NOT in `cache_manager.py`)
- `SignalProcessor.process()` takes `(event, tiered, bar, symbol, tf, raw_signals, cache_snapshot)` — note `symbol` and `tf` are separate params (not derived from bar)
- Private `_setup_last_fire` accessed by orchestrator at line 532 via `self._sig_proc._setup_last_fire.get(fire_key)` — confirmed cross-boundary access
- D-22 metrics NOT yet present: `signal_processor_cis_null_total`, `signal_processor_dlq_total` with `reason` label, etc. are absent from both `signal_processor.py` and `metrics.py`
- Existing signal processor counters: `intelligence_pipeline_signals_generated_total`, `intelligence_pipeline_signals_selected_total`, `intelligence_pipeline_signal_dlq_total`

### `src/intelligence/pipeline/cache_manager.py`

- `CacheSnapshot` is NOT in `cache_manager.py` — it lives in `signal_processor.py`. The `__init__.py` re-exports it from `signal_processor`.
- CacheManager has NO stream cache methods (`update_cross_asset`, `update_macro`, `update_htf_intel`) — confirmed absent, Plan 01 adds them
- `symbols` parameter NOT in `CacheManager.__init__` — Plan 01/D-30 adds it
- CacheManager has 6 properties: `perf_weights`, `cis_weights`, `cis_kalman_params`, `calibration_curves`, `drift_penalties`, `shadow_cache`, `tod_priors`, `cis_weights_version`

### `src/intelligence/pipeline/output_queue.py`

- `drain_loop()` processes ONE item per iteration via `await asyncio.wait_for(self._queue.get(), timeout=1.0)` — confirmed O(1) drain, PERF-06 target
- No batch drain capability exists yet
- PIPE-04 contract (enqueue_blocking with back-pressure) already implemented

### `src/intelligence/pipeline/__init__.py`

- Exports: `CacheManager`, `CacheSnapshot`, `OutputQueue`, `PluginExecutor`, `PluginStateManager`, `SignalProcessor`, `SignalProcessorResult`
- Will need `FeaturePipelineExecutor` added after Plan 01

### `src/config/settings.py`

- `intelligence_thread_pool_workers` field EXISTS (line 29, alias `INTELLIGENCE_THREAD_POOL_WORKERS`)
- `intelligence_pipeline_symbol_filter` does NOT exist — Plan 01/D-28 adds it
- `output_drain_batch_size` does NOT exist — Plan 03/D-14 adds it (configurable via Settings)
- Thread pool formula confirmed at line 169: `min(12, max(4, cpu_count // 2))` — D-29 removes the `min(12, ...)` cap

### `src/observability/metrics.py`

- OTel SDK only (no `prometheus_client`): `counter()`, `gauge()`, `_meter.create_histogram()` are the creation patterns
- `PLUGIN_DURATION_MS` histogram already exists (line 39) — this is what OBS-01 queries
- No `signal_processor_*` prefixed metrics exist yet
- Pattern for new counters: `_meter.create_counter("name", description="...")` at module level, OR `counter("name", "description")` dynamically in `__init__`
- Both module-level constants (e.g. `PLUGIN_DURATION_MS`) and dynamic inline counters (e.g. `self._signal_dlq_total = counter(...)`) are used in the codebase

### Plugin Files (PERF-04 targets)

**`src/intelligence/features/i3_structure/market_profile.py`:**
- `supports_incremental: bool = False` — confirmed
- `compute_full()` uses vectorized TPO: builds `buckets` array from full bar history every call — O(N) confirmed
- `_state: dict` field present but unused (empty)
- No `compute_next()` method — confirmed absent
- `valid_asset_classes` attribute NOT declared in this class (it uses `InputSpec` only)

**`src/intelligence/features/i3_structure/session_levels.py`:**
- `supports_incremental: bool = False` — confirmed
- `compute_full()` slices full DataFrame every call (sess_n, prior_n, overnight_n) — O(N) confirmed
- No `compute_next()` — confirmed absent

**`src/intelligence/features/smc_context/bocpd_changepoint.py`:**
- `supports_incremental: bool = True` — confirmed
- `compute_next()` exists at line 100 — takes single return, calls `_update(x)` once
- BUT `_timed_plugin_call` at executor line 83 checks `plugin._state` (truthy), not a method — state must be non-empty for incremental path to fire
- PERF-03 race condition means `plugin._state` may be empty/wrong at call time — explains high p95 despite `supports_incremental=True`
- `_update()` itself: needs verification of O complexity (see BOCPD algorithm note below)

**`src/intelligence/features/smc_context/hmm_regime.py`:**
- `supports_incremental: bool = True` — confirmed
- Same PERF-03 race condition applies — incremental path may not be firing reliably
- Forward algorithm step is O(K²) per bar where K=3 states — bounded, not O(N)

---

## Architecture Patterns

### Post-089 DAG Node Map

```
IntelligencePipelineComputeAgent (orchestrator/router)
├── CacheManager           — DB caches + stream caches + refresh loops
├── PluginStateManager     — plugin state, per-key locks, checkpoint
├── FeaturePipelineExecutor  [NEW Plan 01] — I1-I6 execution, returns FeaturePipelineResult
│   └── PluginExecutor     — thread pool, plugin cache, wave execution
├── PluginExecutor         — run_i7_complete() [expanded Plan 01]
├── SignalProcessor        — signal pipeline stages, metrics, alpha decay
├── OutputQueue            — async Kafka publish buffer (batch drain Plan 03)
└── PerKeyWorkerManager    [NEW Plan 06] — per-(symbol,tf) Queue + worker tasks
```

### FeaturePipelineResult Dataclass

```python
@dataclass
class FeaturePipelineResult:
    event: IntelligenceEvent | None
    tiered: dict | None
    main_df: Any  # pandas DataFrame — reused by run_i7_complete to avoid second to_dataframe()
    hmm_regime: int | None
```

The `main_df` field avoids the double `to_dataframe()` call (D-26). FPE calls `self._bar_history.to_dataframe(symbol, tf)` once; orchestrator passes `result.main_df` into `run_i7_complete()`.

### CacheSnapshot Extension (Plan 01, D-19)

```python
@dataclass(frozen=True)
class CacheSnapshot:
    # Existing fields (unchanged):
    perf_weights: dict
    calibration_curves: dict
    tod_priors: dict
    drift_penalties: dict
    cis_weights: dict
    cis_weights_version: int
    # New fields (D-19):
    cross_asset_data: dict  # keyed by tf
    macro_data: dict        # keyed by tf
    htf_intel: dict         # keyed by tf
```

CacheSnapshot is defined in `signal_processor.py`. Extension must be added there. The `__init__.py` re-exports it — no change needed there after extension.

### Plugin State Threading Pattern (PERF-03)

Current broken pattern (creates race):
```python
# In executor.py run_i1/run_tier/run_i7_plugins — BEFORE dispatch:
plugin._state = plugin_states.get(plugin_name, {})
# ... then:
loop.run_in_executor(self._thread_pool, _timed_plugin_call, plugin, frames)
```

Fixed pattern (state as parameter):
```python
# compute_full and compute_next receive state explicitly:
def _timed_plugin_call(plugin, frames, state: dict):
    t0 = time.perf_counter()
    if getattr(plugin, "supports_incremental", False) and state:
        result = plugin.compute_next(frames, state=state)
    else:
        result = plugin.compute_full(frames, state=state)
    duration_ms = (time.perf_counter() - t0) * 1000
    return result, duration_ms
```

Plugin protocol (`src/intelligence/plugins.py`) must be updated: `compute_full(self, frames, state: dict | None = None)` and `compute_next(self, windows, state: dict | None = None)`. All 132+ plugins must be updated — this is the highest-touch change in the phase.

**Critical note:** The state return contract (plugins return `{"_state": new_state, ...other_outputs}`) already exists and is handled by `_collect_plugin_results`. That contract is unchanged — only the INPUT delivery changes.

### Batch Drain Pattern (PERF-06)

Current (one item per iteration):
```python
topic, key, value = await asyncio.wait_for(self._queue.get(), timeout=1.0)
await self._producer.publish(topic, msg=value, key=key)
self._queue.task_done()
```

New pattern (drain up to N):
```python
# Drain first item (blocking with timeout)
topic, key, value = await asyncio.wait_for(self._queue.get(), timeout=1.0)
batch = [(topic, key, value)]
# Drain remaining items non-blocking (up to N-1 more)
for _ in range(self._batch_size - 1):
    try:
        batch.append(self._queue.get_nowait())
    except asyncio.QueueEmpty:
        break
# Publish batch (calls must be awaited individually — KafkaProducerClient.publish is async)
for t, k, v in batch:
    try:
        await self._producer.publish(t, msg=v, key=k)
    except Exception:
        self._publish_failures.add(1)
    finally:
        self._queue.task_done()
```

**Note on KafkaProducerClient:** The `publish()` kwarg is `msg=` (not `value=`) per CLAUDE.md rule. Silent failure if wrong kwarg used.

### PerKeyWorkerManager Pattern (Plan 06)

```python
class PerKeyWorkerManager:
    """Self-managing per-(symbol,tf) worker task pool.

    Each key gets a dedicated asyncio.Queue and a long-running Task.
    Orchestrator calls start_per_key_workers() once in _setup().
    enqueue(bar) fans out to the correct per-key queue.
    """
    def __init__(self, keys: list[tuple[str, str]], process_bar_fn, symbol_filter: list[str]):
        # Filter keys by symbol_filter if non-empty
        ...
    def start_per_key_workers(self) -> list[asyncio.Task]: ...
    async def enqueue(self, bar: BarMessage) -> None: ...
    async def teardown(self) -> None: ...  # drains + cancels all tasks
```

Pattern mirrors `CacheManager.start_refresh_loops()` and `PluginStateManager.start_checkpoint_loop()` from Phase 088 — the orchestrator calls `start_*()` once and stores task handles, worker lifecycle is self-managed.

### Incremental Algorithm Guidance

**MarketProfile `compute_next()` strategy (Claude's discretion):**
The current `compute_full()` rebuilds the full TPO bucket array every call (O(N×B) where N=bars, B=buckets). Incremental approach: maintain a `tpo_counts` array in state, subtract the oldest bar's contribution and add the newest bar's contribution on each call. Key implementation notes:
- State stores: `tpo_counts: np.ndarray`, `buckets: np.ndarray`, `low_min: float`, `high_max: float`
- Challenge: when price range expands (new bar breaks old high/low), buckets must be recomputed — fall back to `compute_full()` in that case
- Recommend: `compute_next()` checks if new bar extends range; if yes, delegates to `compute_full()` + updates state; if no, updates incrementally

**SessionLevels `compute_next()` strategy (Claude's discretion):**
Session levels are window-based (not cumulative). The "incremental" benefit is avoiding full DataFrame slice every bar. State stores session boundaries (start index, window sizes). `compute_next()` checks if session boundary shifted; if not, only recomputes level distances from latest close. Rolling windows (390-bar session) mean most bars don't shift session boundaries.

**BOCPD incremental complexity:**
`compute_next()` calls `_update(x)` once (O(K) where K=max_run_length=200). After `_reset_state()`, the state array `run_length_probs` is size 200. The `_update()` method updates all K run-length entries — confirmed O(K) not O(N) per bar. The high p95 (77.9ms) is likely the PERF-03 race causing fallback to `compute_full()` (which runs N×`_update()` calls). Fixing PERF-03 should resolve BOCPD's p95 without algorithm changes.

**HMM incremental complexity:**
Forward algorithm step is O(K²) per bar where K=3. Current ~35ms p95 for 1m HMM is likely also PERF-03 fallback to full recomputation. After PERF-03 fix, each bar is O(9) matrix ops — should be sub-millisecond.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Kafka batch publish | Custom producer pool | Existing `KafkaProducerClient.publish()` in a loop | Producer handles connection, retry, serialization |
| Per-key task scheduling | asyncio.Semaphore + task pool | Per-key `asyncio.Queue` + dedicated `asyncio.Task` | Simpler, no cross-key synchronization |
| State parameter threading | Pickle/deepcopy per call | Pass state dict reference (copy if needed) | State dicts are per-key already isolated |
| Plugin incremental tracking | External state registry | `_state` dict returned from plugin | Already the established contract |
| New metrics infrastructure | prometheus_client, statsd | OTel SDK via `src/observability/metrics.py` | prometheus_client fully removed in Phase 83 |
| Manual profiling | cProfile, py-spy scripts | Existing `PLUGIN_DURATION_MS` histogram | D-17: no manual profiling ceremony |

---

## Common Pitfalls

### Pitfall 1: PERF-03 Half-Fix (State Threading)
**What goes wrong:** Developer adds `state=` parameter to `_timed_plugin_call` but forgets to update one of three call sites (run_i1, run_tier, run_i7_plugins). The missed site still uses `plugin._state = ...` assignment. Test suite passes because unit tests mock plugins.
**Prevention:** Update `_timed_plugin_call` signature first, then update all three call sites together. Grep for `plugin._state =` in executor.py — zero results after fix.
**Warning sign:** Any remaining `plugin._state =` assignment in executor.py.

### Pitfall 2: Plugin Protocol Breadth (PERF-03)
**What goes wrong:** 132+ plugins implement `compute_full(self, frames)` and `compute_next(self, windows)` without `state=` parameter. Adding `state=` to the protocol doesn't break existing plugins if the parameter is optional (`state: dict | None = None`) with default. Plugins that DON'T return `_state` in their output dict are unaffected by the state input change.
**Prevention:** Make `state` optional with default `None`. Plugins that need to use injected state read `state or {}`. Plugins that don't care ignore it.
**Warning sign:** Any plugin raising `TypeError: compute_full() got unexpected keyword argument 'state'`.

### Pitfall 3: CacheSnapshot in signal_processor.py
**What goes wrong:** Developer looks for CacheSnapshot in `cache_manager.py` (natural location), doesn't find it, creates a duplicate or imports from wrong place.
**Root cause:** CacheSnapshot was extracted into `signal_processor.py` during Phase 088. The `__init__.py` re-exports it.
**Prevention:** Always import CacheSnapshot from `src.intelligence.pipeline` (the package `__init__`) or explicitly from `src.intelligence.pipeline.signal_processor`. When extending CacheSnapshot with stream cache fields (D-19), edit `signal_processor.py`.

### Pitfall 4: Deferred Import Removal Timing
**What goes wrong:** Developer removes deferred imports at lines 485–487 and 517–519 before Plan 01 is complete. The top-level imports fail or create circular dependencies if the refactored functions aren't fully moved.
**Prevention:** Remove deferred imports in Plan 01 AFTER D-18 (FPE) and D-21 (alpha decay in SignalProcessor) are both complete. The deferred imports exist specifically because the functions will eventually not be called from the orchestrator.

### Pitfall 5: run_i7_complete Signature vs SignalProcessor.process()
**What goes wrong:** `run_i7_complete()` is given `state_mgr` as a parameter (D-20 signature) and internally calls `state_mgr.get_all_states_for()` and `state_mgr.get_lock()` — but PluginExecutor must remain DB-ignorant and must not hold PluginStateManager reference (D-15).
**Resolution:** `run_i7_complete()` receives `state: dict, lock: threading.Lock` as pre-fetched parameters (not `state_mgr`). Orchestrator calls `self._state_mgr.get_all_states_for(symbol, tf)` and `self._state_mgr.get_lock((symbol, tf))` before passing to `run_i7_complete()`. The D-20 description says `state_mgr` but D-15 says PluginExecutor never holds a reference — resolve in favor of D-15 (pre-fetched parameters).

### Pitfall 6: to_dataframe() Double-Call After FPE Extraction
**What goes wrong:** After extracting FPE, a developer adds a call to `to_dataframe()` in the orchestrator for I7 (e.g., to build `plugin_input["main"]`), not realizing `main_df` is already in `FeaturePipelineResult`.
**Prevention:** `run_i7_complete()` accepts `main_df: DataFrame` as a parameter from `FeaturePipelineResult.main_df`. The orchestrator passes `result.main_df` directly. No `to_dataframe()` call in orchestrator after Plan 01.

### Pitfall 7: Per-Key Worker Race on _process_bar_inner
**What goes wrong:** After PERF-07, `_process_bar_inner` is called concurrently from multiple per-key workers. If any orchestrator-level mutable state (e.g., `self._last_bar_ts`, `self._last_events`, `self._prev_i1_features`) is accessed without protection, data races occur.
**Resolution per CONTEXT.md:** After Plan 01 (FPE extraction), `_last_events` and `_prev_i1_features` move INTO `FeaturePipelineExecutor` as instance state. FPE instance is per-orchestrator (not per-key), so FPE must use per-key keyed dicts internally. `_last_bar_ts` stays in orchestrator but is keyed by `f"{symbol}:{tf}"` — each key only touches its own entry; no race between keys.
**Warning sign:** THREAD-02 requirement mentions `_cross_asset_cache` and `_macro_cache` need `asyncio.Lock` protection for concurrent per-key workers. After D-19 migrates them to CacheManager, CacheManager's atomic replacement pattern handles this safely.

### Pitfall 8: OutputQueue.drain_loop task_done() Under Batch Drain
**What goes wrong:** With batch drain, `task_done()` must be called once per `get()` call (not once per batch). If items are `get_nowait()`'d in the batch loop, each must have its own `task_done()`.
**Prevention:** Use try/finally in the inner loop — each dequeued item (whether from the blocking `get()` or from `get_nowait()`) must call `task_done()` in its own `finally` block. The existing `drain_loop` has this pattern for the single-item case; replicate it per item in the batch.

---

## Code Examples

### OTel Counter Creation Pattern (for Plan 01 SignalProcessorResult metrics)

```python
# Source: src/observability/metrics.py pattern (module-level, HIGH confidence)
SIGNAL_PROCESSOR_CIS_NULL_TOTAL = _meter.create_counter(
    "signal_processor_cis_null_total",
    description="CIS scoring returned None — no score available for this bar",
)
SIGNAL_PROCESSOR_DLQ_TOTAL = _meter.create_counter(
    "signal_processor_dlq_total",
    description="Signals routed to DLQ",
)
SIGNAL_PROCESSOR_GATE_REJECTIONS_TOTAL = _meter.create_counter(
    "signal_processor_gate_rejections_total",
    description="Signal gate rejections by gate type",
)
SIGNAL_PROCESSOR_WINNER_TOTAL = _meter.create_counter(
    "signal_processor_winner_total",
    description="Winner signals selected by entry type",
)
SIGNAL_PROCESSOR_SIGNALS_EVALUATED_TOTAL = _meter.create_counter(
    "signal_processor_signals_evaluated_total",
    description="Total signals entering the pipeline per bar",
)

# Call-site pattern (with labels):
SIGNAL_PROCESSOR_DLQ_TOTAL.add(1, {"reason": "cis_score_null"})
SIGNAL_PROCESSOR_GATE_REJECTIONS_TOTAL.add(1, {"gate": "regime"})
SIGNAL_PROCESSOR_WINNER_TOTAL.add(1, {"entry_type": winner.get("entry_type", "unknown")})
```

### Settings Field Addition Pattern (D-28, D-29)

```python
# Source: src/config/settings.py existing pattern (HIGH confidence)
intelligence_pipeline_symbol_filter: list[str] = Field(
    default_factory=list,
    validation_alias="INTELLIGENCE_PIPELINE_SYMBOL_FILTER",
    description="Symbols this process handles. Empty = all active contracts.",
)
output_drain_batch_size: int = Field(
    default=10,
    validation_alias="OUTPUT_DRAIN_BATCH_SIZE",
    description="Max items drained from output queue per drain_loop iteration.",
)
```

Thread pool formula change (D-29) — remove `min(12, ...)`:
```python
# Before (line 169):
_workers = _configured if _configured > 0 else min(12, max(4, cpu_count // 2))
# After (D-29):
_workers = _configured if _configured > 0 else max(4, cpu_count // 2)
```

### asyncio.Queue Per-Key Worker Pattern (Plan 06)

```python
# Source: asyncio standard library patterns + existing OutputQueue pattern
class PerKeyWorkerManager:
    def __init__(
        self,
        keys: list[tuple[str, str]],
        process_bar_fn,  # Callable[[BarMessage], Coroutine]
        symbol_filter: list[str],
    ) -> None:
        active_keys = (
            [k for k in keys if k[0] in symbol_filter]
            if symbol_filter else keys
        )
        self._queues: dict[tuple[str, str], asyncio.Queue] = {
            k: asyncio.Queue(maxsize=100) for k in active_keys
        }
        self._process_bar_fn = process_bar_fn
        self._tasks: list[asyncio.Task] = []

    def start_per_key_workers(self) -> list[asyncio.Task]:
        for key, queue in self._queues.items():
            task = asyncio.create_task(self._worker(key, queue), name=f"worker_{key}")
            self._tasks.append(task)
        return list(self._tasks)

    async def enqueue(self, bar: BarMessage) -> None:
        key = (bar.symbol, bar.tf)
        queue = self._queues.get(key)
        if queue is not None:
            await queue.put(bar)

    async def _worker(self, key: tuple, queue: asyncio.Queue) -> None:
        while True:
            bar = await queue.get()
            try:
                await self._process_bar_fn(bar)
            except Exception as exc:
                _logger.error("per_key_worker.error", key=key, error=str(exc))
            finally:
                queue.task_done()
```

### FeaturePipelineExecutor Constructor Pattern (Plan 01)

```python
class FeaturePipelineExecutor:
    def __init__(
        self,
        bar_history: BarHistory,
        executor: PluginExecutor,
        state_mgr: PluginStateManager,
        instrument_map: dict,
        vix_symbol: str | None,
    ) -> None:
        # Carry-forward state (owned by FPE, not orchestrator):
        self._last_events: dict = {}
        self._prev_i1_features: dict = {}
        # Read-only references:
        self._bar_history = bar_history
        self._executor = executor
        self._state_mgr = state_mgr
        self._instrument_map = instrument_map
        self._vix_symbol = vix_symbol

    async def run(
        self, bar: BarMessage, cache_snapshot: CacheSnapshot
    ) -> FeaturePipelineResult:
        # Body = _run_i1_to_i6 contents (lines 628–745), reading
        # cross_asset_data/macro_data/htf_intel from cache_snapshot
        ...
```

---

## State of the Art

| Old Approach | Current Approach | Changed | Impact |
|--------------|------------------|---------|--------|
| 1928-line god class | 763-line orchestrator + 5 extracted DAG nodes | Phase 088 | Foundation for Phase 089 perf wins |
| Sequential per-bar processing | Per-key concurrent workers (PERF-07) | Phase 089 Plan 06 | Independent keys don't block each other |
| `plugin._state =` before dispatch | `state=` parameter threading (PERF-03) | Phase 089 Plan 04 | Eliminates race condition |
| `BarMessage(**msg)` full validation | `BarMessage.model_construct(**msg)` on hot path | Phase 089 Plan 02 | Skips validation for trusted internal msgs |
| One Kafka `await` per drain iteration | Batch drain up to N items (PERF-06) | Phase 089 Plan 03 | Amortizes Kafka round-trip over bursts |
| 7× None-filter comprehensions at event construction | Pre-filtered dicts during wave merge (PERF-05) | Phase 089 Plan 02 | Eliminates dict comprehension allocations |

---

## Open Questions

1. **`run_i7_complete()` state parameter vs state_mgr parameter**
   - D-20 says `run_i7_complete(intel_event, bar, cache_snapshot, state_mgr)` but D-15 says PluginExecutor must not hold PluginStateManager reference
   - What we know: Orchestrator already calls `self._state_mgr.get_all_states_for()` and `self._state_mgr.get_lock()` before calling `run_i7_plugins()`
   - Recommendation: `run_i7_complete(intel_event, bar, cache_snapshot, plugin_states: dict, lock: threading.Lock)` — pre-fetched by orchestrator. This resolves D-20/D-15 conflict cleanly. Planner should make this explicit in Plan 01.

2. **FPE ownership of state_mgr reference**
   - FPE needs to call `self._state_mgr.get_all_states_for(symbol, tf)` and `self._state_mgr.update_batch(updates)` for both I1 and I2-I6 tiers
   - PluginExecutor's no-reference contract is specifically stated for PluginExecutor — FPE is a different class and orchestrator-level DAG node
   - Recommendation: FPE holds PluginStateManager reference (it's a DAG node at the orchestrator level, not the plugin executor level). This is consistent with D-18's description of FPE owning `_prev_i1_features` + `_last_events` carry-forward state.

3. **CacheSnapshot frozen dataclass extension**
   - `CacheSnapshot` is `@dataclass(frozen=True)` — adding new fields requires updating all call sites where `CacheSnapshot(...)` is constructed
   - Call site is in `_process_bar_inner` at lines 538–545
   - Recommendation: Plan 01 must update the `CacheSnapshot` constructor call at line 538–545 to pass the three new fields. After D-19 migrates stream caches to CacheManager, the orchestrator reads `self._cache_mgr.cross_asset_data`, etc.

---

## Test Patterns to Follow

All pipeline unit tests in `tests/unit/pipeline_tests/` follow this pattern:
- `_make_executor()` / `_make_processor()` / `_make_snapshot()` factory functions at module level
- `MagicMock()` for external dependencies (CIS scorer, settings, DB)
- Tests verify structural contracts (no lateral imports, 3-tuple state keys, parameter passing) not algorithmic correctness
- Each test file covers one class with explicit "Proves:" docstring listing invariants

New test files needed:
- `tests/unit/pipeline_tests/test_feature_pipeline_executor.py` — proves FPE owns carry-forward state, reads from CacheSnapshot (not orchestrator dicts), returns FeaturePipelineResult
- `tests/unit/pipeline_tests/test_per_key_worker_manager.py` — proves enqueue routes to correct key, workers start/stop, symbol_filter scoping

Existing tests to update:
- `tests/unit/pipeline_tests/test_executor.py` — add `test_run_i7_complete_returns_raw_signals`, `test_state_not_assigned_to_plugin_attr`
- `tests/unit/pipeline_tests/test_signal_processor.py` — add tests for D-22 counters, `_apply_alpha_decay` being called in `process()`
- `tests/unit/pipeline_tests/test_cache_manager.py` — add tests for stream cache methods and `symbols` scoping

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection of all referenced files — post-088 line numbers verified
- `services/intelligence_pipeline_agent.py` — 763 lines, all CONTEXT.md references confirmed
- `src/intelligence/pipeline/executor.py` — plugin._state assignment pattern confirmed at 3 sites
- `src/intelligence/pipeline/signal_processor.py` — CacheSnapshot location, _apply_alpha_decay confirmed
- `src/intelligence/pipeline/cache_manager.py` — stream cache methods absence confirmed
- `src/intelligence/pipeline/output_queue.py` — single-item drain confirmed
- `src/intelligence/features/i3_structure/market_profile.py` — O(N) TPO rebuild confirmed
- `src/intelligence/features/smc_context/bocpd_changepoint.py` — compute_next() O(K) confirmed
- `src/observability/metrics.py` — OTel SDK patterns, PLUGIN_DURATION_MS histogram confirmed
- `src/config/settings.py` — intelligence_thread_pool_workers exists, symbol_filter absent confirmed

### Secondary (MEDIUM confidence)
- BOCPD O(K) complexity: inferred from `_update()` iterating over `max_run_length=200` entries per call, not over N bars. Would need profiling to confirm at 77.9ms p95 — but the PERF-03 race hypothesis is the more likely explanation.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries (asyncio, OTel SDK) are existing project dependencies
- Architecture: HIGH — all patterns verified against actual post-088 code
- Pitfalls: HIGH — identified from direct code inspection of the three race condition sites
- Plugin algorithms: MEDIUM — BOCPD/HMM complexity inferred from code; not profiled live

**Research date:** 2026-05-18
**Valid until:** 2026-06-17 (30 days — stable Python/asyncio patterns)
