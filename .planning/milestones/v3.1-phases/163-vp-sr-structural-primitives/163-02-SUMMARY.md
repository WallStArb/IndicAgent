---
phase: 163-vp-sr-structural-primitives
plan: 02
subsystem: database
tags: [timescaledb, feature-factory, volume-profile, feature-vectors, session-state]

# Dependency graph
requires:
  - phase: 163-01
    provides: "17 new feature_vectors columns + FeatureVector dataclass fields + FeatureCache.update_session_vp() mutator (session POC/VAH/VAL/HVN/LVN raw-level accumulator)"
provides:
  - "cache.update_session_vp() wired into both FeatureFactory.compute() (live) and compute_batch() (backfill), called once per bar including warm-up"
  - "_derive_session_vp()/_rolling_poc_price() helpers deriving the 14 ATR-normalized/bounded VP FeatureVector fields from FeatureCache's raw session levels"
  - "compute_batch()'s stale D-05 None-branch removed -- VP is computed from OHLCV identically in live and batch"
  - "Regression test (test_volume_profile_primitives.py): VP non-constant across bars, live==batch parity to 1e-6, no raw price ever persisted"
affects: [163-03, 166]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single shared derivation helper (_derive_session_vp) called from both compute() and compute_batch() -- structurally prevents live/batch divergence rather than relying on a parity test alone"
    - "Neutral-defaults dict (_NEUTRAL_VP_EXTRA) for the tf=='1d' branch, reused verbatim in both compute paths"
    - "Stateless rolling-window POC (D-18) computed inline via the same _compute_session_vp_profile/_compute_session_value_area helpers the session-anchored track uses, guaranteeing identical bucket/tie-break semantics between the two tracks"

key-files:
  created:
    - tests/unit/intelligence/test_volume_profile_primitives.py
  modified:
    - src/intelligence/feature_factory.py
    - services/feature_vector_pipeline.py
    - tests/unit/test_feature_factory.py
    - tests/unit/services/test_backfill_feature_factory.py

key-decisions:
  - "poc_dist_atr/va_position keep the legacy 0.0/0.5 neutral fallback (cold start, degenerate histogram, atr_val<=0) to preserve pre-existing downstream expectations; the 12 new fields fall back to None in the same conditions since they have no legacy default to preserve"
  - "compute_batch()'s loop structurally starts at i=1 (pre-existing, unrelated to this plan) -- update_session_vp() is called for every bar the loop visits (including warm-up), not literally bar index 0, which the loop never visits for any feature"

requirements-completed: ["TODO-153", "D-03", "D-05", "D-13", "D-16"]

# Metrics
duration: ~20min
completed: 2026-07-23
---

# Phase 163 Plan 02: VP Compute-Path Wiring Summary

**Session-anchored volume profile now computes real, non-constant, ATR-normalized values identical between the live streaming path and the batch backfill path -- closing the compute half of todo 153 (schema half closed by Plan 01).**

## Performance

- **Duration:** ~20 min (2 tasks; task commits span 13:06:40-13:06:55 local, base commit 12:50:24)
- **Completed:** 2026-07-23
- **Tasks:** 2/2 completed
- **Files modified:** 5 (1 created, 4 modified)

## Accomplishments

- `cache.update_session_vp()` (Plan 01's mutator) is now invoked once per bar in both the live pipeline (`services/feature_vector_pipeline.py`'s `_process_bar_compute`, before `FeatureFactory.compute()`) and `compute_batch()`'s loop (before the warm-up skip, so the session accumulator stays current through warmup)
- New `_derive_session_vp()` helper in `feature_factory.py` derives all 14 ATR-normalized/bounded VP fields (`poc_dist_atr`, `va_position`, + 12 new structural fields) from `FeatureCache`'s raw `_sess_*` levels plus the compute-path `atr_val` -- a single shared helper called from both `compute()` and `compute_batch()`, so live/batch parity is structural, not just tested
- New `_rolling_poc_price()` helper computes the rolling-480 POC track (D-18) statelessly inline, reusing the same profile/value-area helpers as the session-anchored track for identical bucket/tie-break semantics
- `compute_batch()`'s stale `cross_asset_by_date is not None` -> VP forced `None` branch (the literal todo-153 bug, justified by a never-verified "requires I3 intraday injection" claim) is removed -- VP is now computed from OHLCV identically in both paths (D-05)
- Regression test suite (`tests/unit/intelligence/test_volume_profile_primitives.py`) proves: VP fields vary across a realistic 90-bar intraday sequence (not frozen at 0.0/0.5), live and batch produce identical VP output to 1e-6, and no raw price level is ever persisted on `FeatureVector` (D-16/D-18 guard)
- Verified the regression test actually catches the original bug: temporarily forced `_derive_session_vp` to return constants, confirmed `test_vp_fields_non_constant_batch` fails, reverted

## Task Commits

1. **Task 1: Wire update_session_vp call sites + derive 14 VP outputs; remove D-05 None-branch** - `fde6a2a4` (feat)
2. **Task 2: Regression unit test -- VP non-constant + live/batch parity** - `f1e39433` (test)

## Files Created/Modified

