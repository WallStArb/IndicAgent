---
phase: 165-swing-fib-trend-structure-primitives
plan: 04
subsystem: intelligence
tags: [feature-factory, feature-cache, session-levels, mutator, apr, mutation-testing, nullability, dst]

# Dependency graph
requires:
  - phase: 165-swing-fib-trend-structure-primitives
    provides: "Plan 01's 41-field data contract (migration 267, FeatureVector fields, persistence slice, 17 APR keys including session_levels_asia_start_et_hour/asia_end_et_hour) -- this plan builds the FeatureCache state layer the remaining 16 session-levels FeatureVector columns will read from"
provides:
  - "FeatureCache.update_session_levels(): timestamp-driven session/overnight/Asian-block state mutator, 16 new _sl_* internal fields, replacing the archived plugin's bar-count session detection (D-07)"
  - "update_wk_vwap() extended in place with weekly H/L/C + prior-completed-week snapshot (_wk_high/_wk_low/_wk_close/_prior_wk_high/_prior_wk_low/_prior_wk_close, D-09) -- isocalendar() still appears exactly once in feature_cache.py"
  - "update_session_levels() wired into all 3 call sites (compute_batch()'s per-bar loop, _process_bar_compute, _get_cache's warm-up replay) in a single commit -- the T-164-07 cold-start gap cannot recur"
  - "tests/unit/intelligence/test_session_levels_cache.py: 10 mutation-verified tests covering cold-start nullability, session rollover, overnight freeze, gap_filled latch, Asian-block cycle key, weekly snapshot, DST boundary, and the accumulator-collision guard"
