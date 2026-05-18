# Phase 088: God Class Decomposition - Context

**Gathered:** 2026-05-17
**Last revised:** 2026-05-18 (post cross-AI review — see `088-REVIEWS.md`)
**Status:** Plans revised to address 5 HIGH-severity Codex findings; ready for execution

<domain>
## Phase Boundary

Extract five focused classes from the 1928-line `IntelligencePipelineComputeAgent` into a new module `src/intelligence/pipeline/`. Each class owns one responsibility, is independently unit-testable, and communicates only through the orchestrator (no lateral coupling). The service file becomes a ~150-line thin orchestrator that wires the classes and delegates to them.

This is a pure refactor — zero behavior change, zero latency overhead (all in-process), all existing tests remain green.

</domain>

<decisions>
## Implementation Decisions

### File Layout
- **D-01:** New module `src/intelligence/pipeline/` with 5 files: `executor.py`, `state_manager.py`, `signal_processor.py`, `cache_manager.py`, `output_queue.py`, plus `__init__.py` exporting all public classes plus `CacheSnapshot` and `SignalProcessorResult` dataclasses.
- **D-02:** `services/intelligence_pipeline_agent.py` becomes a thin orchestrator (~150 lines with tolerance for 4-way output routing + journal helper) that imports from `src/intelligence/pipeline/`, constructs the 5 classes in `_setup()`, and delegates in `_process_bar_inner()`.
- **D-03:** Each new file is a proper Python module — no inner classes, no nested definitions.

### Wiring / Dependency Injection
- **D-04:** Constructor injection with precisely-scoped dependencies per class. No `PipelineContext` bag (service locator anti-pattern). Each class receives only what it actually computes with.
- **D-05 (REVISED — HIGH finding 2):** Precise constructor signatures:
  - `OutputQueue(producer: KafkaProducerClient, maxsize: int)`
  - `PluginStateManager(checkpoint_path: Path)`
  - `CacheManager(db: DatabaseManager, settings: Settings)`
  - `PluginExecutor(thread_pool: ThreadPoolExecutor, plugin_cache: dict, instrument_map: dict, circuit_breakers: dict)`
  - `SignalProcessor(cis_scorer: CISScorer, settings: Settings, transform_recorder=None)` — **NO `cache` parameter.** Cache values flow in per-call via a `CacheSnapshot` dataclass argument to `process()` (HIGH finding 2: eliminate SignalProcessor→CacheManager lateral coupling).
- **D-06:** The orchestrator constructs all 5 classes in `_setup()` and holds them as `self._state_mgr`, `self._cache_mgr`, `self._executor`, `self._sig_proc`, `self._out_queue`. The bare attribute `self._executor` = PluginExecutor instance; the underlying ThreadPoolExecutor is `self._thread_pool`.

### In-Process DAG (Data Flow)
- **D-07 (REVISED — HIGH finding 2):** Orchestrator mediates ALL inter-class data flow. ZERO lateral coupling between extracted classes:
  - `StateManager → Executor`: orchestrator calls `state_mgr.get_all_states_for(symbol, tf)` and passes the result `dict[plugin_name, state]` as a per-call parameter to `executor.run_tiers(...)`.
  - `Executor → StateManager`: executor returns `state_updates: dict[(plugin_name, symbol, tf), state]`; orchestrator calls `state_mgr.update_batch(state_updates)`.
  - `CacheManager → SignalProcessor`: orchestrator builds a `CacheSnapshot` dataclass from `self._cache_mgr` properties per bar and passes it as `cache_snapshot=` kwarg to `sig_proc.process(...)`. SignalProcessor does NOT hold a CacheManager reference.
  - `CacheManager → Executor`: orchestrator reads `self._cache_mgr.shadow_cache` and passes it as `shadow_cache=` kwarg per call (Pitfall 2).
