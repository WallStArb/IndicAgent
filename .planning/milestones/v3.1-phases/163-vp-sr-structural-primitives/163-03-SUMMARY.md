---
phase: 163-vp-sr-structural-primitives
plan: 03
subsystem: database
tags: [feature-factory, support-resistance, pivot-clustering, feature-vectors, atr-normalization]

# Dependency graph
requires:
  - phase: 163-01
    provides: "17 new feature_vectors columns + FeatureVector dataclass fields (incl. the 5 D-19 S/R fields) + feature.sr.* APR config on FeatureFactoryConfig (sr_window, sr_cluster_atr_mult, sr_lookback_by_tf)"
  - phase: 163-02
    provides: "VP compute-path wiring pattern (single shared derivation helper called from both compute()/compute_batch(), pre-sliced causal windows) mirrored here for S/R"
provides:
  - "_compute_sr_dist_atr()/_cluster_levels()/_finalize_cluster() in feature_factory.py: stateless inline pivot-clustering S/R, ported from i3_structure/support_resistance.py (D-02/D-04)"
  - "sr_support_dist/sr_resist_dist computed in ATR units (not percent) in both compute() and compute_batch()"
  - "resistance_strength/support_strength/resistance_age_bars/support_age_bars/sr_level_count populated from the same cluster objects (D-19), closing a silent 5-field omission caught post cross-AI review"
  - "S/R computed for tf=='1d' too (decoupled from VP's tf=='1d' neutral-default branch -- daily pivot-clustering is valid, unlike session VP)"
  - "Regression suite (test_support_resistance_primitives.py): non-constant, ATR-unit-pinned, live==batch parity, D-19 non-null/non-constant guard"
affects: [166]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single shared helper (_compute_sr_dist_atr) called from both compute()/compute_batch(), same structural-parity-over-testing-alone approach as Plan 02's _derive_session_vp"
    - "compute_batch() pre-slices the causal window (bars[max(0,i-lookback+1):i+1]) before calling the helper, so the helper's own internal tail-slice is a no-op there but correctly windows the full growing history in compute()'s live path -- one implementation, two callers, no lookahead"

key-files:
  created:
    - tests/unit/intelligence/test_support_resistance_primitives.py
  modified:
    - src/intelligence/feature_factory.py
    - tests/unit/test_feature_factory.py
    - tests/unit/services/test_backfill_feature_factory.py

key-decisions:
  - "S/R is NOT gated by tf=='1d' the way VP is -- per the plan's own scope note, pivot-clustering over daily bars is structurally valid (no single-bar-has-no-distribution constraint), so S/R is computed unconditionally in both compute() and compute_batch(), independent of the VP tf branch"
  - "_compute_sr_dist_atr's internal '[-lookback:]' tail-slice works correctly for both callers without divergent code paths: compute() passes the full live-history array (ending at the current bar), so the tail-slice is the real window; compute_batch() pre-slices the causal per-bar window itself, so the helper's tail-slice is a harmless no-op on an already-correctly-sized array"

requirements-completed: ["TODO-153", "D-02", "D-04", "D-05", "D-06", "D-14", "D-19"]

# Metrics
duration: ~35min
completed: 2026-07-23
---

# Phase 163 Plan 03: S/R Compute-Path Wiring Summary

**Support/resistance now computes real, ATR-normalized, non-constant pivot-clustering values (7 fields, not 2) identical between live and batch, fully closing todo 153 -- plus 5 D-19 strength/age/count fields that were previously silently discarded.**

## Performance

- **Duration:** ~35 min (2 tasks)
- **Completed:** 2026-07-23
- **Tasks:** 2/2 completed
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- `_compute_sr_dist_atr()` (feature_factory.py) ports `i3_structure/support_resistance.py`'s pivot-clustering algorithm verbatim: `find_peaks`/`find_troughs` over a bounded per-tf lookback window, clustered within `atr_val * config.sr_cluster_atr_mult` via ported `_cluster_levels`/`_finalize_cluster`, nearest resistance above close / nearest support below close
- Distance output converted from the archived plugin's PERCENT distance to ATR units (D-02): `sr_resist_dist = (level - close) / atr_val`
- 5 D-19 fields (`resistance_strength`, `support_strength`, `resistance_age_bars`, `support_age_bars`, `sr_level_count`) populated from the exact same cluster objects the distance calc already builds -- zero extra passes over the data
- Both `compute()` (live) and `compute_batch()` (backfill) call the identical helper; `compute_batch()` pre-slices the causal window ending at the current bar (`bars[max(0,i-lookback+1):i+1]`) to guarantee no lookahead
- S/R is computed for `tf=='1d'` too -- decoupled entirely from VP's `tf=='1d'` neutral-default branch, since daily pivot-clustering is structurally valid (unlike session-anchored VP)
- Confirmed zero remaining "requires I3"/"I3 intraday" text and zero `ctx_SRConsensus`/`zone_engine`/`collect_sr_candidates` references (D-05/D-14)
- New regression suite (`test_support_resistance_primitives.py`, 4 tests) proves: S/R non-constant across bars, ATR-unit conversion pinned via a hand-constructed deterministic micro-case (constant-true-range bars so Wilder ATR converges to exactly 1.0), live==batch parity to 1e-6 for all 7 fields, and the 5 D-19 fields are non-null/non-negative/non-constant
- Verified all 4 new assertions actually fail when `_compute_sr_dist_atr` is forced to return its all-zero fallback (temporary local edit, reverted before committing) -- confirms the tests catch the regressions they claim to

