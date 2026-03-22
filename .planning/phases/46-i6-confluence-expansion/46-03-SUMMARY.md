---
phase: 46-i6-confluence-expansion
plan: "03"
subsystem: services/feature_pipeline_service.py
tags: [cross-asset, vix, frame-injection, i6-confluence, pipeline-wiring]
dependency_graph:
  requires: [46-01]
  provides: [frames.cross_asset, frames.cross_asset_5m, frames.vix for I6 execution]
  affects: [services/feature_pipeline_service.py, src/intelligence/context/cross_timeframe_confluence.py]
tech_stack:
  added: []
  patterns: [cross_asset cache pattern, VIX bar history lookup, EQ_INDEX guard, __new__ service test pattern]
key_files:
  created:
    - tests/unit/service_tests/test_feature_pipeline_vix_injection.py
  modified:
    - services/feature_pipeline_service.py
decisions:
  - Own _CROSS_ASSET_VALID_TFS constant in feature_pipeline_service (not imported from signal_generator_service)
  - VIX symbol resolved once at __init__ time by scanning get_active_contracts() for symbol in ("VX", "VIX")
  - VIX frame injected for ALL symbols; cross_asset frames injected for EQ_INDEX only
  - Frame injection placed after prev_features and before I1 execution so I6 can access both
metrics:
  duration: "2 minutes"
  completed_date: "2026-03-22"
  tasks_completed: 2
  files_changed: 2
---

# Phase 46 Plan 03: Frame Injection Wiring for FeaturePipelineService Summary

Wired FeaturePipelineService to subscribe to the cross_asset topic, cache payloads by TF, and inject `frames["cross_asset"]`, `frames["cross_asset_5m"]`, and `frames["vix"]` before I6 execution. Replicates the cross_asset injection pattern established in signal_generator_service.py and adds VIX context via compute_vix_context() for all symbols.

## Tasks Completed

### Task 1: Add cross_asset subscription + VIX frame injection (commit: d34b1f0)

Changed `services/feature_pipeline_service.py`:

1. **Added imports**: `topic_cross_asset`, `resolve_eq_index_base`, `compute_vix_context`
2. **Module-level constant**: `_CROSS_ASSET_VALID_TFS: frozenset[str]` — own constant per CONTEXT.md
3. **Instance attributes in `__init__`**: `_cross_asset_cache`, `_cross_asset_enabled`, `_vix_symbol` (resolved from active contracts)
4. **Topic subscription**: `topics.append(topic_cross_asset(env))` when `cross_asset_enabled=True`
5. **Message routing** in `_process_market_data()`: cache cross_asset payloads by TF when `ready=True`
6. **Frame injection** in `_run_pipeline()` before I1 execution:
   - `frames["cross_asset"]` + `frames["cross_asset_5m"]` for EQ_INDEX symbols when enabled
   - `frames["vix"]` for ALL symbols via `compute_vix_context(vix_deque)`

### Task 2: Unit tests for frame injection logic (commit: ddb3c0e)

Created `tests/unit/service_tests/test_feature_pipeline_vix_injection.py` with 6 tests:

| Test | Guard condition | Result |
|------|----------------|--------|
| `test_eq_index_gets_cross_asset_frames` | EQ_INDEX + enabled + cache populated | cross_asset + cross_asset_5m injected |
| `test_non_eq_index_does_not_get_cross_asset_frames` | Non-EQ_INDEX symbol | no cross_asset keys |
| `test_cross_asset_disabled_no_cross_asset_frames` | cross_asset_enabled=False | no cross_asset keys for any symbol |
| `test_vix_ready_when_sufficient_bars` | vix_symbol set + 20 bars | frames["vix"]["ready"] is True |
| `test_vix_not_ready_when_insufficient_bars` | vix_symbol set + 5 bars | frames["vix"]["ready"] is False |
| `test_no_vix_symbol_returns_not_ready` | _vix_symbol=None | frames["vix"] == {"ready": False} |

## Decisions Made

- **Own constant**: `_CROSS_ASSET_VALID_TFS` defined in feature_pipeline_service — CONTEXT.md explicitly says do not import from signal_generator_service (separate ownership)
- **VIX resolution at init**: `_vix_symbol` resolved once by scanning active contracts; downstream code does a simple `get()` on bar_history per bar — no repeated contract lookups
- **Injection placement**: After `prev_features` and before I1 call in `_run_pipeline()`. Both frames must be present before `_run_analysis_pipeline()` which runs I6 later in the DAG

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all injected frames use real compute_vix_context() and live cross_asset cache data.

## Self-Check: PASSED
- `services/feature_pipeline_service.py` modified and verified: `ruff` clean, import test passes
- `tests/unit/service_tests/test_feature_pipeline_vix_injection.py` created: 6/6 tests pass
- Commits `d34b1f0` and `ddb3c0e` verified in git log
