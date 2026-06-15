---
phase: 125-apr-full-migration-all-three-tiers
plan: "02"
subsystem: intelligence/trading
tags: [confidence-utils, weight-validation, parameter-naming, unit-tests, todos]
dependency_graph:
  requires: []
  provides: [_validate_weights_sum utility, APR-03 weight invariant, cfg-rename fix]
  affects: [src/intelligence/trading/confidence_utils.py, tests/unit/intelligence/test_param_store_migration.py]
tech_stack:
  added: []
  patterns: [fail-fast at init, ValueError over AssertionError, float tolerance invariant]
key_files:
  created:
    - .planning/todos/pending/2026-06-14-rename-confidence-utils.md
    - .planning/todos/pending/2026-06-14-rename-cfg-in-zone-engine.md
  modified:
    - src/intelligence/trading/confidence_utils.py
    - tests/unit/intelligence/test_param_store_migration.py
decisions:
  - "Raise ValueError (not AssertionError) so weight invariant fires even under python -O"
  - "Tolerance 1e-6 chosen to handle float repr of 0.40+0.35+0.25 without false failures"
  - "Deferred confidence_utils.py rename - 39 import sites; captured as TODO"
  - "Deferred zone_engine._cfg() rename - out of scope for Phase 125; captured as TODO"
metrics:
  duration: 5m
  completed: "2026-06-15"
  tasks_completed: 2
  files_modified: 2
  files_created: 2
---

# Phase 125 Plan 02: _validate_weights_sum Utility + cfg Rename Summary

**One-liner:** Centralized weight-sum invariant (_validate_weights_sum) added to confidence_utils.py with ValueError semantics; set_config_service cfg->config parameter rename closes D-04 naming violation.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add _validate_weights_sum + fix cfg parameter | 3f86ce38 | src/intelligence/trading/confidence_utils.py |
| 2 | Add unit tests + capture cleanup TODOs | 70752e7b | tests/unit/intelligence/test_param_store_migration.py, 2 TODO files |

## What Was Built

### confidence_utils.py changes

Two targeted changes to `src/intelligence/trading/confidence_utils.py`:

1. `set_config_service(cfg: Any)` parameter renamed to `set_config_service(config: Any)` - closes the D-04 banned abbreviation violation. Positional callers (including teardown_function in tests) unaffected.

2. `_validate_weights_sum(weights, plugin, tol=1e-6)` added between `get_min_ctf_score()` and `clamp01()`. Raises `ValueError` (not `AssertionError`) so the invariant fires even when Python is run with `-O` (which disables assert statements). Called at prewarm/init time to fail fast before any signal fires.

### Unit tests (4 new)

- `test_validate_weights_sum_passes_on_exact` - exact sum 0.40+0.35+0.25=1.0
- `test_validate_weights_sum_passes_within_tolerance` - 0.4+0.3+0.3 passes within 1e-6
- `test_validate_weights_sum_raises_on_bad_seed` - bad DB seed raises ValueError with message
- `test_validate_weights_sum_raises_value_error_not_assertion_error` - confirms ValueError semantics

All 17 tests pass (13 existing + 4 new).

### Cleanup TODOs captured

- `.planning/todos/pending/2026-06-14-rename-confidence-utils.md` - 39 import sites to update when renaming to confidence.py
- `.planning/todos/pending/2026-06-14-rename-cfg-in-zone-engine.md` - _cfg() to _read_config() in zone_engine.py

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- src/intelligence/trading/confidence_utils.py: FOUND
- tests/unit/intelligence/test_param_store_migration.py: FOUND
- .planning/todos/pending/2026-06-14-rename-confidence-utils.md: FOUND
- .planning/todos/pending/2026-06-14-rename-cfg-in-zone-engine.md: FOUND
- Commit 3f86ce38: FOUND
- Commit 70752e7b: FOUND
- 17 tests pass: VERIFIED
