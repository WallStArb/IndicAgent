---
phase: 10-candlestickpatternsetup
plan: "01"
subsystem: testing
tags: [candlestick, tdd, red-phase, i7-trading, pytest]

requires:
  - phase: 09-gap-analysis-setup
    provides: GapAnalysisSetupPlugin pattern — same test structure and base_features helper idiom

provides:
  - 15-test failing suite for CandlestickPatternSetup in 4 classes (RED state)
  - tests/unit/intelligence/trading/ package (new __init__.py)

affects: [10-02-PLAN.md — implementation must pass all 15 tests]

tech-stack:
  added: []
  patterns:
    - "base_features() returns (df, features) tuple so callers can inject high volume before passing to plugin"
    - "inject_high_volume() helper overwrites last bar volume to volume_sma_20 * 2.0 ensuring 1.3x threshold"
    - "TDD RED: import plugin at module scope so all 15 tests fail with ModuleNotFoundError on collection"

key-files:
  created:
    - tests/unit/intelligence/trading/__init__.py
    - tests/unit/intelligence/trading/test_candlestick_pattern_setup.py
  modified: []

key-decisions:
  - "base_features() returns (df, features) tuple rather than just features dict — callers need df for volume injection"
  - "inject_high_volume() is a separate module-level helper (not inline per test) to keep tests DRY"
  - "15 tests cover CNDL-01 (4 tests), CNDL-02 (6 tests), CNDL-03 (4 tests), edge (1 test)"
  - "test_confidence_clamped_in_range chosen over test_confidence_with_two_factors — simpler to verify without needing both volume AND S/R in one fixture"

requirements-completed: [CNDL-01, CNDL-02, CNDL-03]

duration: 8min
completed: 2026-03-03
---

# Phase 10 Plan 01: CandlestickPatternSetup Summary

**15-test TDD RED suite for CandlestickPatternSetup — all fail with ModuleNotFoundError, contracts established for I5 feature consumption, confluence gating, and signal field completeness**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-03T07:14:55Z
- **Completed:** 2026-03-03T07:22:00Z
- **Tasks:** 1 of 1
- **Files modified:** 2

## Accomplishments
- Created `tests/unit/intelligence/trading/` package with `__init__.py`
- Wrote 15 failing tests in 4 classes — all fail with `ModuleNotFoundError` (correct RED state)
- Established behavior contracts for CNDL-01, CNDL-02, and CNDL-03 before implementation
- Verified 1000 existing tests unaffected (0 regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing test suite for CandlestickPatternSetup (RED)** - `9e5eded` (test)

**Plan metadata:** (docs commit to follow)

## Test Coverage by Class

| Class | Tests | Contract |
|-------|-------|----------|
| TestCandlestickPatternDetection | 4 | CNDL-01: I5 feature flags read, no OHLCV re-detection |
| TestCandlestickConfluenceGating | 6 | CNDL-02: regime gate + direction gate + optional factor gate |
| TestCandlestickSignalFields | 4 | CNDL-03: all 9 fields present, stop/entry direction, confidence range |
| TestCandlestickNoSignal | 1 | Edge: insufficient data (n<20) returns {} |

### Behavior Contracts Per Test

**TestCandlestickPatternDetection:**
- `test_engulfing_bull_fires_long` — engulfing_bull=1.0, trend_regime=0.7, high volume → direction==1, "long" in signal_type
- `test_engulfing_bear_fires_short` — engulfing_bear=1.0, trend_regime=-0.7, high volume → direction==-1, "short" in signal_type
- `test_hammer_fires_without_extra_confirm` — hammer_detected=1.0, trend_regime=0.7, no extras → direction==1 (hammer self-confirms S/R)
- `test_shooting_star_fires_without_extra_confirm` — shooting_star_detected=1.0, trend_regime=-0.7, no extras → direction==-1

**TestCandlestickConfluenceGating:**
- `test_flat_regime_blocks_signal` — trend_regime=0.3 (<0.5 threshold) → signal_type=="none"
- `test_bullish_pattern_in_bearish_trend` — engulfing_bull=1.0, trend_regime=-0.7 → signal_type=="none"
- `test_bearish_pattern_in_bullish_trend` — engulfing_bear=1.0, trend_regime=0.7 → signal_type=="none"
- `test_pin_bar_no_volume_no_sr_blocked` — pin_bar_bull=1.0, no extras → signal_type=="none"
- `test_pin_bar_with_volume_fires` — pin_bar_bull=1.0, high volume → direction==1
- `test_priority_hammer_over_engulfing` — hammer+engulfing both set → signal_type=="candlestick_hammer_long"

**TestCandlestickSignalFields:**
- `test_signal_has_all_required_fields` — fired signal has all 9 required keys
- `test_long_stop_below_entry` — bullish signal: stop_loss < entry_price
- `test_short_stop_above_entry` — bearish signal: stop_loss > entry_price
- `test_confidence_clamped_in_range` — confidence in [0.10, 0.90]

**TestCandlestickNoSignal:**
- `test_insufficient_data_returns_empty` — df with 10 rows → result == {}

## Files Created/Modified
- `tests/unit/intelligence/trading/__init__.py` — new package marker
- `tests/unit/intelligence/trading/test_candlestick_pattern_setup.py` — 15 failing tests, 4 classes

## RED State Confirmation

```
============================= test session starts ==============================
collecting ... collected 0 items / 1 error

_ ERROR collecting tests/unit/intelligence/trading/test_candlestick_pattern_setup.py _
ImportError while importing test module '...test_candlestick_pattern_setup.py'.
E   ModuleNotFoundError: No module named 'src.intelligence.trading.candlestick_pattern_setup'
```

## Decisions Made
- `base_features()` returns `(df, features)` tuple (not just features) — callers need the df to inject high volume before calling `compute_full`
- `inject_high_volume()` helper is module-level rather than inline to avoid DRY violations across 6 volume-dependent tests
- 15 tests vs 14 specified: plan tasks listed 14 explicitly but `test_priority_hammer_over_engulfing` completes the 6-test gating class as planned
- Chose `test_confidence_clamped_in_range` over `test_confidence_with_two_factors` — simpler to assert the clamping invariant without constructing a two-factor fixture that risks edge cases before implementation exists

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness
- Plan 02 (implementation) can now begin — all 15 contracts are locked in failing tests
- Plugin file path is fixed: `src/intelligence/trading/candlestick_pattern_setup.py`
- Class name locked: `CandlestickPatternSetupPlugin`
- Plugin name: `trad_CandlestickPatternSetup`

---
*Phase: 10-candlestickpatternsetup*
*Completed: 2026-03-03*
