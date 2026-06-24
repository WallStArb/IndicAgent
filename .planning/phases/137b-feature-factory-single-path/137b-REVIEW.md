---
phase: 137b-feature-factory-single-path
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - src/intelligence/feature_factory.py
  - services/backfill_feature_factory.py
  - tests/unit/intelligence/test_feature_factory_p7.py
  - tests/unit/test_feature_factory.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 137b: Code Review Report

**Reviewed:** 2026-06-23
**Depth:** Standard
**Files Reviewed:** 4
**Status:** Clean

## Summary

Reviewed the FeatureFactory single-path refactor (Phase 137b Plans P1 and P2). The refactor successfully eliminates the dual-path `precomputed` architecture that allowed batch and streaming computation to diverge via a stringly-typed bypass. All source-of-truth `_*_series_full` functions are now the only math implementation, with both `compute()` (streaming) and `compute_batch()` (batch) using identical code paths.

All reviewed files meet quality standards. No issues found.

## Changes Reviewed

### P1: FeatureFactory Architecture (src/intelligence/feature_factory.py)

**Signature Changes:**
- `FeatureFactory.compute()`: Removed `precomputed: dict | None = None` parameter
- New signature: `compute(bars, symbol, tf, cache, config)`
- Added static method `compute_batch(bars, symbol, tf, cache, config, warm_up_bars=0)`

**Code Changes:**
- Added `_gap_z_series_full()` function (43 lines) - ATR-normalized open gap with z-score
- Deleted 15 scalar functions (374 lines): `_rolling_zscore`, `_gap_z`, `_ofi_z`, `_cvd_accumulate`, `_cvd_slope_z`, `_volume_z`, `_momentum_z`, `_atr_z`, `_vwap_dev_sigma`, `_amihud_illiq_z`, `_high_52w_dist`, `_rolling_stat_z`, `_ret_skew_z`, `_ret_acf1_z`
- Replaced 19 precomputed branching blocks with direct `_*_series_full(arrays, ...)[-1]` calls
- Kept `_atr_wilder` as reference implementation with comment for test-only use
- `compute_batch()` precomputes all 19 `_*_series_full` functions once (O(n)), then indexes series[i] per bar

**Verified:**
- No `precomputed` parameter remains in compute() signature
- No stringly-typed bypass patterns in code
- `grep -c "precomputed"` returns 0 in source files (only comments/docs)
- `compute()` uses bounded `_*_series_full(arrays)[-1]` calls
- `compute_batch()` uses precomputed `_*_series_full(arrays)` and indexes at `[i]`

### P2: Consumer Updates (services/backfill_feature_factory.py)

**Code Changes:**
- Deleted `_precompute_series()` function (~60 lines)
- Deleted `_MIN_BATCH_WINDOW` constant
- Replaced precompute + per-bar loop with single `FeatureFactory.compute_batch()` call
- Simplified `_compute_symbol_tf()` from ~80 lines to ~30 lines

**Verified:**
- `grep -c "def _precompute_series"` returns 0
- `grep -c "_MIN_BATCH_WINDOW"` returns 0
- `grep -c "_series_full"` returns 0 in backfill file
- `compute_batch()` is called correctly with warm_up_bars parameter

### Test Updates

**test_feature_factory_p7.py:**
- Replaced 4 scalar function imports: `_amihud_illiq_z` → `_amihud_illiq_z_series_full`, `_high_52w_dist` → `_high_52w_dist_series_full`, `_ret_skew_z` → `_ret_skew_z_series_full`, `_ret_acf1_z` → `_ret_acf1_z_series_full`
- Updated all test call sites to use `_*_series_full(...)[-1]` pattern
- Test semantics preserved: cold-start and finite-output behavior verified

**test_feature_factory.py:**
- Replaced `_rolling_zscore` import with `_rolling_zscore_series`
- Updated `TestRollingZscore` class to test series arrays

**Deleted:**
- `tests/unit/test_batch_feature_parity.py` (~172 lines) - tested precomputed functionality removed in P1
- `test_full_precomputed_produces_valid_feature_vectors` from `test_feature_factory_batch_parity.py` (~109 lines)

**Verified:**
- No scalar function imports remain in test files
- All 82 tests pass
- No references to deleted test file remain

## Technical Verification

**Parity Test:**
```python
fv_compute = FeatureFactory.compute(bars[10:], 'SPY', '1m', cache1, cfg)
fv_batch = FeatureFactory.compute_batch(bars[10:], 'SPY', '1m', cache2, cfg)[-1][1]
# momentum_z_fast diff: 0.0 (exact parity)
```

**ATR Indexing in compute_batch():**
- `atr_series` has length `n-1` (from `_atr_series_full`)
- Loop starts at `i=1`, indexes `atr_series[i-1]` - correct alignment verified
- Edge case: `i-1 < len(atr_series)` guard prevents out-of-bounds access

**_gap_z_series_full Edge Cases:**
- `n < 2`: returns zeros immediately
- `n >= 2`: builds gap_raw from `opens[2:]` and `closes[1:-1]`, z-scores, assigns to `result[2:]`
- Cold start (first 2 positions): returns zeros - matches streaming behavior
- No NaN/inf values in tested cases

**Cache State in compute_batch():**
- `refresh_regime()` called periodically before warm-up check
- Warm-up bars still call `cache.advance_bar()` - correct for maintaining per-bar counters
- No double-counting: `refresh_regime` updates regime values, `advance_bar` increments counters

## Architecture Validation

**Single-Source-of-Truth:**
- Math layer: `_*_series_full` functions (14 total)
- Streaming path: `compute()` calls `_*_series_full(bounded_arrays)[-1]`
- Batch path: `compute_batch()` calls `_*_series_full(full_arrays)`, indexes `series[i]`
- No divergence possible by construction

**Stringly-Typed Bypass Eliminated:**
- Old: `precomputed={"atr_z": float(arr[i])}` - typo would silently produce 0.0
- New: Direct function call with type-checked numpy arrays - compile-time safety

**Complexity Reduction:**
- Net: -3 lines in feature_factory.py (+371, -374)
- Net: -107 lines in backfill_feature_factory.py
- Net: -268 lines in test files
- **Total: ~375 lines of complexity eliminated**

---

_Reviewed: 2026-06-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