- **D-08 (REVISED — HIGH findings 1 + 4):** `_process_bar_inner()` is the DAG description with full 4-way output routing:
  ```python
  plugin_states  = self._state_mgr.get_all_states_for(symbol, tf)   # dict[plugin_name, state] — HIGH finding 1
  lock           = self._state_mgr.get_lock((symbol, tf))
  tiered, state_updates = await self._executor.run_tiers(plugin_states, lock, bar, symbol, tf, frames,
                                                          shadow_cache=self._cache_mgr.shadow_cache)
  self._state_mgr.update_batch(state_updates)                       # keyed by (plugin_name, symbol, tf)
  self._cache_mgr.update_hmm_regime(tiered.get("smc", {}).get("hmm_regime"))
  await self._out_queue.enqueue_blocking(topic_intelligence_events, key, intel_event)  # canonical event publish

  i7_plugin_states = self._state_mgr.get_all_states_for(symbol, tf)
  raw_signals, sig_state_updates = await self._executor.run_i7_plugins(i7_plugin_states, lock, bar, symbol, tf, tiered,
                                                                        shadow_cache=self._cache_mgr.shadow_cache)
  if sig_state_updates: self._state_mgr.update_batch(sig_state_updates)

  snapshot = CacheSnapshot(perf_weights=..., calibration_curves=..., tod_priors=..., drift_penalties=...,
                           cis_weights=..., cis_weights_version=...)
  result = await self._sig_proc.process(intel_event, tiered, bar, symbol, tf,
                                        raw_signals=raw_signals, cache_snapshot=snapshot)
  # 4-way output routing (HIGH finding 4)
  if result.success and result.signals_payload: await self._out_queue.enqueue_blocking(topic_intelligence_i7_signals, key, result.signals_payload)
  elif result.dlq_payload:                       await self._out_queue.enqueue_blocking(topic_signal_dlq, key, result.dlq_payload)
  if result.winner_payload:                      await self._out_queue.enqueue_blocking(topic_signals_aggregated, key, result.winner_payload)
  self._enqueue_intel_journal(bar, intel_event, t0, key, result.i7_result)  # topic_intelligence_journal
  ```

### Shared State Ownership
- **D-09:** `PluginStateManager` owns `_plugin_states` (dict keyed by `(plugin_name, symbol, tf)`), `_locks` (dict keyed by `(symbol, tf)`), and the checkpoint file. It is the single writer.
- **D-10:** `PluginExecutor` never holds a reference to `PluginStateManager`. It receives `plugin_states: dict[str, dict]` (per-plugin view from `state_mgr.get_all_states_for(symbol, tf)`) and `lock: threading.Lock` as parameters per call. State mutation before thread-pool dispatch is eliminated (Phase 089 concern — not in scope here, but the interface must support the future fix: executor receives state as parameter, not via shared mutation).
- **D-11:** `CacheManager` is the single owner of all 6 live cache dicts: `perf_weights`, `cis_weights`, `calibration_curves`, `shadow_cache`, `drift_penalties`, `tod_priors`. Exposes them as properties (atomic dict replacement on refresh — readers always see a consistent snapshot).

### CacheManager Self-Management
- **D-12:** `CacheManager.start_refresh_loops()` creates and returns all 6 background `asyncio.Task`s. The orchestrator stores them in `_background_tasks` as before. CacheManager owns the refresh logic and intervals — orchestrator only stores the task handles.
- **D-13:** Refresh intervals remain unchanged: `perf_weights=3600`, `drift_penalties=14400`, `cis_weights=1800`, `calibration_curves=1800`, `tod_multipliers=14400`, `shadow_cache=300`.

### PluginStateManager Checkpoint Automation
- **D-14:** `PluginStateManager` owns a background checkpoint loop (periodic, configurable interval). The orchestrator no longer calls `_write_local_checkpoint()` directly — it calls `state_mgr.start_checkpoint_loop(interval_sec, get_extra_fn)` in `_setup()`. The loop catches non-CancelledError exceptions per iteration (logs + counts via `intelligence_pipeline_checkpoint_failures_total`) so transient I/O failure does not kill the task. `CancelledError` is re-raised so the orchestrator can cancel cleanly.
- **D-15:** Checkpoint still raises on failure (Phase 086 contract preserved) — `write_checkpoint()` itself raises; the loop wrapper catches the raise so the background task lives.

### Observability
- **D-16:** Each class creates its own OTel metrics internally using existing module-level helpers (`counter()`, `gauge()`, `histogram()` from `src/observability/metrics.py`). Zero metrics wiring in the orchestrator. Metric names are unchanged — this is a structural refactor, not a metrics rename.

