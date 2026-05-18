# Phase 089: Compute Performance Optimization - Context

**Gathered:** 2026-05-18
**Updated:** 2026-05-18 (post-codebase review)
**Status:** Ready for planning

<domain>
## Phase Boundary

Complete the DAG decomposition started in Phase 088, eliminate per-bar allocation overhead, fix the plugin state race condition, convert O(N) recomputation plugins to incremental compute, batch Kafka drain output, and introduce per-key concurrent bar processing.

Phase 089 = architectural completion + performance. The orchestrator exits the phase as a pure router: it constructs DAG nodes, routes bars to per-key workers, and routes outputs to 4 topics. All compute logic lives in extracted DAG nodes.

All work is inside `IntelligencePipelineComputeAgent` (and its extracted classes). Zero behavior change — no signal logic altered, no schema changes. Phase delivers measurable throughput improvement validated by before/after OBS-01 histogram comparison.

**Requires Phase 088 complete before executing any plan.**

</domain>

<decisions>
## Implementation Decisions

### PERF-07: Per-Key Concurrency Model
- **D-01:** Per-key Queue + worker tasks. Each `(symbol, tf)` key gets a dedicated `asyncio.Queue` and a long-running `asyncio.Task` that consumes from it. The orchestrator fans out incoming bars to per-key queues. Each worker task processes bars sequentially within its key — preserving in-order guarantees. Independent keys run concurrently with no coordination overhead.
- **D-02:** This is Plan 06 (wave 3), executing after PERF-03 (state threading). Safe concurrent dispatch requires plugin state to be a per-call parameter, not shared mutable assignment on `plugin._state` before thread-pool dispatch. PERF-03 is the prerequisite.
- **D-03:** Architecture mirrors the service DAG: each `(symbol, tf)` is a DAG node with its own input buffer and processor. A bar for ES:1m never blocks NQ:5m. Renaissance principle: independent streams must run independently.

### PERF-10: Out of Scope
- **D-04:** PERF-10 (checkpoint writes off hot path) is already delivered by Phase 088 Plan 02. `PluginStateManager.start_checkpoint_loop(interval_sec, get_extra_fn)` removes checkpoint writes from the per-bar processing path. Do NOT re-implement this in Phase 089.

### PERF-04: O(N) Plugin Targets
- **D-05:** Target all plugins with p95 latency > 20ms. Live OBS-01 data (queried 2026-05-18 against running pipeline) identified these 12 plugins:
  - `struct_MarketProfile` (i3) — 206.7ms p95, `supports_incremental=False` → new incremental algorithm needed (update volume buckets on each bar, recalculate POC/VAH/VAL from updated buckets)
  - `struct_SessionLevels` (i3) — 94.3ms p95, `supports_incremental=False` → new incremental algorithm needed (track session high/low/levels, update on each bar)
  - `smc_BOCPDChangePoint` (smc) — 77.9ms p95, `supports_incremental=True` → profile incremental path; optimize if incremental form is still O(N)
  - `smc_HMMRegime_1m` (smc) — 35.8ms, `supports_incremental=True`
  - `smc_HMMRegime_5m` (smc) — 32.6ms, `supports_incremental=True`
  - `MovingAverages` (I1) — 27.5ms → check incremental status
  - `smc_HMMRegime_15m` (smc) — 24.6ms, `supports_incremental=True`
  - `smc_HMMRegime_1h` (smc) — 23.6ms, `supports_incremental=True`
  - `Stochastic` (I1) — 22.9ms, `supports_incremental=True`
  - `ind_ACOscillator` (I1) — 22.3ms → check incremental status
  - `BollingerBands` (I1) — 21.7ms, `supports_incremental=True`
  - `WilliamsR` (I1) — 21.0ms → check incremental status
- **D-06:** For plugins with `supports_incremental=True`: profile to confirm incremental path is exercised after PERF-03 state threading is fixed. If p95 remains high after PERF-03, the incremental algorithm itself may need optimization. HMM and BOCPD have statistically complex incremental updates — document the computational bound rather than forcing O(1) if the algorithm doesn't admit it.
- **D-07:** For plugins with `supports_incremental=False` (MarketProfile, SessionLevels): implement `compute_next()` and set `supports_incremental=True`. Profile before/after to confirm improvement.

