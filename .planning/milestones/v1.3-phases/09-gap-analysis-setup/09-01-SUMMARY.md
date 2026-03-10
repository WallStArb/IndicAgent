---
phase: 09-gap-analysis-setup
plan: "01"
subsystem: testing
tags: [tdd, gap-analysis, trading, i7, red-phase]

# Dependency graph
requires: []
provides:
  - "Failing test suite for GapAnalysisSetup with 13 tests in 4 classes — RED state"
  - "make_gap_df() helper enforcing explicit gap injection via open[-1] overwrite"
  - "Contracts for GAP-01 detection, GAP-02 bias classification, GAP-03 signal fields"
affects:
  - "09-02 (GapAnalysisSetup implementation — Plan 02 makes these tests green)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED: test file imports from non-existent module to establish contracts before implementation"
    - "Gap injection pattern: overwrite df.at[df.index[-1], 'open'] after make_ohlcv() to force controlled gap"
    - "Volume confirmation: vol[-1] = mean(vol[:-1]) * 2.5 for high-volume tests (reliably exceeds 1.5x threshold)"

key-files:
  created:
    - tests/unit/intelligence/test_gap_analysis_setup.py
  modified: []

key-decisions:
  - "13 tests across 4 classes: TestGapDetection (4), TestGapClassification (5), TestGapSignalFields (4), TestGapNoSignal (1)"
  - "make_gap_df() always overwrites open[-1] explicitly — never relies on make_ohlcv() random seed"
  - "Normal-volume tests use np.full(n, 1000.0) so vol_ratio = 1.0, reliably below 1.5x threshold"

patterns-established:
  - "RED-phase test file: import from target module first so ModuleNotFoundError is the collection error"
  - "pytest.approx() used for entry_price float comparison against df['open'].iloc[-1]"

requirements-completed:
  - GAP-01
  - GAP-02
  - GAP-03

# Metrics
duration: 2min
completed: 2026-03-03
---

# Phase 09 Plan 01: GapAnalysisSetup Test Suite (RED) Summary

**13 failing tests in 4 classes establishing contracts for gap detection, bias classification, and signal field completeness — all fail with ModuleNotFoundError (correct RED state)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-03T07:02:39Z
- **Completed:** 2026-03-03T07:04:12Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `tests/unit/intelligence/test_gap_analysis_setup.py` with 13 tests across 4 classes
- Confirmed RED state: `ModuleNotFoundError: No module named 'src.intelligence.trading.gap_analysis_setup'`
- No regressions: 986 existing tests still pass
- Ruff 0 errors on new file

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing test suite for GapAnalysisSetup (RED)** - `d50e46b` (test)

## Files Created/Modified

- `tests/unit/intelligence/test_gap_analysis_setup.py` — 13 failing tests in 4 classes covering GAP-01 through GAP-03 plus insufficient-data edge case

## Decisions Made

- Used `pytest.approx()` for `entry_price` float comparison — avoids floating point equality pitfalls
- Ruff auto-fix applied once to correct import block ordering (I001)
- `make_gap_df()` defined at module level for reuse across all 4 test classes

## Deviations from Plan

None - plan executed exactly as written.

The only minor deviation was an import ordering fix (ruff I001): `src.*` must precede `tests.*` in the same import block. Auto-fixed with `ruff --fix`, no logic change.

## Issues Encountered

- **Ruff I001 import ordering:** Initial file had `tests.unit.intelligence.helpers` before `src.intelligence.trading.gap_analysis_setup`. Ruff flagged this as unsorted. Fixed with `ruff check --fix`. No functional impact.

## RED State Confirmation

```
collected 0 items / 1 error
ImportError while importing test module '.../test_gap_analysis_setup.py'.
ModuleNotFoundError: No module named 'src.intelligence.trading.gap_analysis_setup'
ERROR tests/unit/intelligence/test_gap_analysis_setup.py
```

## Test Count by Class

| Class | Tests | Requirement |
|-------|-------|-------------|
| TestGapDetection | 4 | GAP-01 |
| TestGapClassification | 5 | GAP-02 |
| TestGapSignalFields | 4 | GAP-03 |
| TestGapNoSignal | 1 | GAP-01 |
| **Total** | **13** | |

## Behavior Contracts Established

1. `test_bullish_gap_detected` — open > close[-2] by 0.5*ATR → direction == 1
2. `test_bearish_gap_detected` — open < close[-2] by 0.5*ATR → direction == -1
3. `test_no_gap_no_signal` — open == close[-2] exactly → signal_type == "none", direction == 0
4. `test_sub_threshold_gap_no_signal` — abs(gap) < 0.3*ATR → signal_type == "none"
5. `test_large_gap_high_volume_continuation` — gap_size_atr=1.2, vol_ratio=2.5 → bias == "continuation"
6. `test_medium_gap_normal_volume_fade` — gap_size_atr=0.5, vol_ratio=1.0 → bias == "fade"
7. `test_bullish_fade_signal_type` — bullish fade → signal_type == "gap_fade_long"
8. `test_bearish_fade_signal_type` — bearish fade → signal_type == "gap_fade_short"
9. `test_bullish_continuation_signal_type` — large bullish + high vol → signal_type == "gap_cont_long"
10. `test_fade_entry_at_limit` — fade: entry_type == "at_limit", entry_price == open[-1]
11. `test_continuation_entry_at_pullback` — continuation: entry_type == "at_pullback"
12. `test_all_fields_present_on_fired_signal` — confidence > 0.0, len(targets) >= 1, stop_loss != entry_price
13. `test_fade_stop_below_entry_for_long` — long fade: stop_loss < entry_price

## Next Phase Readiness

- RED state confirmed — Plan 02 can implement `GapAnalysisSetupPlugin` to make all 13 tests green
- All contracts explicit in test assertions; implementation has a clear specification to follow
- No blockers

---
*Phase: 09-gap-analysis-setup*
*Completed: 2026-03-03*
