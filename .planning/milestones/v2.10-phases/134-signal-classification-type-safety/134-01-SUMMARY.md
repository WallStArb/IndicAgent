---
phase: 134-signal-classification-type-safety
plan: 01
subsystem: signal-lifecycle
tags: [signal-outcome, trade-executions, lifecycle-replay, type-safety, migration]
dependency_graph:
  requires: []
  provides:
    - trade_executions.outcome column (TEXT, 9-value CHECK, partial index)
    - SignalOutcome.CONDITION_EXPIRED enum member (9th value)
    - lifecycle_replay zone_exit + market_exit + reconcile write outcome
    - signal_events_repository.record_execution forwards outcome
    - backfill 955,533 rows (894,759 migration + 60,774 replay catch-up)
  affects:
    - production/migrations/149_phase134_outcome_column.sql
    - src/intelligence/trading/signal_outcome.py
    - production/scripts/lifecycle_replay.py
    - src/persistence/repository/signal_events_repository.py
tech_stack:
  added: []
  patterns:
    - Backfill SQL mirrors _classify_stop_outcome() exactly — no drift possible
    - outcome normalization in record_execution via hasattr('value') pattern
key_files:
  created:
    - production/migrations/149_phase134_outcome_column.sql
    - tests/unit/intelligence/trading/test_outcome_persistence.py
  modified:
    - src/intelligence/trading/signal_outcome.py
    - production/scripts/lifecycle_replay.py
    - src/persistence/repository/signal_events_repository.py
    - tests/unit/intelligence/test_signal_outcome.py
decisions:
  - CONDITION_EXPIRED grouped into TTL_OUTCOMES (time/condition exit semantics, not stop)
  - Backfill in migration 149 runs BEFORE the CHECK constraint to avoid scan cost
  - record_execution outcome param is str | None; enum normalization via hasattr('value')
  - _reconcile_outcomes synthetic ttl_expired rows use 'ttl_expired_behind' (pnl_r=0 => never ahead)
metrics:
  duration: 16 minutes
  completed: "2026-06-18"
  tasks_completed: 4
  files_modified: 6
  rows_backfilled: 955533
---

# Phase 134 Plan 01: Persist SignalOutcome to trade_executions.outcome Summary

Wired the 9-class SignalOutcome taxonomy to `trade_executions.outcome`, eliminating re-derivation and fixing the live-writer rejection risk for `condition_expired` exits.

## What Was Built

### Task 1: CONDITION_EXPIRED + Migration 149

Added `CONDITION_EXPIRED = "condition_expired"` as the 9th `SignalOutcome` member (grouped into `TTL_OUTCOMES`). This resolved the lifecycle_tracker.py:379 path that emits `outcome="condition_expired"` as a verbatim string — previously unrepresented in the 8-value enum, which would have caused CHECK constraint rejection on any live write.

Migration 149 applied:
- `ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS outcome TEXT`
- `ADD CONSTRAINT chk_te_outcome CHECK (outcome IS NULL OR outcome IN (...9 values...))`
- `CREATE INDEX idx_trade_executions_outcome ON trade_executions(outcome) WHERE outcome IS NOT NULL`
- Backfill UPDATE replicating `_classify_stop_outcome()` exactly — 894,759 rows populated

**Constraint timing insight:** CHECK added BEFORE backfill. Column is all-NULL at constraint creation, so validation is instant. Constraint then enforces correctness on the backfill write itself.

### Task 2: Both Write Paths Wired

**lifecycle_replay `_flush_writes`:**
- Zone exit INSERT: added `outcome` column (`$10`) using `_enum_value(data.get("outcome"))`
- Market track INSERT: added `outcome` column (`$14`) reusing `m_outcome`
- `_reconcile_outcomes` synthetic INSERT: added `outcome='ttl_expired_behind'` (pnl_r=0.0 means never moved ahead)

**signal_events_repository:**
- `_INSERT_TRADE_EXECUTIONS_SQL`: added `outcome` to column list and `$15` to VALUES
- `record_execution()`: new `outcome: str | None = None` param, normalized via `hasattr('value')` to handle both SignalOutcome enum and plain str callers

