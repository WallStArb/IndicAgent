---
phase: 29-renaissance-signal-quality
plan: "04"
subsystem: intelligence-context
tags: [hurst-exponent, I4-plugin, TDD, QUAL-07, regime-quality]
dependency_graph:
  requires: [29-03]
  provides: [hurst_exponent, hurst_trend_quality, hurst_mr_quality in intelligence bus]
  affects: [market_analysis_service I4 pipeline, intelligence_features JSONB]
tech_stack:
  added: []
  patterns: [R/S analysis, quality-score mapping, I4 plugin dataclass pattern]
key_files:
  created:
    - src/intelligence/context/hurst_exponent.py
    - tests/unit/intelligence/test_hurst_exponent.py
  modified:
    - src/intelligence/register_plugins.py
    - tests/unit/intelligence/test_i7_registration.py
decisions:
  - "min_lookback=64 with last-64-bars slice — consistent rolling estimate, not full-series"
  - "R/S returns 0.5 for constant-price (s=0) and short series — safe neutral default"
  - "Quality mapping thresholds from RESEARCH.md: trend >= 0.65 -> 1.0, mr <= 0.35 -> 1.0"
  - "Both register_all_plugins() and TIER_I4 updated atomically to avoid validate_tier() crash"
metrics:
  duration: "~4 minutes"
  completed: "2026-03-13"
  tasks: 3
  files: 4
---

# Phase 29 Plan 04: HurstExponentPlugin I4 Context Plugin Summary

HurstExponentPlugin (ctx_HurstExponent) added to I4 tier — R/S analysis of last 64 bars outputs hurst_exponent, hurst_trend_quality, and hurst_mr_quality flowing through the intelligence bus into intelligence_features automatically.

## What Was Built

`HurstExponentPlugin` is an I4 context plugin following the exact GARCHVolatilityPlugin dataclass pattern. It computes the classical Rescaled Range (R/S) Hurst exponent on the last 64 close prices, then maps H to two quality scores:

- `hurst_trend_quality`: 1.0 when H >= 0.65 (trending), 0.3 when H <= 0.45, linear between
- `hurst_mr_quality`: 1.0 when H <= 0.35 (mean-reverting), 0.3 when H >= 0.55, linear between

The plugin will be consumed by plan 29-05 to gate I7 setup classes by measured market regime.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| RED | Failing tests: metadata, edge cases, quality mapping, TIER_I4 registration | b822963 |
| GREEN | HurstExponentPlugin + _hurst_rs + quality functions; register in TIER_I4; fix count test | cb3e57d |

## Verification

- 33 HurstExponentPlugin-specific tests: all passing
- Full unit suite: 1613 passing (0 regressions)
- TIER_I4 includes "ctx_HurstExponent" — validate_tier() safe
- hurst_exponent in [0, 1] for all test inputs
- H=0.7 -> hurst_trend_quality=1.0 >= 0.8
- H=0.3 -> hurst_mr_quality=1.0 >= 0.8
- H=0.5 -> both qualities moderate (0.3 < q < 0.8)
- Constant price series (s=0) -> hurst_exponent=0.5 (safe guard)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing update] test_i7_registration.py total_plugin_count**
- **Found during:** GREEN phase — full suite run
- **Issue:** `test_total_plugin_count` expected 96 but got 97 after adding HurstExponent; this assertion must be updated whenever a new plugin is registered
- **Fix:** Updated docstring and assertion from 96 to 97 (25 indicators + 72 patterns)
- **Files modified:** `tests/unit/intelligence/test_i7_registration.py`
- **Commit:** cb3e57d

## Self-Check: PASSED
