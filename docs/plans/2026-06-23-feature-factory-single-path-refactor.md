# FeatureFactory Single-Path Refactor

**Date:** 2026-06-23
**Status:** Approved

## Problem

`FeatureFactory.compute()` has two implementations of the same math. Every feature
covered by a `_*_series_full` function has an `if precomputed / else` branch:

```python
if precomputed is not None and "momentum_z_fast" in precomputed:
    momentum_z_fast_val = precomputed["momentum_z_fast"]
elif len(closes) > wf:
    ...  # different implementation
```

This is a stringly-typed bypass. A misspelled key, a missing key, or a future
addition to one branch but not the other produces a silent wrong number. Silent
wrong answers are the cardinal sin — they produce poisoned training data for the
IC engine with no error raised.

The `precomputed` dict was added as a performance hack because `compute()` was
called with 2000-bar windows inside a backfill loop, making the naive path
O(n² × window). The O(n) batch optimization is legitimate, but the mechanism
(stringly-typed bypass of the computation) is wrong. The fix is to separate the
optimization from the computation.

## Design

Three layers with a clean separation of concerns:

```
Math layer        _*_series_full functions          single source of truth
                        ↓                  ↓
Streaming         FeatureFactory.compute()      Batch    FeatureFactory.compute_batch()
one bar at        calls series_full[-1]         n bars   calls series_full once → indexes
a time            on bounded window             at once  series arrays per bar
```

### Layer 1 — Math (`_*_series_full`)

All computation lives here. No changes to existing functions.

One addition: `_gap_z_series_full(opens, highs, lows, closes, period, zscore_window)`
extracted from the inline logic currently duplicated in `_precompute_series`. This
is the only new function needed — all other series_full variants already exist.

### Layer 2 — Streaming (`FeatureFactory.compute`)

**What changes:**
- Remove `precomputed: dict | None = None` parameter
- Replace every `if precomputed / else` branch with a direct `_*_series_full(arrays, ...)[-1]` call
- `_atr_series_full` + `_rolling_zscore_series` produce `atr_val` and `atr_z_val`
- All 19 precomputed features become single-expression calls

**What stays identical:**
- Signature: `compute(bars, symbol, tf, cache, config) -> FeatureVector`
- All cache reads (hmm, hurst, garch, vix_z, ctf, session)
- All calendar computations
- Features without series_full equivalents: `cmf`, `cci`, `aroon`, `vol_ratio`,
  `range_position`, `bar_close_pos`, `informed_flow` — these are already O(n) per
  call and not drift-prone; they keep their current scalar/array implementations
- Cold-start semantics: `_*_series_full` functions already return 0.0 at cold-start
  positions by construction

