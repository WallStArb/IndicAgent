# Phase 089: Compute Performance Optimization - Pattern Map

**Mapped:** 2026-05-18
**Files analyzed:** 13 new/modified files
**Analogs found:** 13 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/intelligence/pipeline/feature_pipeline_executor.py` | service | request-response | `services/intelligence_pipeline_agent.py` (`_run_i1_to_i6`) | exact — extract-in-place |
| `src/intelligence/pipeline/per_key_worker_manager.py` | service | event-driven | `src/intelligence/pipeline/output_queue.py` | role-match — asyncio.Queue + loop pattern |
| `services/intelligence_pipeline_agent.py` | service | event-driven | self (existing, trimming) | exact — orchestrator slim-down |
| `src/intelligence/pipeline/executor.py` | service | request-response | self (existing, adding `run_i7_complete` + PERF-03) | exact |
| `src/intelligence/pipeline/cache_manager.py` | service | CRUD | self (existing, adding stream cache methods) | exact |
| `src/intelligence/pipeline/signal_processor.py` | service | request-response | self (existing, absorbing `_apply_alpha_decay` + D-22 metrics) | exact |
| `src/intelligence/pipeline/output_queue.py` | service | event-driven | self (existing, adding batch drain) | exact |
| `src/intelligence/plugins.py` | utility | transform | self (existing, adding `state=` param to protocol) | exact |
| `src/intelligence/features/i3_structure/market_profile.py` | utility | transform | `src/intelligence/features/smc_context/bocpd_changepoint.py` | role-match — incremental plugin with state |
| `src/intelligence/features/i3_structure/session_levels.py` | utility | transform | `src/intelligence/features/smc_context/bocpd_changepoint.py` | role-match — incremental plugin with state |
| `src/intelligence/features/smc_context/bocpd_changepoint.py` | utility | transform | self (verify/profile only — no code change if PERF-03 fix resolves it) | exact |
| `src/intelligence/features/smc_context/hmm_regime.py` | utility | transform | self (verify/profile only) | exact |
| `src/config/settings.py` | config | transform | self (existing, adding two fields + removing min cap) | exact |
| `src/observability/metrics.py` | utility | transform | self (existing, adding 5 module-level counters) | exact |

---

## Pattern Assignments

### `src/intelligence/pipeline/feature_pipeline_executor.py` (service, request-response)

**Analog:** `services/intelligence_pipeline_agent.py` lines 628-745 (the `_run_i1_to_i6` body being extracted) and `src/intelligence/pipeline/signal_processor.py` (structural pattern for a class that receives injected dependencies and CacheSnapshot, owns carry-forward state).

**Constructor pattern** — mirror SignalProcessor lines 153-169 but with bar_history/executor/state_mgr injections:

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
        self._bar_history = bar_history
        self._executor = executor
        self._state_mgr = state_mgr
        self._instrument_map = instrument_map
        self._vix_symbol = vix_symbol
        # Carry-forward state — owned by FPE, migrated FROM orchestrator lines 163-165
        self._prev_i1_features: dict = {}   # keyed by f"{symbol}:{tf}"
        self._last_events: dict = {}         # keyed by f"{symbol}:{tf}"
        self._logger = structlog.get_logger(__name__)
```

**Return dataclass** — mirror `SignalProcessorResult` at `signal_processor.py` lines 122-134:

```python
@dataclass
class FeaturePipelineResult:
    event: IntelligenceEvent | None
    tiered: dict | None
    main_df: Any          # pandas DataFrame — reused by run_i7_complete (D-26)
    hmm_regime: int | None
```

**Core run() body** — exact extraction from orchestrator lines 628-745. After D-19 migration, reads stream caches from `cache_snapshot` fields (not self._):

