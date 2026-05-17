# Phase 088: God Class Decomposition - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract five focused classes from the 1928-line `IntelligencePipelineComputeAgent` into a new module `src/intelligence/pipeline/`. Each class owns one responsibility, is independently unit-testable, and communicates only through the orchestrator (no lateral coupling). The service file becomes a ~100-line thin orchestrator that wires the classes and delegates to them.

This is a pure refactor — zero behavior change, zero latency overhead (all in-process), all existing tests remain green.

</domain>

<decisions>
## Implementation Decisions

### File Layout
- **D-01:** New module `src/intelligence/pipeline/` with 5 files: `executor.py`, `state_manager.py`, `signal_processor.py`, `cache_manager.py`, `output_queue.py`, plus `__init__.py` exporting all public classes.
- **D-02:** `services/intelligence_pipeline_agent.py` becomes a thin orchestrator (~100 lines) that imports from `src/intelligence/pipeline/`, constructs the 5 classes in `_setup()`, and delegates in `_process_bar_inner()`.
- **D-03:** Each new file is a proper Python module — no inner classes, no nested definitions.

### Wiring / Dependency Injection
- **D-04:** Constructor injection with precisely-scoped dependencies per class. No `PipelineContext` bag (service locator anti-pattern). Each class receives only what it actually computes with.
- **D-05:** Precise constructor signatures:
  - `OutputQueue(producer: KafkaProducerClient, maxsize: int)`
  - `PluginStateManager(checkpoint_path: Path)`
  - `CacheManager(db: DatabaseManager, settings: Settings)`
  - `PluginExecutor(thread_pool: ThreadPoolExecutor, plugin_cache: dict, instrument_map: dict, circuit_breakers: dict)`
  - `SignalProcessor(cis_scorer: CISScorer, cache: CacheManager, settings: Settings)`
- **D-06:** The orchestrator constructs all 5 classes in `_setup()` and holds them as `self._state_mgr`, `self._cache_mgr`, `self._executor`, `self._sig_proc`, `self._out_queue`.

### In-Process DAG (Data Flow)
- **D-07:** Orchestrator mediates ALL inter-class data flow. No lateral coupling between classes. Data flows: `StateManager → Executor` (state passed per call), `Executor → StateManager` (results via orchestrator), `CacheManager → SignalProcessor` (via constructor reference).
- **D-08:** `_process_bar_inner()` becomes a DAG description:
  ```python
  state   = self._state_mgr.get_state(key)
  lock    = self._state_mgr.get_lock(key)
  tiered  = await self._executor.run_tiers(plugins, state, lock, bar, symbol, tf)
  self._state_mgr.update(key, tiered)
  signals = await self._sig_proc.process(event, tiered, bar, symbol, tf)
  await self._out_queue.enqueue(topic, key, signals)
  ```

### Shared State Ownership
- **D-09:** `PluginStateManager` owns `_plugin_states` (dict keyed by `(plugin_name, symbol, tf)`), `_plugin_states_locks`, and the checkpoint file. It is the single writer.
- **D-10:** `PluginExecutor` never holds a reference to `PluginStateManager`. It receives `state: dict` and `lock: asyncio.Lock` as parameters per call. State mutation before thread-pool dispatch is eliminated (Phase 089 concern — not in scope here, but the interface must support the future fix: executor receives state as parameter, not via shared mutation).
- **D-11:** `CacheManager` is the single owner of all 6 live cache dicts: `perf_weights`, `cis_weights`, `calibration_curves`, `shadow_cache`, `drift_penalties`, `tod_multipliers`. Exposes them as properties (atomic dict replacement on refresh — readers always see a consistent snapshot).

### CacheManager Self-Management
- **D-12:** `CacheManager.start_refresh_loops()` creates and returns all 6 background `asyncio.Task`s. The orchestrator stores them in `_background_tasks` as before. CacheManager owns the refresh logic and intervals — orchestrator only stores the task handles.
- **D-13:** Refresh intervals remain unchanged: `perf_weights=3600`, `drift_penalties=14400`, `cis_weights=1800`, `calibration_curves=1800`, `tod_multipliers=14400`, `shadow_cache=300`.

