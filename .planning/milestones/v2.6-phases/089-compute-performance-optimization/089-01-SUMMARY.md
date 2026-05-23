---
phase: "089"
plan: "01"
subsystem: intelligence-pipeline
tags: [dag-decomposition, refactor, observability, orchestrator]
dependency_graph:
  requires: []
  provides:
    - FeaturePipelineExecutor (new DAG node owning I1-I6 compute)
    - PluginExecutor.run_i7_complete (consolidated I7 setup)
    - CacheManager.update_cross_asset/update_macro/update_htf_intel/update_hmm_regime
    - 5 signal_processor_* OTel counters
    - CacheSnapshot.cross_asset_data/macro_data/htf_intel fields
    - Settings.intelligence_pipeline_symbol_filter/intelligence_output_drain_batch_size
  affects:
    - services/intelligence_pipeline_agent.py (orchestrator slimmed to router)
    - src/intelligence/pipeline/* (executor, cache_manager, signal_processor extended)
tech_stack:
  added: []
  patterns:
    - DAG node injection (FPE: constructor injection of bar_history, executor, state_mgr)
    - CacheSnapshot as frozen per-bar view for DAG nodes (D-19)
    - PluginExecutor.run_i7_complete for D-15 compliance (no state_mgr reference)
key_files:
  created:
    - src/intelligence/pipeline/feature_pipeline_executor.py
  modified:
    - services/intelligence_pipeline_agent.py (763 -> 581 lines, -182)
    - src/intelligence/pipeline/executor.py (added run_i7_complete)
    - src/intelligence/pipeline/cache_manager.py (symbols param + 4 update methods)
    - src/intelligence/pipeline/signal_processor.py (CacheSnapshot fields + alpha decay + OTel)
    - src/intelligence/pipeline/__init__.py (added FPE exports)
    - src/observability/metrics.py (5 signal_processor_* counters)
    - src/config/settings.py (2 new fields)
    - tests/unit/pipeline_tests/test_orchestrator_integration.py (updated mocks for new flow)
decisions:
  - "FPE owns _prev_i1_features and _last_events carry-forward state (migrated from orchestrator)"
  - "CacheSnapshot fields default to empty dict for backward compatibility with existing call sites"
  - "HTF intel cached after processing 15m/1h/4h/1d bars so lower-TF FPE reads it via CacheSnapshot"
  - "SignalProcessor applies alpha decay internally; orchestrator's call site deleted"
  - "PluginExecutor.run_i7_complete stores state updates in _last_i7_state_updates; orchestrator reads and applies"
metrics:
  duration: "~17 minutes (16:13 to 16:30 UTC-4)"
  completed: "2026-05-18"
  tasks_completed: 6
  tasks_total: 6
  files_modified: 9
  files_created: 1
---

# Phase 089 Plan 01: DAG Decomposition Summary

**One-liner:** Orchestrator reduced from 763 to 581 lines — all I1-I6 compute extracted to FeaturePipelineExecutor, I7 setup consolidated into PluginExecutor.run_i7_complete, stream caches migrated to CacheManager with symbol scoping, 5 OTel counters wired for SignalProcessor gate observability.

## What Was Built

### Task 1: OTel Counters + Settings + CacheSnapshot (D-22, D-28)

Added 5 module-level OTel counters to `src/observability/metrics.py`:
- `signal_processor_cis_null_total`
- `signal_processor_dlq_total` (label: reason)
- `signal_processor_gate_rejections_total` (label: gate)
- `signal_processor_winner_total` (label: entry_type)
- `signal_processor_signals_evaluated_total`

Added to `src/config/settings.py`:
- `intelligence_pipeline_symbol_filter: list[str]` (D-28, for sharding)
- `intelligence_output_drain_batch_size: int = 10` (D-14, for Plan 03)

Extended `CacheSnapshot` in `signal_processor.py` with 3 new fields (all default to `{}`):
- `cross_asset_data`, `macro_data`, `htf_intel`

### Task 2: Stream Cache Migration + CacheManager Symbols Scoping (D-19, D-30)

`CacheManager.__init__` now accepts `symbols: frozenset[str] | None = None`. When set, all 6 DB refresh queries gain `WHERE symbol = ANY($N::text[])` clauses.

Added 4 update methods and stream cache instance dicts:
- `update_cross_asset(tf, payload)`, `update_macro(tf, payload)`, `update_htf_intel(tf, data)`, `update_hmm_regime(regime)`

Added `snapshot()` method returning `CacheSnapshot` populated from all stream caches + existing DB-backed caches.

### Task 3: Alpha Decay Ownership + OTel Counters (D-21, D-22)

`SignalProcessor.process()` now applies `_apply_alpha_decay` internally at the start of the gate pipeline. All 5 D-22 OTel counters emitted at their correct decision points:
- signals_evaluated: after alpha decay
- gate_rejections: after each gate stage (regime, quality, tod, calibration)
- cis_null: when CIS scoring returns None
- dlq: when signal routed to DLQ
- winner: when winner selected (labeled by entry_type)

### Task 4: PluginExecutor.run_i7_complete (D-20, D-15)

Added `async def run_i7_complete(self, intel_event, bar, cache_snapshot, plugin_states, lock, *, main_df)` to `PluginExecutor`. Consolidates the 52-line I7 setup block that was in the orchestrator. Calls `_build_features_from_event` once, assembles plugin_input, calls `run_i7_plugins`, post-processes signals with `regime_type` lookup from `self._plugin_cache` (D-15: no PluginStateManager reference). State updates stored in `self._last_i7_state_updates` for orchestrator to apply.

### Task 5: FeaturePipelineExecutor (D-18, D-25, D-26)

New file `src/intelligence/pipeline/feature_pipeline_executor.py`. Owns:
- `_prev_i1_features` and `_last_events` carry-forward state (migrated from orchestrator)
- `run(bar, cache_snapshot) -> FeaturePipelineResult`
  - Calls `to_dataframe()` once, returns `main_df` on result (D-26)
  - Reads stream caches from `cache_snapshot.cross_asset_data/macro_data/htf_intel` (D-19)
  - Extracts `hmm_regime` from I1 output, places on result (D-25)

`FeaturePipelineResult` dataclass: `{event, tiered, main_df, hmm_regime}`.

### Task 6: Orchestrator Slim-down + Wire FPE/run_i7_complete (D-18, D-19, D-20, D-21, D-24, D-25, D-26, D-29)

`_process_bar_inner` rewritten as ~69-line DAG router (reduced from ~125 lines):
```
gap detection
cache_snapshot = self._cache_mgr.snapshot()
fp_result = await self._feature_pipeline.run(bar, cache_snapshot)
if fp_result.event is None: return
self._cache_mgr.update_hmm_regime(fp_result.hmm_regime)
[HTF intel cache update for 15m/1h/4h/1d bars]
raw_signals = await self._executor.run_i7_complete(...)
result = await self._sig_proc.process(...)
4-way routing + journal
```

Deleted: `_run_i1_to_i6`, `_df_cache`, `_cross_asset_cache`, `_macro_cache`, `_htf_intel_cache`, `_prev_i1_features`, `_last_events`, redundant `_plugin_cache` init, `min(12, ...)` thread cap, deferred imports, `_apply_alpha_decay` call, `self._executor._plugin_cache` access.

## _process_bar_inner Before/After

- **Before:** ~125 lines including 52-line I7 setup block + 73-line I1-I6 frame assembly delegation
- **After:** 69 lines (pure routing: gap detect + FPE + HMM update + HTF cache + I7 + SignalProcessor + 4-way route + journal)
- **Orchestrator file:** 763 lines -> 581 lines (-182 lines)

## grep "self\._executor\._plugin_cache" services/intelligence_pipeline_agent.py

Returns zero results. Private cross-class access eliminated. PluginExecutor.run_i7_complete owns `regime_type` lookup internally via `self._plugin_cache`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing] HTF intel cache never written in original orchestrator**
- **Found during:** Task 6 acceptance criteria verification (grep count returned 3, not 4)
- **Issue:** `_htf_intel_cache` was initialized as empty dict and read in FPE but never written - the HTF cross-tf context feature was infrastructure-only with no write site.
- **Fix:** Added `self._cache_mgr.update_htf_intel(bar.tf, fp_result.event.model_dump())` call in `_process_bar_inner` for HTF timeframes (15m/1h/4h/1d). Satisfies D-19 and closes the cross-tf context loop.
- **Files modified:** `services/intelligence_pipeline_agent.py`
- **Commit:** 244d8b80

**2. [Rule 3 - Blocking] Test mocks referenced deleted API**
- **Found during:** Task 6 - tests failed after orchestrator refactor
- **Issue:** `test_orchestrator_integration.py`'s `_wire_agent()` still mocked `agent._run_i1_to_i6` and `agent._executor.run_i7_plugins` (both removed/replaced in refactor)
- **Fix:** Updated `_wire_agent()` to mock `agent._feature_pipeline.run` with `FeaturePipelineResult` and `agent._executor.run_i7_complete` with state updates via `_last_i7_state_updates`
- **Files modified:** `tests/unit/pipeline_tests/test_orchestrator_integration.py`
- **Commit:** 0f2761f3

## Self-Check

### Commits Made
- `194b2b2e` feat(089-01): add 5 OTel counters, 2 Settings fields, 3 CacheSnapshot fields
- `8cb929a8` feat(089-01): migrate stream caches into CacheManager + add symbols scoping
- `440335c8` feat(089-01): move alpha decay into SignalProcessor.process() + emit D-22 OTel counters
- `94e8f2e1` feat(089-01): add PluginExecutor.run_i7_complete() — D-15-compliant I7 consolidation
- `553ffb91` feat(089-01): create FeaturePipelineExecutor — 6th DAG node extracting _run_i1_to_i6
- `0f2761f3` feat(089-01): slim orchestrator to pure DAG router + wire FPE/run_i7_complete
- `244d8b80` fix(089-01): wire update_htf_intel call in _process_bar_inner (D-19)