```python
async def run(self, bar: BarMessage, cache_snapshot: CacheSnapshot) -> FeaturePipelineResult:
    symbol, tf = bar.symbol, bar.tf
    key = f"{symbol}:{tf}"

    main_df = self._bar_history.to_dataframe(symbol, tf)
    frames: dict[str, Any] = {"main": main_df, "__symbol__": symbol, "__timeframe__": tf}

    # Cross-tf frames (orchestrator lines 638-655)
    for other_tf in _STANDARD_TFS:
        if other_tf == tf:
            continue
        # ... (copy exact body from orchestrator lines 639-655)

    # Instrument context (line 657-659)
    instrument = self._instrument_map.get(symbol)
    if instrument:
        frames["__instrument__"] = instrument

    frames["prev_features"] = self._prev_i1_features.get(key, {})

    # Stream caches from CacheSnapshot (D-19 — no longer reads self._cross_asset_cache etc.)
    if resolve_eq_index_base(symbol) is not None:
        cross_asset = {**cache_snapshot.cross_asset_data.get(tf, {"ready": False})}
        cross_asset.update(cache_snapshot.macro_data.get(tf, {}))
        frames["cross_asset"] = cross_asset

    # VIX context (lines 671-675)
    if self._vix_symbol:
        vix_deque = self._bar_history.get(self._vix_symbol, VIX_REGIME_TF)
        frames["vix"] = compute_vix_context(vix_deque)
    else:
        frames["vix"] = {"ready": False}

    # HTF intel from CacheSnapshot (D-19)
    htf_cache = cache_snapshot.htf_intel.get(tf)
    if htf_cache:
        frames["htf_intel"] = htf_cache

    # State fetch for I1 + tiers (orchestrator lines 681-682)
    plugin_states = self._state_mgr.get_all_states_for(symbol, tf)
    lock = self._state_mgr.get_lock((symbol, tf))

    # I1 execution (orchestrator lines 684-696)
    i1_result, i1_state_updates = await self._executor.run_i1(...)
    if i1_state_updates:
        self._state_mgr.update_batch(i1_state_updates)
    frames["features"] = dict(i1_result)
    self._prev_i1_features[key] = dict(i1_result)

    # Tier execution (orchestrator lines 698-710)
    tiered, tier_state_updates = await self._executor.run_tiers(...)
    if tier_state_updates:
        self._state_mgr.update_batch(tier_state_updates)
    if not tiered:
        return FeaturePipelineResult(event=None, tiered=None, main_df=main_df, hmm_regime=None)

    # IntelligenceEvent construction (orchestrator lines 716-745)
    # 7x comprehensions: {k: v for k, v in tier.items() if v is not None} — PERF-05 target
    event = IntelligenceEvent(
        ts=bar.ts, symbol=symbol, tf=tf,
        i1=I1Indicators(**{k: v for k, v in i1_result.items() if v is not None}),
        # ... other tiers same pattern
    )

    self._last_events[key] = event
    hmm_val = frames.get("features", {}).get("hmm_regime")
    hmm_regime = int(hmm_val) if isinstance(hmm_val, (int, float)) else None
    return FeaturePipelineResult(event=event, tiered=tiered, main_df=main_df, hmm_regime=hmm_regime)
```

**Imports pattern** — copy top-level imports from `intelligence_pipeline_agent.py` lines 9-85 (all schema types, stream key helpers, pipeline imports). FPE needs: `IntelligenceEvent`, `I1Indicators`, `I2Events`, `I3Structure`, `I4Context`, `I5Patterns`, `I6Confluence`, `SMCContext`, `OHLCVBar`, `BarMessage`, `BarHistory`, `CacheSnapshot`, `PluginExecutor`, `PluginStateManager`, `compute_vix_context`, `resolve_eq_index_base`, structlog.

**No lateral imports rule** — FPE MUST NOT import from `cache_manager.py` or `output_queue.py`. It receives `CacheSnapshot` as a parameter. Same pattern as `SignalProcessor` which also never holds a CacheManager reference (signal_processor.py line 8-10 docstring).

---

### `src/intelligence/pipeline/per_key_worker_manager.py` (service, event-driven)

**Analog:** `src/intelligence/pipeline/output_queue.py` (asyncio.Queue + background task lifecycle), `src/intelligence/pipeline/state_manager.py` `start_checkpoint_loop()` (self-managing background task lifecycle).

**Constructor + Queue init pattern** — copy `OutputQueue.__init__` structure (output_queue.py lines 47-63) substituting per-key queues for a single queue:

```python
class PerKeyWorkerManager:
    def __init__(
        self,
        keys: list[tuple[str, str]],
        process_bar_fn,                # Callable[[BarMessage], Coroutine]
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
        self._logger = structlog.get_logger(__name__)
```

**Self-managing lifecycle pattern** — copy `PluginStateManager.start_checkpoint_loop()` pattern (state_manager.py lines 80+): orchestrator calls `start_per_key_workers()` once in `_setup()`, stores returned task handles in `self._background_tasks`, never calls the lifecycle again:

```python
def start_per_key_workers(self) -> list[asyncio.Task]:
    """Start one worker Task per (symbol,tf) key. Call once from orchestrator._setup()."""
    for key, queue in self._queues.items():
        task = asyncio.create_task(self._worker(key, queue), name=f"worker_{key[0]}_{key[1]}")
        self._tasks.append(task)
    return list(self._tasks)

async def enqueue(self, bar: BarMessage) -> None:
    key = (bar.symbol, bar.tf)
    queue = self._queues.get(key)
    if queue is not None:
        await queue.put(bar)

async def _worker(self, key: tuple, queue: asyncio.Queue) -> None:
    """Long-running per-key task — processes bars sequentially within key."""
    while True:
        bar = await queue.get()
        try:
            await self._process_bar_fn(bar)
        except Exception as exc:
            self._logger.error("per_key_worker.error", key=key, error=str(exc))
        finally:
            queue.task_done()

async def teardown(self) -> None:
    """Cancel all worker tasks. Called from orchestrator._teardown()."""
    for task in self._tasks:
        task.cancel()
```

