# Compute & Latency Audit — 2026-05-23

**Scope:** Intelligence pipeline hot path — Kafka consume through I1→I7→publish.
**Framing:** Renaissance Technologies lens. Latency is alpha. Every millisecond on the hot path
is edge leaked. Every unobservable component is a blind feedback gap.

---

## Finding CL-1: I1-I6 Stage Latency Is Completely Dark

**Severity:** HIGH
**Category:** Feedback Loop Gap
**Files:** `services/intelligence_pipeline_agent.py:180-184`, `src/intelligence/pipeline/feature_pipeline_executor.py:117-277`
**Description:**
`intelligence_pipeline_i1_latency_ms` is declared as a gauge on line 180 but `.add()` is never
called anywhere in the codebase. The metric is registered but dead. Meanwhile
`intelligence_pipeline_i7_latency_ms` is recorded (line 517). This means only two
measurements exist: end-to-end pipeline latency and I7 latency. The I1 wave (28 plugins), I2-I3
wave, I4 wave (GARCH + Kalman), I5, SMC, and I6 stages are completely invisible. When a 1m bar
latency spikes there is no way to identify which of the 4 sequential waves is the bottleneck
without attaching a profiler.

The per-plugin histogram `intelligence_pipeline_plugin_duration_ms{plugin_name, tier}` is
recorded via `PluginObserver` and provides granular data, but there is no per-wave aggregate
to allow fast triage before digging into 132 per-plugin series.

**Estimated cost:** Zero CPU cost. Pure observability gap — prevents regression detection and
blocks targeted optimization.
**Fix:** Record `_i1_latency_ms` in `FeaturePipelineExecutor.run()` around the `run_i1()` call.
Add per-wave gauges (`i2_i3_wave_ms`, `i4_wave_ms`, `i5_smc_wave_ms`, `i6_ms`) inside
`PluginExecutor.run_tiers()` at the wave loop boundary.

---

## Finding CL-2: `PluginCircuitBreaker` (584-line class) Is Unused on the Hot Path

**Severity:** HIGH
**Category:** Alpha Leakage
**Files:** `src/core/plugin_circuit_breaker.py:89`, `services/intelligence_pipeline_agent.py:284`
**Description:**
`PluginCircuitBreaker` from `src/core/plugin_circuit_breaker.py` is a 584-line production-ready
class with windowed failure tracking, half-open recovery testing, performance degradation
detection (5000ms threshold), and Prometheus integration. It is used only for the LLM chain
(`src/core/llm/providers.py:48`) and IBKR (`src/providers/ibkr.py:105`).

`PluginExecutor` uses the simpler `CircuitBreaker` from `src/observability/circuit_breaker.py`
(failure threshold=3, timeout=300s), constructed on-demand per plugin. The orchestrator passes
`circuit_breakers={}` at line 284 — an empty dict, so every breaker starts from zero on every
restart with no persistence or warmup.

This means: if a heavy plugin (BOCPD, GARCH, HMM) starts timing out at 4500ms, it will not be
detected or tripped by the circuit breaker. The 5000ms performance threshold in
`PluginCircuitBreaker` exists precisely for this case and is unused on the plugin execution path.

**Estimated cost:** A slow plugin running at 4500ms/bar on 12 active (symbol, tf) keys adds
~54s of accumulated latency per bar cycle across all per-key workers.
**Fix:** Either wire `PluginCircuitBreaker` into `PluginExecutor._get_plugin_cb()` as a drop-in
replacement, or add a `performance_threshold_ms` check to the existing `CircuitBreaker` calls in
`_collect_plugin_results`.

---

## Finding CL-3: `enqueue` on the Intelligence Topic Drops Silently on QueueFull

**Severity:** HIGH
**Category:** Information Destruction
**Files:** `services/intelligence_pipeline_agent.py:507`, `src/intelligence/pipeline/output_queue.py:78-83`
**Description:**
Line 507 calls `self._out_queue.enqueue(intel_topic, ...)` (non-blocking, drops on QueueFull)
for the `IntelligenceEvent` published to the intelligence topic. This is the highest-volume
output and the primary data stream consumed by `feature_writer_service` and downstream services.