**Verified:** GBPUSD 1m replay 2026-06-17+ shows 0 NULL outcomes; exit_reason→outcome mapping correct (stop_loss→stopped_at_entry/in_trade, target_1→target_1, etc.)

### Task 3: Historical Backfill

Backfill embedded in migration 149 and verified:
- Initial migration: 894,759 rows backfilled
- Post-replay catch-up (rows written by pre-patch lifecycle_replay.py): 60,774 rows
- Final state: 0 NULL outcomes in `trade_executions` (955,533 total rows populated)

Distribution: ttl_expired_behind=444,296 | stopped_in_trade=184,226 | ttl_expired_ahead=147,804 | stopped_at_entry=122,606 | target_1=56,527 | never_activated=308

### Task 4: Unit Tests

34 tests in `test_outcome_persistence.py`:
- `TestClassifyStopOutcomeMfeThreshold` (4 tests) — boundary at mfe=0.05
- `TestClassifyStopOutcomeBarsThreshold` (3 tests) — boundary at bars=2
- `TestClassifyStopOutcomeNoneBars` (2 tests) — None bars = entry stop
- `TestConditionExpiredIsValidOutcome` (6 tests) — 9th enum member, TTL_OUTCOMES group, backfill non-remapping
- `TestBackfillSqlCoverage` (19 parametrized + 1) — full CASE coverage

Updated `test_signal_outcome.py` — renamed `_has_8_members` to `_has_9_members`; updated `_contains_2_members` to 3 for TTL_OUTCOMES.

Full suite: **4,849 passed, 37 skipped, 0 failed**.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Reconcile path needs outcome**
- Found during: Task 2
- Issue: `_reconcile_outcomes()` synthetic INSERT lacked `outcome` column
- Fix: Added `outcome='ttl_expired_behind'` to params and INSERT (pnl_r=0.0 logic)
- Files modified: production/scripts/lifecycle_replay.py
- Commit: cada6617

**2. [Rule 1 - Bug] Pre-existing tests expected 8-member enum and 2-member TTL_OUTCOMES**
- Found during: Task 4
- Issue: `test_signal_outcome_has_8_members` and `test_ttl_outcomes_contains_2_members` failed after adding CONDITION_EXPIRED
- Fix: Updated test assertions to 9 and 3 respectively
- Files modified: tests/unit/intelligence/test_signal_outcome.py
- Commit: 2473950e

**3. [Rule 1 - Bug] 60,774 rows acquired NULL outcome from pre-patch replay run**
- Found during: Task 3 verification
- Issue: Replay ran from main repo (unpatched) between migration 149 and worktree replay verification
- Fix: Re-ran backfill SQL UPDATE directly against DB; 60,774 rows updated
- Not a code bug — backfill was already in migration; just needed re-run for rows written post-migration

### Operational note

Worktree isolation means the lifecycle_replay.py changes are only in the worktree. Any direct `cd /home/bg/dev/indicagent && python production/scripts/lifecycle_replay.py` invocation uses the main repo's unpatched version. Always use the absolute worktree path when testing worktree changes.

## Commits

| Commit | Message | Files |
|--------|---------|-------|
| 6af11108 | feat(134-01): add CONDITION_EXPIRED to SignalOutcome + migration 149 | signal_outcome.py, 149_phase134_outcome_column.sql |
| cada6617 | feat(134-01): wire outcome to both write paths | lifecycle_replay.py, signal_events_repository.py |
| 2473950e | test(134-01): 34 outcome persistence tests + update 8-member assertions to 9 | test_outcome_persistence.py, test_signal_outcome.py |

## Self-Check: PASSED

Files exist:
- production/migrations/149_phase134_outcome_column.sql: FOUND
- tests/unit/intelligence/trading/test_outcome_persistence.py: FOUND
- src/intelligence/trading/signal_outcome.py (modified): FOUND

Commits exist:
- 6af11108: FOUND
- cada6617: FOUND
- 2473950e: FOUND

DB state:
- `SELECT COUNT(*) FROM trade_executions WHERE outcome IS NULL` = 0: VERIFIED
- `SELECT DISTINCT outcome FROM trade_executions` = 6 valid SignalOutcome values: VERIFIED
- `len(SignalOutcome) == 9 and CONDITION_EXPIRED present`: VERIFIED
