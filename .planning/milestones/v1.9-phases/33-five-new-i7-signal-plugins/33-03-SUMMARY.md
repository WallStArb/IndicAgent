---
phase: 33-five-new-i7-signal-plugins
plan: 03
subsystem: intelligence
tags: [plugin-registry, i7, aggregator, trading-setups]

# Dependency graph
requires:
  - phase: 33-01
    provides: Six new I7 plugin implementations (FailedBreakout, ORB15, ORB30, PrevDayLevelTest, SecondLegContinuation, VCP)
  - phase: 33-02
    provides: regime_type attributes on all I7 plugin classes
provides:
  - All six new I7 plugins wired into production pipeline via register_plugins.py
  - TIER_I7 updated from 17 to 23 entries
  - TREND_SETUPS frozenset updated with four trend-mode plugin names
  - Plugin count tests updated to reflect new totals (98 -> 104, 17 -> 23)
affects: [signal_generator_service, market_analysis_service, aggregator]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Plugin registration follows alphabetical import order within trading block", "TREND_SETUPS frozenset drives hurst quality routing in aggregator"]

key-files:
  created: []
  modified:
    - src/intelligence/register_plugins.py
    - src/intelligence/trading/aggregator.py
    - tests/unit/intelligence/test_i7_registration.py
    - tests/unit/intelligence/test_plugin_registry.py

key-decisions:
  - "trad_FailedBreakout excluded from TREND_SETUPS — mean_reversion regime type routes to hurst_mr_quality"
  - "trad_PrevDayLevelTest excluded from TREND_SETUPS — any regime type handles both trend and mean-reversion internally"
  - "trad_ORB15, trad_ORB30, trad_SecondLegContinuation, trad_VCP added to TREND_SETUPS — trend-continuation setups requiring directional momentum"

patterns-established:
  - "Plugin count tests (test_total_plugin_count, test_tier_i7_has_N_plugins) must be updated whenever TIER_I7 grows"

requirements-completed: [PLUG-01, PLUG-02, PLUG-03, PLUG-04, PLUG-05]

# Metrics
duration: 8min
completed: 2026-03-17
---

# Phase 33 Plan 03: Register New I7 Plugins Summary

**Six new I7 plugins (FailedBreakout, ORB15, ORB30, PrevDayLevelTest, SecondLegContinuation, VCP) wired into production pipeline: TIER_I7 = 23, total plugins = 104, TREND_SETUPS extended to 12 entries**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-17T05:12:57Z
- **Completed:** 2026-03-17T05:20:57Z
- **Tasks:** 1
- **Files modified:** 4

## Accomplishments
- All six new I7 plugins imported and registered in `register_all_plugins()` with alphabetical import ordering
- `TIER_I7` list extended from 17 to 23 entries — `registry.validate_tier()` passes on service startup
- `TREND_SETUPS` frozenset extended from 8 to 12 entries: ORB15, ORB30, SecondLegContinuation, VCP added; FailedBreakout and PrevDayLevelTest correctly excluded
- Plugin count tests updated to track new totals (verified pre-existing 8 test failures were unrelated to these changes)

## Task Commits

Each task was committed atomically:

1. **Task 1: Register all six plugins and update TREND_SETUPS** - `312bab5` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified
- `src/intelligence/register_plugins.py` - Added 6 imports, 6 register_pattern() calls, 6 TIER_I7 entries
- `src/intelligence/trading/aggregator.py` - TREND_SETUPS extended with trad_ORB15, trad_ORB30, trad_SecondLegContinuation, trad_VCP
- `tests/unit/intelligence/test_i7_registration.py` - Updated expected set to 23 plugins, count assertion 98 -> 104
- `tests/unit/intelligence/test_plugin_registry.py` - Updated test_tier_i7_has_17_plugins -> test_tier_i7_has_23_plugins

## Decisions Made
- FailedBreakout excluded from TREND_SETUPS: mean_reversion regime type requires hurst_mr_quality routing, not trend quality
- PrevDayLevelTest excluded from TREND_SETUPS: "any" regime type handles both internally, no regime routing needed
- ORB15/ORB30/SecondLegContinuation/VCP added to TREND_SETUPS: all are trend-continuation setups that require directional momentum (hmm_regime=1 or 2) for edge

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated plugin count tests to match new plugin totals**
- **Found during:** Task 1 (running test suite verification)
- **Issue:** `test_tier_i7_has_17_plugins` and `test_total_plugin_count` hardcode counts that must increase when new plugins are added — they failed with 23 != 17 and 104 != 98
- **Fix:** Updated both tests to assert new correct values (23 and 104); updated expected_i7 set in test_i7_plugins_registered to include all 6 new plugin names
- **Files modified:** tests/unit/intelligence/test_i7_registration.py, tests/unit/intelligence/test_plugin_registry.py
- **Verification:** Both tests now pass; 8 pre-existing unrelated failures confirmed identical before and after changes
- **Committed in:** 312bab5 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug: stale hardcoded counts in plugin count tests)
**Impact on plan:** Necessary correctness fix. No scope creep — the tests existed specifically to track plugin counts and required updating.

## Issues Encountered
- 8 pre-existing test failures exist in the suite (test_signals_route, test_settings, test_feature_writer_config, test_historical_backfill) — all verified to fail before our changes and are unrelated to plugin registration. Not fixed (out of scope).

## Next Phase Readiness
- All 23 I7 plugins registered and discoverable by signal_generator_service on restart
- Services will auto-discover the new plugins — no manual configuration needed
- Phase 34 (new I4 infrastructure: AVWAP, Volume Profile) is unblocked

---
*Phase: 33-five-new-i7-signal-plugins*
*Completed: 2026-03-17*
