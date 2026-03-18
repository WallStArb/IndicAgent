---
phase: 34-i4-infrastructure-anchored-vwap-volume-profile
plan: "03"
subsystem: intelligence/trading
tags: [i7, plugins, vwap, volume-profile, mean-reversion, trend-breakout]
dependency_graph:
  requires: [34-01, 34-02]
  provides: [trad_AnchoredVWAPReversion, trad_VWAPReclaim, trad_POCRejection, trad_HVNRejection, trad_LVNBreakout]
  affects: [register_plugins, aggregator, TIER_I7, intelligence_features.i7]
tech_stack:
  added: []
  patterns: [i7-plugin, frame_trade, tdd-red-green, orb15-volume-fallback]
key_files:
  created:
    - src/intelligence/trading/anchored_vwap_reversion.py
    - src/intelligence/trading/vwap_reclaim.py
    - src/intelligence/trading/poc_rejection.py
    - src/intelligence/trading/hvn_rejection.py
    - src/intelligence/trading/lvn_breakout.py
    - production/migrations/037_vwap_volume_profile_fields.sql
    - tests/unit/intelligence/trading/test_anchored_vwap_reversion.py
    - tests/unit/intelligence/trading/test_vwap_reclaim.py
    - tests/unit/intelligence/trading/test_poc_rejection.py
    - tests/unit/intelligence/trading/test_hvn_rejection.py
    - tests/unit/intelligence/trading/test_lvn_breakout.py
  modified:
    - src/intelligence/register_plugins.py
    - src/intelligence/trading/aggregator.py
    - tests/unit/intelligence/test_i7_registration.py
    - tests/unit/intelligence/test_plugin_registry.py
decisions:
  - "TIER_I7 count 23→28; total plugin count 106→111"
  - "trad_LVNBreakout added to TREND_SETUPS (regime_type=trend); 4 others excluded"
  - "AnchoredVWAPReversion/POCRejection/HVNRejection are regime_type=mean_reversion; VWAPReclaim is regime_type=any"
  - "Pre-existing test failure in test_setup_performance_updater.py excluded as out-of-scope (30-day window test fails before and after our changes)"
metrics:
  duration_minutes: 11
  completed_date: "2026-03-17"
  tasks: 3
  files_created: 11
  files_modified: 4
  tests_added: 44
---

# Phase 34 Plan 03: VWAP + Volume Profile I7 Plugins Summary

Five new I7 trading setup plugins consuming I4 AnchoredVWAP and VolumeProfile fields, registered in TIER_I7, with full TDD test coverage and DB migration.

## What Was Built

### trad_AnchoredVWAPReversion
Mean-reversion signal firing when `|session_vwap_deviation_sigma| >= 1.5` in a ranging regime (`hmm_regime=0`) with Hurst exponent confirmation (`hurst < 0.55`). Direction: short when sigma > 0 (above VWAP), long when sigma < 0. T1 = session_vwap, T2 = opposite VWAP band. Confidence: sigma magnitude + velocity-toward-vwap + hurst quality + vol stability.

### trad_VWAPReclaim
Any-regime signal firing on VWAP cross with volume expansion (`rel_volume >= 1.2`). Tracks `bars_below`/`bars_above` per `(symbol, tf)` state key. Requires at least 1 bar spent on wrong side before the cross. ORB15 volume fallback used when `rel_volume` unavailable.

### trad_POCRejection
Mean-reversion signal at the Point of Control. Gates: `abs(close - poc_price) / atr < 0.3` (proximity) + momentum reversal (`rsi_div > 0.3` or stoch extreme). Long if below POC, short if above.

### trad_HVNRejection
Mean-reversion signal at High Volume Node levels. Checks `nearest_hvn_above` and `nearest_hvn_below` proximity (< 0.3 ATR). Picks closer HVN when both qualify. Same momentum reversal gate as POCRejection.

### trad_LVNBreakout
Trend setup firing when `in_lvn == 1.0` with trending regime (`hmm_regime in {1, 2}`) and volume expansion (`rel_volume >= 1.5`). Direction from bar close vs open. T1 overridden with `nearest_hvn_above` (long) or `nearest_hvn_below` (short).

## Registration Changes

- TIER_I7: 23 → 28 (added 5 new plugins)
- Total plugins: 106 → 111 (25 indicators + 86 patterns)
- TREND_SETUPS: added `trad_LVNBreakout`
- All other 4 plugins excluded from TREND_SETUPS (mean_reversion or any regime)

## DB Migration

`037_vwap_volume_profile_fields.sql` — documentation-only migration. No DDL required since `intelligence_features.i4` is JSONB. Documents all AnchoredVWAP (15 fields) and VolumeProfile (18 fields) I4 output fields for discoverability.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Missing Field] test_plugin_registry.py hardcoded 23 for TIER_I7 count**
- **Found during:** Task 3 verification
- **Issue:** `test_tier_i7_has_23_plugins` would fail after registering 5 new plugins
- **Fix:** Updated test to `test_tier_i7_has_28_plugins` with count == 28
- **Files modified:** `tests/unit/intelligence/test_plugin_registry.py`
- **Commit:** 95476f9

### Deferred Issues

**Pre-existing test failure: `test_compute_setup_performance_30day_window`**
- Fails before and after this plan's changes (confirmed via `git stash`)
- `sample_size == 55` when `== 30` expected — 30-day window filtering bug in `compute_setup_performance()`
- Out of scope for this plan — logged to deferred

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | db54d46 | feat(34-03): implement trad_AnchoredVWAPReversion + trad_VWAPReclaim I7 plugins |
| Task 2 | 754291a | feat(34-03): implement trad_POCRejection + trad_HVNRejection + trad_LVNBreakout I7 plugins |
| Task 3 | 95476f9 | feat(34-03): register 5 new I7 plugins, update TREND_SETUPS, create migration 037 |

## Test Coverage

| File | Tests |
|------|-------|
| test_anchored_vwap_reversion.py | 10 |
| test_vwap_reclaim.py | 9 |
| test_poc_rejection.py | 8 |
| test_hvn_rejection.py | 8 |
| test_lvn_breakout.py | 9 |
| test_i7_registration.py | +3 new assertions |
| **Total** | **44 new tests** |

## Self-Check: PASSED

All created files verified present. All task commits verified in git log. 44 new tests passing. TIER_I7 count = 28 confirmed. trad_LVNBreakout in TREND_SETUPS confirmed.