## Task Commits

1. **Task 1: Inline stateless S/R computation in compute()/compute_batch() + D-05 docstring cleanup** - `bd485e4e` (feat)
2. **Task 2: Regression unit test -- S/R non-constant, ATR-unit, live/batch parity** - `a748d13d` (test)

## Files Created/Modified

- `src/intelligence/feature_factory.py` - `_compute_sr_dist_atr()`/`_cluster_levels()`/`_finalize_cluster()` helpers, `find_peaks`/`find_troughs` import, `compute()`/`compute_batch()` wired to call the helper and thread all 7 fields through `_build_feature_vector`, `compute_batch()` docstring corrected (no longer claims sr_* still reads from cache)
- `tests/unit/intelligence/test_support_resistance_primitives.py` - new regression suite (4 tests: non-constant, ATR-unit micro-case, live/batch parity, D-19 non-constant)
- `tests/unit/test_feature_factory.py` - 2 tests updated: `test_session_sr_support_from_cache` -> `test_sr_computed_from_ohlcv_not_cache` (asserts cache stub values now have no effect); `test_1d_tf_session_features_are_defaults` -> `test_1d_tf_vp_features_are_defaults` (removed the now-incorrect sr_*==0.0 assertions for tf=='1d', since S/R is no longer forced neutral there)
- `tests/unit/services/test_backfill_feature_factory.py` - `test_vp_computed_from_ohlcv_in_batch_mode` updated: replaced the stale `sr_support_dist == 0.0` cache-default assertion with a finiteness check, matching the new real computation

## Decisions Made

- **S/R computed unconditionally regardless of tf, unlike VP:** the plan explicitly calls out that pivot-clustering over daily bars is valid (S/R doesn't share VP's "a single daily bar has no intraday distribution" constraint), so the S/R block was pulled entirely out of the `tf=='1d'` branch that still gates VP's 14 fields.
- **No lookahead risk despite one shared helper for two different windowing strategies:** `_compute_sr_dist_atr` always tail-slices its `highs`/`lows`/`volume` inputs to `lookback` bars internally. `compute()` passes the full live-history array (whose last element IS the current bar), so this tail-slice is the real causal window. `compute_batch()` pre-slices `bars[max(0,i-lookback+1):i+1]` itself before calling the helper, so the helper's internal tail-slice is a harmless no-op (the array is already <= lookback bars). One implementation, two callers, verified via the live==batch parity test.

## Deviations from Plan

None - plan executed exactly as written. Task 1's `services/backfill_feature_factory.py` "requires I3" docstring cleanup (D-05) had already been completed by Plan 02 (verified via grep before starting, confirmed zero occurrences) -- no change was needed to that file in this plan, consistent with the plan's own read_first note pointing at a docstring that Plan 02's D-05 fix had already removed.

### Blast-radius test updates (mechanical, not deviations from scope)

2 pre-existing tests in `test_feature_factory.py` and 1 in `test_backfill_feature_factory.py` encoded the now-removed cache-stub S/R behavior (same class of update as Plan 01/02's own blast-radius fixes for their respective schema/VP changes). These were updated in Task 1's commit to assert the new real-computation behavior instead of the old stub passthrough. Not logged as Rule 3 deviations since they were anticipated by the plan's acceptance criteria ("no cache.sr_support_dist / cache.sr_resist_dist reads remain in the non-cold-start paths").

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- todo 153 is now fully closed: both VP (Plan 02) and S/R (this plan) compute real, ATR-normalized, non-constant values in both live and batch paths, with regression tests proving it.
- Phase 166's Wave-0 prerequisite (`sr_support_dist`/`sr_resist_dist` non-NULL, referenced in that phase's structural-candidate work) is now satisfied.
- No blockers. `ic_engine`'s feature_registry alignment gate remains satisfied (no schema changes in this plan, only computation wiring -- Plan 01 already added all 17 columns/registry rows).

## Self-Check: PASSED

- All 4 key files confirmed present on disk: `src/intelligence/feature_factory.py`, `tests/unit/intelligence/test_support_resistance_primitives.py`, `tests/unit/test_feature_factory.py`, `tests/unit/services/test_backfill_feature_factory.py`
- Both commits (`bd485e4e`, `a748d13d`) confirmed present in `git log`
- Full unit suite green (`pytest tests/unit/ -q`, 0 failures, 3 pre-existing unrelated skips)

---
*Phase: 163-vp-sr-structural-primitives*
*Completed: 2026-07-23*
