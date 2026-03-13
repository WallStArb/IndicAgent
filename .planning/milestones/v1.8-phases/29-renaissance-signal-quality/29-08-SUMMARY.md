---
phase: 29-renaissance-signal-quality
plan: "08"
subsystem: signal-lifecycle
tags: [signal-quality, freshness-decay, exponential-decay, confidence, lifecycle]

# Dependency graph
requires:
  - phase: 29-renaissance-signal-quality
    provides: "_compute_freshness_decay() helper implemented and mathematically verified"
provides:
  - "_compute_freshness_decay() called once per signal per bar in _evaluate_signals_against_bar()"
  - "effective_confidence used at both exit paths (active + shadow/regime_suppressed)"
  - "signal_ledger confidence column protected — update_signal_status never receives confidence kwarg"
  - "TestFreshnessDecayWiring: 2 integration tests (RED->GREEN wiring test + immutability invariant)"
affects:
  - signal-lifecycle
  - signal-quality
  - ml-training-data

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "QUAL-03 freshness decay: compute effective_confidence in-memory per bar; never persist to DB"
    - "Exponential decay wired post-sig_with_extras, before either exit path, for single computation point"

key-files:
  created: []
  modified:
    - services/signal_lifecycle_service.py
    - tests/unit/service_tests/test_lifecycle_freshness.py

key-decisions:
  - "effective_confidence computed once after sig_with_extras (not inside each exit branch) — avoids duplication"
  - "Patch target services.signal_lifecycle_service.update_signal_status (imported name), not ledger module"

patterns-established:
  - "TDD RED-GREEN: write integration tests using __new__ pattern + AsyncMock patch on imported name"
  - "Decay computed in service loop, not in lifecycle_tracker — keeps evaluate_signal() pure"

requirements-completed: [QUAL-03]

# Metrics
duration: 4min
completed: 2026-03-13
---

# Phase 29 Plan 08: QUAL-03 Freshness Decay Wiring Summary

**Wired exponential freshness decay into signal exit evaluation so stale active signals receive lower signal_quality scores, closing the QUAL-03 gap where _compute_freshness_decay() existed but was never called.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-13T15:06:33Z
- **Completed:** 2026-03-13T15:10:04Z
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Added `TestFreshnessDecayWiring` class with 2 integration tests covering the wiring contract and the DB immutability invariant
- Wired `_compute_freshness_decay()` into `_evaluate_signals_against_bar()` — computed once per signal after `sig_with_extras`, covering both exit paths
- `effective_confidence` replaces raw confidence in `signal_quality` at active exit and shadow (regime_suppressed) exit paths
- `update_signal_status()` call signatures unchanged — stored `confidence` in `signal_ledger` is never touched
- Full unit suite: 1644 passing, zero regressions

## Task Commits

1. **Task 1: Write failing integration tests (RED)** - `9d3cc55` (test)
2. **Task 2: Wire effective_confidence into _evaluate_signals_against_bar() (GREEN)** - `d23b98a` (feat)

## Files Created/Modified

- `services/signal_lifecycle_service.py` - Added `effective_confidence` computation (3 lines) and replaced raw confidence in both exit-path `signal_quality` calculations
- `tests/unit/service_tests/test_lifecycle_freshness.py` - Added `TestFreshnessDecayWiring` class with 2 async integration tests

## Decisions Made

- Patch target is `services.signal_lifecycle_service.update_signal_status` (the imported name in the service module), not the original `src.intelligence.trading.signal_ledger` module — otherwise the mock doesn't intercept the call
- `effective_confidence` computed once after `sig_with_extras` block (not duplicated in each branch) — single computation point, shared by both exit paths

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Wrong patch target in tests**
- **Found during:** Task 1 (RED phase)
- **Issue:** Plan specified `src.intelligence.trading.signal_ledger.update_signal_status` as patch target; this is not what the service calls at runtime (service imported the function into its own namespace)
- **Fix:** Changed patch target to `services.signal_lifecycle_service.update_signal_status` — the name in the calling module's namespace
- **Files modified:** tests/unit/service_tests/test_lifecycle_freshness.py
- **Verification:** Test B (immutability invariant) switched from TypeError to PASSED
- **Committed in:** 9d3cc55 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in test setup)
**Impact on plan:** Minor test plumbing fix; no scope creep, no behavioral change to production code.

## Issues Encountered

- Plan's pnl_r formula `(3990.0 - 3986.0) / (4000.0 - 3990.0) = -0.4` is incorrect for the stop-loss scenario (actual pnl_r = -1.0 at stop, clipped to 0 by max()). Resolved by using a target hit scenario (positive pnl_r = 1.0) instead — cleaner test that demonstrates freshness decay effect unambiguously (1.0 → 0.5 at half-life).

## Next Phase Readiness

- QUAL-03 gap fully closed — freshness decay now active in production lifecycle evaluation
- Remaining Phase 29 plans can proceed; no blockers

---
*Phase: 29-renaissance-signal-quality*
*Completed: 2026-03-13*
