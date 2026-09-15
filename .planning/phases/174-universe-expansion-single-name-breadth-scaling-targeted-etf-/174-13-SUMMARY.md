---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 13
subsystem: database
tags: [postgresql, config, instrument-governance, apr-adjacent, structlog]

# Dependency graph
requires:
  - phase: 174-02
    provides: "instruments.compute_eligible / instruments.live_tradeable columns (migration 337), COMPUTE_READY_PREDICATE_SQL"
  - phase: 174-06
    provides: "get_active_contracts(dimension=) with per-dimension cache dict and dimension-scoped error-path fallback"
provides:
  - "instruments.compute_eligible_1d boolean NOT NULL DEFAULT false, plus a measured backfill for existing rows (migration 341)"
  - "COMPUTE_READY_1D_PREDICATE_SQL beside COMPUTE_READY_PREDICATE_SQL in scripts/analysis/instrument_compute_eligibility_audit.py"
  - "get_active_contracts(dimension='compute_1d') -- fourth eligibility dimension, sibling of 'compute' not a narrowing of it"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Independent (not narrowing) eligibility dimension sitting beside an existing one in the same module-owned clause dict -- compute_1d omits compute_eligible entirely rather than AND-ing it in, so a 1d-only symbol and a four-timeframe symbol can both carry compute_eligible_1d=true without one implying the other"
    - "Clause-driven test fixtures: a test evaluates the real _ACTIVE_CONTRACTS_DIMENSION_CLAUSES text against a flag dict via a small AND-clause interpreter, rather than hardcoding expected membership, so the test fails if a future edit changes which columns any clause reads"

key-files:
  created: []
  modified:
    - production/migrations/341_instruments_compute_eligible_1d.sql
    - scripts/analysis/instrument_compute_eligibility_audit.py
    - src/config/settings.py
    - tests/unit/config/test_settings_active_contracts_dimension.py

key-decisions:
  - "compute_eligible_1d DEFAULT false, the opposite of migration 337's compute_eligible DEFAULT true -- 337 retrofitted a column onto an already-uniformly-ready universe, so true was the measured truth; compute_eligible_1d is forward-looking for a cohort (D-09 down-cap) that does not exist in the table yet, so false is the honest default for any future row"
  - "compute_1d clause is a SIBLING of compute, not a narrowing -- deliberately omits compute_eligible = true so a four-timeframe symbol appears in both compute and compute_1d (a 1d cross-sectional cell should see the full 1d-capable universe), while a 1d-only symbol appears only in compute_1d and backfill"
  - "Backfill UPDATE promoted 231 rows, measured via SELECT immediately before writing the migration and matched on apply -- identical to the pre-existing is_active=true AND compute_eligible=true count at the same point in time, confirming every currently-active symbol is 1d-complete (1d is one of the four timeframes Plan 02's own audit already verified)"

patterns-established:
  - "A fourth key in a shared per-dimension clause dict is the entire mechanism for a new eligibility axis -- no new cache plumbing, no new validation branch, no new function (per Plan 06's design, now proven by a second dimension addition)"

requirements-completed: [D-07a, D-09]

# Metrics
duration: ~10min
completed: 2026-09-15
---

# Phase 174 Plan 13: compute_eligible_1d and the compute_1d Dimension Summary

**A fourth `get_active_contracts()` eligibility dimension (`compute_1d`) reads a new, independent `instruments.compute_eligible_1d` column so the D-09 down-cap cohort's 1d-only symbols can be measured at 1d without ever becoming visible to the 5m/15m/1h cross-sectional cells -- proven structurally unreachable by a fixture-driven test, not by convention.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-09-15T17:01:00-04:00 (worktree base correction + venv symlink)
- **Completed:** 2026-09-15T17:07:48Z
- **Tasks:** 2/2 completed
- **Files modified:** 4 (1 new migration, 1 script extended, 1 settings module extended, 1 test file extended)

## Accomplishments

