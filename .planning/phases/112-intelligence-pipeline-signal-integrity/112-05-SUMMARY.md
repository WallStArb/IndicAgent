---
phase: 112-intelligence-pipeline-signal-integrity
plan: "05"
subsystem: intelligence-pipeline
tags: [latency, circular-import, serialization, tier-budgets, fast-path, enqueue-many, flat-features, ml-data-gates, clean-data-boundary]
dependency_graph:
  requires:
    - phase: PIPE-INT-04
      provides: two-queue OutputQueue, wave isolation, circuit breakers enabled
  provides: [PIPE-INT-05]
  affects: [executor, output_queue, feature_pipeline_executor, signal_processor, intelligence_pipeline, ml_signal_training_materializer, confidence_calibrator, signal_metrics_analyzer]
tech_stack:
  added: []
  patterns:
    - neutral-module-for-circular-import-prevention
    - tier-deadline-carry-forward
    - batched-enqueue
    - precomputed-per-bar-flat-features
    - clean-data-version-gate
key_files:
  created:
    - src/intelligence/pipeline/feature_flattening.py
  modified:
    - src/intelligence/pipeline/executor.py
    - src/intelligence/pipeline/feature_pipeline_executor.py
    - src/intelligence/pipeline/output_queue.py
    - src/intelligence/pipeline/signal_processor.py
    - src/config/settings.py
    - services/intelligence_pipeline.py
    - src/intelligence/services/ml_signal_training_materializer.py
    - src/intelligence/ml/confidence_calibrator.py
    - services/signal_metrics_analyzer.py
    - services/feature_writer.py
    - src/persistence/logic/warmup_provider.py
    - src/intelligence/services/bar_history_seeder.py
    - src/intelligence/ai/base_group_service.py
key-decisions:
  - "State-commit boundary is SAFE: plugin state is extracted in _collect_plugin_results() after asyncio.gather() completes; a TimeoutError from wait_for at the outer boundary cancels gather before state extraction — state is never committed for timed-out bars"
  - "fast_path=True eligibility gate (D-13): requires supports_incremental=False AND P99 < 100us from 24h histogram — no plugin eligible in this plan; branch is infrastructure only"
  - "TIER_BUDGET_MS defaults (ms): i1=50, i2=30, i3=30, i4=60, i5=40, smc=50, i6=20 — chosen based on tier complexity and stateful plugin presence"
  - "I1 carry-forward on deadline miss lives in FeaturePipelineExecutor (separate from I2-I6 carry-forward in PluginExecutor._last_tier_outputs) because I1 uses run_i1(), not run_tier()"
  - "enqueue_many() was cleanest at the call site: batch includes intel + i7_signals-or-dlq + winner + journal; journal payload is computed synchronously (no separate async enqueue)"
  - "signal_metrics_analyzer.py is the true rolling-stats source, not setup_performance_updater.py (which reads the pre-aggregated shim); the analyzer is gated on signal_schema_version = 'v2'"
requirements-completed: [PIPE-INT-05]
duration: 17min
completed: "2026-06-02"
---

# Phase 112 Plan 05: Latency Improvements + ML/Stats Data-Remediation Gates Summary

**Feature_flattening neutral module preventing circular import, fast-path/tier-budget infra, 500ms outer timeout DLQ, model_dump fix, batched enqueue_many, flat_features precompute, and feature_schema_version >= 2 / signal_schema_version = 'v2' clean-data gates on all ML training and rolling-stats queries.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-06-02T20:17:27Z
- **Completed:** 2026-06-02T20:34:07Z
- **Tasks:** 3
- **Files modified:** 13 (1 created)

## Accomplishments

