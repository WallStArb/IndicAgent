---
phase: 18-financial-math-safety
plan: 04
subsystem: trading
tags: [epsilon-tolerance, floating-point, trade-framer, financial-math, precision]

# Dependency graph
requires:
  - phase: 18-financial-math-safety
    provides: EPSILON_TOLERANCE constant defined in trade_framer.py (was orphaned)
provides:
  - Epsilon-based floating-point comparisons throughout trade_framer.py (46 sites)
  - EPSILON_TOLERANCE (1e-9) fully activated — no longer an orphaned constant
affects:
  - signal_generator_service (uses frame_trade)
  - signal_lifecycle_service (uses TradeFrame zone_low/zone_high)
  - 18-05, 18-06, 18-07 (all depend on trade_framer correctness)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "EPSILON_TOLERANCE guard for all floating-point zero comparisons in financial code"
    - "Directional stop validation uses entry ± EPSILON_TOLERANCE (not raw > 0)"

key-files:
  created: []
  modified:
    - src/intelligence/trading/trade_framer.py

key-decisions:
  - "Stop directional checks use entry ± EPSILON_TOLERANCE (e.g. stop < entry - EPSILON_TOLERANCE) rather than just > 0 to guard against equality edge cases"
  - "OB top/demand zone high comparisons against entry (not zero) kept without epsilon — comparison to entry is not a zero-check so raw > entry is correct"

patterns-established:
  - "Any floating-point value sourced from features dict that is checked against zero must use EPSILON_TOLERANCE"
  - "Structural level validity gates: EPSILON_TOLERANCE < low < high (both bounds checked)"

requirements-completed: [FIN-01]

# Metrics
duration: 10min
completed: 2026-03-08
---

# Phase 18 Plan 04: Epsilon Tolerance Activation Summary

**EPSILON_TOLERANCE (1e-9) activated at all 45 floating-point comparison sites in trade_framer.py — constant promoted from orphaned definition to fully operational precision guard**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-08T14:45:00Z
- **Completed:** 2026-03-08T14:55:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Replaced all raw `> 0` / `< 0` / `<= 0` comparisons on floating-point values with `> EPSILON_TOLERANCE` / `< -EPSILON_TOLERANCE` / `<= EPSILON_TOLERANCE` equivalents
- EPSILON_TOLERANCE now referenced 46 times (1 definition + 45 usage sites) vs previously 1 (just the definition)
- Stop directional guards updated: `stop < entry` → `stop < entry - EPSILON_TOLERANCE` and `stop > entry` → `stop > entry + EPSILON_TOLERANCE` — prevents accepting a stop at exactly entry price
- All 1308 unit tests pass with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace raw floating-point comparisons with epsilon-based comparisons** - `ea3ac22` (fix)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `src/intelligence/trading/trade_framer.py` - 45 comparison sites updated across 6 functions: `_resolve_zone_bounds`, `_resolve_entry`, `_resolve_stop_long`, `_resolve_stop_short`, `_collect_targets_long`, `_collect_targets_short`, and `frame_trade`

## Decisions Made
- Stop directional checks (`stop < entry`, `stop > entry`) updated to include epsilon offset to prevent degenerate stops at exactly entry price — these are logically different from zero-checks but benefit from the same guard
- Comparisons of structural levels vs `entry` (not vs zero) were left as-is (e.g. `ob_top > entry`) — these are order relationships, not zero-validity checks, and don't need epsilon treatment

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- trade_framer.py now has full epsilon precision throughout
- All structural stop/target logic uses EPSILON_TOLERANCE — ready for further hardening in Phase 18 plans 05-07
- 1308 tests passing, ruff E501 only (non-blocking)

---
*Phase: 18-financial-math-safety*
*Completed: 2026-03-08*