When the Kafka drain loop falls behind (broker latency spike, Redpanda slow, drain_batch_size
too small), the asyncio.Queue fills to 500, and every subsequent 1m bar's `IntelligenceEvent`
is silently dropped. The counter `intelligence_pipeline_output_buffer_drops_total` increments,
but no alert is wired to it. The intelligence journal (line 598) also uses non-blocking enqueue.

Signal payloads (lines 529-539) use `enqueue_blocking` and would correctly backpressure, but
the intelligence event itself — the foundation of the entire feature storage pipeline — is
fire-and-forget drop.

**Estimated cost:** Under sustained Kafka lag, feature storage gaps occur. Downstream ML
training and calibration curves degrade as feature rows go missing.
**Fix:** Change line 507 to `await self._out_queue.enqueue_blocking(...)`. Apply the same to
the journal enqueue at line 598.

---

## Finding CL-4: Deprecated `TransformRecorder` Is Instantiated and Called on the Hot Path

**Severity:** HIGH
**Category:** Alpha Leakage
**Files:** `services/intelligence_pipeline_agent.py:250-254`, `src/intelligence/pipeline/quality_gate.py:64-78`, `src/intelligence/pipeline/regime_gate.py:137`, `src/intelligence/pipeline/tod_adjuster.py:100`, `src/intelligence/pipeline/calibrator.py:82`, `src/core/ml/transform_recorder.py:1`
**Description:**
`TransformRecorder` was archived in Phase 78 (D-04). Its module header states:
"ARCHIVED in Phase 78 (D-04). Do NOT import this module from production code."
It emits a `DeprecationWarning` at import time.

Despite this, `intelligence_pipeline_agent._setup()` constructs a live `TransformRecorder`
instance (line 252) and passes it into `SignalProcessor`, which passes it to
`apply_quality_gate`, `apply_regime_gate`, `apply_tod_adjustment`, `apply_calibration`, and
`rank_signals`. Each stage calls `await recorder.record()` per signal, which queues a DB
insert row to `signal_transform_log`.

This means: on every bar with signals, 4-5 async DB-queued writes are interleaved into the
signal processing pipeline. Each `recorder.record()` call appends to `_pending`, checks
batch size, and may trigger a `_flush()` that calls `conn.executemany()` against the pool.
The `_flush_loop` also fires every 2 seconds independently.

**Estimated cost:** ~2-10 additional async coroutine switches per signal per bar. At high signal
rates this adds measurable event loop contention. The writes target a table that the codebase
says should be replaced by `LineageRecorder`.
**Fix:** Remove `TransformRecorder` instantiation from `_setup()`. Pass `recorder=None` to all
signal pipeline stages (the guard `if recorder is not None` is already in place). Delete the
`signal_transform_log` writes as part of the Phase 78 cleanup that was left incomplete.

---

## Finding CL-5: Three Sequential `model_dump()` Calls on Every Bar

**Severity:** MEDIUM
**Category:** Alpha Leakage
**Files:** `services/intelligence_pipeline_agent.py:498-507`, `src/intelligence/pipeline/signal_processor.py:84-96`
**Description:**
On every bar that produces a non-None `IntelligenceEvent`, the following serialization chain
runs sequentially:

1. `fp_result.event.model_dump()` → line 498 (used only for HTF intel cache update on 15m/1h/4h/1d bars)
2. `fp_result.event.model_dump_json()` → line 507 (Kafka publish)
3. `_build_features_from_event(intel_event)` at `signal_processor.py:84` → calls `event.i1.model_dump()` then up to 6 more `sub.model_dump()` calls for i2/i3/i4/i5/smc/i6

`IntelligenceEvent` is a large Pydantic v2 model spanning ~1069 lines with ~480 Optional fields
across 8 nested sub-models. Each `model_dump()` walks the entire field tree.

Call 1 (`model_dump()`) is only needed on 4 of 6 timeframes. Call 3 (`_build_features_from_event`)
re-serializes parts of the same event that call 1 already serialized.

