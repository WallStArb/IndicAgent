---
phase: 165-swing-fib-trend-structure-primitives
plan: 05
subsystem: intelligence
tags: [feature-factory, session-levels, weekly-pivot, apr, mutation-testing, nullability, phase-closing-gate]

# Dependency graph
requires:
  - phase: 165-swing-fib-trend-structure-primitives
    provides: "Plan 04's FeatureCache.update_session_levels() state layer (16 _sl_* fields + weekly _wk_high/_wk_low/_wk_close/_prior_wk_* accumulators), wired into all 3 call sites"
provides:
  - "_derive_session_levels(cache, close_, atr_val, tf): the last 16 Phase 165 FeatureVector fields, derived purely from Plan 04's cache state plus the compute-path atr_val -- zero raw price levels persisted"
  - "_SESSION_LEVELS_FALLBACK (all-None, D-01) and _SESSION_LEVELS_DAILY_SUPPRESSED (5 intraday-only field names) module constants"
  - "compute()/compute_batch() both wired -- zero Phase 165 kwarg remains a hardcoded None at either _build_feature_vector call site; all 41 phase columns now carry computed values"
  - "9 mutation-verified regression tests plus the phase-closing test_phase165_all_41_fields_non_constant_batch gate proving every one of Phase 165's 41 columns produces a real value somewhere in a multi-session, multi-week batch run"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "tf=='1d' suppression applied INSIDE the derivation helper (not at the call site, unlike _derive_session_vp's VP branch) so live and batch cannot diverge on the gating -- documented as a deliberate departure in the docstring since this phase has no analogous 'skip an expensive rolling computation' rationale"
    - "live/batch parity test needs an explicit non-vacuousness guard (assert at least one field is non-None on both sides) -- otherwise a derivation that unconditionally returns its all-None fallback trivially 'passes' parity, since None == None on every field. Found during this plan's own mutation-verification pass, same shape as Plan 04's Mutation 3 finding."

key-files:
  created: []
  modified:
    - src/intelligence/feature_factory.py
    - tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py

key-decisions:
  - "Worktree HEAD was behind the plan's specified base commit (d244977b, which already contains Plans 01-04 merged) -- reset per the worktree_branch_check protocol before reading any plan files, since the worktree had been spawned from an earlier point on main."
  - "Task 1's docstring originally used the literal substring 'update_session_levels(' in prose describing the precondition -- this collided with Plan 04's own structural regression test (test_session_levels_wired_at_all_three_call_sites), which counts non-comment occurrences of that exact string and expects exactly 1 (the real mutator call site). Rephrased to 'the session-levels mutator' to avoid the false positive while keeping the same meaning."
  - "The live/batch parity test (test_session_levels_live_batch_parity) needed a second design pass after Mutation 1 (force _derive_session_levels to always return its all-None fallback) revealed it passed vacuously -- both compute() and compute_batch() paths returned the same trivial all-None result, so they 'agreed' without computing anything real. Added an explicit non-vacuousness assertion (at least one of the 16 fields must be non-None on both sides) before the per-field comparison loop, then re-verified the mutation now fails it as required."
  - "The weekly-pivot-pin and cold-nullability test fixtures both required extending beyond the minimum plausible bar count once Wilder ATR's period=7 warm-up requirement was discovered empirically (a 4-bar fixture silently produced atr_val=0.0 for every bar, making the derivation return its fallback regardless of the field under test) -- both fixtures were rebuilt with >=8-10 bars and re-verified via direct prototyping against the live code before being written into the final test file."

patterns-established:
  - "Derivation helper placed immediately after the most recently added sibling derivation (_derive_amd_cycle, Phase 164 Plan 04) and before _build_feature_vector -- the phase's now-established convention for cache-derived FeatureVector field blocks."

requirements-completed: ["D-01", "D-07", "D-08", "D-09", "D-12", "D-13"]

# Metrics
duration: ~95min
completed: 2026-07-28
---