### Plan Structure (6 plans, 4 waves) — revised post-codebase-review
- **D-08:** 6 plans in 4 waves:
  - **Wave 0 (Plan 01, standalone — must complete before all other plans):**
    - FeaturePipelineExecutor extraction (D-18)
    - CacheManager stream cache migration (D-19, prerequisite for FPE)
    - PluginExecutor.run_i7_complete() (D-20)
    - _apply_alpha_decay into SignalProcessor (D-21)
    - SignalProcessorResult metrics (D-22)
    - Cleanup: dead code, deferred imports, _plugin_cache dedup (D-24)
  - **Wave 1 (Plans 02 + 03, parallel — after Plan 01):**
    - Plan 02: Allocation wins — PERF-01, PERF-02, PERF-05, PERF-08, PERF-09 (now operating on post-FPE structure)
    - Plan 03: Async batching — PERF-06 (OutputQueue.drain(); touches only output_queue.py)
  - **Wave 2 (Plans 04 → 05, sequential):**
    - Plan 04: State threading — PERF-03 (plugin state as parameter to compute_full/compute_next)
    - Plan 05: O(N) plugin conversion — PERF-04 (all 12 >20ms plugins; requires PERF-03)
  - **Wave 3 (Plan 06, depends on all prior):**
    - Plan 06: Per-key concurrency — PERF-07 (per-(symbol,tf) Queue + worker tasks; requires PERF-03)
- **D-09:** Plans 02 and 03 touch different files (feature_pipeline_executor.py + orchestrator vs. output_queue.py) and can execute in parallel.
- **D-10:** Plans 04 and 05 are sequential — plugin incremental path must be correctly threaded (plan 04) before benchmarking incremental plugins (plan 05).

### Measurement Strategy
- **D-11:** OBS-01 histogram data is live and actionable now (queried 2026-05-18). Use Prometheus query `histogram_quantile(0.95, rate(intelligence_pipeline_plugin_duration_ms_milliseconds_bucket[10m]))` before and after each plan to confirm improvement.
- **D-12:** Each plan must include a "before" Prometheus snapshot in its success criteria documentation. After-state must show measurable reduction in p95 for targeted plugins/operations.
- **D-13:** For allocation wins (plans 02, 03): use per-bar latency gauge `intelligence_pipeline_pipeline_latency_ms` as the primary before/after metric — individual alloc savings are too small for plugin histogram resolution.

### Renaissance Design Principles Applied
- **D-14:** Plan 03 (PERF-06): `_drain_output` drains up to N items per iteration. N is configurable (default 10). No manual tuning required — automation over manual caller discipline.
- **D-15:** Plan 04 (PERF-03): Plugin state flows as a parameter through the call stack (`compute_full(frames, state=...)`, `compute_next(windows, state=...)`). The `PluginExecutor` from Phase 088 receives state and lock per call — it never holds a reference to `PluginStateManager`. This eliminates the pre-dispatch mutation race.
- **D-16:** Plan 06 (PERF-07): Per-key workers are self-managing. The orchestrator calls `start_per_key_workers()` once in `_setup()`. Worker lifecycle (start, stop on teardown) is owned by the worker manager, not the orchestrator. Mirrors the CacheManager and PluginStateManager automation pattern from Phase 088.
- **D-17:** No manual profiling steps in the workflow. All measurement is via existing Prometheus histograms. No new tooling, no perf scripts, no manual benchmarks — automation over ceremony.

