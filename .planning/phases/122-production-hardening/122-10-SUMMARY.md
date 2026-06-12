---
phase: 122-production-hardening
plan: 10
subsystem: testing
tags: [pytest, test-fixtures, bar_history, signal_ledger, historical_pipeline]

requires:
  - phase: 122-production-hardening
    plan: 06
    provides: "last_bar=None guard in _build_ledger_entries that skips signal generation when no bar data is available"

provides:
  - "4 test regressions in TestBuildLedgerEntries and TestBuildLedgerEntriesFeatureTs fixed"
  - "_make_bar() staticmethod pattern for bar_history test fixtures"

affects: [tests/unit/scripts/test_run_historical_pipeline.py]

tech-stack:
  added: []
  patterns:
    - "_make_bar() staticmethod returning deque of minimal OHLCV bar dicts for test fixtures requiring bar_history"

key-files:
  created: []
  modified:
    - tests/unit/scripts/test_run_historical_pipeline.py

key-decisions:
  - "Preserve test intent: provide mock bar_history so tests exercise real code paths rather than hitting the guard"
  - "Do not touch test_empty_result_returns_empty_list - it intentionally tests the empty all_ranked path where no bar_history is needed"

patterns-established:
  - "_make_bar() staticmethod: shared helper pattern for test classes needing bar_history in _build_ledger_entries calls"

requirements-completed: []

duration: 4min
completed: 2026-06-12
---

# Phase 122 Plan 10: Test Regression Fix - bar_history Guard Summary

**4 TestBuildLedgerEntries and TestBuildLedgerEntriesFeatureTs regressions fixed by passing mock bar_history deque to _build_ledger_entries calls**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-12T17:20:47Z
- **Completed:** 2026-06-12T17:24:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Added `_make_bar()` staticmethod to both test classes returning a minimal OHLCV bar dict in a deque
- Updated 4 failing tests to pass `bar_history=self._make_bar()` kwarg so the Plan 06 `last_bar=None` guard does not trigger
- `test_empty_result_returns_empty_list` intentionally left unchanged (tests empty `all_ranked=[]` path, not the bar guard)
- All 5 tests in the two classes now pass (4 previously failing + 1 that was already passing)

## Task Commits

1. **Task 1: Update TestBuildLedgerEntries and TestBuildLedgerEntriesFeatureTs to pass mock bar_history** - `bc787468` (fix)

## Files Created/Modified

- `tests/unit/scripts/test_run_historical_pipeline.py` - Added `_make_bar()` staticmethod to TestBuildLedgerEntries and TestBuildLedgerEntriesFeatureTs; updated 4 tests to pass bar_history kwarg

## Decisions Made

None - followed plan as specified.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hook could not find ruff/black because the worktree's `REPO_ROOT` resolves to the worktree directory (not main repo), and no `.venv` existed there. Fixed by creating a symlink: `.claude/worktrees/agent-aa0fb2fa94a9971f1/.venv -> /home/bg/dev/indicagent/.venv`. This is a standard worktree setup issue, not a code problem.

Note: 5 pre-existing test failures remain in `test_run_historical_pipeline.py` (test_insert_signals_sync_writes_cis_fields, test_replay_worker_calls_*, TestCISColumnsInSQL tests). These are out of scope for this plan and were present before any changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 4 target test regressions resolved
- Plan 06 `last_bar=None` guard is intact and correct
- The 5 pre-existing failures in the file are addressed by other plans in wave 1 (plans 08/09)

---
*Phase: 122-production-hardening*
*Completed: 2026-06-12*