**Performance:** streaming calls `compute()` once per live bar with a bounded
history (BarHistory's maxlen). Running `_*_series_full` on that bounded array is
identical in cost to the old scalar path on the same data.

### Layer 3 — Batch (`FeatureFactory.compute_batch`)

New static method. Replaces the `_precompute_series` + per-bar `compute()` pattern
in `backfill_feature_factory.py`.

```python
@staticmethod
def compute_batch(
    bars: list[dict],
    symbol: str,
    tf: str,
    cache: FeatureCache,
    config: FeatureFactoryConfig,
    warm_up_bars: int = 0,
) -> list[tuple[datetime, FeatureVector]]:
```

**Internally:**
1. Extract full numpy arrays from `bars` once
2. Call each `_*_series_full()` once — O(n) total for 19 series
3. Loop over bars `i = 1..n`:
   - Periodically call `cache.refresh_regime(bars[window:i+1], config)`
   - Skip `i < warm_up_bars`
   - Build FeatureVector: series-precomputed features from `series[i]`,
     non-series features from bounded-window calls (`cmf`, `cci`, `aroon`,
     `vol_ratio`, `range_position`, `bar_close_pos`, `informed_flow`),
     cache features from `cache.*`
   - Call `cache.advance_bar(...)`
   - Append `(bar_ts, fv)` to results
4. Return results

Non-series features (`cmf`, `cci x3`, `aroon x2`, `vol_ratio`, `range_position`)
use a 50-bar window per bar. At n=300k bars: 9 calls × O(50) = O(450) per bar =
O(135M) total — negligible vs the O(n) series precompute cost.

**Cross-asset state** (`vix_z`, `flight_quality`, `yield_slope_z`) is seeded by the
caller before `compute_batch()` via `cache.update_cross_asset()`, same as today.

### Invariant enforced by this design

Any future feature addition requires:
1. One `_*_series_full` function (math, single implementation)
2. One line in `compute()`: `feature_val = _feature_series_full(arrays, ...)[-1]`
3. One line in `compute_batch()`: precompute the series, index at `i`

There is no mechanism by which batch and streaming can diverge — both call the
same `_*_series_full` function.

## Dead Code Deleted

### Scalar streaming functions (deleted entirely)

These existed only because of the dual-path design. All dead after refactor:

| Function | Reason deleted |
|----------|---------------|
| `_rolling_zscore(value, history, deque, window)` | Deque-based scalar zscore — replaced by `_rolling_zscore_series` |
| `_ofi_z(high, low, close, vol, history, window)` | Deque-based — replaced by `_ofi_z_series_full[-1]` |
| `_cvd_accumulate(...)` | Helper for deque CVD — replaced by `_cvd_slope_z_series_full` |
| `_cvd_slope_z(session_cvd, history, slope_bars, window)` | Deque-based — replaced by `_cvd_slope_z_series_full[-1]` |
| `_volume_z(volume, history, window)` | Deque-based — replaced by `_volume_z_series_full[-1]` |
| `_momentum_z(closes, window, history, zscore_window)` | Replaced by `_momentum_z_series_full[-1]` |
| `_atr_z(highs, lows, closes, period, history, window)` | Replaced by `_atr_series_full + _rolling_zscore_series` |
| `_rsi_wilder(gains, losses, period)` | Replaced by `_rsi_series_full[-1]` |
| `_amihud_illiq_z(closes, volumes, window)` | Replaced by `_amihud_illiq_z_series_full[-1]` |
| `_high_52w_dist(closes, window)` | Replaced by `_high_52w_dist_series_full[-1]` |
| `_ret_skew_z(closes, skew_window, zscore_window)` | Replaced by `_ret_skew_z_series_full[-1]` |
| `_ret_acf1_z(closes, acf_window, zscore_window)` | Replaced by `_ret_acf1_z_series_full[-1]` |
| `_rolling_stat_z(closes, stat_fn, window, zscore_window)` | Helper for the above two — both gone |
| `_vwap_dev_sigma(opens, highs, lows, closes, volumes)` | Replaced by `_vwap_dev_sigma_series_full[-1]` |
| `_gap_z(open, prev_close, atr, history, window)` | Deque-based, never called from compute() — replaced by `_gap_z_series_full[-1]` |

### `_atr_wilder` — kept

Kept as a scalar reference implementation. Used in `test_feature_factory_batch.py`
to verify `_atr_series_full` numerically. It is the simplest correct statement of
Wilder's EMA and serves as a human-readable spec for the series variant. Marked
with a comment: `# Reference implementation — used in tests only.`

### `backfill_feature_factory.py` changes

- Delete `_precompute_series()` function (~60 lines)
- Delete `_MIN_BATCH_WINDOW` constant
- Delete all `_*_series_full` imports (no longer called directly)
- Replace the `series = _precompute_series(bars, config)` + per-bar `compute()` loop
  with a single `FeatureFactory.compute_batch(bars, symbol, tf, cache, config, warm_up_bars)` call
- Loop over results to build `insert_batch`

### `precomputed` parameter

Removed from `FeatureFactory.compute()`. No migration needed — only
`backfill_feature_factory.py` passed it, and that caller is being rewritten.

## Test Updates

`test_feature_factory_p7.py` imports the scalar functions being deleted:
`_amihud_illiq_z`, `_high_52w_dist`, `_ret_skew_z`, `_ret_acf1_z`. These tests
verify cold-start and finite-output behavior. After refactor, they test the
`_*_series_full` equivalents instead:

```python
# Before
assert _amihud_illiq_z(closes, volumes, 20) == 0.0

# After  
assert _amihud_illiq_z_series_full(closes, volumes, 20)[-1] == 0.0
```

Semantics preserved — cold-start behavior of `_*_series_full` is already tested
and matches.

`test_feature_factory_batch_parity.py` — no changes. Tests already verify
`_*_series_full` functions against `FeatureFactory.compute()`. After the refactor,
both paths use the same functions, so these tests verify internal consistency.

`test_feature_factory_batch.py` — no changes. Tests `_atr_series_full` against
`_atr_wilder` (which is kept).

## Files Changed

| File | Change |
|------|--------|
| `src/intelligence/feature_factory.py` | Add `_gap_z_series_full`; delete 15 scalar functions; remove `precomputed` from `compute()`; rewrite 19 feature blocks to `_series_full[-1]`; add `FeatureFactory.compute_batch()` |
| `services/backfill_feature_factory.py` | Delete `_precompute_series`, `_MIN_BATCH_WINDOW`, series_full imports; simplify `_compute_symbol_tf` to call `compute_batch()` |
| `tests/unit/intelligence/test_feature_factory_p7.py` | Update 4 scalar function imports/calls to `_*_series_full[-1]` |

## What Does Not Change

- `FeatureVector` schema — zero field changes
- `FeatureCache` — zero changes
- `FeatureVectorPipeline` (streaming service) — calls `compute()` with same signature
- All `_*_series_full` functions — math is correct and tested; untouched
- Calendar, cache, session, CTF features — not part of the dual-path problem
- Parity tests — remain valid, now test internal consistency rather than cross-path

## Performance

| Path | Before | After |
|------|--------|-------|
| Streaming (per bar) | O(window) scalar per feature | O(window) `_series_full[-1]` per feature — identical |
| Batch (full backfill) | O(n) precompute + O(1) lookup | O(n) `_series_full` in `compute_batch()` — identical |
| Batch non-series features | O(50) per bar per feature | O(50) per bar per feature — identical |

No regression. The precompute optimization is preserved inside `compute_batch()`.
