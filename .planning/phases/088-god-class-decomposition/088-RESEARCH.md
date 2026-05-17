# Phase 088: God Class Decomposition - Research

**Researched:** 2026-05-17
**Domain:** Python class decomposition, dependency injection, asyncio patterns
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** New module `src/intelligence/pipeline/` with 5 files: `executor.py`, `state_manager.py`, `signal_processor.py`, `cache_manager.py`, `output_queue.py`, plus `__init__.py` exporting all public classes.
**D-02:** `services/intelligence_pipeline_agent.py` becomes a thin orchestrator (~100 lines) that imports from `src/intelligence/pipeline/`, constructs the 5 classes in `_setup()`, and delegates in `_process_bar_inner()`.
**D-03:** Each new file is a proper Python module — no inner classes, no nested definitions.
**D-04:** Constructor injection with precisely-scoped dependencies per class. No `PipelineContext` bag (service locator anti-pattern).
**D-05:** Precise constructor signatures (see CONTEXT.md).
**D-06:** Orchestrator constructs all 5 in `_setup()` and holds them as `self._state_mgr`, `self._cache_mgr`, `self._executor`, `self._sig_proc`, `self._out_queue`.
**D-07:** Orchestrator mediates ALL inter-class data flow. No lateral coupling between classes.
**D-08:** `_process_bar_inner()` becomes a DAG description (see CONTEXT.md snippet).
**D-09:** `PluginStateManager` owns `_plugin_states`, `_plugin_states_locks`, and checkpoint.
**D-10:** `PluginExecutor` never holds a reference to `PluginStateManager`. Receives `state: dict` and `lock: asyncio.Lock` per call.
**D-11:** `CacheManager` owns all 6 live cache dicts as properties (atomic dict replacement on refresh).
**D-12:** `CacheManager.start_refresh_loops()` creates and returns all 6 background `asyncio.Task`s. Orchestrator stores them in `_background_tasks`.
**D-13:** Refresh intervals unchanged: perf_weights=3600, drift_penalties=14400, cis_weights=1800, calibration_curves=1800, tod_multipliers=14400, shadow_cache=300.
**D-14:** `PluginStateManager` owns a background checkpoint loop. Orchestrator calls `state_mgr.start_checkpoint_loop(interval_sec)` in `_setup()`.
**D-15:** Checkpoint still raises on failure.
**D-16:** Each class creates its own OTel metrics internally. Zero metrics wiring in orchestrator.
**D-17:** Extraction order: OutputQueue → PluginStateManager → CacheManager → PluginExecutor → SignalProcessor.
**D-18:** After plan 05, service file should be ~100 lines.
**D-19:** Plans 01-03 are independent (Wave 1, parallel). Plans 04-05 are sequential (Wave 2).
**D-20:** Each extracted class must have a dedicated unit test file at `tests/unit/pipeline_tests/test_{class_name}.py`.
**D-21:** All existing `tests/unit/service_tests/test_intelligence_pipeline_*.py` tests must remain green after each plan.

### Claude's Discretion
- Exact method signatures within each class (beyond the public interface contracts in D-05/D-08)
- Internal implementation of `_run_refresh_loop` (can remain a shared utility or be inlined)
- Whether to use `@dataclass` for any of the 5 classes
- Precise test fixture design

### Deferred Ideas (OUT OF SCOPE)
- Phase 089 (PERF): Plugin state threading as parameter to eliminate `plugin._state =` mutation before thread-pool dispatch.
- Async PluginStateManager: State operations are sync (dict access). Could be made async with asyncio.Lock.
- Protocol/ABC interfaces: Formal typed interfaces for the 5 classes.
</user_constraints>

---

## Summary

The `IntelligencePipelineComputeAgent` is exactly 1928 lines and contains five separable concerns packed into a single class. This is a pure structural refactoring — all behavior, metrics names, and external contracts are preserved. The extraction follows the "microservices DAG within the process" topology: each class is a DAG node with typed I/O, the orchestrator is the router, and no lateral coupling exists between nodes.

The key technical challenge is the module naming conflict: `src/intelligence/pipeline/` already exists and contains pure function pipeline stages (`quality_gate.py`, `ranker.py`, etc.). The five new classes must coexist in that same package (new files added to the existing package) or the planner must clarify the target location. The existing `__init__.py` exports only the pipeline stage functions; it will need updating to also export the five new classes.