**Background task registration pattern** — copy orchestrator lines 247-249, 263-265 (how CacheManager refresh tasks are registered):

```python
# In orchestrator._setup() after constructing PerKeyWorkerManager:
for task in self._worker_mgr.start_per_key_workers():
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
```

---

### `services/intelligence_pipeline_agent.py` (orchestrator — slim-down)

**Pattern: reduce `_process_bar_inner` to pure routing** — after FPE extraction, the method reduces to the structure at lines 441-568 with the FPE call replacing lines 459-513 and the snapshot construction simplified:

```python
async def _process_bar_inner(self, bar: BarMessage) -> None:
    """D-08 DAG description: I1-I6 → canonical event → I7 → 4-way routing."""
    t0 = time.perf_counter()

    # Gap detection (lines 446-452 — unchanged)
    key = f"{bar.symbol}:{bar.tf}"
    prev_ts = self._last_bar_ts.get(key)
    if prev_ts is not None:
        tf_seconds = TF_SECONDS.get(bar.tf, 60)
        if (bar.ts.timestamp() - prev_ts) > tf_seconds * 1.5:
            bar = bar.model_copy(update={"gap_preceding": True})  # PERF-09 target
    self._last_bar_ts[key] = bar.ts.timestamp()

    self._bar_history.append(bar)
    if not self._bar_history.is_warm(bar.symbol, bar.tf, min_bars_for_tf(bar.tf)):
        return

    # Build CacheSnapshot including stream caches (D-19 extended snapshot)
    snapshot = CacheSnapshot(
        perf_weights=self._cache_mgr.perf_weights,
        calibration_curves=self._cache_mgr.calibration_curves,
        tod_priors=self._cache_mgr.tod_priors,
        drift_penalties=self._cache_mgr.drift_penalties,
        cis_weights=self._cache_mgr.cis_weights,
        cis_weights_version=self._cache_mgr.cis_weights_version,
        cross_asset_data=self._cache_mgr.cross_asset_data,  # D-19 new fields
        macro_data=self._cache_mgr.macro_data,
        htf_intel=self._cache_mgr.htf_intel,
    )

    # FPE call (replaces _run_i1_to_i6)
    result = await self._feature_pipeline.run(bar, snapshot)
    if result.event is None:
        return
    self._cache_mgr.update_hmm_regime(result.hmm_regime)  # D-25

    # Intel event publish (line 469-475 — unchanged)
    msg_key = message_key(bar.symbol, bar.tf)
    self._out_queue.enqueue(output_topic, msg_key, {"event": result.event.model_dump_json()})

    # I7 via run_i7_complete (D-20 — replaces lines 482-534)
    raw_signals = await self._executor.run_i7_complete(
        result.event, bar, snapshot, result.main_df,
        plugin_states=self._state_mgr.get_all_states_for(bar.symbol, bar.tf),
        lock=self._state_mgr.get_lock((bar.symbol, bar.tf)),
    )

    # SignalProcessor (line 546-548 — simplified)
    proc_result = await self._sig_proc.process(
        result.event, result.tiered, bar, bar.symbol, bar.tf,
        raw_signals=raw_signals, cache_snapshot=snapshot,
    )

    # 4-way routing (lines 550-566 — unchanged)
    ...
```

**Dead code to delete** (D-24):
- Line 146-150: `self._plugin_cache` block (all 5 lines)
- Line 162: `self._df_cache: dict = {}`
- Lines 485-487: deferred import `_build_features_from_event` with `# noqa: PLC0415`
- Lines 517-519: deferred import `_apply_alpha_decay` with `# noqa: PLC0415`

**`_process_loop` stream cache update pattern** — after D-19, replace direct dict mutation (lines 389-403) with CacheManager method calls:

```python
# Before (lines 389-403):
self._cross_asset_cache[tf] = payload
self._macro_cache.setdefault(tf, {}).update({...})

# After (D-19):
self._cache_mgr.update_cross_asset(tf, payload)
self._cache_mgr.update_macro(tf, payload)
```

**Thread pool cap removal** (D-29) — line 169:

```python
# Before:
_workers = _configured if _configured > 0 else min(12, max(4, cpu_count // 2))
# After:
_workers = _configured if _configured > 0 else max(4, cpu_count // 2)
```