- Created `feature_flattening.py` as a neutral module containing `_I1_ALIAS_MAP` and `build_flat_features()`, preventing the circular import that would result from importing these across `signal_processor.py` and `feature_pipeline_executor.py`
- Added fast-path synchronous branch (`_fast_path_coroutine`) to `run_i1` and `run_tier` in executor.py (no plugin marked `fast_path=True` — infrastructure only per D-13), `TIER_BUDGET_MS` settings dict, per-tier deadline enforcement with carry-forward (non-stateful) / warn-and-run (stateful), and 500ms outer `asyncio.wait_for` wrapping `_process_bar_compute` with DLQ routing and `intelligence_pipeline_bar_timeout_total` counter
- Fixed double-serialization bug: intel publish now uses `fp_result.event.model_dump(mode="json")` (flat dict) instead of `{"event": model_dump_json()}` (nested JSON string); migrated all producers (warmup_provider, bar_history_seeder) and verified consumers
- Added `enqueue_many()` to `OutputQueue`; replaced 4 sequential `enqueue_blocking` calls + separate journal enqueue with one batched `enqueue_many(_batch)` call; journal at LOW priority
- Precomputed `flat_features` once per bar in `FeaturePipelineExecutor.run()` via `build_flat_features(event)`; stored on `FeaturePipelineResult.flat_features`; `SignalProcessor.process()` consumes via new `flat_features=` kwarg — eliminates per-signal `model_dump()` in hot path
- Gated `ml_signal_training_materializer.py` (both Phase A and Phase B queries) on `feature_schema_version >= 2`; gated `confidence_calibrator.py` on `feature_schema_version >= 2`; gated `signal_metrics_analyzer.py` rolling-stats source on `signal_schema_version = 'v2'`
- Complete consumer inventory and complete reader inventory documented below

## Task Commits

1. **Task 5-1: Fast-path branch + tier deadline budgets + 500ms outer timeout** - `73218035` (feat)
2. **Task 5-2: feature_flattening.py + serialization fix + enqueue_many + flat_features** - `6f7ce0df` (feat)
3. **Task 5-3: ML training + rolling-stats clean-data query gates** - `6833f5fe` (feat)

## Files Created/Modified

- `src/intelligence/pipeline/feature_flattening.py` - New neutral module: `_I1_ALIAS_MAP`, `_HMM_REGIME_LABEL`, `build_flat_features(event)`; import-time validation of alias map values against `I1Indicators.model_fields`
- `src/intelligence/pipeline/executor.py` - Added `_fast_path_coroutine()` async helper; fast-path branch in `run_i1` and `run_tier`; `_last_tier_outputs` carry-forward cache; per-tier deadline enforcement in `run_tier`; `tier_budget_ms` param to `run_tiers`
- `src/intelligence/pipeline/feature_pipeline_executor.py` - Added `settings` param to constructor; `_last_i1_outputs` cache; I1 deadline check with carry-forward; import `build_flat_features`; call it after `IntelligenceEvent` construction; `flat_features` field on `FeaturePipelineResult`; pass `tier_budget_ms` to `run_tiers`
- `src/intelligence/pipeline/output_queue.py` - Added `enqueue_many(items, *, timeout_sec)` method
- `src/intelligence/pipeline/signal_processor.py` - Removed `_I1_ALIAS_MAP`, `_HMM_REGIME_LABEL`, `_build_features_from_event` definitions; import from `feature_flattening`; `flat_features` kwarg on `process()`; use precomputed or fall back to `build_flat_features(event)`
- `src/config/settings.py` - Added `tier_budget_ms: dict[str, float]` field with `TIER_BUDGET_MS` alias and sensible defaults
- `services/intelligence_pipeline.py` - Added `intelligence_pipeline_bar_timeout_total` counter; 500ms `wait_for` wrapping `_process_bar_compute`; DLQ routing on `TimeoutError`; serialization fix; `enqueue_many` batch; `_build_journal_record` replacing `_enqueue_intel_journal`; pass `settings=` to `FeaturePipelineExecutor`; pass `flat_features=` to `sig_proc.process()`
- `src/intelligence/services/ml_signal_training_materializer.py` - Added `AND f.feature_schema_version >= 2` to Phase A (yesterday INSERT) and Phase B (30-day UPSERT) WHERE clauses
- `src/intelligence/ml/confidence_calibrator.py` - Added `AND feature_schema_version >= 2` to signal_ledger_full source query
- `services/signal_metrics_analyzer.py` - Added `AND signal_schema_version = 'v2'` to rolling-stats source query; secondary backfill-ratio query at line 363 not gated (counts all signals for ratio, no version column needed)
- `services/feature_writer.py` - Updated intel skip check: `"i1" in payload` instead of `"event" in payload` (intel events are now flat dicts)
- `src/persistence/logic/warmup_provider.py` - Updated to `event.model_dump(mode="json")` publish format
- `src/intelligence/services/bar_history_seeder.py` - Updated to `event.model_dump(mode="json")` publish format
- `src/intelligence/ai/base_group_service.py` - Updated comment; backward-compat fallback preserved for replay messages still using old format