### PluginStateManager Checkpoint Automation
- **D-14:** `PluginStateManager` owns a background checkpoint loop (periodic, configurable interval). The orchestrator no longer calls `_write_local_checkpoint()` directly — it calls `state_mgr.start_checkpoint_loop(interval_sec)` in `_setup()`. This moves from manual-call to automated scheduling (Renaissance principle: prefer automation).
- **D-15:** Checkpoint still raises on failure (Phase 086 contract preserved).

### Observability
- **D-16:** Each class creates its own OTel metrics internally using existing module-level helpers (`counter()`, `gauge()`, `histogram()` from `src/observability/metrics.py`). Zero metrics wiring in the orchestrator. Metric names are unchanged — this is a structural refactor, not a metrics rename.

### Migration Order (5 plans, sequential dependency)
- **D-17:** Extraction order chosen to minimize integration risk — simpler/more isolated classes first:
  1. `OutputQueue` — most isolated, validates the new module structure (~100 lines)
  2. `PluginStateManager` — state dicts + locks + background checkpoint (~150 lines)
  3. `CacheManager` — 6 refresh loops + all `_load_*` methods (~300 lines)
  4. `PluginExecutor` — `_run_i1`, `_run_tier`, `_run_i7_inner`, `_collect_plugin_results` — depends on D-09/D-10 interface from plan 02 (~400 lines)
  5. `SignalProcessor` — `_run_i7`/`_run_i7_inner` signal path, `_publish_signals_or_dlq` — depends on CacheManager interface from plan 03 (~350 lines)
- **D-18:** After plan 05, service file should be ~100 lines. If it's materially larger, something was missed.

### Wave Structure
- **D-19:** Plans 01-03 are independent (no shared files) → Wave 1, parallel execution. Plans 04-05 each depend on prior extractions → Wave 2, sequential.

### Testing Contract
- **D-20:** Each extracted class must have a dedicated unit test file at `tests/unit/pipeline_tests/test_{class_name}.py`. Tests must exercise the class in isolation using fakes/mocks for its dependencies — no standing up a full `IntelligencePipelineComputeAgent`.
- **D-21:** All existing `tests/unit/service_tests/test_intelligence_pipeline_*.py` tests must remain green after each plan — regression coverage.

### Claude's Discretion
- Exact method signatures within each class (beyond the public interface contracts in D-05/D-08)
- Internal implementation of `_run_refresh_loop` (can remain a shared utility or be inlined)
- Whether to use `@dataclass` for any of the 5 classes (appropriate where state is minimal)
- Precise test fixture design

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source file (primary target)
- `services/intelligence_pipeline_agent.py` — The 1928-line god class being decomposed. Read the full `__init__`, `_setup`, `_process_bar_inner`, `_run_i1_to_i6`, `_run_i7`, `_run_i7_inner`, all `_load_*` methods, `_run_refresh_loop`, `_write_local_checkpoint`.

### Architecture principles
- `docs/principles.md` — Core project principles (instrument everything, shadow mode first)
- `.planning/REQUIREMENTS.md` §ARCH-01–ARCH-05 — The 5 acceptance criteria, one per extracted class

### Established patterns to follow
- `services/roll_compute_agent.py` — `RollState` dataclass pattern: parallel dicts → single typed dataclass
- `src/core/agent/base.py` — `BaseAgent` contract, `_record_message_consumed`, `last_processed_at`
- `src/observability/metrics.py` — OTel metric creation helpers (counter, gauge, histogram)
- `src/observability/circuit_breaker.py` — `CircuitBreaker` class wired in Phase 086

