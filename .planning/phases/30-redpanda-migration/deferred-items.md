# Phase 30 Deferred Items

## Pre-existing test failure (out of scope)

**File:** `tests/unit/scripts/test_validate_equity_backfill.py::TestValidateEquityBackfill::test_zero_count_exits_zero`
**Status:** Failing before Phase 30 began (confirmed by git stash test)
**Details:** `validate_symbol()` returns 1 when `count=0`, but test expects 0. Pre-existing regression from commit `0c94bee`.
**Owner:** Separate investigation needed; not caused by Redpanda migration work.
