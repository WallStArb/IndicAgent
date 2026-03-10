---
phase: 07-composite-intelligence-score
plan: 01
subsystem: intelligence
tags: [plugins, i7, cis, tdd, trading-signals, smc, divergence, regime, pattern]

# Dependency graph
requires:
  - phase: 06-dashboard-connected
    provides: fully wired I1-I7 pipeline with typed intelligence bus
  - phase: 05-live-pipeline
    provides: signal_generator_service consuming I7 plugins via TIER_I7
provides:
  - 5 new I7 evidence-contributor plugins (CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition)
  - TIER_I7 expanded from 9 to 14 plugins
  - 32 new TDD tests in test_cis_plugins.py
  - Updated registration tests to assert total==62, all 14 I7 names
affects:
  - 07-02-PLAN (CIS bucket scorer consumes all 14 TIER_I7 plugins as evidence inputs)
  - signal_generator_service (runs all 14 TIER_I7 plugins per bar)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Evidence-contributor plugin: fires _no_signal() for gate misses, returns full signal dict for gate hits"
    - "Dual-gate design (DivergenceStack): both RSI and volume must agree — single signal insufficient"
    - "Confidence formula: base + scalar * normalized_feature_value, clamped 0.10-0.95"
    - "ATR-based stop/target: entry ± atr * 1.5 stop, ± atr * [2.0, 3.5, 5.0] targets"

key-files:
  created:
    - src/intelligence/trading/choch_reversal.py
    - src/intelligence/trading/fvg_fill.py
    - src/intelligence/trading/pattern_completion.py
    - src/intelligence/trading/divergence_stack.py
    - src/intelligence/trading/regime_transition.py
    - tests/unit/intelligence/test_cis_plugins.py
  modified:
    - src/intelligence/register_plugins.py
    - tests/unit/intelligence/test_i7_registration.py
    - tests/unit/intelligence/test_plugin_registry.py

key-decisions:
  - "DivergenceStack uses dual-gate (LOCKED): rsi_div AND vol_div must BOTH exceed 0.3 threshold — single divergence always returns _no_signal()"
  - "PatternCompletion checks dt_db→hs→triangle priority but takes highest-confidence pattern if multiple fire; confidence scaled by 0.9"
  - "CHoCHReversal: confidence = 0.5 + 0.2 (HMM regime aligns) + 0.3 * abs(direction)"
  - "FVGFill: confidence = 0.5 + 0.3 * min(1.0, fvg_open_count/3.0) — more open FVGs = stronger magnetic pull"
  - "RegimeTransition: requires BOCPD cp_probability > 0.5 AND choch_detected == 1.0 (both gates required)"
  - "test_plugin_registry.py test_tier_i7_has_9_plugins updated to test_tier_i7_has_14_plugins (auto-fix Rule 2)"

patterns-established:
  - "Evidence contributor: min_lookback=20, returns {} on insufficient data, _no_signal() on gate miss"
  - "All new I7 plugins follow identical dataclass protocol as TrendFollowingPlugin canonical pattern"

requirements-completed:
  - CIS-A1
  - CIS-A2

# Metrics
duration: 6min
completed: 2026-02-28
---

# Phase 7 Plan 01: CIS Evidence-Contributor Plugins Summary

**5 new I7 evidence-contributor plugins (CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition) added via TDD — TIER_I7 expanded from 9 to 14, total plugin count 57→62**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-28T01:06:33Z
- **Completed:** 2026-02-28T01:12:35Z
- **Tasks:** 2
- **Files modified:** 9 (6 created, 3 modified)

## Accomplishments

- 5 new I7 evidence-contributor plugins with full PatternPlugin protocol compliance and module-level singletons
- 32 TDD tests covering all gate conditions (fire/no-fire), confidence formulas, and singleton assertions
- TIER_I7 expanded from 9 to 14 plugins; register_all_plugins() registers all 14 without crash
- All tests pass (708 total, 0 new failures, 3 pre-existing live-infra failures unchanged)