---

### `src/intelligence/pipeline/executor.py` (adding `run_i7_complete`, fixing PERF-03)

**Analog for `run_i7_complete`:** orchestrator lines 482-534 (the 52-line I7 setup block being extracted into this method).

**`run_i7_complete` method** — consolidates I7 setup, follows existing `run_i1` signature pattern (executor.py lines 255-318):

```python
async def run_i7_complete(
    self,
    intel_event: Any,
    bar: Any,
    cache_snapshot: Any,           # CacheSnapshot — avoid import cycle, use Any
    main_df: Any,                  # DataFrame from FeaturePipelineResult.main_df (D-26)
    plugin_states: dict[str, dict],
    lock: threading.Lock,
) -> list[dict]:
    """Consolidate 52-line I7 setup block from orchestrator (D-20).

    Returns raw_signals: list of signal dicts with setup_plugin, symbol, tf,
    regime_type already set. Alpha decay is applied by SignalProcessor.process() (D-21).

    Receives state/lock as pre-fetched parameters — does NOT hold PluginStateManager
    reference (D-15 contract).
    """
    # Import is top-level after D-18/D-21 remove the deferred import sites
    from src.intelligence.pipeline.signal_processor import _build_features_from_event

    symbol, tf = bar.symbol, bar.tf
    features = _build_features_from_event(intel_event)

    plugin_input = {
        "main": main_df,           # D-26: reuse main_df from FeaturePipelineResult
        "features": features,
        "__symbol__": symbol,
        "__timeframe__": tf,
        "timeframe": tf,
    }

    tasks, outputs, sig_state_updates = await self.run_i7_plugins(
        plugin_states, lock, bar, symbol, tf, plugin_input,
        shadow_cache=cache_snapshot.shadow_cache if hasattr(cache_snapshot, "shadow_cache")
        else {},
    )
    # State updates returned to caller (orchestrator calls state_mgr.update_batch)

    raw_signals: list[dict] = []
    for task, output in zip(tasks, outputs):
        output.pop("_tier_key", None)
        if output.get("direction", 0) != 0:
            sig = output
            sig["setup_plugin"] = task.plugin_name
            sig["symbol"] = symbol
            sig["tf"] = tf
            # regime_type lookup moved inside run_i7_complete (D-20 resolves line 529-530)
            plugin_inst = self._plugin_cache.get(task.plugin_name)
            sig["regime_type"] = getattr(plugin_inst, "regime_type", "any")
            # Alpha decay NOT applied here — SignalProcessor.process() owns it (D-21)
            raw_signals.append(sig)

    return raw_signals, sig_state_updates
```

**PERF-03 fix — state threading pattern.** The `_timed_plugin_call` function and all three call sites (`run_i1` line 298, `run_tier` line 360, `run_i7_plugins` line 508) must be updated together. Current broken pattern and the fix:

```python
# CURRENT (race condition — shared mutable write before thread dispatch):
# executor.py line 298, 360, 508:
plugin._state = plugin_states.get(plugin_name, {})
loop.run_in_executor(self._thread_pool, _timed_plugin_call, plugin, frames)

# FIXED (state as parameter — no shared write):
def _timed_plugin_call(plugin, frames, state: dict):
    """Wrapper passes state as parameter instead of mutating plugin._state."""
    t0 = time.perf_counter()
    if getattr(plugin, "supports_incremental", False) and state:
        result = plugin.compute_next(frames, state=state)
    else:
        result = plugin.compute_full(frames, state=state)
    duration_ms = (time.perf_counter() - t0) * 1000
    return result, duration_ms

# All three call sites become:
state = plugin_states.get(plugin_name, {})
tasks.append(PluginTask(
    coroutine=loop.run_in_executor(
        self._thread_pool, _timed_plugin_call, plugin, frames, state
    ),
    ...
))
```

**Grep verification after PERF-03:** `grep -n "plugin._state =" src/intelligence/pipeline/executor.py` must return zero results.

---

### `src/intelligence/pipeline/cache_manager.py` (adding stream cache methods, D-19 + D-30)

**Analog:** existing `CacheManager` seed methods pattern (cache_manager.py lines 181-213) — atomic replacement or merge depending on semantics.

**Stream cache dict initialization** — add to `__init__` after existing cache dicts (lines 94-109):

```python
# In CacheManager.__init__ — after line 109:
# Stream caches (D-19) — updated from Kafka messages via update_* methods
self._cross_asset_data: dict = {}   # keyed by tf
self._macro_data: dict = {}          # keyed by tf
self._htf_intel: dict = {}           # keyed by tf
```

**Stream cache update methods** — follow `update_hmm_regime` pattern (lines 159-161), simple atomic assignment or merge:

```python
def update_cross_asset(self, tf: str, payload: dict) -> None:
    """Update cross-asset cache for a timeframe. Called from orchestrator._process_loop."""
    self._cross_asset_data[tf] = payload

def update_macro(self, tf: str, payload: dict) -> None:
    """Update macro cache for a timeframe. Merge semantics (same as orchestrator line 392-403)."""
    self._macro_data.setdefault(tf, {}).update(
        {k: payload[k] for k in ("yield_curve_slope", "yield_curve_regime", "ftq_score", "ftq_regime")
         if k in payload}
    )

def update_htf_intel(self, tf: str, data: dict) -> None:
    """Update HTF intel cache. Called from HTF bar processing in orchestrator."""
    self._htf_intel[tf] = data
```

**Stream cache properties** — follow existing property pattern (lines 115-153):

```python
@property
def cross_asset_data(self) -> dict:
    return self._cross_asset_data

@property
def macro_data(self) -> dict:
    return self._macro_data

@property
def htf_intel(self) -> dict:
    return self._htf_intel
```

**Symbol scoping (D-30)** — add `symbols` parameter to `__init__` and apply as `WHERE symbol = ANY($1)` filter on existing DB refresh queries:

```python
def __init__(self, db: DatabaseManager, settings: Settings,
             symbols: frozenset[str] | None = None) -> None:
    ...
    self._symbols = symbols  # None = all symbols (current behavior)
```

---

### `src/intelligence/pipeline/signal_processor.py` (absorbing alpha decay + D-22 metrics)

**Analog:** existing `SignalProcessor.__init__` metric registration pattern (lines 171-183) and existing gate-level counter pattern.

**New D-22 counters** — add to `__init__` after existing counters (lines 171-183), following exact `counter(name, description)` call pattern:

```python
# In SignalProcessor.__init__ — after line 183 (self._signal_dlq_total):
self._cis_null_total = counter(
    "signal_processor_cis_null_total",
    "CIS scoring returned None — no score available for this bar",
)
self._dlq_total = counter(
    "signal_processor_dlq_total",
    "Signals routed to DLQ (labeled by reason)",
)
self._gate_rejections_total = counter(
    "signal_processor_gate_rejections_total",
    "Signal gate rejections by gate type",
)
self._winner_total = counter(
    "signal_processor_winner_total",
    "Winner signals selected by entry type",
)
self._signals_evaluated_total = counter(
    "signal_processor_signals_evaluated_total",
    "Total signals entering the pipeline per bar",
)
```

**Counter call-site pattern** — labels passed as second arg dict, same as existing uses in executor.py line 213-214:

```python
self._cis_null_total.add(1)
self._dlq_total.add(1, {"reason": "cis_score_null"})
self._gate_rejections_total.add(1, {"gate": "regime"})
self._gate_rejections_total.add(1, {"gate": "quality"})
self._winner_total.add(1, {"entry_type": winner.get("entry_type", "unknown")})
self._signals_evaluated_total.add(len(raw_signals))
```

**Alpha decay absorption (D-21)** — `_apply_alpha_decay` is already a module-level function in `signal_processor.py` (line 58-65). The change is calling it INSIDE `process()` instead of in the orchestrator. After D-20 removes the orchestrator's call at line 532, add the call at the top of `process()` before the gate pipeline, using `self._setup_last_fire` (already private state of SignalProcessor):

```python
# In SignalProcessor.process() — add after raw_signals check (before CIS scoring):
for sig in raw_signals:
    fire_key = (sig["symbol"], sig["tf"], sig.get("setup_plugin", ""), sig.get("direction", 0))
    _apply_alpha_decay(sig, sig.get("tf", "1m"), self._setup_last_fire.get(fire_key))
```

**`CacheSnapshot` extension (D-19)** — `CacheSnapshot` is defined at signal_processor.py lines 108-119 as a frozen dataclass. Add three new fields:

```python
@dataclass(frozen=True)
class CacheSnapshot:
    # Existing fields (lines 114-119 — unchanged):
    perf_weights: dict
    calibration_curves: dict
    tod_priors: dict
    drift_penalties: dict
    cis_weights: dict
    cis_weights_version: int
    # New stream cache fields (D-19):
    cross_asset_data: dict   # keyed by tf — from CacheManager.cross_asset_data
    macro_data: dict         # keyed by tf — from CacheManager.macro_data
    htf_intel: dict          # keyed by tf — from CacheManager.htf_intel
```

The constructor call site in `_process_bar_inner` (lines 538-545) must be updated to pass the three new fields.

---

### `src/intelligence/pipeline/output_queue.py` (PERF-06 batch drain)