### FeaturePipelineExecutor: 6th DAG Node
- **D-18:** `FeaturePipelineExecutor` extracts `_run_i1_to_i6` (628–745 in intelligence_pipeline_agent.py post-088). Owns: frame assembly (bar_history reads, cross-tf event flattening, instrument context, VIX context, HTF intel, prev I1 features, cross_asset/macro from CacheSnapshot), I1 execution via PluginExecutor, tier execution (I2-I6) via PluginExecutor, IntelligenceEvent construction, `_prev_i1_features` + `_last_events` carry-forward state. Returns `FeaturePipelineResult(event: IntelligenceEvent | None, tiered: dict | None, main_df: DataFrame, hmm_regime: int | None)`. Orchestrator call: `result = await self._feature_pipeline.run(bar, cache_snapshot)`. File: `src/intelligence/pipeline/feature_pipeline_executor.py`.
- **D-25:** HMM regime update (currently line 490–492 of orchestrator): after FPE extraction, `FeaturePipelineExecutor.run()` sets `hmm_regime` on `FeaturePipelineResult`; orchestrator calls `self._cache_mgr.update_hmm_regime(result.hmm_regime)` from the result. No more sideways coupling where orchestrator reads intelligence output mid-bar and writes back to CacheManager.
- **D-26:** `to_dataframe()` deduplication is absorbed into D-18. Currently called at both line 494 (`_process_bar_inner`, I7 path) and line 635 (`_run_i1_to_i6`, I1-I6 path) for the same symbol/tf. After FPE extraction, FPE owns all dataframe construction; `main_df` is returned in `FeaturePipelineResult` and reused by `run_i7_complete()`. The orchestrator never calls `to_dataframe()` directly.

### CacheManager Stream Cache Migration (prerequisite for D-18)
- **D-19:** Three dicts currently in the orchestrator (lines 158–160 of intelligence_pipeline_agent.py post-088) are stream-fed caches that belong in CacheManager: `_cross_asset_cache` (updated from `topic_cross_asset` messages), `_macro_cache` (updated from `topic_macro_signals`), `_htf_intel_cache` (updated from HTF bar processing). Migration: add `update_cross_asset(tf, payload)`, `update_macro(tf, payload)`, `update_htf_intel(tf, data)` methods to CacheManager; extend CacheSnapshot with `cross_asset_data`, `macro_data`, `htf_intel`. Orchestrator's `_process_loop` calls update methods instead of direct dict assignment. Without this migration, FeaturePipelineExecutor would need 3 extra constructor injections from the orchestrator — violating the CacheSnapshot contract.

### PluginExecutor I7 Completion
- **D-20:** Add `PluginExecutor.run_i7_complete(intel_event, bar, cache_snapshot, state_mgr) -> list[dict]` to consolidate the 52-line I7 setup block currently in `_process_bar_inner` (lines 482–533). Internally: calls `_build_features_from_event(intel_event)`, assembles `plugin_input` dict, calls existing `run_i7_plugins()`, post-processes outputs (sets `setup_plugin`, `symbol`, `tf`, `regime_type` on each signal). Returns `raw_signals: list[dict]`. Orchestrator call reduces to two lines:
  ```python
  raw_signals = await self._executor.run_i7_complete(intel_event, bar, cache_snapshot, self._state_mgr)
  result = await self._sig_proc.process(intel_event, tiered, bar, raw_signals, cache_snapshot)
  ```
  The `regime_type` lookup currently accesses `self._executor._plugin_cache` directly (private attribute, line 529–530) — this is resolved by moving the lookup inside `run_i7_complete()`.

### Alpha Decay Ownership
- **D-21:** Move `_apply_alpha_decay` execution into `SignalProcessor.process()` as a pre-processing step. Currently the orchestrator calls `_apply_alpha_decay(sig, tf, self._sig_proc._setup_last_fire.get(fire_key))` at line 532, directly accessing private SignalProcessor state. Alpha decay is signal pre-processing — it belongs inside SignalProcessor. Orchestrator passes undecayed `raw_signals`; SignalProcessor applies decay before the gate pipeline. This closes the private attribute access across class boundaries.

### SignalProcessorResult Metrics
- **D-22:** SignalProcessor.process() must emit OTel counters for the following dimensions. Simons' principle: if you cannot see it on a dashboard, you cannot detect drift.
  - `signal_processor_cis_null_total` — counter incremented when CIS scoring returns None (no score available)
  - `signal_processor_dlq_total` — counter per DLQ event with `reason` label
  - `signal_processor_gate_rejections_total` — counter with `gate` label: `regime`, `quality`, `tod`, `calibration`
  - `signal_processor_winner_total` — counter with `entry_type` label (at_close, at_pullback, at_limit, at_reclaim, zone_proximal)
  - `signal_processor_signals_evaluated_total` — counter per bar (total signals entering the pipeline)
  Add to `src/observability/metrics.py`. These feed a single Grafana panel covering all 5 dimensions.