- `src/intelligence/feature_factory.py` - `_NEUTRAL_VP_EXTRA` constant, `_rolling_poc_price()`/`_derive_session_vp()` helpers, `compute()`/`compute_batch()` VP derivation wired through `_build_feature_vector`, stale D-05 docstring/None-branch removed
- `services/feature_vector_pipeline.py` - `cache.update_session_vp()` call added to `_process_bar_compute()` before `FeatureFactory.compute()`
- `tests/unit/intelligence/test_volume_profile_primitives.py` - new regression suite (3 tests: non-constant, live/batch parity, no-raw-price guard)
- `tests/unit/test_feature_factory.py` - 2 tests updated to assert the new raw-session-level derivation mechanism instead of the removed flat `cache.poc_dist_atr`/`cache.va_position` attribute read
- `tests/unit/services/test_backfill_feature_factory.py` - 1 test renamed/rewritten to assert VP is now computed (not forced `None`) in batch mode

## Decisions Made

- **Neutral fallback split by field vintage:** `poc_dist_atr`/`va_position` (pre-existing since before Phase 163) keep their legacy 0.0/0.5 fallback on cold start/degenerate histogram/`atr_val<=0`, matching the established `tf=='1d'` convention already in the codebase. The 12 new fields (brand new to Phase 163, no legacy default to preserve) fall back to `None` in the same conditions -- consistent with every other nullable structural field in the dataclass.
- **compute_batch()'s pre-existing `range(1, len(bars))` loop bound left untouched:** the loop structurally never visits bar index 0 for any feature (not new to this plan) -- `update_session_vp()` is called for every bar the loop *does* visit, satisfying the plan's "every bar including warm-up" requirement without changing loop bounds unrelated to VP.
- **Test rolling window overridden to 15 (not the 480 production default):** the 90-bar synthetic test session is smaller than the 480-bar production default, which would make the rolling and session-anchored POC tracks degenerate (differing only by the single bar `compute_batch()`'s loop excludes from the session accumulator) -- unable to demonstrate real divergence. A smaller override lets the test genuinely exercise `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 3 pre-existing tests encoded the now-removed VP behavior**
- **Found during:** Task 1, running the full unit suite after wiring the new derivation
- **Issue:** `tests/unit/services/test_backfill_feature_factory.py::test_vp_sr_none_when_batch_mode` asserted VP fields are forced `None` when `cross_asset_by_date` is provided -- exactly the D-05 behavior this task removes. `tests/unit/test_feature_factory.py::test_session_poc_dist_from_cache`/`test_session_va_position_from_cache` asserted `poc_dist_atr`/`va_position` are read directly from flat `FeatureCache.poc_dist_atr`/`.va_position` attributes -- those attributes are no longer read anywhere in the compute path (superseded by `_derive_session_vp()` reading `cache._sess_poc`/`_sess_vah`/`_sess_val` + `atr_val`)
- **Fix:** Rewrote `test_vp_sr_none_when_batch_mode` -> `test_vp_computed_from_ohlcv_in_batch_mode` to assert VP is now computed (not `None`) in batch mode, while `sr_support_dist`/`sr_resist_dist` still read 0.0 from cache (Plan 03's job, unchanged). Rewrote the two session-primitive tests to set `cache._sess_poc`/`_sess_val`/`_sess_vah` directly and assert the new formula-based derivation (using values chosen so the expected result is exactly computable without needing to reproduce the internal ATR calculation: `_sess_poc == close` gives an exact-0.0 expected `poc_dist_atr`; `va_position`'s formula has no ATR dependency at all, so it's directly computable)
- **Files modified:** `tests/unit/services/test_backfill_feature_factory.py`, `tests/unit/test_feature_factory.py`
- **Verification:** Full unit suite green (`pytest tests/unit/ -q`, 0 failures, 3 pre-existing unrelated skips)
- **Committed in:** `fde6a2a4` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3, blast-radius test updates)
**Impact on plan:** The fix was a necessary, mechanical consequence of Task 1's deliberate behavior change (matching Plan 01's own precedent of updating blast-radius test fixtures). No scope creep -- S/R fields (`sr_support_dist`/`sr_resist_dist`) remain untouched throughout, still reading 0.0 from cache pending Plan 03.

## Issues Encountered

None beyond the deviation documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 03 can now wire real S/R computation (`resistance_strength`/`support_strength`/`resistance_age_bars`/`support_age_bars`/`sr_level_count`) and populate `cache.sr_support_dist`/`cache.sr_resist_dist` for real, alongside the now-real VP fields this plan delivers
- No blockers. `ic_engine`'s feature_registry alignment gate remains satisfied (no schema changes in this plan, only computation wiring)
- Phase 166's Wave-0 prerequisite (`sr_support_dist`/`sr_resist_dist` non-NULL) is NOT yet satisfied by this plan -- that is explicitly Plan 03's scope

## Self-Check: PASSED

- Both key files confirmed present on disk: `src/intelligence/feature_factory.py`, `services/feature_vector_pipeline.py`
- New test file confirmed present: `tests/unit/intelligence/test_volume_profile_primitives.py`
- Both commits (`fde6a2a4`, `f1e39433`) confirmed present in `git log`

---
*Phase: 163-vp-sr-structural-primitives*
*Completed: 2026-07-23*