**Analog:** existing `drain_loop` at lines 98-125 — extend with batch collection before the publish loop. Pattern from RESEARCH.md exactly:

```python
async def drain_loop(self, running_fn: Callable[[], bool]) -> None:
    """Background drain loop — batch drain up to self._batch_size items per iteration."""
    while running_fn() or not self._queue.empty():
        # Block on first item (existing pattern, lines 115-117)
        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=1.0)
        except TimeoutError:
            continue

        # Collect up to N-1 more items non-blocking (PERF-06)
        batch = [first]
        for _ in range(self._batch_size - 1):
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        # Publish each item — task_done() per get() call (Pitfall 8 from RESEARCH.md)
        self._buffer_depth.add(self._queue.qsize())
        for topic, key, value in batch:
            try:
                await self._producer.publish(topic, msg=value, key=key)
            except Exception:
                self._publish_failures.add(1)
                self._logger.exception("output.publish_failed")
            finally:
                self._queue.task_done()   # MUST be per-item, not per-batch
```

**`_batch_size` init pattern** — add to `__init__`, sourced from settings:

```python
def __init__(self, producer: KafkaProducerClient, maxsize: int, batch_size: int = 10) -> None:
    ...
    self._batch_size = batch_size
```

Orchestrator construction becomes: `OutputQueue(producer=..., maxsize=_OUTPUT_QUEUE_MAXSIZE, batch_size=self.settings.output_drain_batch_size)`.

---

### `src/intelligence/plugins.py` (PERF-03 protocol update)

**Current protocol** (lines 27-44) — `compute_full` and `compute_next` have no `state` parameter. Add optional `state` parameter to both protocols and both classes:

```python
class IndicatorPlugin(Protocol):
    ...
    def compute_full(self, frames: dict[str, Any], state: dict | None = None) -> dict[str, Any]: ...
    def compute_next(self, windows: dict[str, Any], state: dict | None = None) -> dict[str, Any]: ...

class PatternPlugin(Protocol):
    ...
    def compute_full(self, frames: dict[str, Any], state: dict | None = None) -> dict[str, Any]: ...
    def compute_next(self, windows: dict[str, Any], state: dict | None = None) -> dict[str, Any]: ...
```

**Critical:** `state` must be optional (`= None`) so existing plugins that don't use injected state don't break. Plugins that do need state read `state or {}` instead of `self._state`. The state return contract (`{"_state": new_state, ...}`) is unchanged — only the INPUT delivery changes.

---

### `src/intelligence/features/i3_structure/market_profile.py` (PERF-04 incremental)

**Analog:** `src/intelligence/features/smc_context/bocpd_changepoint.py` lines 100-131 — the incremental plugin pattern: `compute_next()` checks for valid state, falls back to `compute_full()` if state absent or invalid, updates state before returning.

**Change `supports_incremental`** from `False` to `True` (line 32).

**`compute_next()` method** — follow BOCPD's fallback-first pattern (bocpd_changepoint.py lines 100-103):

```python
def compute_next(self, windows: dict[str, Any], state: dict | None = None) -> dict[str, Any]:
    """Incremental TPO update — update state bucket counts with newest bar only.

    Falls back to compute_full() when price range expands (bucket grid changes).
    State stores: tpo_counts (np.ndarray), buckets (np.ndarray), low_min, high_max.
    """
    st = state or self._state  # Accept injected state (PERF-03) or fall back to instance
    if not st or "tpo_counts" not in st:
        return self.compute_full(windows, state=state)

    df = windows.get("main")
    if df is None or len(df) < self.min_lookback:
        return {}

    new_high = float(df["high"].iloc[-1])
    new_low = float(df["low"].iloc[-1])

    # Range expansion check — must rebuild buckets
    if new_high > st["high_max"] or new_low < st["low_min"]:
        return self.compute_full(windows, state=state)

    # Incremental update: add newest bar contribution to tpo_counts
    buckets = st["buckets"]
    tpo_counts = st["tpo_counts"].copy()
    mask = (buckets >= new_low) & (buckets <= new_high)
    tpo_counts[mask] += 1.0

    # Optionally subtract oldest bar if using fixed-window (rolling lookback)
    # ... subtract oldest bar contribution from tpo_counts

    st["tpo_counts"] = tpo_counts

    # POC/VAH/VAL computation from updated tpo_counts (same logic as compute_full lines 67-99)
    ...
    result["_state"] = st  # State return contract unchanged
    return result
```

**State structure to maintain in `compute_full()`** — at end of `compute_full()`, before return, add state update:

```python
self._state = {
    "tpo_counts": tpo_counts,
    "buckets": buckets,
    "low_min": float(low.min()),
    "high_max": float(high.max()),
}
result["_state"] = self._state
```

---

