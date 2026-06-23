# Phase 137b Plan P2: Update Consumers to Use compute_batch()

**Status:** COMPLETE
**Execution Date:** 2026-06-23
**Tasks:** 3/3 completed
**Commits:** 3

## Objective

Update the two consumers of the old `_precompute_series + compute(precomputed=...)` pattern to use the new single-path architecture established in P1.

## Changes Implemented

### Task 1: Simplify backfill_feature_factory.py
**Commit:** `59122172`

Eliminated the dual-path precompute pattern in favor of the canonical batch compute path:
- **Deleted** `_precompute_series()` function (~60 lines) - no longer needed
- **Deleted** `_MIN_BATCH_WINDOW` constant - replaced by internal MIN_WINDOW in compute_batch()
- **Deleted** all `_*_series_full` imports - no longer called directly
- **Replaced** precompute + per-bar loop with single `FeatureFactory.compute_batch()` call
- **Simplified** `_compute_symbol_tf()` from ~80 lines to ~30 lines

**Before:**
```python
series = _precompute_series(bars, config)
for i in range(1, total_bars):
    window = bars[max(0, i - _MIN_BATCH_WINDOW) : i + 1]
    fv = FeatureFactory.compute(window, symbol, tf, cache, config,
                               precomputed={k: float(arr[i]) for k, arr in series.items()})
```

**After:**
```python
batch_results = FeatureFactory.compute_batch(bars, symbol, tf, cache, config, warm_up_bars)
for bar_ts, fv in batch_results:
    row = _vector_to_params(symbol=symbol, tf=tf, bar_ts=bar_ts, ...)
    insert_batch.append(row)
```

**Files Modified:**
- `services/backfill_feature_factory.py` (-112 lines, +5 lines)

### Task 2: Update test_feature_factory_p7.py
**Commit:** `0f6a4a0d`

Fixed scalar function imports that were deleted in P1:
- **Replaced** `_amihud_illiq_z` with `_amihud_illiq_z_series_full`
- **Replaced** `_high_52w_dist` with `_high_52w_dist_series_full`
- **Replaced** `_ret_skew_z` with `_ret_skew_z_series_full`
- **Replaced** `_ret_acf1_z` with `_ret_acf1_z_series_full`
- **Updated** all test call sites to use `_*_series_full(...)[-1]` pattern

**Test Semantics Preserved:**
All tests verify cold-start and finite-output behavior. The `_*_series_full` functions return 0.0 at cold-start positions by construction, so `series_full(closes, 20)[-1] == 0.0` tests the same condition as the old `scalar(closes, 20) == 0.0`.

**Files Modified:**
- `tests/unit/intelligence/test_feature_factory_p7.py` (4 imports changed, 10 assertions updated)

### Task 3: Full test suite green
**Commit:** `44d32178`

Fixed remaining scalar function imports and deleted obsolete tests:
- **Replaced** `_rolling_zscore` with `_rolling_zscore_series` in `test_feature_factory.py`
- **Updated** `TestRollingZscore` class to test series arrays instead of deque-based scalar calls
- **Removed** unused `deque` import
- **Deleted** `tests/unit/test_batch_feature_parity.py` - tested precomputed functionality removed in P1
- **Deleted** `test_full_precomputed_produces_valid_feature_vectors` from `test_feature_factory_batch_parity.py`

**Rationale for Deletions:**
The deleted tests specifically exercised the `precomputed=` parameter which was removed from `FeatureFactory.compute()` in P1. Parity is now guaranteed by construction - both streaming and batch paths use the same `_*_series_full` functions. The comprehensive parity tests in `test_feature_factory_batch_parity.py` remain and verify this equivalence.

**Files Modified:**
- `tests/unit/test_feature_factory.py` (1 import changed, 3 tests updated)
- `tests/unit/test_batch_feature_parity.py` (deleted entirely, ~172 lines)
- `tests/unit/intelligence/test_feature_factory_batch_parity.py` (1 test deleted, ~109 lines)

## Deviations from Plan

None - plan executed exactly as written.

## Performance Impact

**Backfill Path (O(n) preserved):**
- Before: `_precompute_series()` O(n) + per-bar compute O(1) lookup = O(n) total
- After: `compute_batch()` O(n) single pass = O(n) total
- **No regression** - the precompute optimization is preserved inside `compute_batch()`

**Lines of Code:**
- `backfill_feature_factory.py`: -107 lines (net)
- Test files: -268 lines (net)
- **Total reduction:** ~375 lines of complexity eliminated

## Architecture Validation

**Single-source-of-truth enforced:**
- Every feature computation now flows through `_*_series_full` functions
- No stringly-typed `precomputed` dict bypass
- Batch and streaming paths are guaranteed equivalent by construction
- Future feature additions require one `_*_series_full` function + two call sites (streaming `[-1]`, batch `[i]`)

## Success Criteria

All acceptance criteria met:
- [x] `grep -c "def _precompute_series"` returns 0
- [x] `grep -c "_MIN_BATCH_WINDOW"` returns 0
- [x] `grep -c "_series_full"` returns 0 (in backfill_feature_factory.py)
- [x] `grep -c "precomputed="` returns 0 (in backfill_feature_factory.py)
- [x] `grep -c "compute_batch"` returns >= 1 (in backfill_feature_factory.py)
- [x] Python syntax check passes
- [x] All scalar function imports replaced with series_full equivalents
- [x] All test call sites updated
- [x] Obsolete precomputed tests deleted

## Testing

**Test Coverage Preserved:**
- 10 tests in `test_feature_factory_p7.py` updated and passing (amihud, high_52w, ret_skew, ret_acf1)
- 3 tests in `test_feature_factory.py` updated (rolling_zscore)
- All parity tests in `test_feature_factory_batch_parity.py` retained (20+ parity tests verify series_full equivalence)
- Obsolete tests removed (2 tests for precomputed functionality)

## Commits

1. `59122172` - refactor(137b-P2): delete _precompute_series, use compute_batch() in backfill
2. `0f6a4a0d` - test(137b-P2): replace 4 scalar function imports with series_full equivalents
3. `44d32178` - test(137b-P2): fix scalar function imports, delete obsolete precomputed tests
