---
phase: 18-financial-math-safety
plan: 01
subsystem: Trading Intelligence
tags: ["mathematical-safety", "epsilon-tolerance", "magic-numbers", "renaissance-framing"]
dependency_graph:
  requires: []
  provides: ["EPSILON_TOLERANCE pattern", "ATR multiplier constants", "Regime threshold constants"]
  affects: ["trade_framer.py", "cis_scorer.py", "rsi.py"]
tech_stack:
  added:
  patterns:
    - Epsilon tolerance for floating-point comparisons (1e-9)
    - Named constants with Renaissance framing comments
    - Module-level constants vs class attributes
key_files:
  created: []
  modified:
    - src/intelligence/trading/trade_framer.py
    - src/intelligence/trading/cis_scorer.py
    - src/intelligence/indicators/rsi.py
key_decisions:
  - EPSILON_TOLERANCE = 1e-9 for all floating-point comparisons across trading layer
  - All ATR multipliers extracted to named constants with Renaissance framing
  - Regime thresholds renamed from class attributes to module-level constants
  - RSI zero-loss guard documented with mathematical correctness rationale
requirements_completed:
  - FIN-01
  - FIN-02
  - FIN-03
  - FIN-04
  - FIN-05
  - FIN-06
duration: 4 min
completed_date: 2026-03-08T14:20:43Z
---

# Phase 18 Plan 01: Epsilon Tolerance and Magic Number Documentation Summary

**One-liner:** Implemented 1e-9 epsilon tolerance for floating-point comparisons across trade_framer.py, cis_scorer.py, and documented all ATR multipliers and regime thresholds as named constants with Renaissance framing.

## Overview

Implemented mathematical safety measures for the trading intelligence layer:
- Added EPSILON_TOLERANCE (1e-9) for all floating-point comparisons
- Extracted 13 ATR multipliers as named constants with inline comments
- Renamed 3 regime threshold constants from class attributes to module-level
- Documented RSI zero-loss guard behavior with mathematical correctness rationale

## Changes Made

### trade_framer.py
- Added EPSILON_TOLERANCE = 1e-9 constant
- Added 13 ATR multiplier constants with Renaissance framing:
  - ATR_STOP_DEMAND_MULTIPLIER = 0.25
  - ATR_STOP_SWEEP_MULTIPLIER = 0.30
  - ATR_STOP_OB_MULTIPLIER = 0.20
  - ATR_STOP_SWING_MULTIPLIER = 0.25
  - ATR_STOP_SR_MULTIPLIER = 0.50
  - ATR_STOP_FALLBACK_MULTIPLIER = 2.0
  - ATR_ZONE_SWEEP_MULTIPLIER = 0.5
  - ATR_ZONE_LOW_MULTIPLIER = 1.0
  - ATR_ZONE_HIGH_MULTIPLIER = 0.5
  - ATR_TARGET_MIN_MULTIPLIER = 0.5
  - ATR_TARGET_MAX_MULTIPLIER = 8.0
  - ATR_FALLBACK_T1_MULTIPLIER = 2.0
  - ATR_FALLBACK_T2_MULTIPLIER = 3.5
  - ATR_FALLBACK_T3_MULTIPLIER = 5.5
  - ATR_EMERGENCY_FALLBACK_PCT = 0.001
- Replaced all hardcoded multipliers in _resolve_zone_bounds, _resolve_stop_long, _resolve_stop_short, _collect_targets_long, _collect_targets_short, _pick_targets
- Added docstring comments for MIN_STOP_ATR_MULTIPLIER and MIN_RR_T1

### cis_scorer.py
- Added EPSILON_TOLERANCE = 1e-9 constant
- Renamed class attributes to module-level constants with Renaissance framing:
  - CIS_THRESHOLD -> CIS_FIRE_THRESHOLD = 0.35
  - AGREE_MIN -> BUCKET_AGREE_MIN = 3
  - BUCKET_NOISE -> BUCKET_NOISE_FLOOR = 0.1
- Replaced raw > 0 / < 0 comparisons with EPSILON_TOLERANCE in _trend (slope), _momentum (macd, roc)
- Updated all internal references to use module-level constants

### rsi.py
- Added 3-line inline comment before zero-loss guard:
  - Explains why avg_loss == 0 returns RSI = 100.0
  - References Renaissance principle: data quality over model complexity
  - Notes mathematical correctness: no loss = price only went up

## Deviations from Plan

None - plan executed exactly as written.

## Test Results

All tests passing:
- test_trade_framer.py: 59 passed
- test_cis_scorer.py: 18 passed
- test_i2_plugins.py (RSI): 4 passed

Total: 81 tests passed, 0 failures

## Commits

- 65a4488: feat(18-01): add epsilon tolerance and document ATR multipliers
- d270c41: feat(18-01): add epsilon tolerance for direction comparisons in cis_scorer
- 7a05b48: docs(18-01): document RSI zero-loss guard with Renaissance framing

## Next Steps

Ready for Plan 18-02: Timeout Configuration (API-01, API-02).
