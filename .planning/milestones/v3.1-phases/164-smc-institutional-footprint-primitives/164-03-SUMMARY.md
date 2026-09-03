---
phase: 164-smc-institutional-footprint-primitives
plan: 03
subsystem: intelligence
tags: [feature-factory, smc, fvg, liquidity-sweeps, liquidity-pools, apr, timescaledb]

# Dependency graph
requires:
  - phase: 164-01
    provides: "36 feature_vectors columns + FeatureVector/FEATURE_VECTOR_DOMAIN/persistence-slice contract (36 fields threaded as None placeholders), 39 feature.smc.* APR keys wired into FeatureFactoryConfig at both live and batch sites"
  - phase: 164-02
    provides: "_compute_order_blocks() -- in-function-threading pattern (candidates list -> nearest-by-price selection -> stateless derivation) established as the template this plan extends; module-level _<CONCEPT>_FALLBACK constant + atr_valid-first guard convention"
provides:
  - "_compute_fvg() -- stateless 3-candle imbalance scan, wired into both FeatureFactory.compute() and compute_batch(), replacing 3 None placeholders (fvg_dist_atr/fvg_size_atr/fvg_open_count)"
  - "_compute_liquidity_sweeps() -- stateless wick-beyond-swing + reclaim scan, replacing 4 None placeholders (sweep_detected/sweep_strength/reclaim_velocity/bars_since_last_sweep)"
  - "_compute_liquidity_pools() -- single-timeframe-descoped port (equal-highs/equal-lows + session-high/low only, PWH/PWL/PDH/PDL dropped), replacing 5 None placeholders (bsl_dist_atr/ssl_dist_atr/bsl_touches/ssl_touches/pool_count)"
  - "fvg_midpoint + price_in_premium in-pass locals staged for Plan 04's supply/demand-zones block (soft dependency per 164-RESEARCH.md), never persisted"
  - "tests/unit/intelligence/test_smc_fvg.py -- 7-test regression suite (non-constant, open-count decrements when filled, raw-price absence, determinism, live==batch parity)"
  - "tests/unit/intelligence/test_smc_liquidity.py -- 12-test regression suite (sweeps + pools bounds/counts, PWH/PWL/PDH/PDL descope guard, fallback-never-raises, raw-price absence, determinism, live==batch parity)"
