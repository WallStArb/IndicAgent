# Phase 089: Compute Performance Optimization - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Eliminate per-bar allocation overhead, fix the plugin state race condition, convert O(N) recomputation plugins to incremental compute, batch Kafka drain output, and introduce per-key concurrent bar processing — using live OBS-01 histogram data to prioritize targets.

All work is surgical optimization inside `IntelligencePipelineComputeAgent` (and its 088-extracted classes). Zero behavior change — no signal logic altered, no schema changes. Phase delivers measurable throughput improvement validated by before/after OBS-01 histogram comparison.

**Requires Phase 088 to be complete before executing Plans 03, 04, 05.**

</domain>

<decisions>
## Implementation Decisions

### PERF-07: Per-Key Concurrency Model
- **D-01:** Per-key Queue + worker tasks. Each `(symbol, tf)` key gets a dedicated `asyncio.Queue` and a long-running `asyncio.Task` that consumes from it. The orchestrator (or OutputQueue equivalent) fans out incoming bars to per-key queues. Each worker task processes bars sequentially within its key — preserving in-order guarantees. Independent keys run concurrently with no coordination overhead.
- **D-02:** This is Plan 05 (wave 3), executing after PERF-03 (state threading). Safe concurrent dispatch requires plugin state to be a per-call parameter, not shared mutable assignment on `plugin._state` before thread-pool dispatch. PERF-03 is the prerequisite.
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

