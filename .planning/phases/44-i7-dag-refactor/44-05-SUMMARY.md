---
phase: 44-i7-dag-refactor
plan: "05"
subsystem: intelligence/trading
tags: [i7-plugins, dag-refactor, divergence-stack, utility-wiring, gap-closure]
dependency_graph:
  requires: [44-04]
  provides: [divergence_stack_utility_wiring]
  affects: [signal_generator_service, validate_signal]
tech_stack:
  added: []
  patterns: [shared-utility-wiring, compose_confidence, frame_trade, get_atr, no_signal]
key_files:
  created: []
  modified:
    - src/intelligence/trading/divergence_stack.py
    - tests/unit/test_divergence_stack.py
    - tests/unit/intelligence/test_cis_plugins.py
decisions:
  - "ATR/frame_trade failure path returns base_output merged with neutral signal fields (not no_signal()) to preserve always-logged scoring fields in i7 JSONB"
  - "Updated test_cis_plugins.py TestDivergenceStack tests to use new compose_confidence contract instead of old inline formula"
metrics:
  duration: "~5 minutes"
  completed: "2026-03-21T08:10:00Z"
  tasks_completed: 2
  files_modified: 3
---

# Phase 44 Plan 05: DivergenceStack Gap Closure Summary

Wire `divergence_stack.py` to the 4 shared utility modules (plugin_utils, atr_utils, confidence_utils, trade_framer), closing the single verification gap left by Plan 02. Without this fix, every DivergenceStackPlugin signal was silently dropped by `validate_signal()` due to `targets: []`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Wire divergence_stack.py to shared utilities + frame_trade | 54a04f3 | src/intelligence/trading/divergence_stack.py |
| 2 | Extend divergence_stack tests for utility wiring and signal validation | 68ca5b2 | tests/unit/test_divergence_stack.py, tests/unit/intelligence/test_cis_plugins.py |

## What Was Built

**Task 1 — Plugin wiring (5 transformations):**
- Added 4 imports: `get_atr`, `compose_confidence`, `no_signal`, `signal_type_for_direction`, `frame_trade`
- Replaced `return {}` on insufficient data with `return no_signal()` (canonical form)
- Replaced inline `round(min(1.0, weighted_score/0.60), 4)` with `compose_confidence(weighted_score/0.60)` — system contract `[0.10, 0.95]`
- Added `frame_trade()` call producing real `stop_loss` (float) and `targets` (non-empty list)
- Added `stop_loss` and `regime_context` to outputs frozenset and signal return dict
- ATR failure / non-viable TradeFrame paths return `base_output` merged with neutral fields (preserves always-logged scoring fields for i7 JSONB)

**Task 2 — Test coverage (6 new tests + 3 test updates):**
- `test_insufficient_data_returns_no_signal_dict`: verifies canonical no_signal() return
- `test_signal_has_nonempty_targets`: ensures validate_signal() will not drop the signal
- `test_signal_has_float_stop_loss`: ensures stop_loss is a float
- `test_signal_has_regime_context_string`: ensures regime_context is a string
- `test_confidence_within_system_contract`: verifies [0.10, 0.95] bound enforcement
- `test_no_signal_returns_base_output_with_scoring_fields`: verifies base_output preserved on ATR failure
- Updated `_make_features_with_divergences` helper with structural fields (swing_low/high, sr_nearest_*)
- Updated 3 tests in test_cis_plugins.py TestDivergenceStack to include atr_14 + structural features and use compose_confidence contract

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test_cis_plugins.py TestDivergenceStack tests**
- **Found during:** Task 2 test run
- **Issue:** 3 tests in `tests/unit/intelligence/test_cis_plugins.py::TestDivergenceStack` failed because they didn't include `atr_14` in the features dict, so `get_atr()` returned None and the plugin took the no-signal path. `test_confidence_formula` also tested the old `min(1.0, ...)` formula instead of `compose_confidence()`.
- **Fix:** Added `atr_14`, `swing_low`/`swing_high`, `sr_nearest_support`/`sr_nearest_resistance` to the feature dicts in the 3 failing tests. Updated `test_confidence_formula` to use `compose_confidence()` as the expected value computation.
- **Files modified:** `tests/unit/intelligence/test_cis_plugins.py`
- **Commit:** 68ca5b2

## Known Stubs

None — all signal fields produce real computed values from shared utilities.

## Pre-existing Failures (Out of Scope)

The following 3 tests were failing before this plan and remain failing (confirmed by git stash check):
- `tests/unit/intelligence/test_setup_performance_updater.py::TestWindowAndNullHandling::test_compute_setup_performance_30day_window`
- `tests/unit/intelligence/test_weight_updater.py::TestRunWeightUpdate::test_cluster_training_100_signals`
- `tests/unit/intelligence/test_weight_updater.py::TestRunWeightUpdate::test_global_model_trained_when_enough_signals`

These are unrelated to divergence_stack and were not introduced by this plan.

## Verification Results

```
tests/unit/test_divergence_stack.py: 27 passed (21 existing + 6 new)
tests/unit/intelligence/: 1570 passed, 3 failed (all pre-existing)

Grep confirmations — 4 utility imports present:
  from .atr_utils import get_atr               → line 19
  from .confidence_utils import compose_confidence → line 20
  from .plugin_utils import no_signal, signal_type_for_direction → line 21
  from .trade_framer import frame_trade        → line 22

Anti-patterns absent:
  return {}       → 0 matches
  min(1.0, weighted_score  → 0 matches
  "targets": []   → 0 matches

36/36 I7 plugins now wired to plugin_utils (was 35/36)
```

## Self-Check: PASSED
