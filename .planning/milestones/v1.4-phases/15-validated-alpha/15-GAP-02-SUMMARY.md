---
phase: 15-validated-alpha
plan: GAP-02
subsystem: intelligence
tags: [candlestick, patterns, i5, i7, tdd, bootstrap, validation]

# Dependency graph
requires:
  - phase: 15-validated-alpha
    provides: GAP-01 (bootstrap flag on validate_alpha.py)
provides:
  - CandlestickPatternSetupPlugin reads all 15 candlestick patterns (6 original + 9 new)
  - 9 bootstrap audit JSON files in docs/validation/ for new Tier 1 patterns
  - 9 unit tests (TDD RED→GREEN) covering each new pattern path
affects: [15-validated-alpha, phase-15-gap-summary, signal_generator_service]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "I5→I7 promotion via named feature reads in compute_full() candidates block"
    - "Bootstrap audit trail with verdict=BOOTSTRAP for data-absent correct implementations"
    - "harami_cross context-direction: inline trend_dir_local from features dict avoids forward-reference"

key-files:
  created:
    - docs/validation/2026-03-07-patt_CandlestickPatterns-three_white_soldiers-bootstrap.json
    - docs/validation/2026-03-07-patt_CandlestickPatterns-three_black_crows-bootstrap.json
    - docs/validation/2026-03-07-patt_CandlestickPatterns-morning_star-bootstrap.json
    - docs/validation/2026-03-07-patt_CandlestickPatterns-evening_star-bootstrap.json
    - docs/validation/2026-03-07-patt_CandlestickPatterns-three_inside_up-bootstrap.json
    - docs/validation/2026-03-07-patt_CandlestickPatterns-three_inside_down-bootstrap.json
    - docs/validation/2026-03-07-patt_CandlestickPatterns-harami_cross-bootstrap.json
    - docs/validation/2026-03-07-patt_CandlestickPatterns-dark_cloud_cover-bootstrap.json
    - docs/validation/2026-03-07-patt_CandlestickPatterns-piercing_line-bootstrap.json
  modified:
    - src/intelligence/trading/candlestick_pattern_setup.py
    - tests/unit/intelligence/test_trading_setups.py

key-decisions:
  - "harami_cross direction resolved inline via trend_dir_local = float(features.get('trend_regime', 0.0)) > 0 to avoid forward-reference to trend_dir variable computed later in function"
  - "Bootstrap policy applied: data-absent plugins with correct implementation get verdict=BOOTSTRAP not FAIL"
  - "Priority ranks preserved from plan spec: three_white_soldiers/three_black_crows at rank 1 (same as engulfing), morning_star/evening_star at rank 2, rest at rank 3-4"

patterns-established:
  - "I7 read pattern: float(features.get('<i5_field_name>', 0.0)) then candidate tuple (rank, dir, name, conf, sr_auto)"
  - "Context-direction pattern: harami_cross computes trend_dir_local inline rather than using later-computed trend_dir variable"

requirements-completed: [ALPHA-03]

# Metrics
duration: 3min
completed: 2026-03-07
---

# Phase 15 Plan GAP-02: Candlestick Tier 1 I7 Promotion Summary

**9 new Tier 1 candlestick patterns (three_white_soldiers, morning_star, harami_cross, etc.) wired from I5 to I7 via TDD, closing GAP-02 of the Phase 15 verification report**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-07T19:22:20Z
- **Completed:** 2026-03-07T19:25:09Z
- **Tasks:** 3
- **Files modified:** 2 (+ 9 docs/validation/ bootstrap files created)

## Accomplishments

- CandlestickPatternSetupPlugin now reads all 15 candlestick patterns (6 original + 9 new)
- 9 RED tests added and confirmed failing, then turned GREEN with implementation
- 9 bootstrap audit trails written to docs/validation/ (verdict=BOOTSTRAP)
- Full unit suite: 1295 passing, 0 regressions, ruff 0 errors

## Task Commits

Each task was committed atomically:

1. **Task 1: RED tests for 9 new Tier 1 patterns** - `adbb9f9` (test)
2. **Task 2: Implement 9 pattern reads in CandlestickPatternSetupPlugin** - `5ade581` (feat)
3. **Task 3: Bootstrap audit trails + full suite verification** - `065ad83` (chore)

**Plan metadata:** (docs commit follows)

_Note: TDD tasks have explicit RED→GREEN sequence — Task 1 confirmed all 9 failing before Task 2 turned them GREEN_

## Files Created/Modified

- `src/intelligence/trading/candlestick_pattern_setup.py` - Added 9 named reads + candidate entries; updated docstring priority order
- `tests/unit/intelligence/test_trading_setups.py` - Added TestCandlestickTier1Patterns class with 9 tests
- `docs/validation/2026-03-07-patt_CandlestickPatterns-*-bootstrap.json` (9 files) - Bootstrap audit trails (verdict=BOOTSTRAP)

## Decisions Made

- harami_cross direction computed inline via `trend_dir_local = 1 if float(features.get("trend_regime", 0.0)) > 0 else -1` to avoid forward-reference to the `trend_dir` variable computed later in the function body
- Bootstrap policy: correct implementations blocked only by data absence get BOOTSTRAP verdict (not FAIL)
- Priority ranks assigned per plan spec: three_white_soldiers/three_black_crows at rank 1, morning_star/evening_star at rank 2, three_inside_*/dark_cloud_cover/piercing_line at rank 3, harami_cross at rank 4

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- GAP-02 closed: all 9 new Tier 1 candlestick patterns wired from I5 to I7
- Bootstrap audit trails in place; re-run gate after 30+ days of live data accumulates
- Phase 15 gaps addressed: GAP-01 (bootstrap flag), GAP-02 (candlestick I7 reads)

---
*Phase: 15-validated-alpha*
*Completed: 2026-03-07*

## Self-Check: PASSED

- candlestick_pattern_setup.py: FOUND
- test_trading_setups.py: FOUND
- morning_star bootstrap JSON: FOUND
- Commits adbb9f9, 5ade581, 065ad83: FOUND in git log
