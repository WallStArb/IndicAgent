# FeatureFactory Batch Path Fixes — Unified Plan

**Date:** 2026-06-28
**Status:** Approved
**Milestone:** v3.0 Phase 140

---

## Renaissance Principle Applied

> "Confusion about what's current is technical debt. Four docs means four sources of truth. That's impossible."

This plan consolidates four separate documents:
- `2026-06-23-feature-factory-single-path-refactor.md`
- `2026-06-24-feature-cache-batch-fix-design.md`
- `2026-06-24-feature-factory-batch-integrity.md`
- `2026-06-27-feature-factory-unification.md`

One source of truth. Clear priority. No confusion about what to implement first.

---

## Problem Statement

The `FeatureFactory` batch path has multiple correctness issues that produce silent wrong answers:

1. **Dual-path bypass** — `precomputed` dict allows batch/streaming to diverge silently
2. **12 constant-value features** — cross-asset, CTF, and HMM features return placeholder values in batch mode
3. **Code duplication** — ~95% of compute() and compute_batch() are identical copies
4. **APR violations** — MIN_WINDOW is hardcoded; tuning it has no effect
5. **Performance issues** — O(D×N) cross-asset reprocessing, duplicate RSI loops

Silent constant values are worse than crashes — they produce misleading IC scores and contaminate the training corpus.

---

## Architecture

Three-layer design with clean separation:

```
┌────────────────────────────────────────────────────────────┐
│ Layer 1: Math (_*_series_full functions)                  │
│ Single source of truth for all computation                │
└────────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────────┐
│ Layer 2: Streaming (FeatureFactory.compute)              │
│ Calls _precompute_series + _build_feature_vector          │
│ One bar at a time, bounded window                         │
└────────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────────┐
│ Layer 3: Batch (FeatureFactory.compute_batch)             │
│ Calls _precompute_series + _build_feature_vector          │
│ n bars at once, indexes series[i]                         │
└────────────────────────────────────────────────────────────┘
```

---

## File Map

| File | Changes |
|------|---------|
| `src/intelligence/feature_factory.py` | Add `_gap_z_series_full`, `_PrecomputedSeries`, `_precompute_series`, `_build_feature_vector`, `_wilder_rsi_series`; delete 15 scalar functions; remove `precomputed` from `compute()`; refactor both `compute()` and `compute_batch()` to use shared helpers |
| `src/intelligence/feature_cache.py` | Refactor `_rsi_simple` to wrapper; add `_wilder_rsi_series`, `_zscore_from_deque`; add `update_ctf_from_bars()` method |
| `services/backfill_feature_factory.py` | Delete `_precompute_series()`, `_MIN_BATCH_WINDOW`; replace inline RSI loop; rewrite `_build_cross_asset_series`; pass snapshots into `compute_batch`; delete `dataclasses.replace` block |
| `tests/unit/intelligence/test_feature_factory_p7.py` | Update 4 scalar function imports to `_*_series_full[-1]` |
| `tests/unit/intelligence/test_feature_factory_batch.py` | New tests for MIN_WINDOW, RSI series |
| `tests/unit/intelligence/test_feature_factory_batch_parity.py` | New tests for `_precompute_series`, `_build_feature_vector` |
| `tests/unit/services/test_backfill_feature_factory.py` | New tests for cross-asset series, compute_batch injection |
| New migration | Make 4 VP/SR columns nullable in `feature_vectors` |

---

## Implementation Tasks

### Task 1: Extract shared helpers (compute/compute_batch unification)

**Goal:** Eliminate ~95% code duplication between `compute()` and `compute_batch()`.

**Changes:**
1. Add `_PrecomputedSeries` dataclass — bundles all 15 series arrays
2. Add `_precompute_series()` — calls all `_*_series_full()` once, returns `_PrecomputedSeries`
3. Add `_build_feature_vector()` — shared 54-field `FeatureVector` constructor with `_guard`
4. Add module-level `_guard()` — replaces inline closures

**Tests:**
- `test_precompute_series_returns_all_fields` — all arrays have correct length
- `test_build_feature_vector_guards_nan` — non-finite → fallback
- `test_build_feature_vector_none_passthrough` — None flows through for VP/SR

**Commit message:**
```
refactor(feature_factory): extract _PrecomputedSeries + _precompute_series + _build_feature_vector

Eliminates ~95% code duplication between compute() and compute_batch(). Both
methods now delegate to shared helpers, ensuring batch/streaming parity.
```