**Estimated cost:** Pydantic v2 model_dump on a 480-field nested model: estimated 0.3-1ms per
call depending on field count populated. Three calls = 1-3ms of pure serialization on every bar.
**Fix:** (a) Gate the `model_dump()` at line 498 behind the `if bar.tf in (...)` check to avoid
building the dict on 1m/5m bars. (b) Make `_build_features_from_event` accept the already-built
`event_dict` from step 1 when available rather than re-calling `model_dump()` on each sub-model.

---

## Finding CL-6: Up to 5 `to_dataframe()` DataFrame Allocations Per Bar

**Severity:** MEDIUM
**Category:** Alpha Leakage
**Files:** `src/intelligence/pipeline/feature_pipeline_executor.py:141-156`
**Description:**
`FeaturePipelineExecutor.run()` builds the main DataFrame for (symbol, tf) at line 141, then
iterates `_STANDARD_TFS` (6 elements) at line 151, calling `to_dataframe()` for each other
timeframe where the deque has >= 50 bars. For an active symbol on 1m, this means constructing
up to 5 additional pandas DataFrames (5m, 15m, 1h, 4h, 1d) per bar.

`to_dataframe()` in `BarHistory` (line 61) rebuilds the DataFrame from scratch on every call:
list comprehension over the deque, `pd.DataFrame()` construction, `pd.to_datetime()` with utc=True,
and column dtype casting. For a 200-bar deque this creates 200-element arrays 6 times.

**Estimated cost:** Each `to_dataframe()` on a 200-bar deque: estimated 0.1-0.4ms (list comp +
DataFrame + astype). Six calls = 0.6-2.4ms of pure allocation per bar on active symbols.
**Fix:** Cache DataFrames keyed by `(symbol, tf, last_bar_ts)` in `BarHistory`. Invalidate only
when a new bar is appended for that key. On a 1m bar, only `(symbol, "1m")` changes; all HTF
DataFrames are reusable across consecutive 1m bars.

---

## Finding CL-7: GARCH Plugin Sorts Full Sigma History on Every Bar (O(n log n))

**Severity:** MEDIUM
**Category:** Alpha Leakage
**Files:** `src/intelligence/context/garch_volatility.py:91`, `src/intelligence/context/garch_volatility.py:169`
**Description:**
Two separate code paths in `GARCHVolatilityPlugin` call `np.searchsorted(np.sort(sigma_arr), ...)`
where `sigma_arr` is the full GARCH sigma history (up to 200 values). `np.sort()` is O(n log n)
and creates a copy of the array. This runs on every bar for every (symbol, tf) key.

With 200 values, `np.sort()` + `searchsorted` adds ~50-100μs of pure CPU per call. GARCH runs
in Wave 2 on the thread pool. On 12 active (symbol, tf) keys the thread pool runs these
concurrently but under GIL contention.

**Estimated cost:** ~50-100μs per (symbol, tf) key per bar. For 12 keys = 0.6-1.2ms of
thread-pool CPU that could be eliminated.
**Fix:** Replace `np.searchsorted(np.sort(arr), val)` with `np.sum(arr <= val)` (O(n), no
sort) or maintain a sorted copy in plugin state that is updated incrementally using
`bisect.insort`.

---

## Finding CL-8: Thread Pool Has No Contention Measurement

