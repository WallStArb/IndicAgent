---
phase: 100-plugin-shared-infrastructure
plan: "02"
subsystem: intelligence-plugins
tags: [plugin-infra, incremental-state, mixin, atr, unit-tests]
dependency_graph:
  requires: [100-01]
  provides: [IncrementalMixin, ATR-mixin-reference]
  affects: [src/intelligence/plugins/mixins.py, src/intelligence/features/i1_indicators/atr.py]
tech_stack:
  added: []
  patterns: [IncrementalMixin, mutable-in-place-state-contract, state-is-None-fallback]
key_files:
  created:
    - tests/unit/intelligence/test_incremental_mixin.py
  modified:
    - src/intelligence/plugins/mixins.py
    - src/intelligence/features/i1_indicators/atr.py
decisions:
  - "Use state is None for fallback check (not truthiness) so empty dict {} does not trigger full recompute"
  - "State ownership is mutable in-place: _compute_next_core mutates state, mixin re-attaches same dict"
  - "Executor window contract documented: frames passed unchanged to both compute_full and compute_next"
  - "ATR _seed_state re-runs ewm to extract prev_atr/prev_close -- no coupling to _compute_full_core internals"
metrics:
  duration_minutes: 45
  completed: "2026-05-21"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 3
---

# Phase 100 Plan 02: IncrementalMixin and ATR Migration Summary

IncrementalMixin class owns the fallback-to-full and _state attachment contract for incremental plugins, with ATR migrated as the reference implementation using wilders_update and mutable-in-place state.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add IncrementalMixin to mixins.py | 402761a4 (prior session) | src/intelligence/plugins/mixins.py |
| 2 | Unit tests for IncrementalMixin contract | 928d4a47 (prior session) | tests/unit/intelligence/test_incremental_mixin.py |
| 3 | Migrate ATR plugin to IncrementalMixin | ec08fb98 | src/intelligence/features/i1_indicators/atr.py |

## What Was Built

### IncrementalMixin (src/intelligence/plugins/mixins.py)

The mixin provides `compute_full` and `compute_next` methods that own the full state contract:

- `compute_full`: calls `_compute_full_core`, then `_seed_state`, attaches `_state` to output
- `compute_next`: uses `if state is None:` (not truthiness) for fallback; calls `_compute_next_core`, re-attaches same mutated state dict

Key design decisions documented in the docstring:
- **MUTABLE IN-PLACE CONTRACT**: `_compute_next_core` receives a non-None state dict and mutates it. The mixin re-attaches the same dict object as `result["_state"]`.
- **Executor window contract**: The executor passes full historical frames to both paths via `functools.partial` -- no per-call slicing.
- **Empty dict is valid state**: `state is None` triggers fallback, but `state = {}` reaches `_compute_next_core`. If the plugin cannot handle empty state, it returns `{}`.

### Unit Tests (tests/unit/intelligence/test_incremental_mixin.py)

12 tests across two test classes:

**TestIncrementalMixinContract** (9 tests):
- `test_state_attached_in_compute_full` -- _state key present in output
- `test_state_attached_in_compute_next` -- _state key present in output
- `test_fallback_to_full_when_state_is_none` -- None triggers fallback
- `test_empty_dict_state_does_NOT_trigger_fallback` -- {} does NOT trigger fallback (critical)
- `test_compute_next_receives_non_none_state` -- _compute_next_core never sees None
- `test_state_is_same_object_after_mutation` -- identity check with `is`
- `test_empty_result_returns_empty_dict` -- insufficient data returns {}
- `test_empty_result_in_compute_next_returns_empty_dict` -- same for compute_next
- `test_abstract_methods_raise_not_implemented` -- unimplemented subclass raises

**TestIncrementalMixinReplayParity** (3 tests):
- `test_full_equals_seed_plus_incremental` -- SMA over N=50 bars: seed on 20, compute_next x 30, final value matches compute_full on all 50 (tolerance 1e-10)
- `test_state_accumulates_correctly` -- state["count"] and state["sum"] increment correctly
- `test_state_is_threaded_across_calls` -- same state object threaded across multiple calls

### ATR Migration (src/intelligence/features/i1_indicators/atr.py)

Migrated `ATRPlugin` from manual `compute_full`/`compute_next` to `IncrementalMixin`:

- `_compute_full_core`: pure ewm ATR computation, returns `{f"atr_{p}": float}`, no `_state`
- `_seed_state`: re-runs ewm to extract `{f"atr_{p}": {"prev_atr": float, "prev_close": float}}`
- `_compute_next_core`: single-bar Wilder's update using `wilders_update()` from mixins, mutates state in place

The mixin's `compute_full` and `compute_next` are inherited -- `ATRPlugin` defines none of these directly.

## Deviations from Plan

None -- plan executed exactly as written. The context note indicated Tasks 1 and 2 had been completed in a prior session (commit 402761a4 and 928d4a47). Task 3 (ATR migration) was completed in this session (commit ec08fb98).

## Verification Results

All plan verification checks passed:

```
pytest tests/unit/intelligence/test_incremental_mixin.py
  tests/unit/intelligence/test_plugin_incremental.py::TestATRIncremental
  -- 13 passed in 0.34s

isinstance(ATRPlugin(), IncrementalMixin) -- True
grep -c "self._state" atr.py -- 0
grep core methods atr.py -- 3 definitions, 13 total references
grep "if state is None" mixins.py -- 2 occurrences
```

## Self-Check: PASSED

All created files exist on disk. All referenced commits present in git log.