## Intel Event Consumer Inventory - Plan 05

Consumer inventory performed before serialization change (grep: `'"event"' services/ src/`):

| File | Line | Role | Action | Status |
|------|------|------|--------|--------|
| `services/intelligence_pipeline.py` | 565 | Producer (publishes to intel topic) | Fixed to `model_dump(mode="json")` | Migrated |
| `services/feature_writer.py` | 493 | SKIP check: skips raw intel events on journal consumer path | Updated check: `"i1" in payload` vs `"event" in payload` | Migrated |
| `src/persistence/logic/warmup_provider.py` | 187 | Producer (warmup replay publishes to intel topic) | Fixed to `model_dump(mode="json")` | Migrated |
| `src/intelligence/services/bar_history_seeder.py` | 210 | Producer (seeder publishes to intel topic) | Fixed to `model_dump(mode="json")` | Migrated |
| `src/intelligence/schemas.py` | 821 | Docstring comment about stream format | Not a consumer; left as-is | No-op |
| `src/intelligence/ai/base_group_service.py` | 235 | Consumer: `payload.get("event", payload)` + json.loads on str | Already handles both formats via fallback; comment updated | Confirmed no-impact |

## Intelligence Feature Reader Inventory - Plan 05

Reader inventory performed before edits (grep: `'FROM intelligence_features\|JOIN intelligence_features\|signal_ledger_full' src/ services/`):

| File | Lines | Classification | Disposition |
|------|-------|----------------|-------------|
| `src/intelligence/services/ml_signal_training_materializer.py` | 173, 250 | (a) GATED IN THIS TASK | Added `AND f.feature_schema_version >= 2` to both queries |
| `src/intelligence/ml/confidence_calibrator.py` | 76 | (a) GATED IN THIS TASK | Added `AND feature_schema_version >= 2` |
| `services/signal_metrics_analyzer.py` | 95 (primary rolling-stats), 363 (backfill ratio gauge) | (b) GATED IN THIS TASK (primary) / (d) DEFERRED (backfill ratio) | Primary query: `AND signal_schema_version = 'v2'` added. Backfill ratio query counts ALL signals for percentage; version gate would distort the ratio metric; left ungated |
| `src/core/ml/training_data.py` | 49 | (d) DEFERRED | Direct `intelligence_features` join for ML feature builder; gating deferred to Phase 112 follow-up |
| `src/intelligence/ml/feature_builder.py` | 100 | (d) DEFERRED | ML discovery feature builder; gating deferred |
| `services/ml_discovery_analyzer.py` | (header comment) | (d) DEFERRED | Reads via feature_builder; gated transitively when feature_builder is gated |
| `src/intelligence/services/hmm_trainer.py` | 180 | (d) DEFERRED | HMM regime model training; different training modality; deferred |
| `src/monitoring/ks_drift_monitor.py` | 248 | (d) DEFERRED | KS drift detection on feature distributions; monitoring tool; deferred |
| `src/persistence/repository/feature_snapshot_repository.py` | 43 | (d) DEFERRED | Feature snapshot repo; persistence layer; deferred |
| `services/cross_asset_analyzer.py` | 344 | (d) DEFERRED | Cross-asset correlation; reads recent features; deferred |
| `services/signal_auditor.py` | 215, 270, 316-317 | (d) DEFERRED | Signal quality auditing; deferred |
| `services/data_quality_auditor.py` | 108, 124, 142, 163 | (d) DEFERRED | Data quality monitoring; deferred |
| `src/validation/cross_tier_validation.py` | 42, 96, 172 | (d) DEFERRED | Cross-tier feature validation; deferred |
| `src/validation/validation_engine.py` | 61 | (d) DEFERRED | Feature validation engine; deferred |
| `src/api/routes/features.py` | 57, 127 | (d) DEFERRED | API features endpoint; returns all features; version gate would change API behavior; deferred |
| `src/api/routes/signals.py` | 206-208, 333, 507, 742-743, 842-843, 862 | (d) DEFERRED | API signals endpoint; deferred |
| `src/api/routes/narrative.py` | 166-167 | (d) DEFERRED | API narrative; deferred |
| `src/persistence/repository/signal_ledger_repository.py` | 319, 326, 583, 598 | (c) PRE-AGGREGATED TABLE | Reads signal_ledger_full for signal lifecycle tracking; not intelligence_features directly |
| `services/quality_floor_bootstrap.py` | 83, 107 | (c) PRE-AGGREGATED VIEW | Reads signal_ledger_full for quality floor at startup; pre-aggregated |
| `services/graduation_analyzer.py` | 46, 72 | (c) PRE-AGGREGATED VIEW | Reads signal_ledger_full for graduation; pre-aggregated |
| `services/alpha_swarm.py` | 283 | (c) PRE-AGGREGATED VIEW | Alpha swarm reads signal_ledger_full for weight updates |
| `services/shadow_auditor.py` | 125, 266 | (c) PRE-AGGREGATED VIEW | Shadow auditor reads signal_ledger_full |
| `services/signal_tracker.py` | 1107, 1169 | (c) PRE-AGGREGATED VIEW | Signal lifecycle tracker; reads signal_ledger_full |
| `services/signal_replay_auditor.py` | 97, 134 | (c) PRE-AGGREGATED VIEW | Replay auditor reads signal_ledger_full |