---

### Task 2: Refactor compute() to use shared helpers

**Goal:** Remove `precomputed` parameter and all `if precomputed / else` branches.

**Changes:**
- Remove `precomputed: dict | None = None` from `compute()` signature
- Replace every branch with direct `_*_series_full(arrays, ...)[-1]` call
- Use `_precompute_series()` + `_build_feature_vector()`

**Tests:** Parity suite must stay green.

**Commit message:**
```
refactor(feature_factory): compute() uses _precompute_series + _build_feature_vector

Eliminates precomputed dict bypass. No mechanism for batch/streaming divergence
exists — both paths call the same _*_series_full functions.
```

---

### Task 3: Refactor compute_batch() to use shared helpers

**Goal:** Replace inline series precomputation and FeatureVector construction.

**Changes:**
- Replace lines 1212–1255 (series precomputation block) with `s = _precompute_series(...)`
- Replace all `series[i]` references with `s.<field>[i]`
- Replace `FeatureVector(...)` block with `_build_feature_vector(...)`
- Remove inline `_guard` closure

**Tests:** Full parity suite.

**Commit message:**
```
refactor(feature_factory): compute_batch() uses _precompute_series + _build_feature_vector

Both compute() and compute_batch() now delegate to identical shared helpers.
The precompute optimization is preserved inside compute_batch().
```

---

### Task 4: Add _gap_z_series_full and delete dead scalar functions

**Goal:** Complete the single-path refactor by adding the missing series function.

**Changes:**
- Add `_gap_z_series_full()` — extracted from inline logic in deleted `_precompute_series`
- Delete 15 scalar functions: `_rolling_zscore`, `_ofi_z`, `_cvd_accumulate`, `_cvd_slope_z`, `_volume_z`, `_momentum_z`, `_atr_z`, `_rsi_wilder`, `_amihud_illiq_z`, `_high_52w_dist`, `_ret_skew_z`, `_ret_acf1_z`, `_rolling_stat_z`, `_vwap_dev_sigma`, `_gap_z`
- Keep `_atr_wilder` as reference implementation (tests only)

**Tests:** Update `test_feature_factory_p7.py` to call `_*_series_full[-1]`.

**Commit message:**
```
refactor(feature_factory): add _gap_z_series_full, delete 15 scalar functions

Single-path refactor complete. All feature computation lives in _*_series_full
functions. compute() and compute_batch() are thin wrappers that index series[-1]
or series[i] respectively.
```

---

### Task 5: Unify Wilder RSI (eliminate duplicate algorithm)

**Goal:** Two implementations of identical Wilder smoothing → one.

**Changes:**
- Add `_wilder_rsi_series(closes, period) -> np.ndarray` to `feature_cache.py`
- Refactor `_rsi_simple()` to thin wrapper: `return float(_wilder_rsi_series(closes, period)[-1])`
- In `backfill_feature_factory.py`: replace inline RSI loop with `_wilder_rsi_series()` call

**Tests:**
- `test_terminal_value_matches_rsi_simple` — parity for all prefix lengths
- `test_cold_start_returns_50` — handles insufficient data
- `test_values_in_range` — output in [0, 100]

**Commit message:**
```
fix(batch): unify Wilder RSI into _wilder_rsi_series; _rsi_simple is now a wrapper

Two implementations of identical Wilder smoothing existed: _rsi_simple (scalar)
in feature_cache.py and an inline loop in _build_ctf_series. Any numerical fix
to one silently missed the other, poisoning IC parity between batch and live.

_wilder_rsi_series(closes, period) -> np.ndarray is now the single implementation.
Build_ctf_series calls it — eliminating the Python RSI loop entirely.
```

---

### Task 6: Fix MIN_WINDOW APR violation

**Goal:** Derive MIN_WINDOW from config instead of hardcoded constant.

**Changes:**
In `feature_factory.py`, replace:
```python
MIN_WINDOW = 50
```
with:
```python
MIN_WINDOW = max(
    config.cci_slow_period,
    config.aroon_slow_period,
    config.vol_long_bars,
    config.cmf_period,
)
```

**Tests:** `test_compute_batch_produces_results_with_fewer_than_50_bars_warmup`