### Phase 086 contracts (must be preserved)
- `_write_local_checkpoint` raises on failure (not swallows) — preserve in PluginStateManager
- `_enqueue_blocking` blocks rather than drops — preserve in OutputQueue
- `validate_signal` gate is in SignalWriterAgent (not this pipeline) — not in scope

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_run_refresh_loop(load_fn, interval_sec)` at line 1748 — generic refresh loop already extracted as a method; CacheManager can internalize this pattern
- `PluginTask` dataclass at line 352 — already extracted; PluginExecutor imports and uses it
- `CircuitBreaker` / `CircuitState` — already in `src/observability/circuit_breaker.py`; PluginExecutor receives the `circuit_breakers` dict as a constructor param

### Established Patterns
- **Lazy-init dict accessor**: `_get_plugin_cb` and `_get_state_lock` show the pattern; PluginStateManager should expose `get_lock(key)` using the same pattern
- **Atomic dict replacement on refresh**: `_load_perf_weights` replaces `self._perf_weights` with a new dict (not mutates in place); CacheManager properties must preserve this
- **Background task tracking**: `self._background_tasks: set` — orchestrator stores task handles, cancels them in `_teardown()`

### Integration Points
- `_process_bar_inner` (line 861) — the primary integration point; becomes the DAG-description method after all 5 extractions
- `_setup` (line 581) — where all 5 classes are constructed and refresh loops started
- `_teardown` (line 706) — cancels background tasks; must cancel OutputQueue drain loop and CacheManager refresh loops

### State to Re-home (40+ `self._*` attributes)
- **OutputQueue**: `_output_queue`, `_output_buffer_drops`, `_output_buffer_depth`, `_output_publish_failures`
- **PluginStateManager**: `_plugin_states`, `_plugin_states_locks`, checkpoint path/file logic
- **CacheManager**: `_perf_weights`, `_cis_weights`, `_calibration_curves`, `_shadow_cache`, `_drift_penalties`, `_tod_multipliers`, `_cis_kalman_params`, `_pattern_reliability`
- **PluginExecutor**: `_executor` (ThreadPoolExecutor), `_plugin_cache`, `_instrument_map`, `_plugin_circuit_breakers`, `_plugin_call_counts`, `_plugin_skipped_total`
- **SignalProcessor**: `_cis_scorer`, `_cis_weights_cache`, `_signal_gate`, `_setup_cooldown`, `_setup_last_fire`, `_signals_generated`, `_signals_selected`, `_signal_dlq_total`

</code_context>

<specifics>
## Specific Ideas

- "Design this like Renaissance would" — Jim Simons principle applied: each class is a DAG node with typed I/O, explicit contracts, self-managing automation (refresh loops, checkpoint loop), zero lateral coupling between nodes, full OTel instrumentation owned by each class.
- "Microservices DAG within the process" — same topology as the service DAG (Kafka-connected), but in-process with method calls. Orchestrator = router. Classes = workers.
- "Prefer automation" — PluginStateManager owns its checkpoint timer (not caller-driven). CacheManager owns its refresh timers (not orchestrator-driven beyond `start_refresh_loops()`).
- "Balance efficiency with simplicity" — no new abstractions beyond the 5 classes. No Protocol/ABC overhead unless needed for testing. No extra allocations in hot path.

</specifics>

<deferred>
## Deferred Ideas

- **Phase 089 (PERF)**: Plugin state threading as parameter to eliminate `plugin._state =` mutation before thread-pool dispatch. The PluginExecutor interface in this phase (D-10) is designed to support this future fix, but the fix itself is Phase 089 scope.
- **Async PluginStateManager**: State operations are sync (dict access). Could be made async with asyncio.Lock for concurrent symbol/tf access. Deferred — Phase 089 covers the threading model.
- **Protocol/ABC interfaces**: Formal typed interfaces for the 5 classes (e.g., for dependency injection in tests). Useful if a second pipeline implementation ever materializes. Not needed now.

</deferred>

---

*Phase: 088-god-class-decomposition*
*Context gathered: 2026-05-17*