The existing test infrastructure (`tests/unit/pipeline_helpers.py`, `tests/unit/test_pipeline_*.py`) uses `IntelligencePipelineComputeAgent.__new__()` to bypass `__init__`. After extraction, these tests will continue to work against the agent — but D-20 also requires new per-class test files at `tests/unit/pipeline_tests/`. There is no existing `pipeline_tests/` subdirectory; it must be created with an `__init__.py`.

**Primary recommendation:** Extract classes in D-17 order. Create `tests/unit/pipeline_tests/` directory. Add new files to the existing `src/intelligence/pipeline/` package — do not rename or restructure existing files.

---

## Critical Pre-Planning Finding: Module Naming Conflict

`src/intelligence/pipeline/` **already exists** and contains:
```
src/intelligence/pipeline/
├── __init__.py          # exports apply_quality_gate, apply_regime_gate, apply_calibration,
│                        #   rank_signals, apply_tod_adjustment, select_winner
├── calibrator.py
├── quality_gate.py
├── ranker.py
├── regime_gate.py
├── tod_adjuster.py
└── winner_selector.py
```

The intelligence pipeline agent already imports from this package:
```python
from src.intelligence.pipeline import (
    apply_calibration, apply_quality_gate, apply_regime_gate,
    apply_tod_adjustment, rank_signals, select_winner,
)
```

D-01 says to create `src/intelligence/pipeline/` with 5 files. The planner must treat this as: add 5 new files to the existing package (not create a new package from scratch). The existing `__init__.py` exports stage functions; it should be extended to also export the 5 new classes. **Do not modify or remove any existing files in this package.**

---

## Existing Code Inventory (Per-Class)

### OutputQueue (lines ~1030-1057)

The output queue logic is already compact. Current state:

```python
# __init__ attrs to move:
self._output_queue: asyncio.Queue = asyncio.Queue(maxsize=_OUTPUT_QUEUE_MAXSIZE)  # line 478
self._output_buffer_drops = counter(...)   # line 497
self._output_buffer_depth = gauge(...)     # line 493
self._output_publish_failures = counter(...) # line 501

# Methods to move:
def _enqueue(topic, key, value) -> None:         # line 1030 — non-blocking, drops on full
async def _enqueue_blocking(topic, key, value):  # line 1037 — blocks on full (Phase 086 contract)
async def _drain_output() -> None:               # line 1044 — background drain loop
```

Constructor per D-05: `OutputQueue(producer: KafkaProducerClient, maxsize: int)`

The orchestrator's `_teardown()` calls `await asyncio.wait_for(self._output_queue.join(), timeout=10.0)` — this must remain accessible. OutputQueue should expose a `join()` method (or expose the queue directly) and a `drain_loop()` coroutine for `_run()` to schedule.

### PluginStateManager (lines ~559-571, 1563-1598)

```python
# __init__ attrs to move:
self._plugin_states: dict = {}          # line 431
self._plugin_states_locks: dict = {}    # line 432

# Methods to move:
def _get_state_lock(key: tuple) -> threading.Lock:  # line 567 — lazy-init lock
def _write_local_checkpoint() -> None:               # line 1565 — raises on failure (Phase 086)
async def _read_local_checkpoint() -> bool:          # line 1575 — restore on startup
```

D-09: also owns checkpoint path/file logic. Constant `_CHECKPOINT_PATH = Path("cache/pipeline_checkpoint.json")` at line 307 moves here. Constants `_CHECKPOINT_FIELDS`, `_AGENT_VERSION` also move.

D-14: adds a new background `start_checkpoint_loop(interval_sec)` method — not currently in the codebase. The orchestrator's `_teardown()` calls `self._write_local_checkpoint()` directly; after extraction this becomes `self._state_mgr.write_checkpoint()` (or `checkpoint_now()`).

Helper functions `_restore_tuple_key()`, `_tag_value`, `_untag_value` (from `src.core.state_serializer`) are used in checkpoint read/write — they move with the checkpoint logic.

### CacheManager (lines ~626-638, 1771-1920)