## Task Commits

1. **Task 1: TDD — 5 new I7 evidence-contributor plugins** - `8ca9b21` (feat)
2. **Task 2: Register all 5 new plugins in TIER_I7 and update registration test** - `45d039c` (feat)

## Files Created/Modified

- `src/intelligence/trading/choch_reversal.py` - CHoCHReversalPlugin: gates on choch_detected==1.0, direction from choch_direction, HMM alignment bonus
- `src/intelligence/trading/fvg_fill.py` - FVGFillPlugin: gates on fvg_type!=0 AND fvg_open_count>=1, confidence scales with open count
- `src/intelligence/trading/pattern_completion.py` - PatternCompletionPlugin: checks dt_db/hs/triangle, highest-confidence pattern wins
- `src/intelligence/trading/divergence_stack.py` - DivergenceStackPlugin: dual-gate (RSI AND volume must agree), confidence = 0.4*rsi + 0.4*vol + 0.2
- `src/intelligence/trading/regime_transition.py` - RegimeTransitionPlugin: BOCPD cp_probability>0.5 AND choch_detected==1.0 required
- `tests/unit/intelligence/test_cis_plugins.py` - 32 TDD tests for all 5 plugins
- `src/intelligence/register_plugins.py` - 5 new imports, 5 new register_pattern() calls, TIER_I7 expanded to 14
- `tests/unit/intelligence/test_i7_registration.py` - expected_i7 set updated to 14 names, total assertion 57→62
- `tests/unit/intelligence/test_plugin_registry.py` - test_tier_i7_has_9_plugins renamed/updated to 14

## Decisions Made

- DivergenceStack dual-gate LOCKED: single RSI or single volume divergence is insufficient — both must agree. This prevents false positives from noise in one indicator.
- PatternCompletion scales confidence by 0.9 to fit signal-quality range; takes highest-confidence when multiple patterns fire simultaneously.
- CHoCHReversal and RegimeTransition both use choch_detected as a gate — deliberate overlap ensures the CHoCH signal has structural context when used independently vs. paired with a changepoint event.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Updated test_plugin_registry.py TIER_I7 count assertion**
- **Found during:** Task 2 (registration updates)
- **Issue:** `test_tier_i7_has_9_plugins` asserted `len(TIER_I7) == 9` — would fail after expanding TIER_I7 to 14 as planned
- **Fix:** Renamed to `test_tier_i7_has_14_plugins` and updated assertion to `== 14`
- **Files modified:** tests/unit/intelligence/test_plugin_registry.py
- **Verification:** Full suite passes, 708 tests green
- **Committed in:** 45d039c (Task 2 commit)

**2. [Rule 1 - Bug] Fixed ruff E501 line-too-long in pattern_completion.py**
- **Found during:** Task 2 verification (ruff lint check)
- **Issue:** f-string for signal_type construction was 107 chars (limit 100)
- **Fix:** Split into `suffix = "long" if direction == 1 else "short"` + `signal_type = f"pattern_{pattern_name}_{suffix}"`
- **Files modified:** src/intelligence/trading/pattern_completion.py
- **Verification:** `ruff check` returns 0 errors
- **Committed in:** 45d039c (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 missing critical assertion, 1 lint bug)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered

None — plan executed cleanly. All 5 plugins followed the established TrendFollowingPlugin protocol exactly.

## User Setup Required

None — no external service configuration required. New plugins are automatically picked up by signal_generator_service via TIER_I7.

## Next Phase Readiness

- TIER_I7 has 14 plugins ready for CIS bucket scorer (07-02)
- All 14 plugins follow PatternPlugin protocol, return standardized signal dicts with direction/confidence
- 07-02 can import all 5 new plugins by name from TIER_I7 without any additional wiring

---
*Phase: 07-composite-intelligence-score*
*Completed: 2026-02-28*
