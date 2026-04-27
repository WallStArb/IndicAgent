---
phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep
plan: 03
subsystem: intelligence
tags: [gradient, smc, i3-structure, i5-patterns, companion-fields, schema-first]

# Dependency graph
requires: [65-01]
provides:
  - bos_strength/choch_strength continuous companion fields for BOS/CHoCH
  - sweep_strength/reclaim_velocity for LiquiditySweeps
  - kz_*_progress killzone time fractions for ICTKillzones
  - manip_strength for AMDCycle
  - va_position_pct/va_distance_atr for MarketProfile
  - inside_bar_depth/outside_bar_expansion for CandlestickPatterns
  - Continuous MTFVolatility expansion values (replacing binary)
  - Exponential freshness decay for SupplyDemandZones
affects: [65-04, 65-05, i7-signals, ml-training-features]

# Tech tracking
tech-stack:
  added: []
  patterns: [gradient-companion-fields, schema-first-registration, exponential-freshness-decay]

key-files:
  created: []
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/features/smc_context/bos_choch.py
    - src/intelligence/features/smc_context/liquidity_sweeps.py
    - src/intelligence/features/smc_context/ict_killzones.py
    - src/intelligence/features/smc_context/supply_demand_zones.py
    - src/intelligence/features/smc_context/amd_cycle.py
    - src/intelligence/features/i3_structure/market_profile.py
    - src/intelligence/features/i5_patterns/candlestick_patterns.py
    - src/intelligence/features/i5_patterns/mtf_volatility.py
    - tests/unit/intelligence/test_i5_new_plugins.py

key-decisions:
  - "SCHEMA FIRST pattern: all fields registered in schemas.py before plugin modifications to prevent validate_schema_coverage() startup crash"
  - "bos_strength/choch_strength use break distance / ATR for cross-instrument normalization"
  - "sweep_strength uses linear_ramp(depth, 0, 2.0) mapping 0-2% penetration to 0-1"
  - "reclaim_velocity uses linear_ramp(1/bars_to_reclaim, 0, 0.5) -- fast reclaims score higher"
  - "kz_*_progress uses simple time fraction (cur-start)/(end-start) not session_progress bell curve since linear progression is more natural for killzone progress"
  - "manip_strength uses spike magnitude / overnight range ratio instead of z-score"
  - "supply_demand freshness replaced 2-step (1.0->0.5->...) with exponential freshness_decay(k=0.5)"
  - "MTFVolatility expansion outputs continuous upstream values directly (max(0, val)) instead of binary 1.0/0.0"
  - "squeeze_within_expansion combines squeeze_depth * expansion_magnitude via linear_ramp"

patterns-established:
  - "Gradient companion: binary detection flag preserved for I7 direction gating; continuous field added alongside"
  - "Schema-first: register ALL new fields in schemas.py before touching plugin outputs frozensets"

requirements-completed: [GRAD-I3-STRUCT, GRAD-SMC, GRAD-I5-PATTERNS]

# Metrics
duration: 9min
completed: 2026-04-24
---

# Phase 65 Plan 03: SMC + I3 + I5 Gradient Companion Fields Summary

**15 new additive gradient companion fields across 8 plugins, with exponential freshness decay replacing 2-step logic, and continuous MTFVolatility outputs replacing binary thresholds**

## Performance

- **Duration:** 9 min
- **Started:** 2026-04-24T11:03:40Z
- **Completed:** 2026-04-24T11:12:28Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments
- Added 13 new gradient companion fields to SMC/I3 schema classes (schemas.py)
- Added 2 new gradient companion fields to I5 schema class (inside_bar_depth, outside_bar_expansion)
- Converted MTFVolatility from binary to continuous expansion outputs
- Replaced SupplyDemandZones 2-step freshness with exponential decay
- All validate_schema_coverage() checks pass (startup gate)
- 31 unit tests pass including 7 new gradient continuity tests

## Task Commits

Each task was committed atomically:

1. **Task 1: SMC + I3 gradient companions + schema registration** - `ea949f4f` (feat)
2. **Task 2: I5 MTFVolatility + CandlestickPatterns gradients + tests** - `8f068387` (feat)

## Files Created/Modified
- `src/intelligence/schemas.py` - 15 new fields across SMCContext (9), I3Structure (2), I5Patterns (2); docstring counts updated
- `src/intelligence/features/smc_context/bos_choch.py` - bos_strength/choch_strength: break distance / ATR
- `src/intelligence/features/smc_context/liquidity_sweeps.py` - sweep_strength/reclaim_velocity with linear_ramp normalization
- `src/intelligence/features/smc_context/ict_killzones.py` - kz_asia/london/ny_am/ny_pm_progress: time fraction [0,1]
- `src/intelligence/features/smc_context/supply_demand_zones.py` - exponential freshness_decay(k=0.5) replacing 2-step logic
- `src/intelligence/features/smc_context/amd_cycle.py` - manip_strength: spike / overnight range ratio
- `src/intelligence/features/i3_structure/market_profile.py` - va_position_pct/va_distance_atr
- `src/intelligence/features/i5_patterns/candlestick_patterns.py` - inside_bar_depth/outside_bar_expansion companions
- `src/intelligence/features/i5_patterns/mtf_volatility.py` - continuous expansion values, gradient squeeze_within
- `tests/unit/intelligence/test_i5_new_plugins.py` - 7 new tests for gradient companions and continuous MTF outputs

## Decisions Made
- SCHEMA FIRST pattern enforced: all fields registered in schemas.py before plugin modifications to prevent validate_schema_coverage() startup crash
- bos_strength/choch_strength use break distance / ATR for cross-instrument normalization
- sweep_strength uses linear_ramp(depth, 0, 2.0) mapping 0-2% penetration to 0-1
- reclaim_velocity uses linear_ramp(1/bars_to_reclaim, 0, 0.5) -- fast reclaims score higher
- kz_*_progress uses simple linear time fraction (cur-start)/(end-start) rather than session_progress bell curve since linear progression is more natural for killzone progress tracking
- manip_strength uses spike magnitude / overnight range ratio instead of z-score (z-score requires statistical window that is not available in the plugin's state)
- supply_demand freshness replaced 2-step (1.0->0.5->...) with exponential freshness_decay(k=0.5)
- MTFVolatility expansion outputs continuous upstream values directly (max(0, val)) instead of binary 1.0/0.0
- squeeze_within_expansion combines squeeze_depth * expansion_magnitude via linear_ramp

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All SMC/I3/I5 gradient companion fields ready for I7 consumption
- SupplyDemandZones freshness now provides richer gradient signal for zone scoring
- MTFVolatility continuous outputs enable finer-grained volatility regime detection
- 31 unit tests CI-clean, schema coverage validates

## Self-Check: PASSED

All files verified present: schemas.py, bos_choch.py, liquidity_sweeps.py, ict_killzones.py, supply_demand_zones.py, amd_cycle.py, market_profile.py, candlestick_patterns.py, mtf_volatility.py, test_i5_new_plugins.py
All commits verified in git log: ea949f4f (Task 1), 8f068387 (Task 2)
Schema coverage validation passed: register_all_plugins() completes without RuntimeError

---
*Phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep*
*Completed: 2026-04-24*