### Migration Order (5 plans, sequential dependency)
- **D-17:** Extraction order chosen to minimize integration risk — simpler/more isolated classes first:
  1. `OutputQueue` — most isolated, validates the new module structure (~100 lines)
  2. `PluginStateManager` — state dicts + locks + background checkpoint (~150 lines)
  3. `CacheManager` — 6 refresh loops + all `_load_*` methods + `load_initial()` (~300 lines)
  4. `PluginExecutor` — `_run_i1`, `_run_tier`, `_run_i7_inner`, `_collect_plugin_results` — depends on D-09/D-10 interface from plan 02 (~400 lines)
  5. `SignalProcessor` — `_run_i7`/`_run_i7_inner` signal path, `_publish_signals_or_dlq` — depends on CacheSnapshot pattern (no CacheManager reference) (~350 lines)
- **D-18 (REVISED):** After plan 05, service file class body should be ~150 lines (was originally targeted at ~100; raised to ~150 with tolerance to accommodate the 4-way explicit output routing + `_enqueue_intel_journal` helper that remains in the orchestrator per HIGH finding 4). Total file ≤ 250 lines.

### Wave Structure
- **D-19:** All 5 plans execute sequentially (waves 1–5). Plans 01-03 all modify `intelligence_pipeline_agent.py`, `src/intelligence/pipeline/__init__.py`, and `tests/unit/pipeline_helpers.py` — they cannot run in parallel. Each plan depends on all prior plans completing first.

### Testing Contract
- **D-20:** Each extracted class must have a dedicated unit test file at `tests/unit/pipeline_tests/test_{class_name}.py`. Tests must exercise the class in isolation using fakes/mocks for its dependencies — no standing up a full `IntelligencePipelineComputeAgent`.
- **D-21:** All existing pipeline regression tests must remain green after each plan - regression coverage:
  - `tests/unit/test_pipeline_attribution.py`
  - `tests/unit/test_pipeline_determinism.py`
  - `tests/unit/test_pipeline_exception_isolation.py`
  - `tests/unit/test_pipeline_parallelization.py`
  - `tests/unit/test_pipeline_recorder_wiring.py`

### Eager-load / Enrollment Contract (NEW — HIGH finding 3 + MEDIUM enrollment finding)
- **D-22:** `CacheManager.load_initial()` eagerly executes all 6 loaders sequentially BEFORE `start_refresh_loops()` is called. Without this, the service starts cold for up to 4 hours (refresh loops sleep first, then load). The orchestrator's `_setup()` ordering is:
  ```python
  self._cache_mgr = CacheManager(db=self._db, settings=self.settings)
  async with self._db.transaction() as conn:
      await enroll_all_plugins(conn)          # shadow registry MUST be seeded BEFORE _load_shadow_cache
  await self._cache_mgr.load_initial()        # eager load — 6 loaders sequential
  for task in self._cache_mgr.start_refresh_loops():
      self._background_tasks.add(task)
  ```
  `enroll_all_plugins` stays on the orchestrator (not inside CacheManager) — it depends on a DB transaction, runs once, and is conceptually a setup step rather than a refresh concern.

### Checkpoint Payload Contract (NEW — HIGH finding 5)
- **D-23:** `PluginStateManager.write_checkpoint(extra_state: dict)` is the SINGLE writer of the checkpoint file AND the single owner of the `"plugin_states"` payload key. `extra_state` MUST NOT contain a `"plugin_states"` key — `write_checkpoint` raises `ValueError` if it does. The orchestrator's `_assemble_checkpoint_extra()` returns exactly:
  ```python
  {
      "kalman_state": self._sig_proc.get_kalman_state(),
      "setup_last_fire": self._sig_proc.get_setup_last_fire(),
      "tod_priors": self._cache_mgr.tod_priors,
      "last_bar_offset": self._last_bar_offset,
  }
  ```
  PluginStateManager merges its own `plugin_states` (from `self._plugin_states`) into the serialized payload internally.

