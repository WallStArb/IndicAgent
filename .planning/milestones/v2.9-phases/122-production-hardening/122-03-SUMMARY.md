---
phase: 122-production-hardening
plan: "03"
subsystem: database
tags: [timescaledb, postgresql, jsonb, migration, intelligence_features, i2]

# Dependency graph
requires:
  - phase: 122-production-hardening-01
    provides: I2Events schema fix (strict field set) — new column stores exactly these fields
provides:
  - "production/migrations/124_add_i2_column.sql — i2 JSONB column on intelligence_features, applied to DB"
  - "Clean column boundary: i2 holds I2 tier data, market_context holds cross_asset only"
affects:
  - 122-04  # feature_writer deploy reads/writes new i2 column
  - feature_replay  # populates i2 for historical rows on next run

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "JSONB column separation: one column per tier, disjoint semantics enforced at migration time"
    - "Online DDL ADD COLUMN with IF NOT EXISTS guard for idempotent migrations"
    - "JSONB subtraction operator (- 'key') for selective field extraction during backfill"

key-files:
  created:
    - production/migrations/124_add_i2_column.sql
  modified: []

key-decisions:
  - "ADD COLUMN IF NOT EXISTS guard because migration 013 made a prior attempt — prevents failure on duplicate application"
  - "Backfill uses JSONB subtraction (market_context - 'cross_asset') — cross_asset is the only non-I2 nested object"
  - "UPDATE 0 rows on empty table is expected and correct — backfill populates on next feature_replay.py run"
  - "No COMMIT/BEGIN in migration file — transaction managed by migration runner"

patterns-established:
  - "Migration style: header block with date, description, note, backfill note, rollout order comment"

requirements-completed:
  - I2-PERSIST-03

# Metrics
duration: 2min
completed: 2026-06-12
---

# Phase 122 Plan 03: I2 Column Migration Summary

**Migration 124 adds dedicated i2 JSONB column to intelligence_features with IF NOT EXISTS guard, JSONB subtraction backfill, and market_context cleanup to cross_asset only**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-06-12T18:54:36Z
- **Completed:** 2026-06-12T18:55:19Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `production/migrations/124_add_i2_column.sql` with three SQL statements in correct order
- Applied migration to DB: `i2 JSONB NOT NULL DEFAULT '{}'::jsonb` column confirmed present on `intelligence_features`
- UPDATE 0 rows on both backfill and cleanup statements — expected, table is empty; correct baseline for next replay

## Task Commits

1. **Task 1: Create migration 124 — add i2 column, backfill, clean market_context** - `03797f0f` (feat)

## Files Created/Modified

- `production/migrations/124_add_i2_column.sql` - Three-statement migration: ADD COLUMN i2, backfill from market_context minus cross_asset, clean market_context to cross_asset only

## Decisions Made

- IF NOT EXISTS guard used because migration 013 made a prior ADD COLUMN attempt on another instance
- No COMMIT/BEGIN included — transaction is managed by the migration runner
- UPDATE 0 on empty table is correct — historical rows will be populated on next `feature_replay.py` run

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. DB connection clean, migration applied without errors. UPDATE 0 is the expected result given the table was truncated before this phase as documented in the parallel execution context.

## User Setup Required

None - migration was applied directly as part of this plan execution.

## Next Phase Readiness

- `intelligence_features.i2` column exists and is ready for Plan 04 (feature_writer deploy)
- Column defaults to `'{}'` so any in-flight write during the deploy window is correct (no null risk)
- Rollout order: migration (this plan) → feature_writer deploy (Plan 04) → intelligence_pipeline restart (Plan 01)

---
*Phase: 122-production-hardening*
*Completed: 2026-06-12*