# Phase 165 Plan 05: Session Levels Derivation + Phase-Closing Gate Summary

**_derive_session_levels() derives the final 16 Phase 165 FeatureVector columns from Plan 04's FeatureCache state (prior-session/overnight/Asian-block/prior-completed-week raw levels) as ATR-distances, percents, and one flag; wired into both compute() and compute_batch(); mutation-verified regression tests plus a phase-closing gate prove all 41 Phase 165 columns now carry real, non-constant values in both compute paths -- Phase 165 is complete.**

## Performance

- **Duration:** ~95 min
- **Started:** 2026-07-28T11:15:00Z (approx, worktree setup + base-commit reset)
- **Completed:** 2026-07-28T11:48:48Z
- **Tasks:** 3 (Task 1 `tdd="true"`, Tasks 2-3 `type="auto"`)
- **Files modified:** 2 (1 source, 1 test)

## Accomplishments
- `_SESSION_LEVELS_FALLBACK` (all-16-keys-None, D-01) and `_SESSION_LEVELS_DAILY_SUPPRESSED` (the 5 intraday-only field names) module-level constants, placed immediately after `_derive_amd_cycle` and before `_build_feature_vector`
- `_derive_session_levels(cache, close_, atr_val, tf)`: structured exactly like `_derive_session_vp()` (`atr_valid` guard, `_above()`/`_below()` sign-convention closures, never raises); reads `cache._sl_*` raw session/overnight/Asian-block levels and `cache._prior_wk_high/_low/_close` (the PRIOR COMPLETED ISO week only, never the week in progress); `overnight_range_pct`/`opening_gap_pct` return `None` (not 0.0/inf) on a zero or missing denominator; `nearest_level_dist_atr` considers the same 7 raw levels the archived plugin used, staying in-function locals (D-16); the archived plugin's prior-session-substituted-for-prior-week fallback is deliberately not ported
- `tf=='1d'` suppression applied INSIDE the helper (not at the call site) so live and batch cannot diverge on the gating -- a deliberate departure from `_derive_session_vp`'s call-site branch, documented in the docstring
- Both `compute()` and `compute_batch()` wired: one call each, replacing all 16 `None` placeholders Plan 01 installed at both `_build_feature_vector` call sites; `_cold_start_vector` left with its explicit `None` arguments (Plan 01's existing comment already explains why -- no bar history means nothing has been detected yet)
- 9 new regression tests appended to `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py`: non-constant batch (with gap_filled's both-values guard), cold nullability, ATR-unit pin, weekly-pivot pin, `tf=='1d'` suppression, gap_filled flip-and-latch, live/batch parity, and the phase-closing `test_phase165_all_41_fields_non_constant_batch` gate plus a dataclass/domain/DB-registry cross-check
- Full `tests/unit/` suite green (0 failures, 3 pre-existing unrelated skips); `ruff`/`black` clean on both touched files; `feature_registry` DB check confirms exactly 41 rows with `added_phase='165'`

## Task Commits

Each task was committed atomically:

1. **Task 1: `_derive_session_levels()` -- 16 fields from Plan 04 cache state** - `aa7d1532` (feat)
2. **Task 2: Wire `_derive_session_levels()` into `compute()` and `compute_batch()`** - `ddf3474f` (feat)
3. **Task 3: Regression tests + phase-closing 41-column completeness gate** - `41cd741c` (test)

## Files Created/Modified
- `src/intelligence/feature_factory.py` - `_SESSION_LEVELS_FALLBACK`/`_SESSION_LEVELS_DAILY_SUPPRESSED` constants, `_derive_session_levels()` helper, both `compute()`/`compute_batch()` call sites wired (16 kwargs each, replacing `None` placeholders)
- `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py` - 9 new tests, `_SESSION_LEVEL_FIELDS`/`_PHASE_165_FIELDS` module constants, `_run_live_with_session_levels()` helper, `session_bars` module fixture (8 days of 30-min bars spanning multiple session rollovers and one ISO-week boundary), 4 dedicated small deterministic fixtures for the pinned-value tests

## Decisions Made
See `key-decisions` in frontmatter for: the worktree base-commit reset, the docstring/structural-test string-collision fix, the live/batch parity test's non-vacuousness guard (found via mutation testing), and the ATR-warm-up bar-count discovery that reshaped two test fixtures.

## Mutation-Verification (commit `a748d13d` discipline)

All three mutations applied as temporary local edits to `src/intelligence/feature_factory.py`, tested, then reverted (`git diff --stat` confirmed empty after each revert):

**Mutation 1 -- force `_derive_session_levels` to unconditionally `return dict(_SESSION_LEVELS_FALLBACK)`.**
First pass: 6 of 7 targeted tests failed as required (`test_session_levels_non_constant_batch`, `test_session_levels_dist_in_atr_units`, `test_session_levels_weekly_pivot_pinned`, `test_session_levels_daily_suppression`, `test_session_levels_gap_filled_column`, `test_phase165_all_41_fields_non_constant_batch`) -- but `test_session_levels_live_batch_parity` PASSED, a genuine test-design gap: both `compute()` and `compute_batch()` returned the identical all-None fallback, so the parity check's `None == None` comparisons trivially "agreed" without ever exercising real computation. Fixed by adding an explicit non-vacuousness assertion (at least one of the 16 fields must be non-None on both the batch and live side) before the per-field loop. Re-verified the baseline (unmutated) implementation still passes with this fix, then re-applied Mutation 1 and confirmed all 7 tests now fail as required.

**Mutation 2 -- redirect the weekly derivation to read `cache._wk_high`/`_wk_low`/`_wk_close` (the RUNNING week) instead of `cache._prior_wk_high`/`_low`/`_close`.**
`test_session_levels_weekly_pivot_pinned` failed as required (`assert False` on the pinned pivot-distance comparison, off by the running-week-vs-prior-week value delta).

**Mutation 3 -- remove the `tf=='1d'` suppression branch entirely.**
`test_session_levels_daily_suppression` failed as required (357 unexpected non-None values found on `overnight_high_dist_atr` at `tf=='1d'`, where the test asserts exactly 0).

All three mutations reverted before their respective follow-on commits. Final state: full `tests/unit/` suite green, ruff/black clean on both touched files.

## Issues Encountered
None beyond the two deviations documented above (both caught and fixed during this plan's own execution, not deferred). No auth gates, no architectural decisions needed, no package installs.

## User Setup Required
None - no external service configuration required.

## Phase 165 Closing Status

This is the phase-closing plan. All 41 Phase 165 columns (13 swing/trend structure, Plan 02; 12 swing momentum/fibonacci zones, Plan 03; 16 session levels, this plan) now carry real, non-constant computed values in both `compute()` (live) and `compute_batch()` (backfill), proven by `test_phase165_all_41_fields_non_constant_batch`. Zero raw price levels or raw bar indices are persisted anywhere in the 41-column set (D-02/D-04/D-16). Every tunable numeric is APR-backed (17 keys total across the phase, seeded in Plan 01's migration 267). Historical `feature_vectors` backfill for these 41 columns is deliberately deferred to the consolidated 163/164/165 `--compute-only --refresh` pass (todo 176 / STATE.md's Tier 0 sequencing), not this phase's scope.

## Known Stubs
None. All 41 Phase 165 columns are fully wired with real computed values as of this plan; no `None` placeholders remain at either `_build_feature_vector` call site outside the intentional `_cold_start_vector` case (which correctly stays `None` -- no bar history exists at cold start).

---
*Phase: 165-swing-fib-trend-structure-primitives*
*Completed: 2026-07-28*

## Self-Check: PASSED

All 3 key files verified present (`src/intelligence/feature_factory.py`, `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py`, this SUMMARY.md); all 3 commit hashes (`aa7d1532`, `ddf3474f`, `41cd741c`) verified present in `git log`.