- Shipped migration 341: additive `instruments.compute_eligible_1d boolean NOT NULL DEFAULT false`, backed by a measured backfill UPDATE (231 rows, matching the pre-migration `is_active=true AND compute_eligible=true` count) and a `COMMENT ON COLUMN` documenting the `compute_eligible_1d=true, compute_eligible=false` steady state as the intended D-09 down-cap shape, not an inconsistency.
- Added `COMPUTE_READY_1D_PREDICATE_SQL` beside the existing `COMPUTE_READY_PREDICATE_SQL` in `scripts/analysis/instrument_compute_eligibility_audit.py` -- same `i.symbol` outer-alias convention, scoped to `'1d'` as a SQL literal so the identical text is valid inline in migration 341's `UPDATE ... WHERE` clause as well as inside a future psycopg call. Diff is additions-only; not a single character of the existing constant or `_TIMEFRAMES` changed.
- Added `"compute_1d": "is_active = true AND compute_eligible_1d = true"` as the sole functional change to `src/config/settings.py`'s `_ACTIVE_CONTRACTS_DIMENSION_CLAUSES`, plus one additive docstring bullet -- no change to the three pre-existing clause strings, cache plumbing, TTL, validation branch, or error-path fallback.
- Added 7 new tests to `tests/unit/config/test_settings_active_contracts_dimension.py` (16 total, up from 9): a literal pin of the three pre-existing WHERE-clause strings; `compute_1d`'s clause pinned and proven to omit `compute_eligible`; `compute_1d` cache isolation (4 distinct cache keys after exercising all four dimensions); `invalidate_active_contracts_cache()` clearing `compute_1d`; the invalid-dimension error message naming all four options; and a 1d-only-symbol fixture (`is_active=true, compute_eligible=false, compute_eligible_1d=true`) driven through the *real* `_ACTIVE_CONTRACTS_DIMENSION_CLAUSES` text via a small AND-clause interpreter, proving the symbol is absent from `compute`/`live` and present in `compute_1d`/`backfill`.
- Live spot check against the real 253-row / 231-active-row database: `len(get_active_contracts())=231`, `len(get_active_contracts(dimension='backfill'))=231`, `len(get_active_contracts(dimension='compute_1d'))=231`, `len(get_active_contracts(dimension='live'))=0` -- first three equal and non-zero, last zero, matching the plan's `<verification>` expectation.
- Full `tests/unit/` suite green (0 failures) after both changes.

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 341 -- additive compute_eligible_1d column and the 1d-only predicate** - `b669c920f` (feat)
2. **Task 2: Add the 'compute_1d' dimension and prove the other three did not move** - `0539e450c` (feat)

**Plan metadata:** this SUMMARY's own commit (docs: complete plan)

## Files Created/Modified

- `production/migrations/341_instruments_compute_eligible_1d.sql` - Additive `ALTER TABLE instruments ADD COLUMN compute_eligible_1d`, measured backfill `UPDATE` (231 rows), `COMMENT ON COLUMN` documenting the independent-not-narrowing relationship to `compute_eligible`
- `scripts/analysis/instrument_compute_eligibility_audit.py` - Adds `COMPUTE_READY_1D_PREDICATE_SQL` beside `COMPUTE_READY_PREDICATE_SQL`; additive docstring lines only
- `src/config/settings.py` - Adds `"compute_1d"` entry to `_ACTIVE_CONTRACTS_DIMENSION_CLAUSES`; additive docstring bullet in `get_active_contracts()`
- `tests/unit/config/test_settings_active_contracts_dimension.py` - 7 new test cases (10-15, one of which is two functions) covering non-regression pinning, `compute_1d` narrowing, cache isolation, invalidation, invalid-dimension messaging, and the 1d-only-symbol structural guarantee; `_FakeCursor.fetchall()`'s dimension dispatch extended with a `compute_eligible_1d = true` branch (checked before the pre-existing `compute_eligible = true` branch, though the two do not actually collide as substrings)

## Decisions Made

