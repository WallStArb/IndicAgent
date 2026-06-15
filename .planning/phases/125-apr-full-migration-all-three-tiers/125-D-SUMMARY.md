---
phase: 125-apr-full-migration-all-three-tiers
plan: "04"
subsystem: intelligence/trading
tags: [confidence-weights, weight-validation, cis-scorer, apr, tier-b-plugins, parameter-store]

# Dependency graph
requires:
  - phase: 125-apr-full-migration-all-three-tiers
    plan: "02"
    provides: _validate_weights_sum utility in confidence_utils.py
  - phase: 125-apr-full-migration-all-three-tiers
    plan: "03"
    provides: anchored_vwap_reversion APR weight migration (reference pattern)

provides:
  - weight-sum invariant guard in all 5 remaining applicable Tier B plugins
  - BOOTSTRAP_WEIGHTS renamed to _CONFIG_UNAVAILABLE_FALLBACK in cis_scorer.py
  - D-01 verified: CacheManager._load_cis_weights -> CISScorer.update_weights chain confirmed intact

affects:
  - src/intelligence/trading/gap_analysis_setup.py
  - src/intelligence/trading/mean_reversion.py
  - src/intelligence/trading/momentum_breakout.py
  - src/intelligence/trading/squeeze_expansion.py
  - src/intelligence/trading/vwap_reclaim.py
  - src/intelligence/trading/cis_scorer.py

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_validate_weights_sum called immediately after all weight reads in compute_full() - fails fast before any signal fires"
    - "BOOTSTRAP_WEIGHTS deprecated alias preserved for backward compat; actual constant is _CONFIG_UNAVAILABLE_FALLBACK"
    - "CacheManager mediates scorer updates via cis_weights_version comparison (Pitfall 4 pattern)"

key-files:
  created: []
  modified:
    - src/intelligence/trading/confidence_utils.py (worktree dependency: _validate_weights_sum + cfg->config rename)
    - src/intelligence/trading/gap_analysis_setup.py
    - src/intelligence/trading/mean_reversion.py
    - src/intelligence/trading/momentum_breakout.py
    - src/intelligence/trading/squeeze_expansion.py
    - src/intelligence/trading/vwap_reclaim.py
    - src/intelligence/trading/cis_scorer.py

key-decisions:
  - "Worktree lacks Plan 02 confidence_utils.py changes; applied _validate_weights_sum and cfg->config rename inline (Rule 3 deviation)"
  - "Deprecated alias BOOTSTRAP_WEIGHTS = _CONFIG_UNAVAILABLE_FALLBACK added because weight_updater.py and 2 test files import by old name"
  - "D-01 satisfied by existing infrastructure: no new DB load code added to CISScorer.__init__"
  - "CacheManager mediates weight push via signal_processor.sync_cis_weights() at every bar start - verified chain"

requirements-completed:
  - APR-02
  - APR-03

# Metrics
duration: 12min
completed: "2026-06-15"
---

# Phase 125 Plan 04 (D): _validate_weights_sum in 5 Tier B Plugins + cis_scorer Rename Summary

**Weight-sum invariant guard wired across all 5 remaining Tier B plugins; BOOTSTRAP_WEIGHTS cold-start constant renamed to _CONFIG_UNAVAILABLE_FALLBACK; CacheManager -> CISScorer weight-load chain (D-01) verified intact.**

## Performance

- **Duration:** 12 min
- **Completed:** 2026-06-15
- **Tasks:** 3 (2 code changes + 1 verification)
- **Files modified:** 7

## Accomplishments

- Added `_validate_weights_sum` import and call to 5 Tier B plugins (gap_analysis_setup, mean_reversion, momentum_breakout, squeeze_expansion, vwap_reclaim) immediately after their weight reads in `compute_full()`
- Renamed `BOOTSTRAP_WEIGHTS` to `_CONFIG_UNAVAILABLE_FALLBACK` in `cis_scorer.py`; added deprecated alias to preserve existing imports
- Verified D-01 compliance: `CacheManager._load_cis_weights()` queries `cis_weights` table at startup and every 30 min; `signal_processor.sync_cis_weights()` calls `CISScorer.update_weights()` on every bar when version changes
- Confirmed `liquidity_sweep_reclaim` and `supply_demand_setup` correctly excluded - they use `base_conf + scale * ramp()` formulas, not weighted sums

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add _validate_weights_sum to 5 Tier B plugins | e49c0448 | confidence_utils.py, gap_analysis_setup.py, mean_reversion.py, momentum_breakout.py, squeeze_expansion.py, vwap_reclaim.py |
| 2 | Rename BOOTSTRAP_WEIGHTS to _CONFIG_UNAVAILABLE_FALLBACK | 511ac7cc | cis_scorer.py |
| 3 | Verify CacheManager._load_cis_weights chain (D-01) | - | No code changes needed |

