---
phase: 07-composite-intelligence-score
plan: "04"
subsystem: trading
tags: [trade-framer, entry-types, tdd, i7-signals]

# Dependency graph
requires:
  - phase: 07-01-composite-intelligence-score
    provides: "5 new I7 evidence-contributor plugins (CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition)"
provides:
  - "_resolve_entry() with at_limit case for momentum_breakout and squeeze_expansion"
  - "_resolve_entry() with at_pullback case for trend and mtf_alignment"
  - "TradeFrame.entry_type annotation updated to include at_limit and at_pullback"
  - "Module docstring updated with complete entry offset logic table"
affects: [07-02-composite-intelligence-score, signal-generator-service, trade-framer-consumers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Directional validity check pattern: level must be on structurally correct side of entry price before using it"
    - "Dual-key alias fallback: _fval(f, 'nearest_X') or _fval(f, 'sr_nearest_X') for aliased feature keys"

key-files:
  created: []
  modified:
    - src/intelligence/trading/trade_framer.py
    - tests/unit/intelligence/test_trade_framer.py

key-decisions:
  - "mtf_alignment uses nearest_support/resistance as CTF level proxy — no ctf_level price field exists in IntelligenceEvent schema; documented inline"
  - "at_limit LONG requires level <= entry_price (not strictly less than), so equal-price level is still valid as a limit order"
  - "E501 pre-existing ruff violations in trade_framer.py are out of scope — only new lines introduced by 07-04 were fixed"

patterns-established:
  - "Directional validity gate: at_limit long → level <= entry; at_limit short → level >= entry; at_pullback long → level < entry; at_pullback short → level > entry"

requirements-completed:
  - CIS-D1

# Metrics
duration: 3min
completed: 2026-02-28
---

# Phase 7 Plan 04: Trade Framer Entry Types Summary

**_resolve_entry() extended with at_limit (momentum_breakout, squeeze_expansion) and at_pullback (trend, mtf_alignment) entry types using structural level validity gates and at_close fallbacks**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-28T01:15:55Z
- **Completed:** 2026-02-28T01:19:26Z
- **Tasks:** 1 (TDD: RED + GREEN + REFACTOR)
- **Files modified:** 2

## Accomplishments

- Added `at_limit` entry type: momentum_breakout uses swing_high/low as broken-structure limit level; squeeze_expansion uses bb_middle (squeeze centre)
- Added `at_pullback` entry type: trend_long/short uses nearest_support/resistance; mtf_alignment uses same levels as CTF proxy
- All 4 new cases include directional validity checks and fall back to at_close when level is missing, zero, or directionally invalid
- 16 new tests in `TestResolveEntryNewCases` cover all cases including sr_nearest_support alias fallback and regression tests
- 59 total trade_framer tests pass; 725 unit tests pass overall (pre-existing failures unchanged)

## Task Commits

TDD task committed in two atomic steps:

1. **RED — Failing tests for at_limit and at_pullback** - `370d7e1` (test)
2. **GREEN — Implement _resolve_entry() new cases** - `506f02a` (feat)

**Plan metadata:** (docs commit follows)

_Note: TDD tasks committed in RED then GREEN phases as required by TDD execution flow._

## Files Created/Modified

- `src/intelligence/trading/trade_framer.py` - Extended `_resolve_entry()` with 4 new entry type cases; updated `TradeFrame.entry_type` annotation; updated module docstring
- `tests/unit/intelligence/test_trade_framer.py` - Added `TestResolveEntryNewCases` class with 16 tests; added `_resolve_entry` to imports

## Decisions Made

- **CTF proxy for mtf_alignment:** No `ctf_level` price field exists in IntelligenceEvent schema. Used `nearest_support` (long) and `nearest_resistance` (short) as the CTF confluence level proxy. This was the research finding documented in the plan interfaces section.
- **at_limit equality:** `level <= entry_price` for long at_limit (not strict less-than) — a swing_high exactly at entry price is still a valid limit level.
- **Pre-existing E501:** `trade_framer.py` had 9 pre-existing E501 ruff violations before this plan. Only the 2 new violations introduced by 07-04 were fixed (lines with `sr_nearest_resistance` in `_resolve_entry`). Pre-existing violations left unchanged per scope boundary rule.

## Deviations from Plan

**1. [Rule 1 - Bug] Fixed 2 new E501 ruff violations in added code**
- **Found during:** Task 1 GREEN phase (ruff check after implementation)
- **Issue:** Two new lines in `_resolve_entry()` for the `nearest_resistance or sr_nearest_resistance` lookup were 101 chars (1 over limit)
- **Fix:** Wrapped those two lines in parentheses to allow line break; also shortened `entry_type` annotation comment from 103 to 95 chars
- **Files modified:** `src/intelligence/trading/trade_framer.py`
- **Verification:** New lines pass ruff; pre-existing violations unchanged
- **Committed in:** `506f02a` (GREEN commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - line length in new code)
**Impact on plan:** Minor style fix; no behavior change. Pre-existing E501 violations are documented as out-of-scope.

## Issues Encountered

- **test_cis_scorer.py collection error:** `ModuleNotFoundError: No module named 'src.intelligence.trading.cis_scorer'` — this is from 07-02 (parallel Wave 2 plan) whose test stubs are committed but implementation is not yet complete. Pre-existing, out of scope.
- **TestAggregateCISIntegration failures (7 tests):** Unstaged 07-02 work in `test_aggregator.py` references `aggregate(features=...)` signature not yet implemented. Pre-existing, out of scope for 07-04.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `_resolve_entry()` now produces `at_limit` and `at_pullback` entry types for 4 setup patterns
- Signal generator service will automatically benefit when processing these setup types
- Ready for 07-02 (CIS bucket scorer) and 07-03 (weight updater) to continue Wave 2/3 work
- No breaking changes to existing entry types (at_reclaim, zone_proximal, at_close all unchanged)

## Self-Check: PASSED

- FOUND: `src/intelligence/trading/trade_framer.py`
- FOUND: `tests/unit/intelligence/test_trade_framer.py`
- FOUND: `.planning/phases/07-composite-intelligence-score/07-04-SUMMARY.md`
- FOUND commit `370d7e1` (test: RED phase)
- FOUND commit `506f02a` (feat: GREEN phase)

---
*Phase: 07-composite-intelligence-score*
*Completed: 2026-02-28*