### Cleanup Items (absorbed into Plan 01)
- **D-24:** Four cleanup items with no risk, absorbed into Plan 01:
  1. `self._df_cache: dict = {}` at line 162 of orchestrator — initialized, never populated or read. Delete.
  2. Deferred inline imports at lines 485–487 and 517–519 (`_build_features_from_event`, `_apply_alpha_decay`) with `# noqa: PLC0415` — move to top-level once D-18 and D-21 remove their call sites from the orchestrator entirely.
  3. Orchestrator's `_plugin_cache` (lines 146–150) duplicates `PluginExecutor._plugin_cache`. After D-20 absorbs `regime_type` lookup into `run_i7_complete()`, the orchestrator's copy is unused. Delete.
  4. Direct private access `self._executor._plugin_cache.get(task.plugin_name)` at line 529–530 — resolved by D-20.

### Thread Pool Saturation Check
- **D-27:** Plan 06 (PERF-07) success criteria must include a thread pool saturation measurement. After per-key workers dispatch concurrently to the same thread pool, query whether active thread count approaches the worker cap under normal load. If saturated: PERF-07's benefit is bounded by the pool, not asyncio dispatch; increase `intelligence_thread_pool_workers` toward `cpu_count` (24 on this machine). If not saturated: PERF-07 delivers full benefit. Document the finding either way — it determines the Phase 090 scope.

### Symbol Filter Foundation (shard readiness, Plan 01)
- **D-28:** Add `intelligence_pipeline_symbol_filter: list[str] = []` to `src/config/settings.py`. Empty list = all active contracts (current behavior, no change). Non-empty = this process owns only those symbols. Used by PerKeyWorkerManager (D-29) to filter which keys it creates workers for, and by CacheManager (D-30) to scope DB queries. This single setting is the entire sharding deployment interface — scaling to 1000+ symbols becomes a configuration change, not a code change. No behavior change when unset.

### Thread Pool Cap Removal (Plan 01 cleanup)
- **D-29:** Remove the hardcoded `min(12, ...)` cap from the thread pool sizing formula in `IntelligencePipelineComputeAgent.__init__` (line 169). Current formula: `min(12, max(4, cpu_count // 2))`. New formula: `max(4, cpu_count // 2)` as the default, with `intelligence_thread_pool_workers` Settings override respected with no upper cap. On this machine (AMD Ryzen AI 9 HX 370, 12 physical cores / 24 logical): default remains 12, unchanged. The cap was a GIL-conservative heuristic that predates per-key workers. Our plugin workload is predominantly NumPy/pandas which releases the GIL during BLAS and vectorized operations — hyperthreads (the remaining 12 logical CPUs) are currently left idle. Post-PERF-07 saturation measurement (D-27) determines whether to increase toward 20-24 workers. For sharded deployments with fewer symbols per process, operators set higher values via Settings. No behavior change at default.

### CacheManager Symbol Scope (Plan 01, CacheManager migration)
- **D-30:** Add `symbols: frozenset[str] | None = None` to `CacheManager.__init__`. When None (default) — load and refresh all symbols (current behavior). When set — scope all DB queries (`perf_weights`, `calibration_curves`, `tod_priors`, `drift_penalties`, `cis_weights`) to the provided symbol set. Populated from `settings.intelligence_pipeline_symbol_filter` at construction. Without this, a shard handling 100 symbols out of 1000 still loads and refreshes all 1000 symbols' cache data — wasted memory and DB load. Zero behavior change when `symbol_filter` is empty. Implement as a `WHERE symbol = ANY($1)` clause on existing refresh queries.

