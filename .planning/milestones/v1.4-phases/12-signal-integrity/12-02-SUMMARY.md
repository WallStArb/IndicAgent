---
phase: 12-signal-integrity
plan: "02"
subsystem: intelligence
tags: [i7, plugins, regime-classification, dataclass, signal-integrity]

# Dependency graph
requires:
  - phase: 12-signal-integrity-plan-01
    provides: "test_all_i7_plugins_have_regime_type_attribute RED test"
provides:
  - "regime_type class attribute on all 17 I7 plugin dataclasses"
  - "5 plugins tagged trend, 5 tagged mean_reversion, 7 tagged any"
affects:
  - "12-03 aggregator regime eligibility gate (reads regime_type at runtime)"
  - "12-04 regime-gated signal filtering"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "regime_type: str = 'trend'|'mean_reversion'|'any' placed after inputs field, before _state"

key-files:
  created: []
  modified:
    - src/intelligence/trading/trend_following.py
    - src/intelligence/trading/momentum_breakout.py
    - src/intelligence/trading/liquidity_hunt.py
    - src/intelligence/trading/mtf_alignment.py
    - src/intelligence/trading/squeeze_expansion.py
    - src/intelligence/trading/mean_reversion.py
    - src/intelligence/trading/vwap_deviation.py
    - src/intelligence/trading/fvg_fill.py
    - src/intelligence/trading/liquidity_sweep_reclaim.py
    - src/intelligence/trading/session_extremes_setup.py
    - src/intelligence/trading/choch_reversal.py
    - src/intelligence/trading/regime_transition.py
    - src/intelligence/trading/divergence_stack.py
    - src/intelligence/trading/pattern_completion.py
    - src/intelligence/trading/gap_analysis_setup.py
    - src/intelligence/trading/candlestick_pattern_setup.py
    - src/intelligence/trading/supply_demand_setup.py

key-decisions:
  - "LiquidityHunt classified as trend (not any) — requires trending regime for institutional sweep follow-through"
  - "LiquiditySweepReclaim classified as mean_reversion — counter-trend entry after sweep exhaustion"
  - "SqueezeExpansion classified as trend — squeeze resolves into sustained trending moves; false in ranging"
  - "CHoCHReversal, RegimeTransition classified as any — gating on current regime would suppress at the exact moment they should fire (at transition)"
  - "CandlestickPatternSetup classified as any — confluence score is its own quality gate regardless of regime"

patterns-established:
  - "regime_type field position: after capability_tags + inputs, before first numeric threshold or _state"
  - "regime_type uses default value syntax (regime_type: str = 'trend') not bare annotation — required for dataclass compatibility"

requirements-completed: [SIGINT-01]

# Metrics
duration: 2min
completed: 2026-03-04
---

# Phase 12 Plan 02: Signal Integrity — regime_type Attribute Summary

**regime_type class attribute added to all 17 I7 plugin dataclasses — 5 trend, 5 mean_reversion, 7 any — zero logic changes, pure metadata addition**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-04T23:14:25Z
- **Completed:** 2026-03-04T23:16:31Z
- **Tasks:** 2 of 2
- **Files modified:** 17

## Accomplishments
- Added `regime_type: str = "trend"` to 5 trend plugins (TrendFollowing, MomentumBreakout, LiquidityHunt, MTFAlignment, SqueezeExpansion)
- Added `regime_type: str = "mean_reversion"` to 5 mean-reversion plugins (MeanReversion, VWAPDeviation, FVGFill, LiquiditySweepReclaim, SessionExtremesSetup)
- Added `regime_type: str = "any"` to 7 any-regime plugins (CHoCHReversal, RegimeTransition, DivergenceStack, PatternCompletion, GapAnalysisSetup, CandlestickPatternSetup, SupplyDemandSetup)
- `test_all_i7_plugins_have_regime_type_attribute` turned GREEN (was RED from Plan 12-01)
- Zero ruff errors, zero logic changes in any plugin

## Task Commits

Each task was committed atomically:

1. **Task 1: Add regime_type to 5 trend plugins** - `5b24979` (feat)
2. **Task 2: Add regime_type to 12 remaining I7 plugins** - `c7c216b` (feat)

## Files Created/Modified

- `src/intelligence/trading/trend_following.py` — added `regime_type: str = "trend"`
- `src/intelligence/trading/momentum_breakout.py` — added `regime_type: str = "trend"`
- `src/intelligence/trading/liquidity_hunt.py` — added `regime_type: str = "trend"`
- `src/intelligence/trading/mtf_alignment.py` — added `regime_type: str = "trend"`
- `src/intelligence/trading/squeeze_expansion.py` — added `regime_type: str = "trend"`
- `src/intelligence/trading/mean_reversion.py` — added `regime_type: str = "mean_reversion"`
- `src/intelligence/trading/vwap_deviation.py` — added `regime_type: str = "mean_reversion"`
- `src/intelligence/trading/fvg_fill.py` — added `regime_type: str = "mean_reversion"`
- `src/intelligence/trading/liquidity_sweep_reclaim.py` — added `regime_type: str = "mean_reversion"`
- `src/intelligence/trading/session_extremes_setup.py` — added `regime_type: str = "mean_reversion"`
- `src/intelligence/trading/choch_reversal.py` — added `regime_type: str = "any"`
- `src/intelligence/trading/regime_transition.py` — added `regime_type: str = "any"`
- `src/intelligence/trading/divergence_stack.py` — added `regime_type: str = "any"`
- `src/intelligence/trading/pattern_completion.py` — added `regime_type: str = "any"`
- `src/intelligence/trading/gap_analysis_setup.py` — added `regime_type: str = "any"`
- `src/intelligence/trading/candlestick_pattern_setup.py` — added `regime_type: str = "any"`
- `src/intelligence/trading/supply_demand_setup.py` — added `regime_type: str = "any"`

## Decisions Made

- LiquidityHunt → `"trend"`: Requires a trending regime for institutional sweep follow-through; ranging markets produce ambiguous sweeps
- LiquiditySweepReclaim → `"mean_reversion"`: Counter-trend entry after sweep exhaustion — classic reversion setup
- SqueezeExpansion → `"trend"`: Squeezes resolve into sustained directional moves in trending regimes; ranging markets produce false breakouts (per CONTEXT.md locked decision)
- CHoCHReversal, RegimeTransition → `"any"`: These fire AT regime transitions — gating on current regime would suppress them at the exact moment they should fire
- CandlestickPatternSetup → `"any"`: Confluence score (trend gate + volume + S/R) is its own quality mechanism, regime gating is redundant

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

Pre-existing RED tests from Plan 12-01 (TestShadowSignals, TestRegimeEligibilityFilter in test_aggregator.py) were present and expected — these are TDD RED stubs for Plans 12-03/12-04. Zero new test failures introduced.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All 17 I7 plugins now expose `regime_type` attribute readable at runtime by the aggregator
- Plan 12-03 (aggregator regime eligibility gate) can now read `plugin.regime_type` without any dict lookup
- The REGIME_ELIGIBILITY dict in aggregator.py can be removed in 12-03 (replaced by this attribute)

---
*Phase: 12-signal-integrity*
*Completed: 2026-03-04*