affects: ["164-04-zones-bos-choch-amd"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FVG 'most recent unfilled gap' selection corrected vs. the archived plugin: fair_value_gap.py's descending-index scan makes its own open_fvgs[-1] the OLDEST still-open gap, not the newest -- ported as max-by-formation-index (largest bar3 index) instead of a literal 1:1 copy"
    - "Wave-0-test-plus-partial-implementation task shape (Task 1 authors both new test files but implements only FVG; Task 2, tdd=true, implements the two liquidity helpers against the already-authored, already-failing test_smc_liquidity.py) -- deliberately restructured across a task boundary vs. Plan 02's strict single-task RED/GREEN split; each task still commits atomically at its own well-defined intermediate state (verified by temporarily reverting Task 2's code, confirming test_smc_liquidity.py fails at import, then re-applying)"

key-files:
  created:
    - tests/unit/intelligence/test_smc_fvg.py
    - tests/unit/intelligence/test_smc_liquidity.py
  modified:
    - src/intelligence/feature_factory.py

key-decisions:
  - "FVG 'most recent' selection: literal port of fair_value_gap.py's open_fvgs[-1] would have returned the OLDEST unfilled gap (an inversion caused by its backward/descending scan-and-append order), not the newest as its own docstring claims -- ported the corrected semantics (max-by-formation-index) instead of reproducing the bug, documented explicitly in _compute_fvg()'s docstring"
  - "bars_since_last_sweep fallback = 0.0 when no sweep is ever found in-window (atr-invalid OR empty-sweeps-list cases) -- matches the project's existing 'absence has no defined age' convention (resistance_age_bars/support_age_bars fall back to 0.0 identically), not a distinct lookback-length sentinel"
  - "Liquidity pools' pre-seeded smc_liquidity_pools_atr_fallback_pct APR key (Plan 01) is deliberately left unused -- it corresponds to the archived plugin's own redundant inline ATR recompute-with-fallback, which 164-RESEARCH.md's Don't-Hand-Roll guidance explicitly says to skip in favor of reusing the already-computed atr_val (gated by the same atr_valid check every other SMC helper in this phase uses first)"

patterns-established: []

requirements-completed: ["REQ-164-03", "REQ-164-04", "REQ-164-05"]

# Metrics
duration: ~30min
completed: 2026-07-28
---

# Phase 164 Plan 03: Fair Value Gaps + Liquidity Sweeps + Liquidity Pools Summary

**`_compute_fvg()` / `_compute_liquidity_sweeps()` / `_compute_liquidity_pools()` -- three stateless full-window-scan primitives replacing 12 `None` placeholders in both `FeatureFactory.compute()`/`compute_batch()`, with Liquidity Pools single-timeframe-descoped (no PWH/PWL/PDH/PDL) per 164-RESEARCH.md's cross-timeframe data-gap finding.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-07-28T02:11:00Z (session resume, immediately after Plan 02 completion)
- **Completed:** 2026-07-28T02:39:13Z
- **Tasks:** 2 (both completed)
- **Files modified:** 3 (1 source, 2 new test files)

## Accomplishments
- Ported `fair_value_gap.py`'s 3-candle imbalance-gap geometry into `_compute_fvg()`, correcting a real selection bug found in the archived source during implementation: its own descending-index scan makes `open_fvgs[-1]` return the OLDEST still-open gap despite the docstring's "return the most recent" comment -- ported the intended semantics (max-by-formation-index) instead of reproducing the inversion
- Ported `liquidity_sweeps.py`'s wick-beyond-swing-then-reclaim detection into `_compute_liquidity_sweeps()`, keeping the archived plugin's already-correct `linear_ramp` [0,1] bounding for `sweep_strength`/`reclaim_velocity` and adding the new `bars_since_last_sweep` derivation (raw bar count, D-19 age-bars convention)
- Ported `liquidity_pools.py`'s equal-highs/equal-lows + session-high/low detection into `_compute_liquidity_pools()`, single-timeframe-descoped per 164-RESEARCH.md: PWH/PWL/PDH/PDL (which need a second daily-timeframe frame the live `compute(bars, symbol, tf, cache, config)` signature cannot provide) are dropped entirely -- a dedicated grep gate (`PWH|PWL|PDH|PDL|frames.get("1d"`) confirms no such reference or 1d-frame access remains anywhere in `feature_factory.py`
- Wired all three helpers into both `FeatureFactory.compute()` (full-array call, after the Plan 02 order-blocks block) and `compute_batch()` (causal pre-sliced window per bar, matching every other SMC helper's lookahead-avoidance pattern), replacing 12 of the 29 remaining `None` placeholders
- Staged `fvg_midpoint` and `price_in_premium` as in-pass local variables only (never threaded into `_build_feature_vector`, never a `FeatureVector` field) for Plan 04's supply/demand-zones block to consume in the same compute pass
- Built two new regression suites: `test_smc_fvg.py` (7 tests) and `test_smc_liquidity.py` (12 tests) -- covering non-constant values, bounded strength/velocity, count semantics, the PWH/PWL/PDH/PDL descope guard (both a `hasattr` check and a direct `inspect.signature()` check that `_compute_liquidity_pools()` has no 1d-frame parameter), fallback-never-raises on invalid ATR/short windows, raw-price-field absence, determinism, and live==batch parity
- Full `tests/unit/` suite green (0 failures), ruff/black clean on the touched file, binary-pattern scanner clean (0 violations)

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 tests + `_compute_fvg()` (FVG)** - `b0c0bfa5` (feat) -- lands `_compute_fvg()` fully wired plus both new test files; `test_smc_liquidity.py` fails at import (Task 2's helpers don't exist yet), confirmed and expected per the plan's own acceptance criteria
2. **Task 2: `_compute_liquidity_sweeps()` + `_compute_liquidity_pools()` (single-tf descoped)** - `b58de20a` (feat) -- lands both liquidity helpers, `test_smc_liquidity.py` goes fully GREEN

_Task 2 is `tdd="true"`; its own test file was authored in Task 1 (a deliberate plan-level restructuring, not the strict single-task RED/GREEN split Plan 02 used) -- verified the RED state by temporarily reverting Task 2's implementation and confirming `test_smc_liquidity.py` fails at import before re-applying and committing the GREEN state. Plan frontmatter `type: execute` (not `type: tdd`), so the plan-level TDD gate enforcement section does not apply here; this is task-level TDD discipline only._

## Files Created/Modified
- `src/intelligence/feature_factory.py` -- `linear_ramp` import; `_FVG_FALLBACK`/`_SWEEP_FALLBACK`/`_POOL_FALLBACK` constants; `_compute_fvg()`, `_compute_liquidity_sweeps()`, `_compute_liquidity_pools()`, `_find_equal_price_clusters()`, `_pool_touches_for()` pure functions; wired into `compute()` and `compute_batch()`'s per-bar loop after the Plan 02 order-blocks block, replacing 12 of the 29 remaining SMC `None` placeholders at both `_build_feature_vector(...)` call sites
- `tests/unit/intelligence/test_smc_fvg.py` -- new regression suite (7 tests) for the 3 FVG fields
- `tests/unit/intelligence/test_smc_liquidity.py` -- new regression suite (12 tests) for the 9 liquidity-sweep/pool fields plus the PWH/PWL/PDH/PDL descope guard

## Decisions Made
See `key-decisions` in frontmatter for the full rationale on the FVG selection-bug correction, the `bars_since_last_sweep` fallback convention, and the deliberately-unused `smc_liquidity_pools_atr_fallback_pct` APR key.

## Deviations from Plan

### Auto-fixed Issues (Rule 1 -- bugs found and fixed during implementation)

**1. [Rule 1 - Bug] `fair_value_gap.py`'s "most recent unfilled gap" selection actually returns the oldest**
- **Found during:** Task 1 (writing `_compute_fvg()` against the archived source)
- **Issue:** `fair_value_gap.py` scans bars in descending index order (`for i in range(len(df) - 1, 1, -1)`) and appends each unfilled gap it finds to `open_fvgs`, then returns `open_fvgs[-1]` with a comment claiming this is "the most recent unfilled FVG." Because the scan itself runs newest-to-oldest and appends in that same order, `open_fvgs[-1]` is actually the LAST bar checked, i.e. the OLDEST surviving gap -- the inverse of the stated intent.
- **Fix:** `_compute_fvg()` selects by `max(candidates, key=lambda cand: cand["idx"])` (largest formation-bar index = most recent), matching `order_blocks.py`'s own nearest-by-recency convention and the literal meaning of "most recent." Documented explicitly in the function's docstring so a future reader comparing against the archived source isn't confused by the apparent discrepancy.
- **Files modified:** `src/intelligence/feature_factory.py`
- **Verification:** `test_fvg_size_and_dist_atr_finite_nonzero` and the rest of `test_smc_fvg.py` pass against a hand-built fixture where only one gap exists (so the bug wouldn't have been caught by a single-gap test); the docstring correction is the primary artifact here, not a test-driven catch, since no multi-gap fixture was needed to expose it once the archived source was read carefully during Task 1's `read_first` step.
- **Committed in:** `b0c0bfa5` (Task 1 commit -- caught before the commit, not a follow-up fix)

**2. [Rule 1 - Bug] New docstring text tripped the project's look-ahead-language guard test**
- **Found during:** Task 2 (running the full `tests/unit/` suite, which includes `test_feature_factory.py::TestRegimePrimitives::test_no_smooth_or_backward_in_factory`)
- **Issue:** `_compute_fvg()`'s docstring used the word "backward" to describe the archived plugin's scan order (per Deviation 1 above) -- this project's guard test forbids the literal word "backward" anywhere in `feature_factory.py` outside one documented canary carve-out, as a structural defense against accidental look-ahead bugs being described (or introduced) in comments.
- **Fix:** Reworded the docstring to describe the archived plugin's "descending-index scan order" instead of "backward scan order" -- same meaning, no longer trips the literal-string guard.
- **Files modified:** `src/intelligence/feature_factory.py`
- **Verification:** `test_no_smooth_or_backward_in_factory` passes; full `tests/unit/` suite green.
- **Committed in:** `b58de20a` (Task 2 commit -- caught before the commit, not a follow-up fix)

**3. [Rule 1 - Bug] Descope-guard grep gate initially failed on a docstring explaining the descope, not a real leak**
- **Found during:** Task 2 (running the plan's own descope grep gate: `grep -Eq "PWH|PWL|PDH|PDL|frames.get\("1d""`)
- **Issue:** `_compute_liquidity_pools()`'s own docstring explained the PWH/PWL/PDH/PDL descope rationale using those literal acronyms, which the grep gate (correctly, by design) flags as a substring match regardless of context.
- **Fix:** Reworded the docstring to say "named prior-week/prior-day high/low levels are DESCOPED" instead of spelling out the acronyms, preserving the same explanation without tripping the gate.
- **Files modified:** `src/intelligence/feature_factory.py`
- **Verification:** Grep gate reports "ok: descope holds"; the actual code-level guarantee (no 1d-frame parameter, no PWH/PWL/PDH/PDL computation) was never in question -- confirmed separately via `test_pwh_pwl_pdh_pdl_never_computed`'s `inspect.signature()` check.
- **Committed in:** `b58de20a` (Task 2 commit -- caught before the commit, not a follow-up fix)

---

**Total deviations:** 3 auto-fixed (1 genuine correctness bug ported-and-fixed from the archived source; 2 project-guard-test wording fixes, both caught by automated gates before committing)
**Impact on plan:** All three are correctness/consistency fixes caught by the plan's own automated verification steps working as intended. No scope creep -- none required touching any file outside this task's declared scope.

## Issues Encountered
None beyond the three auto-fixed issues above, all caught and resolved within normal task execution before committing.

## User Setup Required
None -- no external service configuration required.

## Next Phase Readiness
- Plan 04 (supply/demand zones, BOS/CHoCH, AMD cycle) can now consume `fvg_midpoint` and `price_in_premium` as in-pass locals from the same compute pass (soft dependency per 164-RESEARCH.md -- zones default gracefully if either is somehow absent, but the computed `zone_strength`/`zone_friction_score` differ, so Plan 04 must append its block after this plan's FVG + Liquidity Pools block, matching the established single-pass ordering)
- The remaining 18 SMC `FeatureVector` fields (supply/demand zones, BOS/CHoCH, AMD cycle) stay `None` placeholders at both `_build_feature_vector(...)` call sites in `feature_factory.py` -- intentional, Plan 04's scope, not touched here
- No blockers. Full `tests/unit/` suite green (0 failures), ruff/black clean, binary-pattern scanner clean.

## Known Stubs
The 18 remaining SMC `FeatureVector` fields (supply/demand zones, BOS/CHoCH, AMD cycle) are still `None` placeholders at both `_build_feature_vector(...)` call sites -- intentional, out of this plan's scope per its own objective (Plan 03 covers only the FVG/sweeps/pools cluster). Plan 04 replaces them.

---
*Phase: 164-smc-institutional-footprint-primitives*
*Completed: 2026-07-28*

## Self-Check: PASSED

- FOUND: src/intelligence/feature_factory.py
- FOUND: tests/unit/intelligence/test_smc_fvg.py
- FOUND: tests/unit/intelligence/test_smc_liquidity.py
- FOUND commit: b0c0bfa5
- FOUND commit: b58de20a