### Claude's Discretion
- Exact `compute_next()` algorithm for MarketProfile (volume bucket structure, data type for bucket dict)
- Exact `compute_next()` algorithm for SessionLevels (rolling session high/low tracking structure)
- Whether BOCPD incremental is O(N) or O(K²) — profile first, optimize only if confirmed
- Whether per-key worker manager is a new class or inline in the orchestrator (prefer new class if >50 lines — module boundary principle)
- Exact batch size N for `_drain_output` (10 is a reasonable default; make it configurable via Settings)
- Whether `FeaturePipelineResult` carries `main_df` as a DataFrame or the plan passes `bar_history` ref to run_i7_complete — prefer returning `main_df` to avoid a second `to_dataframe()` call

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary target files (post-088 state)
- `services/intelligence_pipeline_agent.py` — 763-line orchestrator (post-088). Read `_process_bar_inner` (441), `_run_i1_to_i6` (628), `_process_loop` (375), `__init__` (111). This is the authoritative current state — not the pre-088 1928-line version.
- `src/intelligence/pipeline/executor.py` — PluginExecutor; `run_i7_complete()` being added in Plan 01
- `src/intelligence/pipeline/cache_manager.py` — CacheManager; stream cache methods + CacheSnapshot extension being added in Plan 01
- `src/intelligence/pipeline/signal_processor.py` — SignalProcessor; `_apply_alpha_decay` moving here, metrics being added in Plan 01
- `src/intelligence/pipeline/output_queue.py` — OutputQueue; `drain()` method target for PERF-06

### Phase 088 deliverables (prerequisite — must be complete)
- `.planning/phases/088-god-class-decomposition/088-CONTEXT.md` — D-10 (PluginExecutor state interface), D-14 (PluginStateManager checkpoint automation)
- `src/intelligence/pipeline/executor.py` — PluginExecutor; state + lock passed per call
- `src/intelligence/pipeline/state_manager.py` — PluginStateManager; per-key state + locks
- `src/intelligence/pipeline/__init__.py` — pipeline package exports

### Requirements
- `.planning/REQUIREMENTS.md` §PERF-01–PERF-09 — Acceptance criteria (PERF-10 excluded — covered by 088)

### Plugin system
- `src/intelligence/plugins.py` — Plugin base classes, `supports_incremental: ClassVar[bool]`, `compute_full`, `compute_next` signatures
- `src/intelligence/features/i3_structure/market_profile.py` — MarketProfile (PERF-04, `supports_incremental=False`)
- `src/intelligence/features/i3_structure/session_levels.py` — SessionLevels (PERF-04, `supports_incremental=False`)
- `src/intelligence/features/smc_context/bocpd_changepoint.py` — BOCPDChangePoint (`supports_incremental=True`, 77.9ms p95)
- `src/intelligence/features/smc_context/hmm_regime.py` — HMMRegime (`supports_incremental=True`, 23–35ms p95)

### Observability
- `src/observability/metrics.py` — OTel metric creation helpers; SignalProcessorResult counters being added in Plan 01
- `src/observability/spans.py` — `observed_span()`, ATTR_* constants

### Architecture principles
- `docs/principles.md` — Renaissance DAG principles

</canonical_refs>

<code_context>
## Existing Code Insights (post-088 line numbers)

### FeaturePipelineExecutor target (D-18)
- `_run_i1_to_i6` at line 628–745 of `intelligence_pipeline_agent.py` — 118 lines to extract. Reads 7 orchestrator-owned fields: `_last_events`, `_prev_i1_features`, `_cross_asset_cache`, `_macro_cache`, `_htf_intel_cache`, `_instrument_map`, `_vix_symbol`. Also calls `self._bar_history`, `self._executor`, `self._state_mgr` (which are injectable). After D-19 migrates the 3 stream caches to CacheManager, FPE receives all inputs via constructor injection + per-call CacheSnapshot.
- `_last_events` and `_prev_i1_features` are mutated inside `_run_i1_to_i6` (lines 695–696, 744) — they are carry-forward state, not caches. FPE owns them as instance dicts, same pattern as PluginStateManager owns plugin states.
- `_instrument_map` and `_vix_symbol` are read-only after `__init__` — pass by constructor reference to FPE.

