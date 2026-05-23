# Plan 089-06 Summary: Per-Key Concurrency (PERF-07)

**Completed:** 2026-05-18
**Requirements:** PERF-07
**Wave:** 4 (final plan in phase 089)

## Files Changed

| File | Change |
|------|--------|
| `src/intelligence/pipeline/per_key_worker_manager.py` | Created - PerKeyWorkerManager class |
| `src/intelligence/pipeline/__init__.py` | Export PerKeyWorkerManager |
| `services/intelligence_pipeline_agent.py` | Wire worker manager, remove sequential _process_bar |
| `tests/unit/pipeline/test_per_key_worker_manager.py` | 5 concurrency tests |

## Architecture Delivered

Each `(symbol, tf)` key now has a dedicated `asyncio.Queue(maxsize=100)` and a long-running `asyncio.Task`. Workers are spawned lazily on first enqueue for a key. The orchestrator's consume loop calls `await self._worker_manager.enqueue(bar)` instead of `await self._process_bar(bar)`.

- Independent keys run concurrently - ES:1m never blocks NQ:5m (D-01, D-03)
- Per-key FIFO order preserved via single asyncio.Task per key (D-01)
- Symbol filter (D-28) drops bars for unowned symbols at enqueue()
- Lifecycle owned by PerKeyWorkerManager - orchestrator calls start_per_key_workers() once in _setup() and stop() in _teardown() (D-16)
- Background task lifecycle pattern: add_done_callback(self._background_tasks.discard)

## Acceptance Criteria

- `grep -c "self._worker_manager.enqueue" services/intelligence_pipeline_agent.py` = 1
- `grep -c "PerKeyWorkerManager(" services/intelligence_pipeline_agent.py` = 1
- `grep -c "await self._process_bar(bar)" services/intelligence_pipeline_agent.py` = 0
- `grep -n "self._worker_manager.stop()" services/intelligence_pipeline_agent.py` = 1 match
- 5 tests pass: concurrent execution, FIFO ordering, symbol filter, back-pressure, shutdown

## Test Results

5/5 tests pass in `test_per_key_worker_manager.py`:
- test_independent_keys_run_concurrently - NQ completes before ES (concurrent proof)
- test_within_key_order_preserved - FIFO guaranteed
- test_symbol_filter_drops_unowned - NQ dropped, ES processed
- test_back_pressure_blocks_producer - queue full blocks producer
- test_stop_cancels_all_workers - all 3 tasks cancelled cleanly

## Thread Pool Saturation (D-27)

**Static analysis (pipeline not running - live measurement pending post-deployment):**

- Thread pool size: `max(4, cpu_count // 2)` = `max(4, 24 // 2)` = **12 workers** (AMD Ryzen AI 9 HX 370, 24 logical cores)
- Pre-PERF-07: single active key at a time; thread pool saturation bounded by I1-I6 tier parallelism within one bar
- Post-PERF-07: multiple active keys dispatch to the same pool concurrently; saturation depends on active symbol count and tier latency

**Phase 090 recommendation:** Measure post-deployment with 6+ active contracts. If peak active workers / 12 > 0.9, increase `intelligence_thread_pool_workers` to 18-24 in settings. The `min(12)` cap was removed in Plan 01 (D-29), so operator can set this directly.

## End-to-End Phase 089 Summary

| Plan | Requirement | Change |
|------|-------------|--------|
| 01 | Architecture | FPE extraction, CacheManager stream caches, run_i7_complete, 5 OTel counters |
| 02 | PERF-01/02/05/08/09 | Single _build_features_from_event, pre-filtered tiers, model_construct, gap param |
| 03 | PERF-06 | Batch drain N=10 per OutputQueue iteration |
| 04 | PERF-03 | Plugin state as parameter - zero plugin._state = assignments |
| 05 | PERF-04 | MarketProfile + SessionLevels incremental; 12-plugin triage |
| 06 | PERF-07 | Per-key concurrent workers - ES:1m never blocks NQ:5m |

**Orchestrator line count:** 763 (pre-089) -> 581 (post-Plan 01) -> ~590 (post-Plan 06 additions)
**Per-bar latency:** Live measurement pending pipeline restart. Structural improvements: elimination of sequential per-bar await, O(N) to O(K) plugin conversion, single _build_features_from_event call per bar.