**Severity:** MEDIUM
**Category:** Feedback Loop Gap
**Files:** `services/intelligence_pipeline_agent.py:161-166`, `src/intelligence/pipeline/executor.py:163-179`
**Description:**
The `ThreadPoolExecutor` with `max_workers=max(4, cpu_count // 2)` (defaulting to 12 on a
24-CPU machine) has no queue depth or wait-time measurement. When all 12 workers are busy
(e.g., during Wave 1 when 28 I1 plugins + SMC-A's 13 plugins compete for 12 slots), new
`run_in_executor` submissions block the event loop waiting for a free worker slot.

`concurrent.futures.ThreadPoolExecutor` queues work items in its internal `_work_queue`.
There is no metric tracking queue depth, worker saturation, or per-submission wait time
(time from `loop.run_in_executor()` call to actual thread start). A saturated thread pool
would manifest as elevated `pipeline_latency_ms` with no signal in any existing metric.

Wave 1 has 28 (I1) + 8 (I2-A) + 8 (I3) + 13 (SMC-A) = 57 concurrent submissions to 12 workers.

**Estimated cost:** Unknown without measurement; potentially the dominant latency driver on
multi-symbol deployments.
**Fix:** Add a gauge tracking `len(thread_pool._work_queue.queue)` sampled in the
`_health_monitor_loop`. Add per-wave submission-to-completion latency measurement using
`asyncio.get_event_loop().time()` before and after `asyncio.gather()` per wave.

---

## Finding CL-9: `snapshot()` Copies Four Stream-Cache Dicts on Every Bar

**Severity:** MEDIUM
**Category:** Alpha Leakage
**Files:** `src/intelligence/pipeline/cache_manager.py:263-283`
**Description:**
`CacheManager.snapshot()` is called once per bar in `_process_bar_inner` (line 488). It creates
shallow copies of four dicts: `cross_asset_data`, `macro_data`, `htf_intel`, and `shadow_cache`.
The `perf_weights`, `calibration_curves`, `tod_priors`, and `drift_penalties` dicts are passed
by reference (no copy).

The four copied dicts change at most once every few minutes (cache refresh intervals: 300s for
shadow_cache, 3600s for perf_weights, 1800s for CIS weights). Copying them on every 1m bar
(~6-12 copies/minute per symbol) when they rarely change is unnecessary work.

**Estimated cost:** Four `dict()` copies per bar. Small individually (microseconds), but
cumulative across all (symbol, tf) keys adds steady allocator pressure that increases GC pause
frequency.
**Fix:** Track a monotonic `_snapshot_version` counter on `CacheManager`. Increment on every
`update_*` or `_load_*` call. In `snapshot()`, return a cached `CacheSnapshot` if the version
has not changed since the last call. This reduces copies from O(bars) to O(cache updates).

---

## Finding CL-10: `BarIntelligenceRecord` `model_dump(mode="json")` on Every Bar

**Severity:** LOW
**Category:** Alpha Leakage
**Files:** `services/intelligence_pipeline_agent.py:596-601`
**Description:**
`_enqueue_intel_journal()` constructs a `BarIntelligenceRecord` (a large Pydantic model
containing a full `IntelligenceEvent` plus ranked signal list) and calls `model_dump(mode="json")`
on every bar. This is the fourth full serialization of the `IntelligenceEvent` per bar
(after the three in CL-5).

`mode="json"` triggers recursive serialization to Python-native JSON-compatible types, which
is slower than `model_dump()` (mode="python") and approximately 2x slower than
`model_dump_json()` (which uses Rust-side serialization).

**Estimated cost:** ~0.5-1.5ms per bar for a full nested model dump in Python mode.
**Fix:** Change to `record.model_dump_json()` and pass the raw JSON string to the enqueue call
(the Kafka serializer accepts strings). This halves the serialization cost for this call.

---

## Finding CL-11: `_health_monitor_loop` Is an Empty 10-Second No-Op

**Severity:** LOW
**Category:** Feedback Loop Gap
**Files:** `services/intelligence_pipeline_agent.py:604-606`
**Description:**
`_health_monitor_loop` is created as a named background task in `_run()` alongside
`_process_loop` and `drain_loop`, but its body contains only `await asyncio.sleep(10)`.
It does not check thread pool queue depth, per-key worker queue depth, output queue depth,
background task health, or cache staleness. The slot is reserved for health monitoring but
nothing is monitored.

**Estimated cost:** Zero CPU cost. Pure observability gap — the hook exists but is unused.
**Fix:** Implement the health monitor: sample `self._out_queue._queue.qsize()`, per-key worker
queue depths from `_worker_manager._queues`, `threading.active_count()` vs pool size, and
emit gauges. Alert on `_drop` counter delta > 0.

---

## Finding CL-12: Kafka Offset Commit Batched at 100 Regardless of Backpressure

**Severity:** LOW
**Category:** Alpha Leakage
**Files:** `services/intelligence_pipeline_agent.py:409-446`
**Description:**
`COMMIT_BATCH_SIZE = 100` at line 409. The commit is a `await self._kafka_consumer.commit()`
call that blocks the `_process_loop` while the Kafka client acks offsets. During fast bar
replays or catch-up from lag, this fires every 100 messages, adding periodic commit latency
directly into the message consumption loop.

The commit fires on the message counter regardless of whether the bars have been processed
(they are dispatched to per-key worker queues which process asynchronously). Committing before
processing completes means an agent restart could re-deliver up to 100 already-dispatched-but-
unprocessed bars.

**Estimated cost:** Kafka commit round-trip to Redpanda on localhost: ~1-5ms every 100 messages.
At sustained throughput of 100 bars/minute (multi-symbol), this is constant background drain
on the event loop.
**Fix:** Commit asynchronously in a background task triggered by the message counter, or after
per-key workers drain their queues (use `asyncio.Queue.join()`). This removes commit latency
from the hot receive path.

---

## Hot Path Stage Map

| Stage | Metric | Measurement Status | Known Bottleneck |
|---|---|---|---|
| Kafka consume | `agent_last_message_timestamp_seconds` | Liveness only, no latency | None identified |
| Bar parse (`model_construct`) | None | **DARK** | None identified |
| Per-key worker enqueue | None | **DARK** | Backpressure via `queue.put()` (blocks on full) |
| Gap detection + warmup check | None | **DARK** | None identified |
| `CacheManager.snapshot()` | None | **DARK** | 4 dict copies per bar (CL-9) |
| `FeaturePipelineExecutor.run()` | None | **DARK** | Up to 5 DataFrame builds (CL-6); no wave timing |
| I1 (28 plugins) | `plugin_duration_ms{tier=I1}` per-plugin | Per-plugin histogram only; **no wave aggregate** | Thread pool saturation risk (CL-8) |
| Wave 1: I2-A + I3 + SMC-A (29 plugins) | `plugin_duration_ms{tier}` per-plugin | Per-plugin histogram only; **no wave aggregate** | BOCPD O(R) per bar; 57 concurrent submissions to 12 workers |
| Wave 2: I2-B + SMC-B + I4-A (14 plugins) | `plugin_duration_ms{tier}` per-plugin | Per-plugin histogram only | GARCH `np.sort()` on 200 values (CL-7) |
| Wave 3: I4-B + I5 (17 plugins) | `plugin_duration_ms{tier}` per-plugin | Per-plugin histogram only | Kalman after GARCH (sequential) |
| Wave 4: I6 (6 plugins) | `plugin_duration_ms{tier=i6}` per-plugin | Per-plugin histogram only | None identified |
| IntelligenceEvent construction | None | **DARK** | Pydantic ValidationError fallback path |
| `model_dump()` x3 + `model_dump_json()` | None | **DARK** | 3 full model serializations per bar (CL-5, CL-10) |
| I7 (36 plugins) | `intelligence_pipeline_i7_latency_ms` | **Aggregate only**, per-plugin histogram | Thread pool contention with I1-I6 wave completion |
| Signal processor (quality/regime/tod/cal) | `SIGNAL_PROCESSOR_GATE_REJECTIONS_TOTAL` | Gate counts only, no stage latency | `TransformRecorder.record()` async calls (CL-4) |
| Output enqueue (intelligence topic) | `output_buffer_drops_total`, `output_buffer_depth` | Drop counter + depth | **Drops silently on QueueFull** (CL-3) |
| Output enqueue (signals/winner) | Same | Blocking (correct) | Backpressure adds to bar processing time |
| Kafka drain (publish) | `output_publish_failures_total` | Failure counter only | None identified |
| End-to-end | `intelligence_pipeline_pipeline_latency_ms` | **Single end-to-end gauge** | Gauge, not histogram (no p50/p95/p99) |

**Summary of highest-priority actions:**

1. **CL-3** (CRITICAL path drop): `enqueue` on intelligence topic is fire-and-forget with silent drop.
2. **CL-1** (observability): I1 gauge declared but never recorded; I2-I6 completely dark.
3. **CL-2** (protection gap): `PluginCircuitBreaker` built for plugins, unused on plugin path.
4. **CL-4** (archived code active): `TransformRecorder` is archived but still instantiated and calling `await recorder.record()` per signal.
5. **CL-5/CL-6/CL-7** (CPU): Redundant model_dump, DataFrame rebuild, and O(n log n) sort are the three most actionable microsecond-level wins.