## Files Modified

- `src/intelligence/trading/confidence_utils.py` - Added `_validate_weights_sum` function + `cfg->config` rename (worktree dependency from Plan 02)
- `src/intelligence/trading/gap_analysis_setup.py` - Import + call with `{geo, vol, timing, type}` weights
- `src/intelligence/trading/mean_reversion.py` - Import + call with `{rsi_extreme, div_score, vol_stability, sr_proximity}` weights
- `src/intelligence/trading/momentum_breakout.py` - Import + call with `{roc, vol, break_margin}` weights
- `src/intelligence/trading/squeeze_expansion.py` - Import + call with `{squeeze_bars, vol_expansion, momentum}` weights
- `src/intelligence/trading/vwap_reclaim.py` - Import + call with `{vol, duration, trend_align, sr_proximity}` weights
- `src/intelligence/trading/cis_scorer.py` - Renamed constant, updated `__init__`, docstrings, added deprecated alias

## Decisions Made

- Applied Plan 02's `confidence_utils.py` changes to this worktree (Rule 3 - blocking): the worktree branched from a base commit before Plan 02 merged, so `_validate_weights_sum` was missing from confidence_utils.py in this worktree
- Added deprecated alias `BOOTSTRAP_WEIGHTS = _CONFIG_UNAVAILABLE_FALLBACK` because `weight_updater.py` and two test files (`test_cis_scorer_vectorization.py`, `test_weight_updater.py`) import the old name by value
- D-01 verification confirmed no new code needed: the chain is `CacheManager._load_cis_weights()` (queries DB at startup + 1800s refresh) -> `CacheSnapshot.cis_weights` -> `signal_processor.sync_cis_weights()` (per bar, version-guarded) -> `CISScorer.update_weights()`; `_CONFIG_UNAVAILABLE_FALLBACK` is only used in the cold-start window before CacheManager first runs

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] confidence_utils.py missing _validate_weights_sum in worktree**
- **Found during:** Task 1 (Add _validate_weights_sum to 5 Tier B plugins)
- **Issue:** Worktree branched before Plan 02's confidence_utils.py changes were merged. Import of `_validate_weights_sum` failed at runtime - function didn't exist in the worktree's confidence_utils.py
- **Fix:** Applied Plan 02's two changes to this worktree's confidence_utils.py: added `_validate_weights_sum()` function and renamed `cfg` parameter to `config` in `set_config_service()`
- **Files modified:** `src/intelligence/trading/confidence_utils.py`
- **Verification:** All 5 plugin imports succeeded; 10 test failures match baseline (no new failures)
- **Committed in:** e49c0448 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking dependency)
**Impact on plan:** Necessary worktree fix; the same changes exist in main repo from Plan 02. No scope creep.

## Issues Encountered

- Pre-commit hook requires `ruff` and `black` in PATH but the worktree has no `.venv`. Fixed by prepending `/home/bg/dev/indicagent/.venv/bin` to PATH on commit invocations.
- Test baseline of 42 failures cited in plan was outdated; actual baseline is 10 failures (same in main repo and worktree).

## Next Phase Readiness

- All 6 applicable Tier B plugins now call `_validate_weights_sum` after weight loading (5 in this plan + anchored_vwap_reversion from Plan 03)
- `cis_scorer.py` rename complete; `_CONFIG_UNAVAILABLE_FALLBACK` name correctly signals cold-start-only semantics
- Phase 125 Plan 05 (E) can proceed

---

## Self-Check: PASSED

- [x] `src/intelligence/trading/gap_analysis_setup.py`: `_validate_weights_sum` present
- [x] `src/intelligence/trading/mean_reversion.py`: `_validate_weights_sum` present
- [x] `src/intelligence/trading/momentum_breakout.py`: `_validate_weights_sum` present
- [x] `src/intelligence/trading/squeeze_expansion.py`: `_validate_weights_sum` present
- [x] `src/intelligence/trading/vwap_reclaim.py`: `_validate_weights_sum` present
- [x] `liquidity_sweep_reclaim.py`: no `_validate_weights_sum` (exempt)
- [x] `supply_demand_setup.py`: no `_validate_weights_sum` (exempt)
- [x] `src/intelligence/trading/cis_scorer.py`: `_CONFIG_UNAVAILABLE_FALLBACK` defined; `BOOTSTRAP_WEIGHTS` alias present
- [x] Commit `e49c0448`: in git log
- [x] Commit `511ac7cc`: in git log
- [x] 10 test failures = baseline (no new failures introduced)
- [x] CacheManager._load_cis_weights -> CISScorer.update_weights chain verified intact (D-01)

*Phase: 125-apr-full-migration-all-three-tiers*
*Completed: 2026-06-15*
