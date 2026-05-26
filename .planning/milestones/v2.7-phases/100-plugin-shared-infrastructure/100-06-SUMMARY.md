---
phase: 100-plugin-shared-infrastructure
plan: "06"
subsystem: intelligence-plugins
tags: [bug-fix, supports-incremental, delegation-pattern, conformance-test, cvd, ofi, ma-composite]
dependency_graph:
  requires: [100-01, 100-03]
  provides: [correct-supports-incremental-flags, delegation-plugin-conformance-test]
  affects: [src/intelligence/features/i1_indicators/cvd.py, src/intelligence/features/i1_indicators/ofi.py, src/intelligence/composites/ma_composites.py, tests/unit/intelligence/test_plugin_mixins.py]
tech_stack:
  added: []
  patterns: [delegation-pattern-annotation, conformance-test-with-source-inspection]
key_files:
  created: []
  modified:
    - src/intelligence/features/i1_indicators/cvd.py
    - src/intelligence/features/i1_indicators/ofi.py
    - src/intelligence/composites/ma_composites.py
    - tests/unit/intelligence/test_plugin_mixins.py
decisions:
  - "supports_incremental=False is correct for delegation plugins because the executor incremental path provides no benefit when compute_next just calls compute_full"
  - "Conformance test uses source inspection (inspect.getsource) rather than runtime behavior to catch flag mismatches at test time without needing real data frames"
  - "IncrementalMixin plugins are exempt from conformance checks because the mixin contract guarantees state threading"
metrics:
  duration_minutes: 12
  completed_date: "2026-05-21"
  tasks_completed: 2
  files_modified: 4
---

# Phase 100 Plan 06: Delegation Plugin Flag Fix and Conformance Test Summary

Corrected supports_incremental=False on CVD, OFI, and MAComposite delegation plugins, and added a conformance test class that validates flag correctness across all 132+ registered plugins.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Set supports_incremental=False on CVD, OFI, MAComposite | f170eaff | cvd.py, ofi.py, ma_composites.py |
| 2 | Add conformance test for supports_incremental flag correctness | 4da21990 | test_plugin_mixins.py |

## What Was Fixed

### Task 1 - Three delegation plugins had misleading supports_incremental=True

All three plugins had `supports_incremental=True` but their `compute_next` methods simply delegate to `compute_full`:

```python
def compute_next(self, windows, *, state=None):
    return self.compute_full(windows)
```

This pattern means:
- The executor puts them on the incremental path
- The executor expects `_state` in the return value and threads it across bars
- But the plugin ignores the passed `state=` parameter entirely
- No incremental optimization occurs -- the full computation runs every bar anyway

Setting `supports_incremental=False` correctly declares they do not support incremental computation, removing them from the incremental validation path. Explanatory comments document the delegation pattern on each plugin.

### Task 2 - Conformance test class with 3 methods

Added `TestSupportsIncrementalFlagCorrectness` to `test_plugin_mixins.py`:

- `test_delegation_plugins_have_false_flag`: Regression test importing CVD, OFI, MAComposite directly and asserting `supports_incremental is False`.
- `test_incremental_plugins_use_state_parameter`: For each `True`-flagged plugin (excluding IncrementalMixin subclasses), inspects `compute_next` source to verify it does not read `self._state` without accepting a `state=` parameter. Catches the RSI/CMF pattern from plan 03.
- `test_incremental_plugins_return_state`: For each `True`-flagged plugin, inspects `compute_next` source to verify `_state` appears in the method body. Delegation plugins that return nothing useful are flagged. IncrementalMixin plugins are exempt.

The helper `_get_all_registered_plugins()` enumerates plugins from `TIER_I1`, `TIER_I2`, `TIER_I3`, `TIER_I4`, `TIER_I5`, `TIER_SMC`, `TIER_I6`, and `TIER_I7` via `register_plugins`.

## Verification Results

```
grep "supports_incremental" cvd.py ofi.py | grep -c "False"  -> 2
grep "supports_incremental" ma_composites.py | grep "False"  -> 1
pytest test_plugin_mixins.py::TestSupportsIncrementalFlagCorrectness -> 3 passed
python -c "assert CVDPlugin.supports_incremental is False and ..."  -> success
```

## Deviations from Plan

None - plan executed exactly as written. The `.venv` symlink was added to the worktree root to satisfy the pre-commit hook (ruff/black check), which is a worktree setup detail, not a code deviation.

## Self-Check: PASSED

- [x] `src/intelligence/features/i1_indicators/cvd.py` exists and contains `supports_incremental: bool = False`
- [x] `src/intelligence/features/i1_indicators/ofi.py` exists and contains `supports_incremental: bool = False`
- [x] `src/intelligence/composites/ma_composites.py` exists and contains `supports_incremental: bool = False`
- [x] `tests/unit/intelligence/test_plugin_mixins.py` contains `class TestSupportsIncrementalFlagCorrectness`
- [x] Commit f170eaff exists in git log
- [x] Commit 4da21990 exists in git log
- [x] All 3 conformance tests pass
