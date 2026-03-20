---
phase: 42-candlestick-pattern-expansion
plan: 01
subsystem: intelligence/patterns
tags: [candlestick, patterns, i5, tdd, schema]
dependency_graph:
  requires: []
  provides: [harami_bull, harami_bear, abandoned_baby_bull, abandoned_baby_bear, tweezer_top, tweezer_bottom, belt_hold_bull, belt_hold_bear, kicker_bull, kicker_bear]
  affects: [I5Patterns schema, candlestick_patterns.py outputs frozenset]
tech_stack:
  added: []
  patterns: [TDD red-green, fixture-driven verification, float 0.0/1.0 pattern output convention]
key_files:
  created:
    - tests/unit/test_candlestick_patterns.py
  modified:
    - src/intelligence/patterns/candlestick_patterns.py
    - src/intelligence/schemas.py
decisions:
  - "Tweezer patterns use p/c bar pair (not pp/p) since they are 2-bar formations"
  - "Kicker uses pp as the reference candle for gap detection (c opens beyond pp_h or pp_l)"
  - "Belt Hold uses strict 70%/10% thresholds matching plan spec"
  - "Harami directional uses p_body < 0.3 * p_range (not doji) to allow small real bodies"
metrics:
  duration: "~7 minutes"
  completed_date: "2026-03-20"
  tasks_completed: 3
  files_modified: 3
---

# Phase 42 Plan 01: Candlestick Pattern Expansion — Task 1/2/3 Summary

Implemented 10 new I5 candlestick pattern detectors with schema extension and unit tests.

## What Was Built

10 new pattern detection functions in `candlestick_patterns.py`:
- **harami_bull / harami_bear**: Directional harami variants — pp large body (>50% range), p small body (<30% range) inside pp body, direction from p candle direction
- **abandoned_baby_bull / abandoned_baby_bear**: 3-bar reversal — pp large body (>60%), gap (p_l > pp_h or p_h < pp_l), p doji (<10% body/range), c large body reversal (>60%)
- **tweezer_top / tweezer_bottom**: Near-identical p/c highs or lows (within 0.1×ATR)
- **belt_hold_bull / belt_hold_bear**: Long body (>70% range) with no wick on the entry side (<10% range)
- **kicker_bull / kicker_bear**: 3-bar — pp directional, c gaps past pp extreme (c_o > pp_h or c_o < pp_l), c large body (>60%) with minimal wick on gapped side (<15%)

Schema extended: `I5Patterns` in `schemas.py` now declares all 10 new fields as `float | None = None`.

Unit tests: 13 tests in `tests/unit/test_candlestick_patterns.py` covering valid patterns, rejection cases, and frozenset completeness check.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (RED+GREEN) | 4b689bc | Add 10 new pattern detectors + unit tests (TDD) |
| 2 | c8eca80 | Extend I5Patterns schema with 10 new fields |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect test fixtures from plan spec**
- **Found during:** Task 1 TDD RED phase
- **Issue:** Plan's fixture data (e.g. `closes=[96, 97, 98.5]` for harami_bull) did not satisfy pattern conditions — pp_body was 40% of range (needed >50%), p_l was below pp_body_low. Similarly for abandoned_baby (pp body 40%), belt_hold (upper/lower wick 17% of range, needed <10%), and kicker_bull (upper wick 15.4% of range, needed <15%).
- **Fix:** Designed fixtures from first principles, verified each condition mathematically before writing to file. All 13 tests pass with corrected data.
- **Files modified:** tests/unit/test_candlestick_patterns.py

**2. [Minor] Pattern count is 28, not 29 as stated in plan**
- **Found during:** Task 2 verification
- **Issue:** Original frozenset had 18 entries (not 19 as stated in plan). The comment "10 new Tier 1 three-bar outputs" was applied to 9 patterns. 18 + 10 = 28 total.
- **Fix:** Implementation is mathematically correct (28 outputs). Plan's stated "29 total" was based on incorrect count of existing patterns. No code change needed — all 10 new patterns are present and verified.

## Success Criteria Verification

- [x] All 10 new candlestick patterns detect their respective formations correctly (13/13 tests pass)
- [x] I5Patterns schema declares all 10 new fields with `extra='forbid'` validation passing
- [x] Unit tests cover valid pattern detection and rejection cases
- [x] Patterns flow through existing I5 pipeline without breaking schema validation (53 related tests pass)
- [x] `candlestick_patterns.py` min_lines: 466 (plan required 400)
- [x] `tests/unit/test_candlestick_patterns.py` min_lines: 253 (plan required 200)

## Known Stubs

None. All 10 patterns are fully implemented with real detection logic.

## Self-Check: PASSED

Files created/modified:
- `/home/bg/dev/indicagent/src/intelligence/patterns/candlestick_patterns.py` — FOUND
- `/home/bg/dev/indicagent/src/intelligence/schemas.py` — FOUND
- `/home/bg/dev/indicagent/tests/unit/test_candlestick_patterns.py` — FOUND

Commits:
- 4b689bc — FOUND (feat(42-01): add 10 new Phase 42 candlestick pattern detectors)
- c8eca80 — FOUND (feat(42-01): extend I5Patterns schema with 10 new candlestick fields)
