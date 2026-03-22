---
phase: 47-shadow-mode-graduation
plan: 04
subsystem: infra
tags: [shadow-mode, cross-asset, feature-flag, kafka, settings]

requires:
  - phase: 47-03
    provides: roll monitor scaffolding removal; cross-asset 7-day pre-enable validation confirmed
  - phase: 37
    provides: cross_asset_service, CROSS_ASSET_ENABLED field, topic_cross_asset stream key, pipeline wiring

provides:
  - Cross-asset intelligence unconditionally active across all 4 services
  - Settings.cross_asset_enabled removed — no conditional code paths remain
  - CrossAssetService always starts (no disabled-state early exit)
  - feature_pipeline_service, signal_generator_service, feature_writer_service always subscribe to cross_asset topic

affects:
  - Phase 49 ML scoring — cross-asset features are now guaranteed non-null for EQ_INDEX training rows
  - Any future service that reads Settings — cross_asset_enabled attribute no longer exists

tech-stack:
  added: []
  patterns:
    - "Graduated feature flag removal: remove attribute, remove all conditional branches, update tests to remove flag setup lines and add missing cache attrs"

key-files:
  created: []
  modified:
    - services/cross_asset_service.py
    - services/feature_pipeline_service.py
    - services/signal_generator_service.py
    - services/feature_writer_service.py
    - src/config/settings.py
    - tests/unit/service_tests/test_cross_asset_service.py
    - tests/unit/service_tests/test_signal_generator_service.py
    - tests/unit/service_tests/test_feature_pipeline_vix_injection.py
    - tests/unit/test_cross_asset_features.py

key-decisions:
  - "Removed test_cross_asset_disabled_no_cross_asset_frames — tests behavior that no longer exists (flag gone); replacement is implicit in EQ_INDEX guard test always passing"
  - "Added svc._cross_asset_cache = {} to test setups that use ESH6 (EQ_INDEX) — required now that injection is unconditional and __new__ pattern skips __init__"
  - "Kept cross_asset_window_bars and cross_asset_metrics_port in Settings — these are runtime tuning, not feature flags"

patterns-established:
  - "Services either participate in the DAG or they don't — no conditional subscription paths for graduated features"

requirements-completed:
  - SHADOW-02

duration: 15min
completed: 2026-03-22
---

# Phase 47 Plan 04: Remove CROSS_ASSET_ENABLED Scaffolding Summary

**CROSS_ASSET_ENABLED feature flag fully removed from 4 services and Settings — cross-asset intelligence unconditionally active in DAG (SHADOW-02 graduated)**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-22T~13:00Z (continuation from Task 1 checkpoint)
- **Completed:** 2026-03-22
- **Tasks:** 1 (Task 2 — Task 1 completed prior session as human-verify checkpoint)
- **Files modified:** 9

## Accomplishments
- Removed `_cross_asset_enabled` attribute from all 4 services (`cross_asset_service`, `feature_pipeline_service`, `signal_generator_service`, `feature_writer_service`)
- Removed `cross_asset_enabled` field from `Settings` (keeping `cross_asset_window_bars` and `cross_asset_metrics_port`)
- Made cross_asset topic subscription and frame injection unconditional in all services
- Removed early-exit guard from `CrossAssetService.start()` — service always runs
- Updated 4 test files to remove `_cross_asset_enabled` setup lines and add missing `_cross_asset_cache` attributes
- All 2749 unit tests pass

## Task Commits

1. **Task 1: Enable CROSS_ASSET_ENABLED, restart services, verify** - human-verify checkpoint (completed prior session)
2. **Task 2: Remove cross_asset_enabled scaffolding** - `610034c` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified
- `services/cross_asset_service.py` — removed `_cross_asset_enabled` attr and early-exit guard in `start()`; updated docstring
- `services/feature_pipeline_service.py` — removed `_cross_asset_enabled` attr; made frame injection and topic subscription unconditional
- `services/signal_generator_service.py` — removed `_cross_asset_enabled` attr; made frame injection and topic subscription unconditional
- `services/feature_writer_service.py` — removed `_cross_asset_enabled` from Settings try/except block; made topic subscription and routing unconditional
- `src/config/settings.py` — removed `cross_asset_enabled: bool = Field(...)` field; added comment noting Phase 47-04 removal
- `tests/unit/service_tests/test_cross_asset_service.py` — removed `svc._cross_asset_enabled = True` from `_make_service()`
- `tests/unit/service_tests/test_signal_generator_service.py` — removed 2x `svc._cross_asset_enabled = False`; added 2x `svc._cross_asset_cache = {}`
- `tests/unit/service_tests/test_feature_pipeline_vix_injection.py` — removed `cross_asset_enabled` param from `_make_service()`; removed `svc._cross_asset_enabled` from `_build_injection()`; removed test_cross_asset_disabled_no_cross_asset_frames test; updated docstrings
- `tests/unit/test_cross_asset_features.py` — removed `test_settings_cross_asset_enabled_default` test

## Decisions Made

- **Removed `test_cross_asset_disabled_no_cross_asset_frames`** — this test verified the disabled flag suppresses injection, but the flag no longer exists. The EQ_INDEX guard remains and is still tested. Removing the test is correct; keeping it would test a code path that cannot exist.
- **Added `svc._cross_asset_cache = {}`** to two signal_generator test setups using `ESH6` (an EQ_INDEX symbol) — with the flag removed, the injection code now always runs for EQ_INDEX symbols, so `_cross_asset_cache` must be present on the mock service or `AttributeError` is raised.
- **Kept `cross_asset_window_bars` and `cross_asset_metrics_port`** — these are operational tuning parameters, not feature flags. D-14/D-15 only mandated removing the enable/disable switch.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added svc._cross_asset_cache to two test setups**
- **Found during:** Task 2 (test run after scaffold removal)
- **Issue:** Tests using `ESH6` (EQ_INDEX) failed with `AttributeError: 'SignalGeneratorService' object has no attribute '_cross_asset_cache'` — the `__new__` test pattern skips `__init__`, so once the injection became unconditional, the cache attr was missing from test fixtures
- **Fix:** Added `svc._cross_asset_cache = {}` to both `test_process_message_accesses_typed_attributes` and `test_process_message_populates_bar_history` setup blocks
- **Files modified:** `tests/unit/service_tests/test_signal_generator_service.py`
- **Verification:** All 2749 tests pass after fix
- **Committed in:** `610034c` (part of task commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug)
**Impact on plan:** Necessary correctness fix — the `__new__` test pattern requires manual attribute setup matching `__init__`. No scope creep.

## Issues Encountered

None beyond the auto-fixed test fixture issue above.

## Known Stubs

None — all cross-asset data flows unconditionally and has been confirmed non-null in intelligence_features for 7+ days per D-11 pre-enable gate.

## Next Phase Readiness

- Phase 47 is complete — all 4 plans executed:
  - 47-01: Regime gate config via env vars (SHADOW-01)
  - 47-02: Roll monitor graduation (SHADOW-03 deferred — D-21 offline validation pending)
  - 47-03: D-21 offline validation framework
  - 47-04: Cross-asset graduation (SHADOW-02) — this plan
- Phase 46.1 (VIX/cross-asset to I4) is queued as next phase
- No blockers

---
*Phase: 47-shadow-mode-graduation*
*Completed: 2026-03-22*
