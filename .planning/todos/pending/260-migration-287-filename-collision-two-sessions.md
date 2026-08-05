---
status: pending
priority: P3
found_during: phase-151-wave-4
found_date: 2026-08-05
---

# production/migrations/287_*.sql: two files share migration number 287

## What

Two unrelated, independently-authored migration files both landed on `main` using the number
287:
- `production/migrations/287_calendar_velocity_atomics.sql` (Phase 151 Plan 01, commit `9e8605a0`)
- `production/migrations/287_single_name_equity_expansion.sql` (unrelated concurrent session,
  commit `301d8225`, equity universe 80->111 instruments)

`tests/unit/test_migration_number_uniqueness.py::test_no_new_migration_number_collisions` now
fails on this pair and will keep failing until one is renumbered.

## Root cause

Two concurrent GSD/interactive sessions both picked "287" as the next-free migration number at
roughly the same time (both had `ls production/migrations/ | sort -n | tail` return 286 as the
last number at the moment they checked), then committed independently to the shared `main`
branch without either session seeing the other's in-flight work.

## Impact

Cosmetic/ordering only, confirmed via live DB check 2026-08-05: both migrations already applied
successfully and independently (`feature_registry` has the expected 33 Phase-151 rows;
`instruments` has the new single-name equity symbols e.g. CVX/XOM/SLB). No data corruption, no
functional conflict -- migrations are applied by full filename via `psql -f`, not by the leading
number alone, so both ran fine as separate scripts. The only breakage is
`test_no_new_migration_number_collisions`, which exists purely to keep the numbering sequence
human-readable/ordered.

## Recommended fix

Renumber one of the two files to the next genuinely-free number (check
`ls production/migrations/ | sort -n | tail` fresh) and update any internal self-references
(header comments, `config_history` `changed_by` values already written for the renumbered one
would need a corresponding `UPDATE`, matching the pattern Phase 151 Plan 01's own SUMMARY.md
documents for its own 259->287 renumbering). Whichever session is still active should do this
for its own file rather than a third party touching either.

## Deliberately not fixed here

Not this session's file to rename -- `287_single_name_equity_expansion.sql` belongs to a
different, concurrently-active session. Renaming it unilaterally risks conflicting with that
session's own in-flight work/notes referencing the filename.
