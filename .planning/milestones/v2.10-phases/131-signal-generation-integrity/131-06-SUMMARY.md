---
plan: 131-06
phase: 131
subsystem: backfill-integrity
tags: [b6-fix, integrity-check, batching, robustness]
dependency_graph:
  requires: [131-03, 131-04]
  provides: [batched-integrity-check, correct-rebuild-status-semantics]
  affects: [production/scripts/run_historical_pipeline.py]
tech_stack:
  added: []
  patterns: [per-symbol-batching, audit-vs-data-separation]
key_files:
  modified:
    - production/scripts/run_historical_pipeline.py
decisions:
  - "Audit infrastructure failure exits 0; only actual invariant violations trigger sys.exit(1)"
  - "Per-symbol batching eliminates full-table-scan OOM at 100+ symbol / 1M+ row scale"
  - "query_errors list accumulates audit failures; reported as WARNING at end, not FAILED"
metrics:
  duration: "~12 minutes"
  completed: "2026-06-17"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 131 Plan 06: Batched Integrity Check + REBUILD_STATUS Semantics Fix Summary

Per-symbol batching of `_assert_backfill_integrity()` eliminates full-table-scan OOM and separates audit infrastructure failures from actual data integrity violations.

## What Was Built

Fixed B6: the `_assert_backfill_integrity()` function previously used a single `ANY(%s)` query across all symbols, causing timeouts/OOM at large corpus sizes, and any crash in the post-commit block incorrectly set the corpus status to FAILED even when all data was written correctly.

### EXPLAIN ANALYZE Diagnosis

Ran `EXPLAIN ANALYZE` on the was_selected invariant query with 2 symbols (`ESM6`, `NQM6`). At 537K rows and 106 active symbols, the query uses parallel workers (7) but still performs a full-table-scan approach. At 1M rows across 106 symbols this will timeout or OOM.

### Changes to `_assert_backfill_integrity()`

**Before:**
- Single `ANY(%s)` query passing all symbols at once for both invariant checks
- Any exception in the function (including OperationalError from PG timeout) would bubble up to the caller, leaving the corpus at FAILED
- No distinction between "audit query crashed" and "data is actually wrong"

**After:**
- Per-symbol loop for Invariant 1 (was_selected uniqueness) with per-symbol try/except
- Per-symbol loop for Invariant 2 (signal_id uniqueness) with per-symbol try/except
- Query errors log `[B6] integrity check for {sym} failed (query error)` and skip that symbol
- `all_violations` list accumulates actual violations across all symbols
- `sys.exit(1)` only fires inside `if all_violations:` or `if total_dup_count:` branches
- `query_errors` accumulates audit failures; if any errors but no violations, logs `[INTEGRITY WARN]` and exits 0
- `[INTEGRITY PASS]` message reports count of symbols checked

### REBUILD_STATUS Semantics

Confirmed via grep that no `REBUILD_STATUS` variable exists in `run_historical_pipeline.py`. The exit code is the only signal:
- `sys.exit(1)` = actual data invariant violated (wipe and investigate)
- exit 0 (default) = data is intact or audit could not complete (re-run audit manually)

This means a post-commit `OperationalError` in the audit query no longer masquerades as a data integrity failure, which was the root cause of the Phase 127 rebuild stopping at 537K instead of ~1M signals.

## Deviations from Plan

None - plan executed exactly as written.

## Verification

All acceptance criteria met:

```
grep -n "for sym in symbols:" production/scripts/run_historical_pipeline.py
# Returns: 1878 and 1913 (both invariant loops)

grep -n "query error\|audit infrastructure" production/scripts/run_historical_pipeline.py
# Returns: 6 matches covering per-symbol error messages and docstring

grep -n "INTEGRITY PASS" production/scripts/run_historical_pipeline.py
# Returns: 1948 (pass message with symbol count)

grep -n "sys.exit(1)" production/scripts/run_historical_pipeline.py
# Lines 1908 (if all_violations:) and 1937 (if total_dup_count:) only
# Line 2132 is in argument validation (--warmup requires --replay-only), unrelated

pytest tests/unit/ -q
# 4759 passed, 37 skipped
```

## Self-Check: PASSED

- `/home/bg/dev/indicagent/.claude/worktrees/agent-a3878807c9fd1ef81/production/scripts/run_historical_pipeline.py` - modified and committed
- Commit hash: 12e22ff1