### `src/intelligence/features/i3_structure/session_levels.py` (PERF-04 incremental)

**Analog:** `src/intelligence/features/smc_context/bocpd_changepoint.py` compute_next pattern (lines 100-131) — same fallback structure.

**Change `supports_incremental`** from `False` to `True` (line 43).

**`compute_next()` method** — session levels are window-based. The incremental benefit is avoiding full DataFrame slice every bar when session boundaries haven't shifted:

```python
def compute_next(self, windows: dict[str, Any], state: dict | None = None) -> dict[str, Any]:
    """Incremental session levels — recompute only level distances from latest close.

    Falls back to compute_full() when session boundary shifts (new session).
    State stores: prior_session_high, prior_session_low, prior_session_close,
    overnight_high, overnight_low, weekly_pivot, weekly_r1/r2/s1/s2,
    asian_session_high/low, bar_count (to detect session boundary shift).
    """
    st = state or self._state
    if not st or "bar_count" not in st:
        return self.compute_full(windows, state=state)

    df = windows.get("main")
    if df is None or len(df) < self.min_lookback:
        return {}

    n = len(df)
    # Detect session boundary shift (session window changes meaning)
    if abs(n - st["bar_count"]) >= _SESSION_BARS:
        return self.compute_full(windows, state=state)

    # Fast path: recompute only distance metrics from latest close
    features = windows.get("features") or {}
    close = float(features.get("close") or df["close"].iloc[-1])
    atr_14 = features.get("atr_14")

    result = dict(st["cached_levels"])   # Copy cached structural levels
    # Recompute nearest_session_level and nearest_level_dist_atr only
    # ... (distance computation from close to cached levels)

    result["_state"] = {**st, "bar_count": n}
    return result
```

---

### `src/intelligence/features/smc_context/bocpd_changepoint.py` (PERF-04 verify)

**No code change needed** if PERF-03 fix resolves the 77.9ms p95. The `compute_next()` already exists (lines 100-131) and calls `_update(x)` once per bar — confirmed O(K) not O(N). The high p95 is the PERF-03 race causing fallback to `compute_full()` (which runs N x `_update()` calls).

**Verification step:** after PERF-03 fix, query `histogram_quantile(0.95, rate(intelligence_pipeline_plugin_duration_ms_milliseconds_bucket{plugin_name="smc_BOCPDChangePoint"}[10m]))` — if p95 drops to <10ms, BOCPD is fixed by PERF-03. If still 77ms, profile `_update()` to determine if truncation of `max_run_length=200` is the bottleneck.

**Pattern to copy if optimization needed:** `compute_next()` lines 100-131 is the reference — the state guard pattern `if not self._state or "run_length_probs" not in self._state: return self.compute_full(windows)` is the PERF-03-robust fallback that all incremental plugins must follow after PERF-03 fix.

---

### `src/intelligence/features/smc_context/hmm_regime.py` (PERF-04 verify)

**Same situation as BOCPD.** `supports_incremental=True` already set. The forward algorithm is O(K²) per bar where K=3 — not O(N). High p95 (23-35ms) is the PERF-03 race causing full recomputation.

**No code change expected** after PERF-03 fix. Same verification query approach as BOCPD above, substituting `plugin_name="smc_HMMRegime_1m"` etc.

---

### `src/config/settings.py` (adding two fields, removing min cap)

**Analog:** existing field declarations in `settings.py` lines 29-33 — `Field()` with `validation_alias` and `description`.

**Two new fields** (D-28, PERF-06 batch size):

```python
# After intelligence_thread_pool_workers field (line 33):
intelligence_pipeline_symbol_filter: list[str] = Field(
    default_factory=list,
    validation_alias="INTELLIGENCE_PIPELINE_SYMBOL_FILTER",
    description="Symbols this process handles. Empty list = all active contracts (current behavior).",
)
output_drain_batch_size: int = Field(
    default=10,
    validation_alias="OUTPUT_DRAIN_BATCH_SIZE",
    description="Max items drained from OutputQueue per drain_loop iteration. Default 10.",
)
```

**Thread pool cap removal** (D-29) — in `intelligence_pipeline_agent.py` line 169 (not in settings.py — the settings field already exists):

```python
# Before (line 169):
_workers = _configured if _configured > 0 else min(12, max(4, cpu_count // 2))
# After:
_workers = _configured if _configured > 0 else max(4, cpu_count // 2)
```

---

### `src/observability/metrics.py` (adding 5 D-22 counters as module-level constants)

**Analog:** existing module-level counter pattern at lines 35-51 — `_meter.create_counter("name", description="...")` at module scope, assigned to `ALL_CAPS` constants.

**Five new counters** — add after existing pipeline metrics section (after line 51):

