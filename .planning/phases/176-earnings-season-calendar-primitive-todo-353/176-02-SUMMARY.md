---
phase: 176-earnings-season-calendar-primitive-todo-353
plan: "02"
subsystem: database
tags: [migration, timescaledb, apr, concept-registry, feature-vectors, ic-engine]

# Dependency graph
requires:
  - phase: 175
    provides: concept_registry/concept_gate genesis-seed pattern, APR provenance-tag convention
provides:
  - "feature_vectors.earnings_season_flag / days_since_quarter_end columns (real, nullable, no DEFAULT)"
  - "APR keys feature.earnings_season.start_days/end_days and alpha.ic.earnings_season_conditioned"
  - "concept_registry/concept_gate genesis rows for both features at tier 1_interaction, broadcast=true"
  - "feature_ic_scores.regime_scope CHECK widened to admit 'earnings_season'"
affects: [176-03, 176-04, 176-05, 176-06, 176-07, 176-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "concept_registry genesis-seed direct INSERT (feature_registry no longer exists, migration 311)"
    - "self-asserting DO $$ verification block at end of migration (mirrors migration 187's style)"

key-files:
  created:
    - production/migrations/350_earnings_season_calendar_primitive.sql
    - tests/unit/test_earnings_season_migration_contract.py
  modified: []

key-decisions:
  - "Corrected 176-RESEARCH.md's drafted concept_registry INSERT to include 'broadcast', true in both metadata objects -- omitting it would have pooled one observation across ~231 symbols and overstated cross-sectional IC significance (the Phase 173 bug class)"
  - "Column type real (float32), matching every feature_vectors column added since migration 312"

requirements-completed: [ES-03, ES-04, ES-06]

# Metrics
duration: 20min
completed: 2026-09-23
---

# Phase 176 Plan 02: Migration 350 (Earnings-Season Calendar Primitive Schema) Summary

**Migration 350 lands `feature_vectors.earnings_season_flag`/`days_since_quarter_end`, three APR keys, concept_registry/concept_gate genesis seeds with the broadcast=true correction, and widens `feature_ic_scores.regime_scope`'s CHECK constraint -- applied live, verified idempotent, and the negative CHECK-constraint case confirmed to raise inside a rolled-back transaction.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-09-23T11:07:17Z
- **Tasks:** 2
- **Files modified:** 2 (both created)

## Accomplishments
- Migration 350 written, applied live against the production `indicagent` database, and committed in the same breath (CLAUDE.md's live-apply rule)
- All four Wave 0 smoke checks passed, including the negative CHECK-constraint case run inside an explicitly rolled-back transaction
- Re-running the migration a second time exited 0 with no error (idempotence confirmed)
- Source-contract test (`tests/unit/test_earnings_season_migration_contract.py`, 7 assertions) guards every clause the plan's `<behavior>` block requires
- `tests/unit/test_compressed_hypertable_migration_vacuum_check.py` (the CI gate that would fail if this migration were misclassified as a column-type change) stays green

## Task Commits

Each task was committed atomically:

1. **Task 1: Write migration 350** - no separate commit (file written, verified against the vacuum-check CI guard and every acceptance-criteria grep, then committed together with Task 2 per the plan's explicit instruction)
2. **Task 2: Migration source-contract test + apply live + commit** - `49d60f64f` (feat) -- migration file, contract test, live apply, and all four smoke checks in one commit

**Plan metadata:** (this commit) -- docs: complete plan

## Files Created/Modified
- `production/migrations/350_earnings_season_calendar_primitive.sql` - 2 new `feature_vectors` columns, 3 APR keys, concept_registry/concept_gate genesis seed (broadcast=true), `feature_ic_scores.regime_scope` CHECK widening, self-asserting DO block
- `tests/unit/test_earnings_season_migration_contract.py` - 7 source-level contract assertions against the migration text (comment-stripped before matching)

## Decisions Made
- Reworded one header-comment sentence (originally containing the literal substring `'broadcast', true`) so the plan's own literal grep acceptance criterion (`grep -c "'broadcast', true" == 2`) counts only the two real INSERT occurrences, not an incidental comment match. No semantic change -- the comment still explains why the key is mandatory.
- Used the live `feature_ic_scores` schema (`vector_domain`, `lookahead_bars`, `training_window_end`, `is_pooled`, `n_independent`, `reliable` -- not the plan's illustrative `ic_sharpe`/`n_obs`) for the negative-case INSERT in the smoke check, since the plan's smoke-check text named illustrative columns rather than the literal schema.

## Deviations from Plan

None - plan executed exactly as written. The two items above are drafting/verification-mechanics adjustments within Task 1/Task 2's own acceptance criteria, not deviations from the plan's design.

## Issues Encountered
- First attempt at the negative-case smoke check (Task 2, smoke check 4) used illustrative column names (`ic_value`, `ic_sharpe`, `n_obs`) that don't exist on the live `feature_ic_scores` table; `\d feature_ic_scores` resolved the actual required columns and the retry correctly raised and rolled back on `feature_ic_scores_regime_scope_chk`.
- This worktree has no local `.venv` (a known gap, see `feedback_gsd_worktree_venv_missing.md`); ran `pytest` via the main checkout's `.venv/bin/pytest` against the worktree's test files, and prepended the main checkout's `.venv/bin` to `PATH` so the pre-commit hook's `ruff`/`black` fallback (`which ruff`/`which black`) resolved correctly. No hook was skipped or bypassed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both new `feature_vectors` columns, all three APR keys, both `concept_registry`/`concept_gate` rows, and the widened `regime_scope` CHECK are live in the production database -- 176-03 (feature_factory compute functions) and 176-04/05/06 (ic_engine conditioning workstream) can now read/write against this schema.
- No blockers.

---
*Phase: 176-earnings-season-calendar-primitive-todo-353*
*Completed: 2026-09-23*

## Self-Check: PASSED

- FOUND: production/migrations/350_earnings_season_calendar_primitive.sql
- FOUND: tests/unit/test_earnings_season_migration_contract.py
- FOUND: commit 49d60f64f