- **`compute_eligible_1d` defaults `false`, not `true`** -- the plan's own instruction, justified in the migration header: 337's `true` default was a measured truth about an already-ready universe; this column gates a cohort that does not exist yet, so `false` is the honest default for any row inserted later, before its own 1d backfill is measured complete.
- **`compute_1d`'s clause omits `compute_eligible`** -- deliberately a sibling dimension, not `compute`'s subset. Verified both by the SQL-text assertion (`"compute_eligible = true" not in sql`) and by the fixture-driven case 15, which proves a symbol with `compute_eligible=false, compute_eligible_1d=true` is reachable via `compute_1d` while remaining absent from `compute`.
- **1d-only-symbol test drives the real `_ACTIVE_CONTRACTS_DIMENSION_CLAUSES` dict rather than hardcoding expected membership** -- a small `_clause_matches()` AND-clause interpreter evaluates the actual clause strings against a row-flags dict, so the test would fail (not silently pass) if a future edit to any clause changed which columns it reads, directly implementing the plan's T-174-51/T-174-52 mitigation intent as executable behavior rather than a comment.
- **231 both times** -- the pre-migration `SELECT count(*)` used to size the migration header and the migration's actual `UPDATE 231` output matched exactly, and both equal the pre-existing `is_active=true AND compute_eligible=true` count measured at the same point in the run. No symbol needed calling out as a discrepancy.

## Deviations from Plan

None - plan executed exactly as written. One environment fix was required and is not a deviation from the plan's scope: the worktree spawned without its own `.venv` (a known, previously-documented gotcha for this project's worktree-based execution, also noted in 174-02-SUMMARY.md and 174-06-SUMMARY.md), which would have blocked the pre-commit hook's ruff/black checks. Fixed by symlinking `.venv` in the worktree to the main repo's `.venv` (`ln -s /home/bg/dev/indicagent/.venv .venv`) -- a read-only, non-destructive link, no code or migration content affected.

A second environment note, also not a deviation: the worktree branch's HEAD was found on an older commit than the plan's declared base commit at startup (behind by 2 commits: `2c6f138cd`, `763c23eac`). The working tree was clean, so per the `<worktree_branch_check>` protocol the branch was reset (`git reset --hard`) to the correct base commit before any file reads or edits began.

## Issues Encountered

One incidental finding, not a defect in this plan's scope: `instruments.compute_eligible = true` total is 253 (all rows in the table), while `is_active = true AND compute_eligible = true` is 231 -- meaning 22 rows exist with `is_active = false` but `compute_eligible = true`. This is unrelated to this plan (this plan's migration and dimension only ever gate on `is_active = true AND ...`, so those 22 rows are excluded from every dimension this plan touches regardless), and is consistent with other Phase 174 plans running in parallel worktrees against the same live database (e.g. onboarding plans inserting new `instruments` rows). Recorded here for visibility; not investigated further as out of this plan's scope per the executor's scope-boundary rule.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `dimension='compute_1d'` is live, committed, and behaviorally verified against the real database. Any future D-09 down-cap onboarding plan can promote a symbol to `compute_eligible_1d=true` using `COMPUTE_READY_1D_PREDICATE_SQL` as the gate, exactly mirroring how Plans 10/12 used `COMPUTE_READY_PREDICATE_SQL` for the four-timeframe dimension.
- The structural guarantee D-09 required is proven by test, not left as a convention every future 1d-cell consumer must remember: a 1d-only symbol cannot reach `dimension='compute'` because it does not carry `compute_eligible=true`, full stop.
- No blockers. All four STRIDE threats registered in this plan's threat model (T-174-51, T-174-52, T-174-53, T-174-54) are mitigated and covered by an automated test case or acceptance-criteria `git diff` check.

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-15*

## Self-Check: PASSED

- FOUND: production/migrations/341_instruments_compute_eligible_1d.sql
- FOUND: scripts/analysis/instrument_compute_eligibility_audit.py
- FOUND: src/config/settings.py
- FOUND: tests/unit/config/test_settings_active_contracts_dimension.py
- FOUND: commit b669c920f
- FOUND: commit 0539e450c