```python
# ---------------------------------------------------------------------------
# SignalProcessor stage metrics (D-22)
# ---------------------------------------------------------------------------

SIGNAL_PROCESSOR_CIS_NULL_TOTAL = _meter.create_counter(
    "signal_processor_cis_null_total",
    description="CIS scoring returned None — no score available for this bar",
)
SIGNAL_PROCESSOR_DLQ_TOTAL = _meter.create_counter(
    "signal_processor_dlq_total",
    description="Signals routed to DLQ by reason label",
)
SIGNAL_PROCESSOR_GATE_REJECTIONS_TOTAL = _meter.create_counter(
    "signal_processor_gate_rejections_total",
    description="Signal gate rejections by gate type label",
)
SIGNAL_PROCESSOR_WINNER_TOTAL = _meter.create_counter(
    "signal_processor_winner_total",
    description="Winner signals selected by entry_type label",
)
SIGNAL_PROCESSOR_SIGNALS_EVALUATED_TOTAL = _meter.create_counter(
    "signal_processor_signals_evaluated_total",
    description="Total signals entering the pipeline per bar",
)
```

**Note:** `SignalProcessor` can EITHER import these module-level constants OR use the inline `counter()` helper (both patterns exist in the codebase — executor.py line 137 uses `counter()`, metrics.py uses `_meter.create_counter()` directly). Prefer importing the module-level constants for these since they need Grafana visibility by name — consistent with `PLUGIN_DURATION_MS` and `PLUGIN_ERRORS_TOTAL` which are imported by executor.py.

---

## Shared Patterns

### DAG Node Constructor Pattern
**Source:** `src/intelligence/pipeline/cache_manager.py` lines 89-109, `src/intelligence/pipeline/signal_processor.py` lines 153-169
**Apply to:** `FeaturePipelineExecutor`, `PerKeyWorkerManager`

All DAG nodes follow: constructor receives injected dependencies as named params, assigns to `self._*` private attrs, initializes owned state dicts as empty `{}`, creates a `structlog.get_logger(__name__)` logger. No DB queries, no `settings` access — dependencies pre-resolved by orchestrator `_setup()`.

### Background Task Lifecycle Pattern
**Source:** `src/intelligence/pipeline/state_manager.py` `start_checkpoint_loop()`, `src/intelligence/pipeline/cache_manager.py` `start_refresh_loops()`
**Apply to:** `PerKeyWorkerManager.start_per_key_workers()`

```python
# Orchestrator _setup() wiring pattern (lines 247-249, 263-265):
for task in self._component.start_background_method():
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
```

The component owns task creation via `asyncio.create_task()`. The orchestrator stores handles in `self._background_tasks` set. Teardown happens naturally when the set is garbage collected or tasks are cancelled.

### No Lateral Imports (DB-Ignorant Node Contract)
**Source:** `src/intelligence/pipeline/executor.py` lines 1-9 (docstring), `src/intelligence/pipeline/signal_processor.py` lines 8-10
**Apply to:** `FeaturePipelineExecutor`, `PerKeyWorkerManager`

New DAG nodes MUST NOT import from `cache_manager.py`, `state_manager.py`, or `output_queue.py` in the lateral direction. Dependencies flow via constructor injection and per-call parameters only. `CacheSnapshot` is the boundary object — pass it, don't reach through it.

### Plugin Incremental Fallback Pattern
**Source:** `src/intelligence/features/smc_context/bocpd_changepoint.py` lines 100-113
**Apply to:** `MarketProfilePlugin.compute_next()`, `SessionLevelsPlugin.compute_next()`

```python
def compute_next(self, windows, state=None):
    st = state or self._state
    if not st or "<required_key>" not in st:
        return self.compute_full(windows, state=state)
    # ... incremental logic
    result["_state"] = updated_st    # state return contract unchanged
    return result
```

### OTel Counter Usage
**Source:** `src/intelligence/pipeline/executor.py` lines 213-214, `src/observability/metrics.py` lines 35-51
**Apply to:** All D-22 counter call-sites in `signal_processor.py`

```python
# Counter with labels:
METRIC.add(1, {"label_key": "label_value"})
# Counter without labels:
METRIC.add(1)
# Never: METRIC.inc() or METRIC.labels(...).inc()  — prometheus_client removed in Phase 083
```

---

## No Analog Found

All files have analogs. No new-from-scratch files exist in this phase.

---

## Metadata

**Analog search scope:** `services/`, `src/intelligence/pipeline/`, `src/intelligence/features/smc_context/`, `src/intelligence/features/i3_structure/`, `src/observability/`, `src/config/`
**Files scanned:** 14 (all primary target files read directly)
**Pattern extraction date:** 2026-05-18
