---
phase: 165-swing-fib-trend-structure-primitives
plan: 02
subsystem: intelligence
tags: [feature-factory, swing-detection, trend-structure, find-peaks, apr, mutation-testing, nullability]

# Dependency graph
requires:
  - phase: 165-swing-fib-trend-structure-primitives
    provides: "Plan 01's 41-field data contract (migration 267, FeatureVector fields, persistence slice, 17 APR keys) -- this plan replaces 13 of those 41 None placeholders with real compute logic"
provides:
  - "_compute_swing_structure(): shared stateless find_peaks/find_troughs pivot pass (D-06), returns 7 FeatureVector fields plus in-memory-only swing_high_price/swing_low_price/swing_high_indices/swing_low_indices/n_bars intermediates for Plan 03's fibonacci port (D-05)"
  - "_compute_trend_structure(): leg-scoring/strength/integrity/price-position/duration geometry consuming the shared swing pass's indices -- never re-runs find_peaks/find_troughs (D-06)"
  - "_SWING_FALLBACK / _TREND_STRUCTURE_FALLBACK: all-None fallback dicts (D-01), mutation-verified to actually gate the associated tests"
  - "tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py: 8 tests (module now shared by Plans 03/04 for their own test classes)"
affects: ["165-03-swing-momentum-fibonacci-zones", "165-04-session-levels"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mutation-verification discipline (commit a748d13d precedent): temporarily force compute functions to their fallback dicts / swap fallback to archived numeric defaults, confirm the specific tests that should catch each mutation actually fail, revert before committing -- proves the tests are effective guards, not just green by construction"

key-files:
  modified:
    - src/intelligence/feature_factory.py
  created:
    - tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py

key-decisions:
  - "Mutation-verification step performed as temporary local edits (never committed) after the WIP commit landed, rather than re-opening the WIP commit -- the compute code and tests were already correct and committed (3238d2e0); the mutation check is a verification activity, not a code change, so no new source diff resulted from it"
  - "Observed mutation-kill set differs slightly from the plan's predicted (a,b,d,f,g): forcing both compute functions to return their fallback dicts actually fails (a) test_swing_trend_non_constant_batch, (b) test_swing_dist_in_atr_units, (d) test_swing_detector_partial_nullability, (g) test_trend_structure_apr_keys_are_live, plus the extra test_structure_integrity_bounded -- but NOT (f) test_swing_trend_live_batch_parity, since both compute() and compute_batch() call the same forced-deterministic function and trivially agree with each other under the mutation. Parity's real job is catching a live/batch wiring divergence, not catching a forced-fallback mutation, so this is a correct null result, not a gap."

requirements-completed: ["D-01", "D-02", "D-04", "D-06"]

# Metrics
duration: ~2h45min
completed: 2026-07-28
---

# Phase 165 Plan 02: Swing Detection + Trend Structure Compute Summary

**Adds `_compute_swing_structure()` and `_compute_trend_structure()` to `feature_factory.py`, wired into both `compute()` and `compute_batch()` for 13 of Phase 165's 41 columns (7 swing detection + 6 trend structure), sharing a single `find_peaks`/`find_troughs` pass (D-06) and emitting `None` rather than a fake numeric placeholder on every insufficient-data branch (D-01) -- mutation-verified.**

## Performance

- **Duration:** ~2h45min (includes the WIP compute/test pass and this session's mutation-verification + SUMMARY completion)
- **Completed:** 2026-07-28
- **Tasks:** 3 (all `type="auto"`), committed together as one WIP commit; mutation check performed as a separate verification pass afterward
- **Files modified:** 2 (1 source, 1 new test file)

## Accomplishments
- `_compute_swing_structure()`: ports `i3_structure/swing_detector.py`'s pivot detection over `config.swing_lookback_bars`, ATR-normalizes swing-high/low distance, classifies higher-high/lower-high type and swing pattern, and returns the raw price/index intermediates Plan 03 needs for fibonacci zones -- those extra keys are in-memory only and never threaded into `_build_feature_vector` (D-02/D-16)
- `_compute_trend_structure()`: consumes the shared swing pass's `swing_high_indices`/`swing_low_indices`/`n_bars` (exactly one `find_peaks(` call site added versus the plan's starting commit) to score bullish/bearish legs, trend strength (APR-backed `trend_structure_atr_strength_divisor`, no `5.0` literal), structure integrity, price position, and duration
- `_SWING_FALLBACK`/`_TREND_STRUCTURE_FALLBACK`: all-`None` (D-01) -- the archived plugins' `trend_direction=0.0`/`price_position=0.5` early-return placeholders exist nowhere in the port
- Both `compute()` and `compute_batch()` wired to pass real values for all 13 fields at their `_build_feature_vector` call sites
- 8 regression tests in `test_swing_fib_trend_structure_primitives.py`: non-constant batch values, structure-integrity bounds, ATR-unit distance pinning (exact value on a constant-true-range fixture), trend nullability on insufficient swing data, partial-swing nullability, zero-ATR all-None, live/batch parity to 1e-6, and APR-key liveness
- **Mutation-verification performed this session** (commit `a748d13d` discipline, `165-02-PLAN.md` Task 3's closing requirement): see Mutation Check below

## Mutation Check

Two temporary local mutations were applied, tested, and reverted (no diff survives in the committed code):

**Mutation 1 -- force both compute functions to return their fallback dict unconditionally.**
Ran `pytest tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py -q`. Result: 5 of 8 tests failed as expected --
`test_swing_trend_non_constant_batch`, `test_swing_dist_in_atr_units`, `test_swing_detector_partial_nullability`,
`test_trend_structure_apr_keys_are_live`, and the extra `test_structure_integrity_bounded` (not named in the plan's
mutation list but correctly caught since it also asserts real bounded values). `test_trend_structure_nullability`,
`test_swing_trend_zero_atr_all_none`, and `test_swing_trend_live_batch_parity` did NOT fail -- all three assert
None/None-equality properties that hold trivially true under an all-None forced fallback. This is a correct null
result for those three, not a missed mutation: nullability and zero-ATR tests are specifically checking for the
all-None shape the mutation produces, and parity only compares live vs. batch to each other (both call the same
forced function, so they trivially agree).

**Mutation 2 -- restore real compute, then swap `_TREND_STRUCTURE_FALLBACK` to the archived numeric defaults
(`trend_direction: 0.0`, `price_position: 0.5`).**
Ran the same test file. Result: `test_trend_structure_nullability` FAILED as required (`assert 0.0 is None` on
`trend_direction`) -- proving the nullability test actually catches the todo-153 failure shape rather than passing
vacuously. `test_swing_trend_zero_atr_all_none` and `test_structure_integrity_bounded` also failed (same shape:
both assert all-None on zero-ATR/insufficient-data fixtures, and the zero-ATR path routes through the same
mutated fallback dict).

Both edits were reverted (`git diff --stat src/intelligence/feature_factory.py` confirmed empty after each revert).
Final state: full `tests/unit/` suite green, `ruff check` clean on both touched files.

## Task Commits

Tasks 1-3 (swing structure compute, trend structure compute, regression tests) were implemented and committed
together as one WIP commit, then finalized by this session's mutation-verification pass:

1. **Tasks 1-3: swing structure + trend structure compute + regression tests** - `3238d2e0` (feat, WIP)
2. **Mutation-verification + SUMMARY + STATE/ROADMAP updates** - this commit (docs/verification, no source diff)

## Files Created/Modified
- `src/intelligence/feature_factory.py` - `_SWING_FALLBACK`/`_TREND_STRUCTURE_FALLBACK` (all-None), `_compute_swing_structure()`, `_trend_duration_bars()`, `_compute_trend_structure()`, wired into both `compute()`/`compute_batch()` call sites (committed in `3238d2e0`; no diff from this session's mutation-verification work, which was fully reverted)
- `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py` - 8 tests (committed in `3238d2e0`)

## Decisions Made
- Mutation-verification performed as a standalone verification pass rather than folded into the WIP commit -- the compute code and tests were already functionally complete and correctly committed; re-opening that commit to append a verification note would have mixed a code commit with a pure-verification activity
- Documented the observed (not predicted) mutation-kill set in this SUMMARY per the plan's own acceptance criterion ("the SUMMARY records which tests failed") -- the actual results diverge slightly from the plan's predicted `(a,b,d,f,g)` list in a way that has a sound explanation (parity trivially holds under a fully-deterministic forced mutation), not a defect in either the tests or the plan

## Deviations from Plan
None requiring code changes. The only deviation is procedural: the plan's Task 3 predicted `test_swing_trend_live_batch_parity` would fail under Mutation 1; it did not, for the reason explained above. No fix was needed since this reflects correct test behavior, not a weak test -- the parity test's actual job (catching a live/batch wiring divergence) is unaffected.

## Issues Encountered
None. No auth gates, no architectural decisions needed, no package installs.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 03 (swing momentum + fibonacci zones) can now consume `_compute_swing_structure()`'s in-memory `swing_high_price`/`swing_low_price`/`swing_high_indices`/`swing_low_indices`/`n_bars` intermediates directly -- D-05's cross-plugin fallback duplication is avoidable outright rather than reimplemented, per this plan's success criteria
- Plan 04 (session levels) is independent of this plan's scope
- `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py`'s module-level `_make_cfg`/fixtures are shared -- Plans 03/04 append their own test classes to this same file rather than creating new files
- No blockers. Full `tests/unit/` suite green (0 failures), ruff clean on every touched file, mutation-verification discipline satisfied.

## Known Stubs
None. 13 of 41 Phase 165 columns now carry real computed values in both live and batch paths; the remaining 28 (swing momentum 8, fibonacci zones 4, session levels 16) stay `None` pending Plans 03-04, per this plan's own scope boundary.

---
*Phase: 165-swing-fib-trend-structure-primitives*
*Completed: 2026-07-28*

## Self-Check: PASSED

Both key files verified present in the working tree; commit `3238d2e0` verified present in git log. Mutation-verification re-run live during SUMMARY authorship (not just recalled from memory): both mutations applied, tested, and reverted with `git diff --stat` confirming zero residual diff.