### Output Routing Contract (NEW — HIGH finding 4)
- **D-24:** The orchestrator routes to FIVE output channels per bar (4 from SignalProcessor result + 1 canonical event):
  1. `topic_intelligence_events` — canonical `IntelligenceEvent` (orchestrator-built from `tiered`, unchanged from god class)
  2. `topic_intelligence_i7_signals` — `result.signals_payload` (success path)
  3. `topic_signal_dlq` — `result.dlq_payload` (CIS assertion failure)
  4. `topic_signals_aggregated` — `result.winner_payload` (god class line 1544 publish — feeds signal_tracker_agent)
  5. `topic_intelligence_journal` — via `_enqueue_intel_journal(bar, intel_event, t0, key, result.i7_result)` helper RETAINED in orchestrator (god class lines 1683-1727)
  `SignalProcessorResult` dataclass carries `signals_payload`, `dlq_payload`, `winner_payload`, `i7_result` so all four can be routed without coupling SignalProcessor to topic names. SignalProcessor does NOT import any `topic_*` name or `message_key`.

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

### Cross-AI review feedback (MANDATORY — addresses contract risks)
- `.planning/phases/088-god-class-decomposition/088-REVIEWS.md` — Codex review identified 5 HIGH-severity contract mismatches. Plans 01-05 revised 2026-05-18 to address all 5. See D-05, D-07, D-08, D-22, D-23, D-24 above for the canonical decisions.

### Established patterns to follow
- `services/roll_compute_agent.py` — `RollState` dataclass pattern: parallel dicts → single typed dataclass
- `src/core/agent/base.py` — `BaseAgent` contract, `_record_message_consumed`, `last_processed_at`, **canonical `running` property** (NOT `_running` — REVIEWS MEDIUM finding)
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
- **Eager-then-refresh pattern**: god class _setup lines 627-637 — load all caches sequentially, then start the periodic refresh loops. Preserved via `CacheManager.load_initial()` (D-22).

### Integration Points
- `_process_bar_inner` (line 861) — the primary integration point; becomes the DAG-description method after all 5 extractions
- `_setup` (line 581) — where all 5 classes are constructed, enroll_all_plugins runs, load_initial fires, then refresh loops start
- `_teardown` (line 706) — cancels background tasks; must cancel OutputQueue drain loop, CacheManager refresh loops, and PluginStateManager checkpoint loop
- `_enqueue_intel_journal` (line 1683) — **RETAINED** in orchestrator post-extraction (per D-24); receives `result.i7_result` from SignalProcessor

### State to Re-home (40+ `self._*` attributes)
- **OutputQueue**: `_output_queue`, `_output_buffer_drops`, `_output_buffer_depth`, `_output_publish_failures`
- **PluginStateManager**: `_plugin_states`, `_plugin_states_locks`, checkpoint path/file logic
- **CacheManager**: `_perf_weights`, `_cis_weights`, `_calibration_curves`, `_shadow_cache`, `_drift_penalties`, `_tod_multipliers`, `_cis_kalman_params` (note: `_pattern_reliability` is a dead attribute — written but never read anywhere — delete it without rehoming AFTER `rg "_pattern_reliability|load_pattern_reliability"` confirms zero readers across the repo)
- **PluginExecutor**: `_executor` (ThreadPoolExecutor — renamed to `_thread_pool`; bare `_executor` becomes the PluginExecutor instance per D-06), `_plugin_cache`, `_instrument_map`, `_plugin_circuit_breakers`, `_plugin_call_counts`, `_plugin_skipped_total`
- **SignalProcessor**: `_cis_scorer`, `_cis_weights_cache`, `_signal_gate`, `_setup_cooldown`, `_setup_last_fire`, `_kalman_state`, `_signals_generated`, `_signals_selected`, `_signal_dlq_total`

</code_context>

<specifics>
## Specific Ideas

- "Design this like Renaissance would" — Jim Simons principle applied: each class is a DAG node with typed I/O, explicit contracts, self-managing automation (refresh loops, checkpoint loop), zero lateral coupling between nodes, full OTel instrumentation owned by each class.
- "Microservices DAG within the process" — same topology as the service DAG (Kafka-connected), but in-process with method calls. Orchestrator = router. Classes = workers.
- "Prefer automation" — PluginStateManager owns its checkpoint timer (not caller-driven). CacheManager owns its refresh timers (not orchestrator-driven beyond `start_refresh_loops()`).
- "Balance efficiency with simplicity" — no new abstractions beyond the 5 classes plus 2 dataclasses (`CacheSnapshot`, `SignalProcessorResult`). No Protocol/ABC overhead unless needed for testing. No extra allocations in hot path.

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
*Revised post-REVIEWS: 2026-05-18 — D-05, D-07, D-08, D-18 revised; D-22, D-23, D-24 added*