**Commit message:**
```
fix(batch): derive MIN_WINDOW from config instead of magic constant 50

MIN_WINDOW governed the bounded window for CCI/Aroon/vol_ratio/CMF but was
hardcoded to 50. If cci_slow_period is tuned via APR above 50, features would
silently compute over an insufficient window. Now derived from max of the four
constituent APR-backed params. With defaults (cci_slow=40), value drops 50→40.
```

---

### Task 7: O(D×N) → O(D) cross-asset series + aligned dict structure

**Goal:** Eliminate O(D×N) reprocessing and parallel list misalignment risk.

**Changes:**
- Rewrite `_build_cross_asset_series` with incremental state
- Use single `symbol_bars` dict instead of parallel date lists
- Maintain cursors, deques, and incremental values O(1) per date

**Tests:**
- `test_parity_with_reference_implementation` — matches O(D×N) values to 1e-10
- `test_all_values_finite` — no NaN/inf leaks

**Commit message:**
```
fix(batch): O(D) incremental cross-asset series; eliminate parallel date lists

_build_cross_asset_series was calling update_cross_asset(spy_bars[:end], ...) once
per trading date, re-materializing and re-computing the full growing prefix each
time — O(D×N) total.

Replaced with incremental state: one log-return appended per date to a deque,
realized_vol = std(deque), z-score from history. O(D) total.

Also eliminated three parallel date lists (spy_dates/tlt_dates/shy_dates) in favor
of a single symbol_bars dict — misalignment was a silent look-ahead bias risk.
```

---

### Task 8: compute_batch owns external state injection

**Goal:** Factory owns complete FeatureVector construction; no post-injection patches.

**Changes:**
- Add optional params to `compute_batch`: `cross_asset_by_date`, `ctf_by_ts`, `ctf_ts_list`
- When provided (batch): read cross-asset/CTF from dicts; VP/SR = None
- When None (live): read all from cache (unchanged)
- Update `_guard` to None-passthrough
- Delete `dataclasses.replace` block from `backfill_feature_factory.py`

**Tests:**
- `test_cross_asset_from_dict_not_cache` — dict values used, not cache zeros
- `test_vp_sr_none_when_batch_mode` — VP/SR None in batch
- `test_live_path_unchanged_reads_from_cache` — cache values flow when no dict

**Commit message:**
```
fix(batch): compute_batch owns external state injection; delete dataclasses.replace

FeatureFactory.compute_batch() now accepts cross_asset_by_date, ctf_by_ts, and
ctf_ts_list as optional params. When supplied (batch path), it reads cross-asset
and CTF values from pre-built causal dicts instead of cache, and sets VP/SR to
None. When omitted (live path), all reads fall back to cache — unchanged.

Eliminates the dataclasses.replace post-injection block from _compute_symbol_tf.
The factory now owns complete FeatureVector construction.
```

---

### Task 9: Fix cross-asset one-shot seeding bug

**Goal:** Fix vix_z, flight_quality, yield_slope_z returning constant values.

**Changes:**
- In `_compute_symbol_tf`, replace one-shot `cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, config)` call
- Build date-indexed lookup maps for SPY/TLT/SHY
- For each bar at timestamp T, advance cross-asset position to most recent daily bar ≤ T
- Call `update_cross_asset()` incrementally

**Invariant:** Cross-asset value at bar T uses only bars with `timestamp.date() <= T.date()`.

**Commit message:**
```
fix(batch): incremental cross-asset alignment eliminates look-ahead bias

Cross-asset features (vix_z, flight_quality, yield_slope_z) were constant because
update_cross_asset() was called once with full bar history. Each deque had exactly
1 entry → z-score of 1 value = 0.000 for every bar. Also introduced look-ahead:
today's realized vol stamped on all bars back to 2016.

Now builds date→bar_index maps and advances incremental position per bar. No
look-ahead, correct temporal evolution, non-constant feature values.
```

---

### Task 10: Add CTF batch updater

**Goal:** Fix ctf_momentum, ctf_vwap_align, ctf_regime_align constant zeros.

**Changes:**
- Add `update_ctf_from_bars()` method to `FeatureCache`
- Computes CTF features from most recent HTF bar
- In `_compute_symbol_tf`: load HTF bars, build timestamp list, call `update_ctf_from_bars()` on boundary crossings

