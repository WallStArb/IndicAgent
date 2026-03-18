---
phase: 34-i4-infrastructure-anchored-vwap-volume-profile
plan: 01
subsystem: intelligence
tags: [vwap, anchored-vwap, i4-context, plugins, schema, migration, tdd]

# Dependency graph
requires:
  - phase: 32-stop-architecture
    provides: trade_framer.py, stop architecture stable before new plugins

provides:
  - ctx_AnchoredVWAP plugin in src/intelligence/context/anchored_vwap.py with 15 output fields
  - 7 new VWAP fields: avwap_upper_band, avwap_lower_band, swing_vwap_upper_band, swing_vwap_lower_band, session_vwap_deviation_sigma, swing_vwap_deviation_sigma, session_vwap_deviation_velocity
  - I4Context schema extended with all 15 VWAP fields
  - I3Structure cleaned of VWAP fields (67 fields, was 75)
  - TIER_I4 updated to include ctx_AnchoredVWAP

affects:
  - phase: 34-02 (VolumeProfile plugin may use VWAP fields)
  - phase: 34-03 (I7 VWAP deviation/reclaim setups consume these fields)
  - market_analysis_service (runs I4 pipeline including new plugin)
  - intelligence_features hypertable (new VWAP fields in i4 JSONB)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "I4 plugins receive I3 swing outputs (swing_high_idx, swing_low_idx) via features dict — DAG ordering ensures availability"
    - "_state dict keyed by (symbol, timeframe) for per-stream velocity tracking"
    - "TDD: RED (test commit) → GREEN (implementation commit) pattern"

key-files:
  created:
    - src/intelligence/context/anchored_vwap.py
    - tests/unit/intelligence/context/test_anchored_vwap.py
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/register_plugins.py
    - tests/unit/intelligence/test_i3_new_plugins.py
  deleted:
    - src/intelligence/structure/anchored_vwap.py

key-decisions:
  - "AnchoredVWAP migrated from I3/structure/ to I4/context/ so it runs after I3 swing detection and provides swing anchor index to swing VWAP computation"
  - "velocity field uses 3-bar rolling sigma history in _state keyed by (symbol, timeframe) to track per-stream deviation change rate"
  - "std bands use population std (np.std, ddof=0) over all session bars for stability"

patterns-established:
  - "I4 context plugins can consume I3 structural outputs via features dict without direct import"
  - "Sigma + velocity pattern: compute deviation sigma each bar, store in _state, derive velocity from slope over 3-bar window"

requirements-completed: [VWAP-01]

# Metrics
duration: 5min
completed: 2026-03-17
---

# Phase 34 Plan 01: AnchoredVWAP I4 Migration Summary

**AnchoredVWAP migrated from I3/structure/ to I4/context/ with 15 output fields: 8 backward-compatible originals + 7 new std band, sigma, and velocity metrics for I7 setup consumption**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-17T19:28:32Z
- **Completed:** 2026-03-17T19:33:52Z
- **Tasks:** 1 (TDD: 2 commits)
- **Files modified:** 5 (1 created, 3 modified, 1 deleted)

## Accomplishments
- Migrated AnchoredVWAPPlugin from `src/intelligence/structure/anchored_vwap.py` (name: `struct_AnchoredVWAP`) to `src/intelligence/context/anchored_vwap.py` (name: `ctx_AnchoredVWAP`)
- Added 7 new fields: 2x std deviation bands for session and swing VWAP, 2x deviation sigma scores, 1x sigma velocity from 3-bar rolling state
- Updated I3Structure (removed 8 VWAP fields, 75 -> 67), updated I4Context (added 15 VWAP fields, 60 -> 75)
- TIER_I3 and validate_schema_coverage() updated to reflect migration
- 11 new unit tests passing; all 1225 intelligence unit tests pass

## Task Commits

Each task was committed atomically:

1. **TDD RED: test_anchored_vwap.py** - `15862f1` (test)
2. **TDD GREEN: migration + schema + registration** - `cd47e50` (feat)

_Note: TDD tasks have two commits (test RED → implementation GREEN)_

## Files Created/Modified
- `src/intelligence/context/anchored_vwap.py` - New I4 plugin with 15 output fields, velocity state tracking
- `src/intelligence/structure/anchored_vwap.py` - DELETED (migrated)
- `src/intelligence/schemas.py` - I3Structure: removed 8 VWAP fields; I4Context: added 15 VWAP fields
- `src/intelligence/register_plugins.py` - Import updated, TIER_I3 -1, TIER_I4 +1, validate_schema_coverage() updated
- `tests/unit/intelligence/context/test_anchored_vwap.py` - 11 new unit tests
- `tests/unit/intelligence/test_i3_new_plugins.py` - Updated imports and assertions to reflect migration

## Decisions Made
- Kept `capability_tags = frozenset({"context"})` (not "structure") to signal correct tier membership
- Used population std (np.std, no ddof) over all session bars — stable against single-bar outliers
- Velocity = (sigma[-1] - sigma[0]) / window_len over 3-bar rolling window; 0.0 when only 1 bar in history

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test_i3_new_plugins.py to import from new module path**
- **Found during:** Task 1 (GREEN phase — run full test suite)
- **Issue:** `test_i3_new_plugins.py` imported `from src.intelligence.structure.anchored_vwap import AnchoredVWAPPlugin` and checked for `struct_AnchoredVWAP` in TIER_I3 and registry — both broken after deletion
- **Fix:** Updated all imports to `from src.intelligence.context.anchored_vwap import AnchoredVWAPPlugin`; updated registration assertions to check `ctx_AnchoredVWAP` in TIER_I4 (not TIER_I3); updated `test_i3structure_accepts_new_fields` to not pass `session_vwap` to I3Structure and added I4Context assertion
- **Files modified:** `tests/unit/intelligence/test_i3_new_plugins.py`
- **Verification:** `pytest tests/unit/intelligence/test_i3_new_plugins.py` — all pass
- **Committed in:** `cd47e50` (task commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 bug — stale test imports from deleted module)
**Impact on plan:** Fix was necessary for correctness; all affected tests verified after update.

## Issues Encountered
- Pre-existing test failure in `tests/unit/intelligence/test_setup_performance_updater.py::TestWindowAndNullHandling::test_compute_setup_performance_30day_window` — confirmed pre-existing via git stash; unrelated to VWAP migration. Deferred to `deferred-items.md`.

## Next Phase Readiness
- `ctx_AnchoredVWAP` plugin available in TIER_I4 with all 15 fields
- I4Context schema validated via `validate_schema_coverage()` in `test_plugin_registry.py`
- I7 VWAP deviation/reclaim setups in Plan 03 can consume `session_vwap_deviation_sigma`, `avwap_upper_band`, `avwap_lower_band`, `swing_vwap_deviation_sigma` directly from I4Context
- Plan 02 (VolumeProfile) can proceed independently — no dependency on VWAP fields

---
*Phase: 34-i4-infrastructure-anchored-vwap-volume-profile*
*Completed: 2026-03-17*