### Plan Structure (5 plans, wave-based)
- **D-08:** 5 plans in 3 waves:
  - **Wave 1 (plans 01 + 02, parallel):**
    - Plan 01: Allocation wins — PERF-01 (model_dump cache), PERF-02 (flat features dual-write), PERF-05 (IntelligenceEvent comprehensions), PERF-08 (model_construct), PERF-09 (model_copy gap flag)
    - Plan 02: Async batching — PERF-06 (drain N items per iteration)
  - **Wave 2 (plan 03 then 04, sequential):**
    - Plan 03: State threading — PERF-03 (plugin state as parameter to compute_full/compute_next; eliminates plugin._state mutation before thread-pool dispatch; requires 088's PluginExecutor interface)
    - Plan 04: O(N) plugin conversion — PERF-04 (all 12 >20ms plugins; requires PERF-03 to verify incremental path is exercised)
  - **Wave 3 (plan 05, depends on plans 01–04):**
    - Plan 05: Per-key concurrency — PERF-07 (per-(symbol,tf) Queue + worker tasks; requires PERF-03 state threading for safe concurrent dispatch)
- **D-09:** Plans 01 and 02 touch different code paths (hot-path allocation methods vs `_drain_output` loop) and can execute in parallel.
- **D-10:** Plans 03 and 04 are sequential — plugin incremental path must be correctly threaded (plan 03) before benchmarking incremental plugins (plan 04).

### Measurement Strategy
- **D-11:** OBS-01 histogram data is live and actionable now (queried 2026-05-18). Use Prometheus query `histogram_quantile(0.95, rate(intelligence_pipeline_plugin_duration_ms_milliseconds_bucket[10m]))` before and after each plan to confirm improvement.
- **D-12:** Each plan must include a "before" Prometheus snapshot in its success criteria documentation. After-state must show measurable reduction in p95 for targeted plugins/operations.
- **D-13:** For allocation wins (plans 01, 02): use per-bar latency gauge `intelligence_pipeline_pipeline_latency_ms` as the primary before/after metric — individual alloc savings are too small for plugin histogram resolution.

### Renaissance Design Principles Applied
- **D-14:** Plan 02 (PERF-06): `_drain_output` drains up to N items per iteration. N is configurable (default 10). No manual tuning required — automation over manual caller discipline.
- **D-15:** Plan 03 (PERF-03): Plugin state flows as a parameter through the call stack (`compute_full(frames, state=...)`, `compute_next(windows, state=...)`). The `PluginExecutor` from Phase 088 receives state and lock per call — it never holds a reference to `PluginStateManager`. This eliminates the pre-dispatch mutation race.
- **D-16:** Plan 05 (PERF-07): Per-key workers are self-managing. The orchestrator calls `start_per_key_workers()` once in `_setup()`. Worker lifecycle (start, stop on teardown) is owned by the worker manager, not the orchestrator. Mirrors the CacheManager and PluginStateManager automation pattern from Phase 088.
- **D-17:** No manual profiling steps in the workflow. All measurement is via existing Prometheus histograms. No new tooling, no perf scripts, no manual benchmarks — automation over ceremony.

### Claude's Discretion
- Exact `compute_next()` algorithm for MarketProfile (volume bucket structure, data type for bucket dict)
- Exact `compute_next()` algorithm for SessionLevels (rolling session high/low tracking structure)
- Whether BOCPD incremental is O(N) or O(K²) — profile first, optimize only if confirmed
- Whether per-key worker manager is a new class or inline in the orchestrator (prefer new class if >50 lines — module boundary principle)
- Exact batch size N for `_drain_output` (10 is a reasonable default; make it configurable via Settings)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary target file
- `services/intelligence_pipeline_agent.py` — 1928-line file containing all PERF targets. Read `_process_bar`, `_process_bar_inner`, `_build_features_from_event`, `_run_tiers`, `_run_i7_inner`, `_drain_output`, `_parse_bar`. After Phase 088 executes, read the thin orchestrator + extracted classes instead.

### Phase 088 deliverables (prerequisite — must be complete before plans 03, 04, 05)
- `.planning/phases/088-god-class-decomposition/088-CONTEXT.md` — D-10 (PluginExecutor state interface), D-14 (PluginStateManager checkpoint automation), D-15 (checkpoint raises on failure)
- `src/intelligence/pipeline/executor.py` — PluginExecutor class (post-088); state + lock passed per call
- `src/intelligence/pipeline/state_manager.py` — PluginStateManager class (post-088); per-key state + locks

### Requirements
- `.planning/REQUIREMENTS.md` §PERF-01–PERF-09 — Acceptance criteria for each PERF item (PERF-10 excluded — covered by 088)

### Plugin system
- `src/intelligence/plugins.py` — Plugin base classes, `supports_incremental: ClassVar[bool]`, `compute_full`, `compute_next` signatures
- `src/intelligence/features/i3_structure/market_profile.py` — MarketProfile plugin (PERF-04 target, `supports_incremental=False`)
- `src/intelligence/features/i3_structure/session_levels.py` — SessionLevels plugin (PERF-04 target, `supports_incremental=False`)
- `src/intelligence/features/smc_context/bocpd_changepoint.py` — BOCPDChangePoint (`supports_incremental=True`, 77.9ms p95)
- `src/intelligence/features/smc_context/hmm_regime.py` — HMMRegime (`supports_incremental=True`, 23–35ms p95)

### Observability
- `src/observability/metrics.py` — OTel metric creation helpers (counter, gauge, histogram)
- `src/observability/spans.py` — `observed_span()` for span creation; ATTR_* constants

### Architecture principles
- `docs/principles.md` — Renaissance DAG principles: automation over manual tasks, separation of concerns

</canonical_refs>

<code_context>
## Existing Code Insights

### PERF-01 Target
- `_build_features_from_event()` at line 214 — module-level function, called at line 1313 inside `_run_i7_inner`. Called once per I7 plugin call today. Cache result per bar (pass `features` dict from caller rather than recomputing).

### PERF-02 Target
- Flat `features` dual-write at line 1253 — wave merges write same data to both tiered dict and flat features dict on every tier. Profile whether any active plugin uses the flat path; remove if unused.

### PERF-03 Target
- `plugin._state = self._plugin_states.get(state_key, {})` at lines 1146, 1223, 1349 — shared mutable assignment before thread-pool dispatch. After 088, `PluginExecutor` receives `state: dict` and `lock: asyncio.Lock` per call — this pattern must be eliminated.

### PERF-05 Target
- `IntelligenceEvent` construction at lines 987-993 — 7× `{k: v for k, v in tier.items() if v is not None}` comprehensions at event build time. Replace with pre-filtered dicts assembled during wave merging.

### PERF-06 Target
- `_drain_output` at line 1044 — single `await` per message. Change to drain up to N items from queue per iteration before yielding.

### PERF-07 Target
- `await self._process_bar(bar)` at line 820 — sequential per-bar in the consume loop. Refactor to per-key Queue + worker task dispatch.

### PERF-08 Target
- `BarMessage(**msg)` at line 845 — full Pydantic validation on trusted internal messages. Replace with `BarMessage.model_construct(**msg)` on the hot path; keep full validation on DLQ/error paths.

### PERF-09 Target
- `bar.model_copy(update={"gap_preceding": True})` at line 871 — allocates a new BarMessage just to set one flag. Pass gap flag as parameter through the call stack instead.

### Established Patterns
- Per-key state isolation: `_plugin_states: dict[tuple, dict]` keyed by `(plugin_name, symbol, tf)` — each key is fully independent, enabling safe concurrent dispatch
- Background task automation: `CacheManager.start_refresh_loops()` and `PluginStateManager.start_checkpoint_loop()` patterns from Phase 088 — per-key worker manager should follow the same `start_*()` / teardown pattern
- `asyncio.Queue` already in use as `_output_queue` (OutputQueue class after 088) — per-key worker queues follow the same pattern

### Integration Points
- After Phase 088: `PluginExecutor.run_tiers()` receives `state: dict, lock: asyncio.Lock` as parameters (D-10 from 088) — PERF-03 state threading threads state through to `compute_full`/`compute_next`
- `_drain_output` (PERF-06) is owned by `OutputQueue` class after 088 — PERF-06 modifies `OutputQueue.drain()` method, not the orchestrator
- Per-key workers (PERF-07) replace `await _process_bar(bar)` in the orchestrator's consume loop — orchestrator calls `worker_manager.enqueue(bar)` and the per-key task calls `_process_bar_inner`

</code_context>

<specifics>
## Specific Ideas

- "Design this like Renaissance would" — Jim Simons principle applied throughout: each optimization is a DAG node transformation (state as parameter = typed I/O), automation over manual discipline (configurable drain batch size, self-managing per-key workers, Prometheus-based measurement), no manual profiling ceremonies. Independence where independence exists — per-key workers is the natural consequence of recognizing that (symbol, tf) streams are independent DAG lanes.
- "Microservices DAG within the process" — PERF-07's per-key Queue + worker architecture IS the in-process microservices DAG for bar processing. Each (symbol, tf) key is a worker node. Orchestrator is the router. Exactly mirrors the service DAG topology.
- "Balance efficiency with simplicity" — allocation wins (plans 01, 02) are zero-risk, high-leverage. Do them first. PERF-07 is highest risk and highest reward — do it last, after state threading makes it safe.
- "No manual tasks, prefer automation" — batch drain size configurable via Settings (not hardcoded); per-key worker lifecycle owned by worker manager class (not orchestrator); measurement via existing Prometheus (no new tooling).

</specifics>

<deferred>
## Deferred Ideas

- **Phase 090 candidate**: If PERF-07 per-key concurrency reveals additional parallelism opportunities (e.g., wave-level parallelism within a single bar's I1→I7 pipeline), that is a separate phase.
- **HMM/BOCPD algorithm optimization**: If profiling after PERF-03 shows HMM/BOCPD incremental is still unacceptably slow (not just statistically bounded), deeper algorithmic work (GPU acceleration, approximation) is a future phase.
- **Thread pool sizing**: Current 12-worker cap is a GIL-era constant. Post-PERF-07 concurrency may expose new thread pool saturation. Thread pool tuning is Phase 090+ concern.

</deferred>

---

*Phase: 089-compute-performance-optimization*
*Context gathered: 2026-05-18*
