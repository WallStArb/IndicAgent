---
phase: 124-signal-universe-integrity-cold-start-hardening
plan: "01"
subsystem: database
tags: [timescaledb, migration, feature-writer, ctf, cold-start, warmup]

# Dependency graph
requires:
  - phase: 123-ecl-boundary-restoration
    provides: Phase 123 None-vs-0.0 semantics (None=cold-start, 0.0=genuine neutral); _nullable_float() pattern

provides:
  - migration 130: 4 CTF columns (ctf_score, ctf_trend_alignment, ctf_structure_alignment, ctf_regime_agreement) as top-level double precision on intelligence_features
  - feature_writer ON CONFLICT IS NULL guard: only overwrites cold-start NULL, preserves genuine 0.0
  - CTF readers migrated from JSONB to top-level columns (training_data.py, embedding.py)
  - --warmup flag on run_historical_pipeline.py for two-pass cold-start correction

affects:
  - Phase 125 (APR migration) - feature_writer now has updated param tuple ($37 elements)
  - Phase 126 (Clean Replay) - --warmup flag enables cold-start-corrected replay
  - Phase 127-129 (3-table architecture) - ctf_score now top-level column, not JSONB
  - ML training (training_data.py reads f.ctf_score directly)
  - Agent memory (embedding.py reads ctf_score without ctf_composite fallback)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "IS NULL-only ON CONFLICT guard: WHERE intelligence_features.ctf_score IS NULL (never IS NULL OR = 0.0)"
    - "NULLIF backfill: NULLIF(jsonb->>'key', '')::double precision handles null/missing/empty-string"
    - "Two-pass warmup: skip_signals=True (I1-I6) then False (I1-I7) for cold-start correction"

key-files:
  created:
    - production/migrations/130_promote_ctf_columns.sql
    - tests/unit/test_124_ctf_column_promotion.py
  modified:
    - services/feature_writer.py
    - src/core/ml/training_data.py
    - src/core/memory/embedding.py
    - production/scripts/run_historical_pipeline.py

key-decisions:
  - "ON CONFLICT guard is WHERE ctf_score IS NULL only - never IS NULL OR = 0.0 (Phase 123 semantics)"
  - "NULLIF pattern for backfill: empty string -> NULL, numeric string -> float, missing key -> skipped (WHERE ? guard)"
  - "--warmup restricted to --workers 1 only; parallel mode logs warning (ProcessPoolExecutor workers have separate state)"
  - "ctf_composite fallback alias removed from embedding.py - top-level columns are single source of truth"
  - "--warmup requires --replay-only validation to prevent fetch/warmup race condition"

patterns-established:
  - "IS NULL guard pattern for ON CONFLICT fills: DO UPDATE SET col = EXCLUDED.col WHERE table.col IS NULL"

# Metrics
duration: 25min
completed: 2026-06-14
---

# Phase 124 Plan 01: CTF Column Promotion + Cold-Start Guard + Warmup Flag Summary

**4 CTF sub-scores promoted from JSONB to top-level double precision columns with IS NULL-only ON CONFLICT guard and two-pass --warmup flag for cold-start correction**

## Performance

- **Duration:** 25 min
- **Started:** 2026-06-14T20:50:00Z
- **Completed:** 2026-06-14T21:15:00Z
- **Tasks:** 5
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments

- Migration 130 adds 4 nullable CTF columns, backfills from JSONB with NULLIF guard, strips JSONB keys for single source of truth
- feature_writer ON CONFLICT changed from DO NOTHING to DO UPDATE SET with WHERE ctf_score IS NULL guard - genuine 0.0 neutral readings are never overwritten (Phase 123 semantics)
- training_data.py migrated from JSONB extraction to f.ctf_score top-level column reads; ctf_structure_alignment added (was missing)
- embedding.py ctf_composite fallback alias removed; direct ctf_score read only
- run_historical_pipeline.py --warmup flag orchestrates two-pass replay: I1-I6 warmup (skip_signals=True), then I1-I7 signal pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Create migration 130** - `e2036745` (feat)
2. **Task 2: Wire CTF columns in feature_writer** - `867ee7f4` (feat)
3. **Task 3: Migrate CTF readers from JSONB** - `cf4b63ec` (feat)
4. **Task 4: Add --warmup flag** - `651cc5ef` (feat)
5. **Task 5: Unit tests** - `f1222f64` (test)

## Files Created/Modified

- `production/migrations/130_promote_ctf_columns.sql` - 3-statement migration: ADD COLUMN, backfill with NULLIF, JSONB strip
- `services/feature_writer.py` - INSERT extended to $37 params; ON CONFLICT DO UPDATE WHERE ctf_score IS NULL
- `src/core/ml/training_data.py` - f.ctf_score instead of JSONB extraction; ctf_structure_alignment added
- `src/core/memory/embedding.py` - ctf_composite fallback removed; direct ctf_score read
- `production/scripts/run_historical_pipeline.py` - --warmup flag with validation and two-pass orchestration
- `tests/unit/test_124_ctf_column_promotion.py` - 3 unit tests (all passing)

## Decisions Made

- ON CONFLICT guard uses WHERE ctf_score IS NULL only - the IS NULL OR = 0.0 antipattern would corrupt ML training data by overwriting genuine neutral readings
- --warmup restricted to --workers 1 only because ProcessPoolExecutor workers run in separate processes with isolated state; the warmup cache built in one process is not visible to worker processes
- --warmup requires --replay-only to prevent race condition between IBKR fetch and warmup pass building the I6 cache
- ctf_composite fallback alias removed from embedding.py because ctf_composite is not in any schema and the top-level column is the canonical source after migration 130

## Deviations from Plan

None - plan executed exactly as written.

The pre-execution check (ps aux | grep lifecycle_replay) was not needed in this context as the migration file is created for later application; the check is documented in the migration file header.

## Issues Encountered

- Worktree .venv symlink: pre-commit hooks look for `.venv/bin/ruff` via `git rev-parse --show-toplevel` which returns the worktree path, not the main repo. Fixed by symlinking `/home/bg/dev/indicagent/.venv` into the worktree. All files passed ruff/black clean.
- `src/core/memory/embedding.py` is gitignored by the `memory/` pattern in .gitignore but is already tracked. Used `git add -f` for the tracked file (idiomatic for this situation).

## User Setup Required

None - no external service configuration required.

Migration 130 must be applied before deploying updated feature_writer and before intelligence_pipeline restart. The DDL (ADD COLUMN) is safe against a live table. The backfill UPDATE should be applied after lifecycle_replay.py completes.

## Next Phase Readiness

- Phase 124 Plan 02 can proceed: signal universe fix (5 over-firing plugins)
- Migration 130 is ready to apply once lifecycle_replay.py completes (see pre-execution check in migration header)
- --warmup flag ready for Phase 126 (Clean Replay) to produce cold-start-corrected signal corpus

---
*Phase: 124-signal-universe-integrity-cold-start-hardening*
*Completed: 2026-06-14*