### Orphaned stream caches (D-19)
- `self._cross_asset_cache: dict = {}` at line 158, updated at line 390 from `topic_cross_asset` messages
- `self._macro_cache: dict = {}` at line 159, updated at lines 392–403 from `topic_macro_signals` messages
- `self._htf_intel_cache: dict = {}` at line 160, read at line 677 inside `_run_i1_to_i6`
- None of these are in CacheManager. They should be — CacheManager is the single owner of all read caches. Migration is purely additive (new methods on CacheManager, new fields on CacheSnapshot).

### I7 setup block to extract (D-20)
- Lines 482–533 of `_process_bar_inner`: 52 lines of I7 setup that is not routing. Contains `_build_features_from_event()` call (with deferred import), HMM cache update, `plugin_input` assembly, `run_i7_plugins()` call, raw_signal post-processing (regime_type, setup_plugin, alpha_decay). All of this moves into `PluginExecutor.run_i7_complete()`.
- Line 529–530: `self._executor._plugin_cache.get(task.plugin_name)` — private attribute access across class boundary. Resolved by D-20 (lookup moves inside run_i7_complete).

### Deferred imports (D-24)
- Line 485–487: `from src.intelligence.pipeline.signal_processor import _build_features_from_event` with `# noqa: PLC0415`
- Line 517–519: `from src.intelligence.pipeline.signal_processor import _apply_alpha_decay` with `# noqa: PLC0415`
- Both become unnecessary after D-18 (FPE) and D-21 (alpha decay into SignalProcessor).

### Dead code (D-24)
- `self._df_cache: dict = {}` at line 162 — initialized, never read or written anywhere in the file. Delete.
- Orchestrator `_plugin_cache` (lines 146–150) — redundant with `PluginExecutor._plugin_cache`. Unused after D-20.

### PERF-01 Target
- `_build_features_from_event()` in `src/intelligence/pipeline/signal_processor.py` — called at line 489 of orchestrator (with deferred import). After D-18/D-20, called once per bar inside `run_i7_complete()`; result passed to SignalProcessor. The 7x `model_dump()` allocations happen inside this function — verify it's called once, not once per I7 plugin.

### PERF-02 Target
- Flat `features` dual-write in `executor.py` (run_tiers method) — wave merges write same data to both tiered dict and flat features dict. Profile whether any active plugin uses the flat path after PERF-03; remove if unused.

### PERF-03 Target
- `plugin._state` assignment in `executor.py` (run_i1, run_tiers, run_i7_plugins methods) — shared mutable assignment before thread-pool dispatch. Thread state through as parameter to `compute_full(frames, state=...)` and `compute_next(windows, state=...)`.

### PERF-05 Target
- `IntelligenceEvent` construction at lines 716–727 of `intelligence_pipeline_agent.py` (inside `_run_i1_to_i6`, moving to `feature_pipeline_executor.py` in Plan 01) — 7× `{k: v for k, v in tier.items() if v is not None}` comprehensions. Replace with pre-filtered dicts assembled during wave merging in executor.py.

### PERF-06 Target
- `drain()` method in `src/intelligence/pipeline/output_queue.py` (post-088 owner) — single `await` per message. Change to drain up to N items from queue per iteration before yielding.

### PERF-07 Target
- `await self._process_bar(bar)` at line 412 of orchestrator — sequential per-bar in the consume loop. Refactor to per-key Queue + worker task dispatch.

### PERF-08 Target
- `BarMessage(**msg)` at line 430 of orchestrator — full Pydantic validation on trusted internal messages. Replace with `BarMessage.model_construct(**msg)` on hot path; keep full validation on DLQ/error paths.

### PERF-09 Target
- `bar.model_copy(update={"gap_preceding": True})` at line 451 — allocates a new BarMessage just to set one flag. Pass gap flag as parameter through the call stack instead.

### to_dataframe() dedup (D-26)
- Line 494 in `_process_bar_inner`: `main_df = self._bar_history.to_dataframe(symbol, tf)` for I7 `plugin_input`
- Line 635 in `_run_i1_to_i6`: same call for I1-I6 `frames`
- Line 643: additional calls for cross-tf frames
- After D-18 (FPE) owns both frame assembly paths, `main_df` is built once and returned in `FeaturePipelineResult`. Absorbed into Plan 01; not a separate task.

