---
phase: 076-signal-lifecycle-labeling-activation-gate
plan: 02
subsystem: signal-lifecycle
tags: [signal-tracker, ttl-sweep, activation-gate, temporal-guard]

# Dependency graph
requires:
  - phase: 076-signal-lifecycle-labeling-activation-gate
    plan: 01
    provides: lifecycle_tracker.py with signal_timestamp/bar_time parameters
provides:
  - Bootstrap TTL sweep reduces tracker restart from 6-min cycle to stable operation
  - Activation probability gate filters hopeless signals before tracking
  - Temporal guard wiring completes anti-corruption fix for pre-fire activations
affects: [signal-tracker, signal-ledger]

# Tech tracking
tech-stack:
  added: []
  patterns: [bootstrap-sql-sweep, heuristic-gate, temporal-guard-caller]

key-files:
  created: []
  modified:
    - services/signal_tracker_compute_agent.py
    - tests/unit/service_tests/test_signal_tracker_compute_agent.py

key-decisions:
  - "Used 4-hour TTL sweep cutoff (not 3-day) because 99.78% of signals are 1m timeframe"
  - "Zone distance measured in risk units (not ATR) for gate simplicity - always available"
  - "Gate returns early without publishing transition - bootstrap sweep handles cleanup on restart"

patterns-established:
  - "Bootstrap SQL sweep: expire stale data before SELECT to reduce memory pressure"
  - "Ingestion gate: heuristic pre-filter to skip hopeless work early"
  - "Temporal guard: pass timestamps through pure functions for time-order validation"

requirements-completed: []

# Metrics
duration: 25min
completed: 2026-04-28T18:35:00Z
---

# Phase 076 Plan 02: Bootstrap TTL Sweep + Activation Gate + Temporal Guard Summary

**Bootstrap TTL sweep expires 4h-old pending signals before loading, activation gate filters hopeless signals at ingestion, and temporal guard caller passes timestamps to prevent pre-fire activations**

## Performance

- **Duration:** 25 min
- **Started:** 2026-04-28T18:10:00Z
- **Completed:** 2026-04-28T18:35:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- **Bootstrap TTL sweep (D-03):** Added pre-filter UPDATE SQL that expires pending signals >4h old before SELECT runs, reducing bootstrap from 29k signals to manageable set and eliminating 6-min restart cycle
- **Activation probability gate (D-05):** Implemented heuristic pre-filter in `_ingest_signal_payload()` that filters hopeless signals (zone > 3x risk, <20% TTL remaining) before they enter tracking pipeline
- **Temporal guard wiring (D-01 caller):** Completed temporal guard implementation by passing `signal_timestamp` and `bar_time` parameters to `evaluate_signal()` call

## Task Commits

1. **Task 1: Bootstrap TTL sweep + activation probability gate + temporal guard wiring** - `63c73347` (feat)

**Plan metadata:** `63c73347` (feat: complete plan 02)

## Files Created/Modified

- `services/signal_tracker_compute_agent.py` - Added bootstrap TTL sweep SQL UPDATE, activation probability gate heuristic, and temporal guard parameter passing
- `tests/unit/service_tests/test_signal_tracker_compute_agent.py` - Added 8 new tests (TestBootstrapTTLSweep, TestActivationProbabilityGate, TestTemporalGuardWiring)

## Decisions Made

### D-01 Temporal Guard Implementation
- **Decision:** Pass `signal_timestamp` (from signal dict's `timestamp` field) and `bar_time` (from bar payload) to `evaluate_signal()` in `_evaluate_bar()` method
- **Rationale:** Completes the temporal guard implementation from Plan 01, ensuring `_check_zone_activation()` can prevent impossible activations from stale bars

### D-03 Bootstrap TTL Sweep Cutoff
- **Decision:** Use 4-hour cutoff (not 3-day SELECT window) for expiring pending signals
- **Rationale:** 99.78% of signals are 1m timeframe; 4 hours = 240 bars, well beyond max I7 TTL of ~60 bars. HTF signals (1h, 4h, 1d) still loaded via 3-day SELECT window but won't be swept unless >4h old (rare for HTF)

### D-05 Activation Gate Heuristic
- **Decision:** Measure zone distance in risk units (|entry - stop|), not ATR or GARCH sigma
- **Rationale:** Risk is always available for valid signals; ATR/GARCH sigma may be missing or computed differently. Gate uses zone_distance_risk > 3.0 AND ttl_remaining_pct < 0.20 as hopeless threshold

### D-05 Gate Return Behavior
- **Decision:** Gate returns early without publishing TTL-expired transition
- **Rationale:** Bootstrap sweep will catch expired signals on next restart. Publishing transition from sync context would require async complexity. Gate's primary benefit is reducing active index size, not immediate persistence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Pre-commit Violation] Removed unused import from test**
- **Found during:** Post-commit pre-commit hook
- **Issue:** Test file had unused import `from src.intelligence.trading.lifecycle_tracker import evaluate_signal`
- **Fix:** Removed the unused import, kept the `from unittest.mock import patch` import which is actually used
- **Files modified:** tests/unit/service_tests/test_signal_tracker_compute_agent.py
- **Verification:** Pre-commit hook passed on second attempt
- **Committed in:** `63c73347` (same commit)

---

**Total deviations:** 1 auto-fixed (1 pre-commit violation)
**Impact on plan:** Minor code style fix, no functional change.

## Issues Encountered

### Pre-commit Hook Dead Import Detection
- **Issue:** Initial commit failed pre-commit hook due to unused import in test file
- **Resolution:** Removed unused import, re-staged test file, committed successfully
- **Impact:** Trivial - added ~30 seconds to execution time

## Known Stubs

None - all code is functional and tested.

## Threat Flags

None - no new security-relevant surface introduced. The activation gate uses safe defaults (missing fields = no gate) and type-checks on floats before division.

## Self-Check: PASSED

- [x] All tests pass (30/30 in test_signal_tracker_compute_agent.py)
- [x] Bootstrap TTL sweep SQL exists with 4-hour cutoff
- [x] Activation gate filters hopeless signals (8 test assertions)
- [x] Temporal guard wired (signal_timestamp + bar_time passed)
- [x] No regressions in existing tests
- [x] Commit hash verified: 63c73347

## Next Phase Readiness

- Plan 03 (backfill correction + labeling constraint) can proceed - all lifecycle_tracker.py changes from Plan 01 are in place
- Signal tracker now has operational fixes to prevent 6-min restart cycle and reduce active index bloat
- No external dependencies or manual setup required

---
*Phase: 076-signal-lifecycle-labeling-activation-gate*
*Plan: 02*
*Completed: 2026-04-28*