```python
# __init__ attrs to move:
self._perf_weights: dict = {}       # line 467
self._cis_weights_cache: dict = {}  # line 464
self._cis_kalman_params: dict = {}  # line 465
self._calibration_curves: dict = {} # line 466
self._drift_penalties: dict = {}    # line 468
self._shadow_cache: dict = {}       # line 419
self._pattern_reliability: dict = {}# line 450  (note: also has module-level cache)
self._tod_priors: dict = {}         # line 444  (NOTE: also written by _load_tod_multipliers)

# Methods to move (all ~_load_*):
async def _load_perf_weights()          # line 1771 (~65 lines, regime-conditioned)
async def _load_shadow_cache()          # line 1839
async def _refresh_drift_penalties()    # line 1850
async def _load_cis_weights()          # line 1854
async def _load_calibration_curves()   # line 1871
async def _load_tod_multipliers()      # line 1900
async def _run_refresh_loop(load_fn, interval_sec)  # line 1748 (generic loop)
def _current_hmm_regime_label() -> str # line 1757 (needed by _load_perf_weights)
```

`start_refresh_loops()` creates and returns 6 `asyncio.Task`s per D-12. Each task wraps `_run_refresh_loop(load_fn, interval_sec)`.

Tricky: `_cis_scorer.update_weights()` is called inside `_load_cis_weights`. Per D-05, `CacheManager(db, settings)` — it does NOT own `_cis_scorer`. SignalProcessor owns the scorer. The planner must decide whether CacheManager calls a callback when CIS weights update, or SignalProcessor references the cache's `cis_weights` property and calls `update_weights()` itself in `_process_bar_inner()`. The orchestrator-mediated pattern (D-07) suggests: CacheManager loads weights, SignalProcessor.cis_scorer is updated by the orchestrator after cache refresh.

The `_pattern_reliability` dict is currently backed by a module-level cache (`_pattern_reliability_cache`/`_pattern_reliability_cache_ts`) in addition to the instance dict. CacheManager should internalize this entirely (remove the module-level cache, own it as an instance property with its own TTL logic).

`_tod_priors` is special: `_load_tod_multipliers` does `self._tod_priors = {**self._tod_priors, **priors}` — a merge, not a replace. This merge behavior must be preserved in CacheManager.

