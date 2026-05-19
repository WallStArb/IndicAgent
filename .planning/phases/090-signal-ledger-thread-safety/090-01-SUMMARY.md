---
phase: 090-signal-ledger-thread-safety
plan: "01"
subsystem: persistence
tags: [signal-ledger, refactor, named-params, test-guard, fleet-alignment]
dependency_graph:
  requires: []
  provides: [LedgerEntry._to_row, dynamic-tuple-count-guard]
  affects: [signal_ledger_repository, test_signal_ledger_repository, test_pipeline_attribution]
tech_stack:
  added: []
  patterns: [named-field-tuple-helper, dynamic-sql-param-count-guard]
key_files:
  modified:
    - src/persistence/repository/signal_ledger_repository.py
    - tests/unit/test_signal_ledger_repository.py
    - tests/unit/test_pipeline_attribution.py
    - tests/unit/intelligence/test_signal_ledger.py
decisions:
  - "Renamed to_insert_params to _to_row (module-private) matching fleet convention from feature_writer_agent.py"
  - "Corrected docstring from 65-element to 67-element; SQL is the authority verified dynamically"
  - "Auto-fixed tests/unit/intelligence/test_signal_ledger.py (Rule 1) as all .to_insert_params() calls there broke after rename"
metrics:
  duration_minutes: 4
  completed: "2026-05-19T16:50:27Z"
  tasks_completed: 2
  files_modified: 4
---

# Phase 090 Plan 01: LedgerEntry _to_row Refactor Summary

**One-liner:** Renamed `to_insert_params()` to `_to_row()` with 67 per-position `# $N field_name` annotations, 5 lifecycle UPDATE call sites annotated, and a self-maintaining dynamic tuple-count guard test added.

## What Was Done

### Task 1: Rename + Annotate + Update Call Sites

**File:** `src/persistence/repository/signal_ledger_repository.py`

Renamed `LedgerEntry.to_insert_params(self) -> tuple` to `LedgerEntry._to_row(self) -> tuple`.

**Docstring (exact wording):**
> Return a 67-element tuple of INSERT parameters for _INSERT_SQL.
>
> JSONB columns (targets, supporting_factors, market_context, bucket_scores, trailing_stop_price, features_snapshot) are passed as Python dicts/lists; asyncpg serializes them to jsonb natively via codec.

**Field count:** `_to_row()` returns 67 elements. `re.findall(r'\$\d+', _INSERT_SQL)` returns 67 tokens. Both counts match (verified at runtime).

**Docstring correction:** Original docstring said "65-element tuple" — stale since `is_backfill` ($66) and `ttl_bars` ($67) were added. Corrected to 67.

**Per-position annotations:** All 67 return elements carry `# $N field_name` inline comments matching the fleet style from `feature_writer_agent.py` lines 171-203. Example:
```python
self.signal_id,  # $1 signal_id
self.targets,    # $10::jsonb targets
self.co_fire_partners,  # $64::text[] co_fire_partners
```

**Repository call sites updated:**
- `insert_signals()` line ~555: `entry.to_insert_params()` → `entry._to_row()`
- `insert_signals_with_features()` line ~568: `*entry.to_insert_params()` → `*entry._to_row()`

**Lifecycle UPDATE call sites (5 sites, LEDGER-02):**
All five methods annotated with `# $N field_name` comments per arg:
1. `update_signal_status()` — 17 args matching `_UPDATE_STATUS_SQL ($1..$17)`
2. `record_activation()` — 5 args matching `_RECORD_ACTIVATION_SQL ($1..$5)`
3. `record_zone_resolution()` — 12 args matching `_RECORD_ZONE_RESOLUTION_SQL ($1..$12)`
4. `record_market_resolution()` — 10 args matching `_RECORD_MARKET_RESOLUTION_SQL ($1..$10)`
5. `record_zone_resolution_with_activation()` — 16 args matching `_RECORD_ZONE_WITH_ACTIVATION_SQL ($1..$16)`

Total lifecycle annotated kwargs: 55 (verified with grep -cP pattern).

### Task 2: Guard Test + Test Call Site Updates

**New test:** `tests/unit/test_signal_ledger_repository.py::test_to_row_returns_correct_count`
- Uses `re.findall(r"\$\d+", _INSERT_SQL)` to get `sql_param_count` dynamically
- Asserts `isinstance(entry._to_row(), tuple)` and `len(entry._to_row()) == sql_param_count`
- No hardcoded count — self-maintaining as columns are added

**Updated:** `tests/unit/test_pipeline_attribution.py::TestAttributionInvariant::test_attribution_fields_on_ledger_entry`
- `entry.to_insert_params()` → `entry._to_row()`
- `assert len(params) == 67` → dynamic `sql_param_count = len(re.findall(...))` pattern
- Positional assertions `params[58]` and `params[59]` preserved unchanged

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated tests/unit/intelligence/test_signal_ledger.py**
- **Found during:** Task 2 verification (`grep -rn "to_insert_params" tests/`)
- **Issue:** 20 call sites in that file still used `entry.to_insert_params()` after the rename — all tests would fail at runtime
- **Fix:** Renamed all `.to_insert_params()` → `._to_row()` calls; ran black to normalize formatting
- **Files modified:** `tests/unit/intelligence/test_signal_ledger.py`
- **Commit:** `844f51a6`

**2. [Rule 3 - Blocking] Created .venv symlink in worktree**
- **Found during:** First commit attempt
- **Issue:** Pre-commit hook looks for `${REPO_ROOT}/.venv/bin/ruff` but worktree has no `.venv`
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a404f64b0017eac1c/.venv`
- **Impact:** Worktree-local; no source files affected

## Confirmation

- `grep -rn "to_insert_params" src/ services/ tests/` — ZERO hits (excluding `_record_to_insert_params` in feature_writer_agent which is a different function)
- Test names added: `test_to_row_returns_correct_count` (PASS)
- All 9 tests in `test_signal_ledger_repository.py` + `test_pipeline_attribution.py` PASS
- All 55 tests across all three affected test files PASS
- ruff + black clean on all 4 modified files

## Self-Check

All task commits exist:
- `3480e7d6` refactor(090-01): rename to_insert_params to _to_row with full field annotations
- `844f51a6` test(090-01): add dynamic tuple-count guard test and update all call sites

## Self-Check: PASSED