### Established Patterns
- Per-key state isolation: `_plugin_states: dict[tuple, dict]` keyed by `(plugin_name, symbol, tf)` — each key is fully independent, enabling safe concurrent dispatch after PERF-03
- Background task automation: `CacheManager.start_refresh_loops()` and `PluginStateManager.start_checkpoint_loop()` from Phase 088 — per-key worker manager follows the same `start_*()`/teardown pattern
- `asyncio.Queue` in use as `OutputQueue` (post-088) — per-key worker queues follow the same pattern
- `CacheSnapshot` dataclass for per-call cache reads (no direct CacheManager reference in downstream nodes) — extend, don't replace

### Integration Points
- After Plan 01: `_process_bar_inner` reduces from 125 lines to ~20 lines (gap detection + FPE call + I7 call + SignalProcessor call + 4-way routing + journal)
- After Plan 04 (PERF-03): `PluginExecutor.run_tiers()` and `run_i7_plugins()` receive `state: dict, lock: asyncio.Lock` as parameters — threads through to `compute_full`/`compute_next`
- After Plan 06 (PERF-07): orchestrator's consume loop calls `worker_manager.enqueue(bar)` instead of `await _process_bar(bar)`; per-key task calls `_process_bar_inner`

</code_context>

<specifics>
## Specific Ideas

- "Design this like Renaissance would" — the orchestrator is the DAG router; every computation belongs in a named node with typed I/O. After Plan 01, _process_bar_inner will be ~20 lines: gap flag, FPE, I7, SignalProcessor, 4-way route. That is the DAG description, not the computation.
- "Microservices DAG within the process" — PERF-07's per-key Queue + worker architecture IS the in-process microservices DAG for bar processing. Each (symbol, tf) key is a worker node. Orchestrator is the router. Exactly mirrors the service DAG topology.
- "Instrument everything" — SignalProcessor emits metrics for every gate (D-22). Without CIS null rate, DLQ rate, and per-gate rejection counts on a Grafana panel, model drift is invisible. This is non-negotiable from a Renaissance standpoint.
- "Balance efficiency with simplicity" — Plan 01 (architecture) first; allocation wins (plans 02/03) after the structure is right. PERF-07 is highest risk and highest reward — last.
- "No manual tasks, prefer automation" — batch drain size configurable via Settings; per-key worker lifecycle owned by worker manager; measurement via existing Prometheus.

</specifics>

<deferred>
## Deferred Ideas

- **Phase 090 candidate (thread pool sizing)**: Plan 06 success criteria require measuring thread pool saturation post-PERF-07 (D-27). If all 12 workers are saturated under load, Phase 090 addresses thread pool sizing. Current 12-worker cap is a GIL-era constant.
- **Phase 090 candidate (wave-level parallelism)**: If PERF-07 reveals that the bottleneck shifts to within-bar computation (I1→I4 independent tiers), wave-level parallelism within a single bar's I1→I7 pipeline is a separate phase.
- **HMM/BOCPD algorithm optimization**: If profiling after PERF-03 shows HMM/BOCPD incremental is still unacceptably slow (not just statistically bounded), deeper algorithmic work (GPU acceleration, approximation) is a future phase.
- **CacheSnapshot versioning**: CacheSnapshot is constructed fresh every bar (line 538–545). Could be cached with a version stamp and only rebuilt when underlying data changes. Micro-optimization; defer until allocation win measurements suggest it's worth it.

</deferred>

---

*Phase: 089-compute-performance-optimization*
*Context gathered: 2026-05-18*
*Context updated: 2026-05-18 — added FeaturePipelineExecutor (D-18/D-25/D-26), stream cache migration (D-19), run_i7_complete (D-20), alpha decay ownership (D-21), SignalProcessorResult metrics (D-22), cleanup (D-24), thread pool saturation check (D-27), symbol filter foundation (D-28), thread pool cap removal (D-29), CacheManager symbol scope (D-30), revised to 6-plan 4-wave structure (D-08)*