CacheManager also needs `_cis_kalman_params` (loaded from a config file, not DB). Per D-05 constructor `CacheManager(db, settings)`, this config file load can happen in `__init__` directly (it's a one-time JSON read, not a refresh loop). The function `_load_cis_kalman_params()` at line 171 moves into CacheManager.

`_last_hmm_regime` (line 470) drives `_current_hmm_regime_label()` and thus `_load_perf_weights`. Currently updated in `_run_i7_inner`. After extraction, the orchestrator must call `cache_mgr.update_hmm_regime(hmm_val)` when processing each bar. CacheManager owns this field and exposes `current_hmm_regime_label()` as a method.

### PluginExecutor (lines ~1119-1248)

```python
# __init__ attrs to move:
self._executor: ThreadPoolExecutor      # line 459
self._plugin_cache: dict                # lines 422-426
self._instrument_map: dict              # line 428
self._plugin_circuit_breakers: dict     # line 481
self._plugin_call_counts: dict          # line 535
self._plugin_skipped_total = counter()  # line 536

# Methods to move:
def _get_plugin_cb(plugin_name) -> CircuitBreaker  # line 559 — lazy-init CB
def _is_shadow(plugin_name) -> bool                # line 573
def _update_plugin_state(task, output)             # line 1063 — writes state back; TRICKY
def _collect_plugin_results(tasks, results, log_prefix)  # line 1069
async def _run_i1(frames, symbol, tf) -> dict      # line 1123
async def _run_tier(tier_key, tier_plugins, symbol, tf, frames, loop) -> dict  # line 1193
async def _run_analysis_pipeline(symbol, tf, frames) -> dict | None  # line 1250
async def _run_i7_inner(bar, event, tiered) -> dict  # I7 plugin execution portion only
```

The `_run_i7_inner` method has two responsibilities: (a) running I7 plugins and collecting raw signals (PluginExecutor concern), and (b) running the pipeline stages and publishing signals (SignalProcessor concern). The split must happen inside `_run_i7_inner`. PluginExecutor should expose something like `run_i7_plugins(symbol, tf, bar, plugin_input) -> tuple[list[dict], list[PluginTask]]` and SignalProcessor takes it from there.

`_update_plugin_state` is entangled with state storage (PluginStateManager) but called inside result collection (PluginExecutor). Per D-10, PluginExecutor receives `state: dict` and `lock: threading.Lock` as parameters per call — it should return the updated state dict rather than writing to PluginStateManager directly. The orchestrator then calls `state_mgr.update(key, new_state)`.

**ANALYSIS_WAVES class variable** (line 1186): moves to PluginExecutor as it drives wave-based tier execution.

**`stop()` and `_executor.shutdown()`**: currently in `IntelligencePipelineComputeAgent.stop()` (line 547). After extraction, PluginExecutor must expose a `shutdown()` method, and the orchestrator's `stop()` calls `self._executor_obj.shutdown()` (renaming `_executor` instance variable to avoid collision with the class name).

**HMM reload**: `_reload_hmm_parameters()` iterates `TIER_SMC` and calls `plugin.reload_parameters()`. It needs `self._plugin_cache`. After extraction, this moves to PluginExecutor as `reload_hmm_parameters()`.

### SignalProcessor (lines ~1298-1677)

```python
# __init__ attrs to move:
self._cis_scorer: CISScorer             # line 463
self._signal_gate: dict = {}            # line 439
self._setup_cooldown: dict = {}         # line 440
self._setup_last_fire: dict = {}        # line 441
self._signals_generated = counter()    # line 515
self._signals_selected = counter()     # line 519
self._signal_dlq_total = counter()     # line 523

# Methods to move:
async def _run_i7(bar, event, tiered) -> dict             # line 1298 (span wrapper)
async def _run_i7_inner(...) -> dict                       # line 1310 (signal pipeline stages)
async def _publish_signals_or_dlq(ranked, symbol, tf, bar) # line 1600

# Module-level functions that move with it:
def _apply_alpha_decay(sig, tf, last_fire_state) -> None  # line 193
def _cis_kalman_update(raw_cis, x_est, P_est, Q, R)      # line 203
def _build_features_from_event(event) -> dict             # line 214
```

Per D-05: `SignalProcessor(cis_scorer: CISScorer, cache: CacheManager, settings: Settings)`

SignalProcessor needs access to: `perf_weights`, `calibration_curves`, `tod_priors`, `drift_penalties` (all from CacheManager properties), plus `transform_recorder` (owned by orchestrator). The transform_recorder is passed to pipeline stage functions (`apply_quality_gate`, `apply_regime_gate`, etc.) — it can be injected at construction or per-call. Given it's used in every bar, construction injection is cleaner.

SignalProcessor also accesses: `settings.regime_prob_min`, `settings.REGIME_PROB_SOFT_MAX`, `settings.regime_dur_min`, `settings.winner_long_bias`, `settings.env_name` (for topic names). These come from the Settings dependency.

CIS Kalman state `_kalman_state` (line 433) is used exclusively in `_run_i7_inner` — it belongs to SignalProcessor, not PluginStateManager. It is currently in `_CHECKPOINT_FIELDS` (line 308), meaning it gets checkpointed. After extraction, PluginStateManager must checkpoint it even though SignalProcessor owns it. Solution: SignalProcessor exposes `get_kalman_state()` / `restore_kalman_state()` methods; the orchestrator hands the kalman state to/from PluginStateManager for checkpointing.

Similarly, `_setup_last_fire` is in `_CHECKPOINT_FIELDS` and owned by SignalProcessor, but must be checkpointed by PluginStateManager. Same pattern applies.

`_publish_signals_or_dlq` calls `self._enqueue_blocking(...)` which requires OutputQueue access. Per D-05, SignalProcessor does NOT receive OutputQueue as a constructor arg. The return value is the list of signals to enqueue — the orchestrator calls `out_queue.enqueue(...)`. This means `_publish_signals_or_dlq` should return signals (not call enqueue directly) or accept an output callback. The cleaner design: `_publish_signals_or_dlq` returns `(bool, list[dict])` — `True` if assertion passed plus the prepared signals; `False` and empty list if DLQ'd. The DLQ publish itself also needs to go through OutputQueue, so the orchestrator handles both.

---

## Architecture Patterns

### Module Location — Clarification Required

`src/intelligence/pipeline/` already exists with 6 files (pure function stage implementations). D-01 says to create this module with 5 new files. The correct interpretation is:

**Add to the existing package** — place `executor.py`, `state_manager.py`, `signal_processor.py`, `cache_manager.py`, `output_queue.py` alongside the existing stage files. Update `__init__.py` to export the 5 new classes in addition to the existing 6 stage functions.

The existing imports `from src.intelligence.pipeline import (apply_calibration, ...)` remain unchanged.

### Test Directory Structure

No `tests/unit/pipeline_tests/` exists yet. Per D-20, it must be created:

```
tests/unit/pipeline_tests/
├── __init__.py
├── test_output_queue.py
├── test_plugin_state_manager.py
├── test_cache_manager.py
├── test_plugin_executor.py
└── test_signal_processor.py
```

### Existing Test Pattern to Preserve

The existing `tests/unit/pipeline_helpers.py` uses `IntelligencePipelineComputeAgent.__new__()` to bypass `__init__`. These tests (`test_pipeline_attribution.py`, `test_pipeline_determinism.py`, `test_pipeline_exception_isolation.py`, `test_pipeline_parallelization.py`, `test_pipeline_recorder_wiring.py`) test behaviors of the agent — they must remain green throughout the refactor, even though they instantiate the agent directly.

After extraction, the agent's `__init__` will be much smaller (no longer initializing the 40+ `self._*` attributes). The `__new__`-based tests inject specific attributes; they will need updating if those attributes move to the extracted classes. **The planner must account for this: each plan should check whether existing `__new__`-based tests break and update `pipeline_helpers.py` accordingly.**

### Checkpoint Fields Ownership Issue

Current checkpoint fields (line 308):
```python
_CHECKPOINT_FIELDS = ("plugin_states", "kalman_state", "tod_priors", "last_bar_offset", "setup_last_fire")
```

After extraction:
- `plugin_states` → PluginStateManager (natural owner)
- `kalman_state` → SignalProcessor (natural owner, but checkpointed by PluginStateManager)
- `tod_priors` → CacheManager (BUT: tod_priors is DB-loaded on startup AND checkpointed; the checkpoint takes precedence over DB load initially, then DB refresh overrides. This is the existing behavior)
- `last_bar_offset` → stays in orchestrator (it's a Kafka offset tracker, unrelated to the 5 classes)
- `setup_last_fire` → SignalProcessor (natural owner)

Resolution pattern: PluginStateManager's `write_checkpoint()` / `read_checkpoint()` receives a `state_snapshot: dict` from the orchestrator, which collects the pieces from each class. The orchestrator assembles: `{"plugin_states": state_mgr.get_all_states(), "kalman_state": sig_proc.get_kalman_state(), "tod_priors": cache_mgr.tod_priors, "last_bar_offset": self._last_bar_offset, "setup_last_fire": sig_proc.get_setup_last_fire()}`. PluginStateManager serializes and restores it; the orchestrator distributes restored values back to each class.

### OTel Metrics Ownership

Per D-16, each class creates its own metrics internally. The `counter()` and `gauge()` helpers from `src.observability.metrics` are the correct API.

Current assignment after extraction:
- OutputQueue: `output_buffer_drops`, `output_buffer_depth`, `output_publish_failures`
- PluginStateManager: (none currently; may add checkpoint write latency)
- CacheManager: (none currently; may add refresh counters)
- PluginExecutor: `plugin_skipped_total`, `i1_latency_ms`, `i7_latency_ms` (timing), `plugin_call_counts` (internally tracked)
- SignalProcessor: `signals_generated`, `signals_selected`, `signal_dlq_total`
- Orchestrator retains: `bars_processed`, `pipeline_errors`, `pipeline_latency`

Shared module-level metrics (`PLUGIN_DURATION_MS`, `PLUGIN_ERRORS_TOTAL`, `CIRCUIT_BREAKER_STATE`, `FEATURES_COMPUTED_TOTAL`, `REGIME_GATE_SUPPRESSIONS_TOTAL`, `INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL`, `THREAD_POOL_WORKERS`) — these are already defined in `src/observability/metrics.py` and imported directly. They do not need to move; each class just imports them from that module.

### RollMonitor Pattern (Reference)

`RollState` dataclass in `roll_compute_agent.py` is the exemplar for private-module state classes. For the 5 extracted classes, the same principle applies: define them as proper module-level classes (not inner classes), each in its own file. No `@dataclass` overhead required for classes with significant behavior — `@dataclass` is appropriate only for pure state containers (`PluginStateManager` and `OutputQueue` could be dataclasses, but their constructor complexity makes plain classes more readable).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OTel metrics | Custom counters/gauges | `counter()`, `gauge()`, `histogram()` from `src.observability.metrics` | Existing API, same meter instance |
| Circuit breakers | Per-plugin try/except | `CircuitBreaker` from `src.observability.circuit_breaker` | Already wired in Phase 086 |
| Background task management | Custom task loops | `asyncio.create_task()` + `self._background_tasks.add()` | Existing pattern, prevents GC |
| Atomic dict replacement | Lock-protected dict update | Direct reassignment `self._cache = new_dict` | Python GIL makes dict reassignment atomic for readers |
| Checkpoint serialization | Custom JSON format | `_tag_value`/`_untag_value` from `src.core.state_serializer` | Handles tuple keys, pydantic models |

---

## Common Pitfalls

### Pitfall 1: Module Name Collision
**What goes wrong:** Creating `src/intelligence/pipeline/__init__.py` from scratch clobbers the existing exports (`apply_quality_gate`, `rank_signals`, etc.), breaking the intelligence pipeline agent's existing imports.
**Why it happens:** D-01 says "create" the module, but it already exists.
**How to avoid:** Each plan's first task must verify the existing `__init__.py` content before writing. Add new exports to the existing file; never overwrite it from scratch.

### Pitfall 2: `_plugin_circuit_breakers` Split
**What goes wrong:** `_collect_plugin_results()` calls `self._get_plugin_cb(plugin_name)` and also `CIRCUIT_BREAKER_STATE.set()`. After moving both to PluginExecutor, the CB dict is owned by PluginExecutor — correct. But `_is_shadow()` also uses `_shadow_cache` which belongs to CacheManager. After extraction, PluginExecutor's `run_i1()`/`run_tier()` must query shadow state from CacheManager.
**How to avoid:** PluginExecutor constructor receives `plugin_cache`, `instrument_map`, and `circuit_breakers` per D-05. Shadow state lookup should be: PluginExecutor queries CacheManager's `shadow_cache` property OR the orchestrator passes shadow state per call. Simplest: PluginExecutor stores a reference to CacheManager's `shadow_cache` property (read-only access through property means atomic dict replacement is transparent).

### Pitfall 3: `_update_plugin_state` Mutation vs. D-10
**What goes wrong:** `_update_plugin_state` directly writes `self._plugin_states[task.state_key] = output.pop("_state")` — this is exactly the shared mutable state D-10 prohibits.
**Why it happens:** The current code treats plugin state as shared mutable. After extraction, PluginExecutor must not write to PluginStateManager directly.
**How to avoid:** `_collect_plugin_results` should return both the outputs list and a `state_updates: dict` — a mapping from state_key to new state dict. The orchestrator calls `self._state_mgr.update_batch(state_updates)` after each tier/wave completes. This is the interface D-10 is designed to support for Phase 089.

### Pitfall 4: CIS Scorer Ownership and Weight Updates
**What goes wrong:** `_load_cis_weights` (CacheManager) calls `self._cis_scorer.update_weights()` (SignalProcessor's scorer). CacheManager should not hold a reference to SignalProcessor per D-07.
**How to avoid:** CacheManager exposes `cis_weights` and `cis_weights_version` as properties. SignalProcessor reads these properties and calls `self._cis_scorer.update_weights()` at the start of each `_run_i7_inner()`, or the orchestrator mediates: after CacheManager refresh, the orchestrator calls `sig_proc.sync_cis_weights(cache_mgr.cis_weights, cache_mgr.cis_weights_version)`. The orchestrator-mediation approach is cleanest (D-07).

### Pitfall 5: Checkpoint State Cross-Ownership
**What goes wrong:** `kalman_state` and `setup_last_fire` live in SignalProcessor but are listed in `_CHECKPOINT_FIELDS`. If PluginStateManager only serializes its own state, these fields are silently dropped from checkpoints.
**How to avoid:** Define a checkpoint protocol: `write_checkpoint(extra_state: dict)` on PluginStateManager, where `extra_state` contains cross-owned fields. The orchestrator assembles `extra_state` from SignalProcessor and passes it in. On restore, orchestrator extracts and distributes the extra fields.

### Pitfall 6: `__new__`-Based Tests Breaking
**What goes wrong:** `tests/unit/pipeline_helpers.py:make_agent()` injects many `self._*` attributes directly onto the agent instance. After each plan removes those attributes from the agent's `__init__`, the `make_agent()` factory becomes stale.
**How to avoid:** Each plan must update `pipeline_helpers.py` to remove migrated attributes from the agent injection and instead inject them on the appropriate extracted class. The plan should specify exact changes to `pipeline_helpers.py`.

### Pitfall 7: `tod_priors` Merge vs. Replace
**What goes wrong:** `_load_tod_multipliers` does `self._tod_priors = {**self._tod_priors, **priors}` — a merge. If CacheManager uses atomic dict replacement (`self._tod_priors = priors`), existing entries not in the new load are dropped.
**How to avoid:** CacheManager's `_load_tod_multipliers` must preserve the merge semantics. The internal refresh uses `self._tod_priors = {**self._tod_priors, **priors}`.

### Pitfall 8: `_enqueue_blocking` in SignalProcessor
**What goes wrong:** `_publish_signals_or_dlq` calls `self._enqueue_blocking(...)` which requires OutputQueue access. Per D-05, SignalProcessor doesn't receive OutputQueue.
**How to avoid:** `_publish_signals_or_dlq` returns a tuple `(success: bool, dlq_payload: dict | None, signals_to_publish: list[dict])`. The orchestrator calls `out_queue.enqueue(...)` and `out_queue.enqueue_blocking(...)` based on the return value.

---

## Code Examples

### Pattern: Atomic Dict Replacement (CacheManager refresh)
```python
# Source: Current _load_perf_weights() at line 1830
async def _load_perf_weights(self) -> None:
    # ... DB query ...
    weights: dict = {}
    for rank, row in enumerate(ranked):
        weights[(row["setup_plugin"], row["tf"], sym)] = round(...)
    self._perf_weights = weights  # atomic replacement — readers always see consistent snapshot
```

### Pattern: Lazy-Init Dict Accessor (PluginStateManager)
```python
# Source: _get_state_lock at line 567, _get_plugin_cb at line 559
def get_lock(self, key: tuple) -> threading.Lock:
    if key not in self._plugin_states_locks:
        self._plugin_states_locks[key] = threading.Lock()
    return self._plugin_states_locks[key]
```

### Pattern: Background Task Management (CacheManager)
```python
# Source: _run in intelligence_pipeline_agent.py lines 671-681, pattern from alpha_swarm
def start_refresh_loops(self) -> list[asyncio.Task]:
    return [
        asyncio.create_task(self._run_refresh_loop(self._load_perf_weights, 3600)),
        asyncio.create_task(self._run_refresh_loop(self._refresh_drift_penalties, 14400)),
        asyncio.create_task(self._run_refresh_loop(self._load_cis_weights, 1800)),
        asyncio.create_task(self._run_refresh_loop(self._load_calibration_curves, 1800)),
        asyncio.create_task(self._run_refresh_loop(self._load_tod_multipliers, 14400)),
        asyncio.create_task(self._run_refresh_loop(self._load_shadow_cache, 300)),
    ]
```

### Pattern: Orchestrator DAG Description (thin `_process_bar_inner`)
```python
# Source: D-08 from CONTEXT.md
async def _process_bar_inner(self, bar: BarMessage) -> None:
    state   = self._state_mgr.get_state(key)
    lock    = self._state_mgr.get_lock(key)
    tiered  = await self._executor.run_tiers(plugins, state, lock, bar, symbol, tf)
    self._state_mgr.update(key, tiered)
    signals = await self._sig_proc.process(event, tiered, bar, symbol, tf)
    await self._out_queue.enqueue(topic, key, signals)
```

### Pattern: OTel Metrics in Extracted Class
```python
# Source: metrics.py counter()/gauge() API
from src.observability.metrics import counter, gauge, PLUGIN_DURATION_MS  # shared module-level

class OutputQueue:
    def __init__(self, producer: KafkaProducerClient, maxsize: int) -> None:
        self._queue = asyncio.Queue(maxsize=maxsize)
        self._drops = counter(
            "intelligence_pipeline_output_buffer_drops_total",
            "Output buffer drops due to queue full",
        )
        # ... existing names preserved ...
```

---

## Open Questions

1. **`_cis_scorer.update_weights()` call site**
   - What we know: Called in `_load_cis_weights` (CacheManager territory) but updates SignalProcessor's scorer.
   - What's unclear: Whether to use callback, property access, or orchestrator mediation.
   - Recommendation: Orchestrator mediation (D-07 says orchestrator mediates all inter-class data flow). After CacheManager refresh, the orchestrator calls `sig_proc.sync_cis_weights(...)`.

2. **`transform_recorder` injection for SignalProcessor**
   - What we know: Used in every I7 bar call (passed to `apply_quality_gate`, `apply_calibration`, etc.). Owned by orchestrator (from `_setup()`).
   - What's unclear: Constructor injection vs. per-call parameter.
   - Recommendation: Constructor injection — it's a stable dependency that doesn't change per call. `SignalProcessor(cis_scorer, cache, settings, transform_recorder)` — OR pass as a parameter to `process()` if the planner wants to keep D-05 constructor signatures unchanged. D-05 doesn't mention transform_recorder; add it to the constructor.

3. **`_shadow_cache` access in PluginExecutor**
   - What we know: `_is_shadow(plugin_name)` needs `self._shadow_cache` (CacheManager's dict). Per D-05, PluginExecutor doesn't receive CacheManager as a constructor arg.
   - What's unclear: How PluginExecutor accesses shadow state without referencing CacheManager.
   - Recommendation: PluginExecutor receives `shadow_cache: dict` as a constructor arg (a reference to CacheManager's internal dict). When CacheManager does atomic replacement, this reference becomes stale. Better: PluginExecutor receives CacheManager's `shadow_cache` property — but that creates a lateral reference. Alternative: orchestrator passes shadow_cache to `run_tiers()` per call. Cleanest D-07-compliant solution: orchestrator passes `shadow_cache=self._cache_mgr.shadow_cache` as a parameter to `run_tiers()`.

4. **`_last_bar_offset` checkpoint field**
   - What we know: Listed in `_CHECKPOINT_FIELDS`, currently tracked as `self._last_bar_offset` in `__init__`.
   - What's unclear: None of the 5 classes own this — it's a Kafka offset tracker.
   - Recommendation: Stays in the orchestrator. Orchestrator passes it to PluginStateManager's checkpoint via `extra_state`.

---

## Sources

### Primary (HIGH confidence)
- `services/intelligence_pipeline_agent.py` — full read, lines 1-1928, all methods inventoried
- `src/intelligence/pipeline/__init__.py` — existing package confirmed, exports verified
- `src/observability/metrics.py` — OTel API confirmed: `counter()`, `gauge()`, module-level metrics
- `src/observability/circuit_breaker.py` — `CircuitBreaker`, `CircuitState` confirmed
- `src/core/agent/base.py` — `BaseAgent` contract confirmed
- `services/roll_compute_agent.py` — `RollState` dataclass pattern confirmed
- `tests/unit/pipeline_helpers.py` — `__new__`-based test pattern confirmed
- `tests/unit/` — all 5 existing pipeline test files confirmed, no `pipeline_tests/` subdirectory exists

### Secondary (MEDIUM confidence)
- CONTEXT.md decisions D-01 through D-21 — authoritative source for all locked decisions
- REQUIREMENTS.md ARCH-01 through ARCH-05 — one requirement per extracted class

---

## Metadata

**Confidence breakdown:**
- Existing code inventory: HIGH — read full 1928-line source file
- Module naming conflict: HIGH — directly confirmed `src/intelligence/pipeline/` exists
- Constructor signatures: HIGH — from locked D-05 in CONTEXT.md
- Cross-class entanglements (CIS scorer, checkpoint, shadow cache): HIGH — traced through source
- Test impact analysis: HIGH — read existing `pipeline_helpers.py` and all pipeline test files

**Research date:** 2026-05-17
**Valid until:** Stable — pure structural refactoring, no external dependencies change