**Commit message:**
```
fix(batch): add update_ctf_from_bars() to FeatureCache; fix CTF constant zeros

Live pipeline receives HTF bars via Kafka and updates ctf_* fields on arrival.
Batch path had no equivalent — fields stayed at default 0.000.

Now loads HTF bars from DB and calls update_ctf_from_bars() incrementally. CTF
features now have correct values in historical backfill.
```

---

### Task 11: Fix HMM regime window

**Goal:** Fix hmm_regime_prob, hmm_entropy returning constant zeros/ones.

**Changes:**
In `compute_batch()`, replace:
```python
window_start = max(0, i - MIN_WINDOW)
cache.refresh_regime(bars[window_start : i + 1], config)
```
with:
```python
regime_window = min(i + 1, config.hurst_window)  # APR-backed, default 500
cache.refresh_regime(bars[max(0, i - regime_window) : i + 1], config)
```

`MIN_WINDOW` remains for bounded per-bar features. Regime refresh gets its own window from `feature.hurst.window` APR key.

**Commit message:**
```
fix(batch): pass full available history to refresh_regime instead of 50-bar window

HMM prob/entropy features were constant because refresh_regime() received only
50 bars. With 50 bars, GaussianHMM either fails min_bars_warmup check (returns
0.000) or fits degenerate single-state solution (returns 1.000/0.000).

Now passes regime_window from feature.hurst.window APR key (default 500 bars).
HMM fits proper 5-state regime; features have meaningful variance.
```

---

### Task 12: NULL VP/SR features in batch

**Goal:** Correctly represent session VP and SR levels as not computable from batch data.

**Changes:**
- Migration: make `poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist` nullable in `feature_vectors`
- In `_compute_symbol_tf`: emit `None` for these 4 fields when in batch mode
- Live path unchanged

**Commit message:**
```
fix(batch): NULL VP/SR features in batch; add migration for nullable columns

Session VP and SR levels require intraday data (1m bars per session, swing
high/low detection). Loading these inside batch would be order-of-magnitude
increase in data reads and complexity.

Correct answer is NULL. Batch path now emits None for poc_dist_atr,
va_position, sr_support_dist, sr_resist_dist. IC engine skips features with
insufficient non-null observations.
```

---

## Migration Plan

1. Apply migration (nullable VP/SR columns)
2. Mark 16 complete `(symbol, tf)` pairs as `status='pending'` in `backfill_status`
3. Run `backfill_feature_factory --compute-only` (all 58 symbols × 4 TFs)
4. Validate: query `feature_vectors` for `std(vix_z) > 0`, `std(ctf_momentum) > 0`, `std(hmm_regime_prob) > 0`
5. Re-run IC pipeline: `regime_writer → forward_return_writer → ic_engine`

---

## Success Criteria

- `std(vix_z) > 0` across all symbols and TFs
- `std(ctf_momentum) > 0` across all symbols and TFs
- `std(hmm_regime_prob) > 0` across all symbols and TFs
- `poc_dist_atr IS NULL` for all rows (correct, not fake 0.0)
- No feature with `std = 0` except cross-sectional rank features (nullable by design)
- IC engine completes full 58-symbol run without NaN explosions
- All parity tests pass
- No `dataclasses.replace` on fv in backfill service
- Only one RSI implementation (`_wilder_rsi_series`)
- MIN_WINDOW derived from config
- Cross-asset O(D) incremental, no parallel lists

---

## Dead Code Deleted

After completion, delete these 4 documents:
- `docs/plans/2026-06-23-feature-factory-single-path-refactor.md`
- `docs/plans/2026-06-24-feature-cache-batch-fix-design.md`
- `docs/plans/2026-06-24-feature-factory-batch-integrity.md`
- `docs/plans/2026-06-27-feature-factory-unification.md`

Archive them to `docs/plans/archive/` with a single commit:
```bash
git commit -m "docs(plans): archive 4 consolidated feature-factory batch path docs

Replaced by 2026-06-28-feature-factory-batch-path-fixes.md — unified plan
following Renaissance principle: one source of truth eliminates confusion."
```

---

## What This Is NOT

- Not a live pipeline change — `feature_vector_pipeline.py` untouched
- Not a new feature — fixes existing broken computation
- Not a schema redesign — minimal DDL (4 columns to nullable)
- Not a performance optimization — correctness first, O(D) cross-asset is side effect