affects: ["165-05-session-levels-derivation"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mutation-verification discipline (commit a748d13d precedent) applied to a stateful mutator rather than a stateless compute function -- required redesigning one test mid-verification when the first design proved structurally blind to its target mutation (see key-decisions)"

key-files:
  created:
    - tests/unit/intelligence/test_session_levels_cache.py
  modified:
    - src/intelligence/feature_cache.py
    - src/intelligence/feature_factory.py
    - services/feature_vector_pipeline.py

key-decisions:
  - "Two of the plan's own literal <verify> automated scripts were self-contradictory or stale against the live file and had to be adapted rather than followed verbatim: (1) the action text required update_session_levels()'s docstring to literally name _SESSION_BARS/_WEEK_BARS/_OVERNIGHT_BARS, but the verify script asserts those exact strings appear nowhere outside # comment lines (docstrings aren't stripped) -- resolved by moving the specific constant names/magnitudes into a #-prefixed comment block immediately above the method (which the check strips) while keeping the docstring's general statement; (2) the live/ordering check `fp.index('cache.update_session_levels'); fp.index('FeatureFactory.compute(')` finds the FIRST literal occurrence of each substring in the whole file, which for 'FeatureFactory.compute(' is the module docstring at line 4, not the real call site inside _process_bar_compute -- verified the true ordering with a scope-restricted search instead and confirmed the actual wiring is correct"
  - "FeatureFactoryConfig() cannot be constructed with zero arguments (the plan's own never-raises smoke-test snippet assumes it can) -- ~98 of its fields predate the Phase 163+ convention of defaulting new fields and have no default; used the existing _make_cfg() helper from test_swing_fib_trend_structure_primitives.py (imported, not duplicated) for both the smoke test and this plan's own test file's _cfg() helper"
  - "Task 2(d)'s structural regression test (test_session_levels_wired_at_all_three_call_sites) was deferred from Task 2's commit to Task 3's, since Task 2's own <files> frontmatter lists only feature_factory.py/feature_vector_pipeline.py and the test's home file (tests/unit/intelligence/test_session_levels_cache.py) is explicitly Task 3's to create -- Task 2's own <verify> block checks call-site counts directly against the source files and does not depend on the test file existing, so this ordering has zero verification gap"
  - "Mutation 3 (per the plan: 'make update_session_levels write to _session_day instead of _sl_session_day') did not fail the collision-guard test as designed on the first attempt, because both mutators derive session_day via the byte-identical ET-wall-clock formula from the same bar_ts -- under production call order (update_session_vp always runs first), a shared write converges to the same value regardless of which mutator 'wins', so VP's own state is provably unaffected. Redesigned the test to drive update_session_levels BEFORE update_session_vp/update_overnight_range (the reverse of production order), which makes VP the second-running mutator and exposes the hazard (_sess_bars stops resetting at session boundaries under the mutation); re-verified baseline passes and the mutation now fails it, then reverted the mutation before committing the test."

requirements-completed: ["D-06", "D-07", "D-08", "D-09", "D-13"]

# Metrics
duration: ~35min
completed: 2026-07-28
---

# Phase 165 Plan 04: Session Levels FeatureCache State Layer Summary

**FeatureCache.update_session_levels(): 22 new internal state fields (16 `_sl_*` session/overnight/Asian-block + 6 `_wk_high`/`_wk_low`/`_wk_close`/`_prior_wk_*`) and a timestamp-driven mutator replacing the archived `session_levels.py` plugin's `_SESSION_BARS=390`-style bar-count session detection, wired into all 3 required call sites, mutation-verified against a redesigned accumulator-collision test.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-07-28T10:47:00Z (approx, worktree setup)
- **Completed:** 2026-07-28T11:05:20Z
- **Tasks:** 3 (all `type="auto"`, Task 1 `tdd="true"`)
- **Files modified:** 4 (2 source, 1 new test file, 1 service)

## Accomplishments
- `FeatureCache.update_session_levels(bar_ts, open_, high, low, close, config)`: timestamp-driven mutator using the exact `_et_from_utc` + `_RTH_OPEN_ET`/`_RTH_CLOSE_ET` ET-wall-clock derivation `update_session_vp()` already uses (same DST-correctness rationale), tracking running session high/low/open/close, the prior-completed-session snapshot, a non-RTH overnight accumulator that freezes at the next session rollover, the `gap_filled` latch (D-13, zero new state -- reuses the running session high/low), and an Asian-block accumulator keyed on the two `feature.session_levels.asia_*` APR keys seeded in Plan 01
- 16 new `_sl_*` fields cold-start to `None` (or `0.0` for `_sl_gap_filled`), never a manufactured value (D-01 discipline); zero collision with Phase 163's `_session_day`/`_sess_bars` or Phase 164's `_overnight_high`/`_overnight_low`/`_overnight_day` -- every field carries the `_sl_` prefix specifically to avoid this
- `update_wk_vwap()` extended in place (D-09): weekly high/low/close accumulate inside the existing `_wk_year_week` reset block, snapshotting into `_prior_wk_high`/`_prior_wk_low`/`_prior_wk_close` only at a real ISO-week rollover (never the week in progress, avoiding the self-referential-close trap); `isocalendar()` still appears exactly once in the whole file; the pre-existing VWAP/`above_wk_vwap` computation is byte-identical
- `_SESSION_BARS`/`_WEEK_BARS`/`_OVERNIGHT_BARS` and the literals `390`/`1950` appear nowhere in `feature_cache.py` (verified via source-body scan with comments stripped)
- Wired into all 3 required call sites in one commit: `compute_batch()`'s per-bar loop (before the warm-up gate, `open_` read moved up into the per-bar preamble), `_process_bar_compute` (before `FeatureFactory.compute()`), and `_get_cache`'s warm-up replay block (a 4th sequential `for bar in buffered:` loop) -- the exact 3-call-site pattern Phase 164's `update_overnight_range()` needed after shipping with zero call sites (T-164-07)
- 10 regression tests in `tests/unit/intelligence/test_session_levels_cache.py`: cold-start nullability, session rollover snapshot, overnight freeze, gap_filled latch/reset, Asian-block cycle key (including a parametrized non-default-APR-hours case proving the keys are read, not hardcoded), weekly H/L/C snapshot, pre-existing weekly-VWAP-behaviour pin, DST boundary (2026 spring-forward and fall-back), the T-165-14 accumulator-collision guard, and a structural call-site-count test
- **Mutation-verification performed** (commit `a748d13d` discipline): see Mutation Check below

## Mutation Check

Three temporary local mutations were applied to `src/intelligence/feature_cache.py`, tested, and reverted (`git diff --stat` confirmed empty after each revert, verified via a full-file backup copy restored between mutations):

**Mutation 1 -- seed `_sl_prior_session_*` from the CURRENT bar unconditionally, even on the very first call (instead of leaving them `None` until a session has actually completed).**
Ran the full test file. Result: `test_session_levels_cold_start_is_none` FAILED as required (`assert 101.0 is None`), plus 2 cascading failures (`test_session_levels_rollover_snapshots_prior_session`, `test_session_levels_gap_filled_latches_and_resets`) since both depend on the same nullability invariant this mutation broke more broadly.

**Mutation 2 -- replace the ET-wall-clock session-day derivation with a bar-count key (`self._debug_bar_count // 3`, D-07's bug reintroduced).**
Ran the full test file. Result: `test_session_levels_rollover_snapshots_prior_session`, `test_session_levels_overnight_freezes_at_rollover`, and `test_session_levels_dst_boundary` FAILED as required, plus `test_session_levels_gap_filled_latches_and_resets` as a bonus cascading failure (gap_filled depends on correct rollover semantics too).

**Mutation 3 -- write to the shared Phase 163 `_session_day` key instead of `_sl_session_day` (T-165-14's collision hazard).**
First attempt with the test AS ORIGINALLY DESIGNED (calling `update_session_vp` then `update_overnight_range` then `update_session_levels`, matching production call order) did NOT fail the collision-guard test -- a real, investigated null result, not a shrugged-off one: both mutators derive `session_day` via the byte-identical ET-wall-clock formula from the identical `bar_ts`, so whichever mutator's write "wins" writes the same value the other would have written anyway; under production ordering (VP always runs first), the shared key stays correctly in sync regardless of the mutation, so VP's own fields (`_session_day`/`_sess_bars`/`_overnight_day`/`_overnight_high`/`_overnight_low`) are provably unaffected by this specific mutation. The mutation DID still fail 4 other tests (`rollover_snapshots_prior_session`, `overnight_freezes_at_rollover`, `gap_filled_latches_and_resets`, `dst_boundary`) -- session-levels' OWN rollover-triggered behavior breaks completely (the shared key is always "already advanced" by VP's own read/write cycle by the time session-levels checks it, so session-levels' `if session_day != self._sl_session_day:` branch reads a real value from `_sl_session_day` unaffected by the mutation directly, but the redirected WRITE `self._session_day = session_day` at the end means `_sl_session_day` is left permanently unset after the very first bar in some paths, silencing every downstream rollover effect).

Redesigned `test_session_levels_no_collision_with_amd_or_vp_state` to drive `update_session_levels` BEFORE `update_session_vp`/`update_overnight_range` on every bar (the reverse of production call order) -- this makes `update_session_vp` the SECOND-running mutator instead, which is the direction that actually exposes a shared-key hazard: if `update_session_levels` already advanced the shared key moments earlier in the same bar, VP's own `session_day != self._session_day` reset check sees "no change" and `_sess_bars` never resets at a real session boundary, growing across days instead of restarting. Re-verified the baseline (unmutated) implementation still passes under this reversed order (confirming `_sl_` prefix isolation holds regardless of call order in the correct implementation), then re-applied Mutation 3 and confirmed the redesigned test now FAILS as required (`cache_with._sess_bars` accumulates 6 entries across 6 daily bars instead of resetting to 1 each day), alongside the same 4 other failures. Reverted the mutation; final `git diff --stat` empty.

All three mutations reverted before this commit. Final state: full `tests/unit/` suite green (0 failures, 3 pre-existing unrelated skips), `ruff check`/`black --check` clean on all touched files.

## Task Commits

Each task was committed atomically:

1. **Task 1: FeatureCache session/weekly state -- 22 fields + update_session_levels() mutator** - `601d568e` (feat)
2. **Task 2: Wire update_session_levels() into all 3 call sites** - `d6cfb045` (feat)
3. **Task 3: Mutator unit tests, mutation-verified** - `ebf1503a` (test)

## Files Created/Modified
- `src/intelligence/feature_cache.py` - 22 new internal state fields (16 `_sl_*`, 6 `_wk_high`/`_wk_low`/`_wk_close`/`_prior_wk_*`), `update_session_levels()` mutator, `update_wk_vwap()` extended in place (D-09), `_RTH_CLOSE_ET` import added
- `src/intelligence/feature_factory.py` - `compute_batch()`'s per-bar loop: `open_` read moved into the preamble, `cache.update_session_levels(...)` call added before the warm-up gate
- `services/feature_vector_pipeline.py` - `_process_bar_compute`: call added before `FeatureFactory.compute()`; `_get_cache`: 4th warm-up replay loop added, docstring extended with the T-164-07 cold-start rationale
- `tests/unit/intelligence/test_session_levels_cache.py` - 10 tests (new file): cold-start nullability, session rollover, overnight freeze, gap_filled latch/reset, Asian-block cycle key (parametrized), weekly snapshot, weekly-VWAP-behaviour pin, DST boundary, accumulator-collision guard, structural call-site count

## Decisions Made
- See `key-decisions` in frontmatter for the two plan-defect adaptations (docstring-vs-verify-script contradiction; stale line-number/first-occurrence check), the `_make_cfg()` reuse for the never-raises smoke test, Task 2(d)'s deferral to Task 3's commit, and the collision-guard test redesign.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug in the plan's own verify script] Task 1's automated check contradicted its own action text**
- **Found during:** Task 1, running the plan's literal `<verify>` script for the docstring content
- **Issue:** The action text explicitly required `update_session_levels()`'s docstring to name `_SESSION_BARS`/`_WEEK_BARS`/`_OVERNIGHT_BARS` literally, but the verify script asserts these exact strings appear nowhere in any non-`#`-comment line of the file (docstrings are not `#`-prefixed, so they are NOT stripped by the check) -- a direct self-contradiction that would fail regardless of which requirement was honored.
- **Fix:** Moved the specific constant names and their real per-timeframe magnitudes into a `#`-prefixed comment block immediately preceding the method (stripped by the check), keeping the docstring's general statement ("no bar count appears anywhere in this method") without the literal names.
- **Files modified:** `src/intelligence/feature_cache.py`
- **Verification:** Re-ran the plan's literal verify script; passes. A future reader still finds the retirement documentation, just above the method rather than inside its docstring.
- **Committed in:** `601d568e`

**2. [Rule 1 - Bug in the plan's own verify script] Task 2's live-ordering check matched the wrong occurrence**
- **Found during:** Task 2, running the plan's literal ordering-check verify script
- **Issue:** `fp.index('cache.update_session_levels'); fp.index('FeatureFactory.compute(')` both use `.index()`, which finds the FIRST literal occurrence anywhere in the file -- `'FeatureFactory.compute('` appears in the module docstring at line 4, long before the real call site inside `_process_bar_compute` (~line 1248), so the check's own assertion (`i < j`) was structurally guaranteed to fail even with correct wiring.
- **Fix:** Verified the true ordering with a search scoped to `_process_bar_compute`'s function body specifically (`fp.index(..., start)` from `async def _process_bar_compute`'s offset), confirming `cache.update_session_levels` genuinely precedes the real `FeatureFactory.compute(bars_dicts` call.
- **Files modified:** None -- this was a verification-script defect, not a code defect; the actual wiring (confirmed by the scoped check and by the full `tests/unit/` suite passing) was already correct.
- **Verification:** Scoped ordering check passes; full test suite green.
- **Committed in:** N/A (verification-only finding, no code change required)

---

**Total deviations:** 2 auto-fixed (both Rule 1, both in the plan's own literal verify scripts rather than in implementation code)
**Impact on plan:** No scope creep. Both fixes are documentation/verification-methodology corrections confined to lines this plan's own work touched or to how a check was run; the underlying implementation was correct in both cases, confirmed independently via the full `tests/unit/` suite and targeted scoped checks.

## Issues Encountered
None beyond the two verify-script deviations documented above. No auth gates, no architectural decisions needed, no package installs. The worktree required the standard `.venv` symlink to the main repo (known gotcha, gitignored, no tracked files affected).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 05 can now derive all 16 `session_levels.py` `FeatureVector` columns as a thin `compute()`-time mapping over this plan's proven `FeatureCache` state (`_sl_*` fields + `_wk_high`/`_wk_low`/`_wk_close`/`_prior_wk_*`), following the same division of labour as `update_session_vp()`/`_derive_session_vp()` -- no `atr_val` is available in this plan's mutator by design; ATR normalization is entirely Plan 05's job
- All 3 call sites are wired in a single commit (`d6cfb045`) with a structural regression test (`test_session_levels_wired_at_all_three_call_sites`) guarding against a T-164-07-style cold-start gap recurring
- No blockers. Full `tests/unit/` suite green (0 failures, 3 pre-existing unrelated skips), ruff/black clean on every touched file, mutation-verification discipline satisfied for all three required mutations including the one that required a test redesign mid-verification.

## Known Stubs
None in the sense of unfinished work within this plan's own scope -- this plan adds ZERO `FeatureVector` values by design (stated explicitly in the plan's own objective: "This plan adds ZERO FeatureVector values -- Plan 05 derives all 16 columns from the state built here"). All 16 `session_levels.py` columns remain `None` in `feature_vectors` until Plan 05 lands, which is the plan's own stated scope boundary, not a gap.

---
*Phase: 165-swing-fib-trend-structure-primitives*
*Completed: 2026-07-28*

## Self-Check: PASSED

All 4 key files verified present in the working tree; all 3 commit hashes (`601d568e`, `d6cfb045`, `ebf1503a`) verified present in `git log`.