**setup_performance_updater.py NOT modified**: the file reads from the `setup_performance` shim table (pre-aggregated by signal_metrics_analyzer.py) which has no `signal_schema_version` column. The true rolling-stats source is `signal_metrics_analyzer.py` — gated there.

## State-Commit Boundary Analysis

**Design:** Plugin state is extracted in `_collect_plugin_results()` which is called AFTER `await asyncio.gather(*tasks)` completes. The call chain is:

```
_process_bar_inner
  asyncio.wait_for(_process_bar_compute, timeout=0.5)  # <-- outer timeout
    feature_pipeline.run(bar, ...)
      executor.run_i1(...)
        asyncio.gather(*[t.coroutine for t in tasks])  # <-- gathers plugin futures
          _collect_plugin_results(tasks, gather_results)  # <-- state commit here
```

When `wait_for` raises `TimeoutError` at the outer boundary:
1. The `_process_bar_compute` coroutine is cancelled
2. The `gather` inside executor is cancelled
3. `_collect_plugin_results` never executes (it's called after `gather` returns)
4. **Plugin state is NOT committed** — the state write only occurs after compute returns to the event loop AND is captured by the calling coroutine

The `run_in_executor` thread may continue running (threads can't be cancelled), but the result is never observed since the coroutine awaiting it has been cancelled. The state dict is returned from the thread but is never written to `state_updates` because `_collect_plugin_results` doesn't run. **This design is safe.**

## Decisions Made

- `TIER_BUDGET_MS` defaults: i1=50ms (28 non-stateful indicators), i2=30ms (10 composite events), i3=30ms (8 structure plugins), i4=60ms (12 context plugins, includes stateful GARCH/Kalman), i5=40ms (16 patterns), smc=50ms (16 SMC plugins, includes stateful HMM), i6=20ms (6 confluence plugins). Chosen conservatively above expected p99 at current load.
- I1 carry-forward is in `FeaturePipelineExecutor` (separate from I2-I6 in `PluginExecutor`) because I1 uses `run_i1()` not `run_tier()`, and FPE is the right owner (it has settings and the I1 result).
- `enqueue_many` uses per-item `enqueue_blocking` semantics internally — same timeout/drop behavior as the individual calls it replaces, just batched at the call site.
- `setup_performance_updater.py` NOT modified: confirmed it reads the `setup_performance` shim table (pre-aggregated row, no version column). The analyzer is the true source.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test files patching removed function `_build_features_from_event`**
- **Found during:** Task 5-2 (after removing `_build_features_from_event` from signal_processor.py)
- **Issue:** 5 test files patched `src.intelligence.pipeline.signal_processor._build_features_from_event` which no longer exists; `test_module_level_helpers_exist` checked for the old function; `test_perf01_build_features_from_event_called_once` checked executor.py which was the wrong file
- **Fix:** Updated all patches to `src.intelligence.pipeline.signal_processor.build_flat_features`; updated `test_module_level_helpers_exist` to check `build_flat_features` in both `signal_processor` and `feature_flattening`; updated PERF-01 test to check `feature_pipeline_executor.py` for `build_flat_features` call count
- **Files modified:** `tests/unit/pipeline/test_signal_processor.py`, `tests/unit/pipeline/test_feature_pipeline_executor.py`, `tests/unit/pipeline/test_pipeline_determinism.py`, `tests/unit/pipeline/test_pipeline_exception_isolation.py`, `tests/unit/pipeline/test_pipeline_parallelization.py`
- **Committed in:** `6f7ce0df` (task 5-2 commit)

**2. [Rule 1 - Bug] Pre-commit hook blocked on missing enqueue_blocking usage check**
- **Found during:** Task 5-1 (first commit attempt)
- **Issue:** `test_intel_and_journal_use_blocking_enqueue` AST scan found `self._out_queue.enqueue()` (non-blocking) call added for DLQ timeout handler; test requires all output queue calls to use `enqueue_blocking`
- **Fix:** Changed DLQ enqueue on timeout to `enqueue_blocking(..., timeout_sec=1.0)` with 1s timeout — prevents handler from stalling consumer loop while satisfying the test contract
- **Files modified:** `services/intelligence_pipeline.py`
- **Committed in:** `73218035` (task 5-1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Verification Gate Results

| Gate | Check | Result |
|------|-------|--------|
| 3-A | `fast_path` branch exists in `run_i1` and `run_tier` | PASS |
| 3-A | No plugin has `fast_path=True` | PASS |
| 3-A | State-commit boundary safe (documented above) | PASS |
| 3-B | Intel publish uses `model_dump(mode="json")` | PASS |
| 3-B | No `model_dump_json` in intel publish path | PASS |
| 3-B | Consumer inventory in SUMMARY | PASS |
| 3-C | `enqueue_many` in OutputQueue; called in intelligence_pipeline | PASS |
| 3-C | Journal is LOW priority in batch | PASS |
| 3-D | `TIER_BUDGET_MS` on Settings | PASS |
| 3-D | Carry-forward for non-stateful; warn-and-run for stateful | PASS |
| 3-D | 500ms outer timeout DLQs bar with `bar_tier_timeout` | PASS |
| 3-D | `intelligence_pipeline_bar_timeout_total` counter exists | PASS |
| 3-E | `feature_flattening.py` exists; `_I1_ALIAS_MAP` and `build_flat_features` importable | PASS |
| 3-E | `FeaturePipelineResult.flat_features` field exists | PASS |
| 3-E | `signal_processor` consumes `flat_features` kwarg | PASS |
| 4-A | `ml_signal_training_materializer` has `feature_schema_version >= 2` in both queries | PASS |
| 4-A | `confidence_calibrator` has `feature_schema_version >= 2` | PASS |
| 4-C | `signal_metrics_analyzer` has `signal_schema_version = 'v2'` | PASS |
| 4-C | Reader inventory in SUMMARY | PASS |
| Tests | `pytest tests/unit/ -q` — 4099 passed | PASS |

## Self-Check

Files verified to exist:
- `src/intelligence/pipeline/feature_flattening.py` - EXISTS
- `src/intelligence/pipeline/executor.py` (has `fast_path` branch) - EXISTS
- `src/intelligence/pipeline/output_queue.py` (has `enqueue_many`) - EXISTS
- `src/intelligence/pipeline/feature_pipeline_executor.py` (has `flat_features`) - EXISTS
- `src/config/settings.py` (has `tier_budget_ms`) - EXISTS
- `services/intelligence_pipeline.py` (has `bar_timeout_total`, `wait_for`, `enqueue_many`) - EXISTS
- `src/intelligence/services/ml_signal_training_materializer.py` (has 2x `feature_schema_version >= 2`) - EXISTS
- `src/intelligence/ml/confidence_calibrator.py` (has `feature_schema_version >= 2`) - EXISTS
- `services/signal_metrics_analyzer.py` (has `signal_schema_version = 'v2'`) - EXISTS

Commits verified: 73218035, 6f7ce0df, 6833f5fe

## Self-Check: PASSED

## Issues Encountered

- Pre-commit hook failed on first commit of Task 5-1 due to missing `.venv/bin/ruff` in worktree path — resolved by symlinking the main project's `.venv` into the worktree directory.

## Next Phase Readiness

- Phase 112 (intelligence-pipeline-signal-integrity) is complete: all 5 plans (01-05) executed
- All latency improvements, circular-import resolution, serialization fix, enqueue batching, and data-remediation gates are shipped
- ML training, calibration, and rolling-stats queries are clean-data gated — future training runs will use only post-fix data
- Follow-up deferred readers (feature_builder, hmm_trainer, ks_drift_monitor, API routes) documented in reader inventory; none block phase completion

---
*Phase: 112-intelligence-pipeline-signal-integrity*
*Completed: 2026-06-02*
