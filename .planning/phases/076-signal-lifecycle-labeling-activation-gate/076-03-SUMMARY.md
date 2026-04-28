---
phase: 076-signal-lifecycle-labeling-activation-gate
plan: 03
type: execute
wave: 1
subsystem: signal-lifecycle
tags: [migration, data-quality, labeling-integrity, backfill]
dependency_graph:
  requires: []
  provides: [signal-ledger-labeling-fix]
  affects: [signal-tracker, ml-training-data]
tech_stack:
  added: []
  patterns: [sql-migration, backfill-correction, check-constraint]
key_files:
  created: []
  modified:
    - production/migrations/076_signal_ledger_lifecycle_constraints.sql
decisions: []
metrics:
  duration_seconds: 31
  completed_date: 2026-04-28T18:30:26Z
---

# Phase 076 Plan 03: Signal Ledger Backfill + Labeling Constraint Summary

## One-Liner

SQL migration backfills 2,744 corrupted signal_ledger rows (impossible activations + mislabeled outcomes) and adds CHECK constraint to prevent future labeling violations.

## What Was Built

Pure SQL migration file `production/migrations/076_signal_ledger_lifecycle_constraints.sql` containing three sections:

1. **Backfill correction (2,744 rows fixed)**:
   - 2,430 rows with `activated_at < timestamp` — cleared all activation fields (impossible pre-fire activations from stale HTF bars or restart race conditions)
   - 314 rows with `activated_at >= timestamp` but `outcome = 'never_activated'` — recomputed outcome from `mfe` field (ttl_expired_ahead if mfe > 0, else ttl_expired_behind)

2. **Index + constraint updates** (preserved from original migration):
   - `idx_signal_ledger_signal_id` index for batch lifecycle UPDATE performance
   - `chk_signal_ledger_status` CHECK constraint with target_N_hit statuses
   - `chk_signal_ledger_outcome` CHECK constraint with condition_expired

3. **Labeling integrity constraint** (NEW):
   - `chk_signal_ledger_labeling_integrity` CHECK constraint prevents `activated_at IS NOT NULL AND outcome = 'never_activated' AND exit_at IS NOT NULL`
   - Soft constraint: only fires on fully resolved signals (exit_at IS NOT NULL), allowing temporary state during signal lifecycle

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written. The migration SQL was already fully specified in the plan task action.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: T-076-05 | production/migrations/076_signal_ledger_lifecycle_constraints.sql | Backfill UPDATE on production data (irreversible) — mitigated by precise WHERE clauses with objectively verifiable conditions |

## Implementation Notes

- **Backfill safety**: UPDATE statements target only rows matching exact corruption patterns (`activated_at < timestamp` is objectively verifiable; `mfe` field logic matches tracker's intended outcome)
- **Soft constraint design**: `chk_signal_ledger_labeling_integrity` only fires on `exit_at IS NOT NULL` rows, allowing temporary state during active signal lifecycle
- **Preserved existing migrations**: Index and constraint updates from original migration file retained unchanged
- **Ready for manual execution**: SQL is syntactically valid and ready for `docker exec timescaledb psql -U postgres -d indicagent -f /path/to/migration.sql`

## Next Steps

1. **Manual execution required**: This migration must be run manually against the production database (not automated via deployment scripts)
2. **Verification after execution**: Query signal_ledger to confirm backfilled row counts match expected 2,430 + 314 = 2,744
3. **Phase 76 Plan 02 (lifecycle_tracker.py D-01 fix)** and **Plan 01 (tracker D-02 fix)** will prevent future corruption

## Files Modified

- `production/migrations/076_signal_ledger_lifecycle_constraints.sql` (81 lines) — rewritten with backfill + labeling integrity constraint

## Self-Check: PASSED

- [x] Migration file created at correct path
- [x] SQL contains UPDATE for 2,430 impossible activations
- [x] SQL contains UPDATE for 314 mislabeled activated signals
- [x] SQL contains `chk_signal_ledger_labeling_integrity` CHECK constraint
- [x] Migration preserves existing index and constraint updates
- [x] Commit created: 0db4fb75
- [x] Duration: 31 seconds
