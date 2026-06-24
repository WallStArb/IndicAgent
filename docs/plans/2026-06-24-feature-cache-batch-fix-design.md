# Feature Cache Batch Path Fix — Design Spec

**Date:** 2026-06-24  
**Status:** Approved  
**Scope:** Fix 12 broken feature primitives in `backfill_feature_factory` batch path before full 58-symbol corpus run

---

## Problem Statement

12 feature primitives in `feature_vectors` return constant placeholder values when computed via the batch path. All 12 share the same root cause: `FeatureCache` fields that require external data (cross-asset bars, HTF bars, session VP, SR levels) are only populated in the live pipeline via real-time bar injection. The batch path never calls the corresponding updaters.

Silent constant values are worse than crashes — they produce misleading IC scores and contaminate the training corpus.

---

## Root Causes

### Group 1 — Cross-asset (vix_z, flight_quality, yield_slope_z): One-shot seeding bug

`update_cross_asset()` is designed for incremental per-bar calling, building internal deques. The batch path calls it **once** with the full bar history. Result: each deque has exactly 1 entry → z-score of 1 value = 0.000 for every historical bar. Also introduces look-ahead bias: today's realized vol is stamped on all bars back to 2016.

**Root cause:** `update_cross_asset()` call site in `_compute_symbol_tf` is one-shot, not incremental.

### Group 2 — CTF (ctf_momentum, ctf_vwap_align, ctf_regime_align): No batch updater

Live pipeline receives HTF bars via Kafka and updates `FeatureCache.ctf_*` fields on arrival. No equivalent exists in the batch path — no HTF bars are loaded, no updater is called. Fields stay at default 0.000.

**Root cause:** `FeatureCache` has no `update_ctf_from_bars()` method; batch path never loads HTF bars.

### Group 3 — Volume Profile / SR (poc_dist_atr, va_position, sr_support_dist, sr_resist_dist): Unbuildable in batch

Session VP requires intraday price distribution (1m bars within session). SR levels require swing-high/low detection across sessions. Loading 1m bars per session inside the batch would be an order-of-magnitude increase in data reads and architectural complexity. Live path populates these from I3 structure plugins injecting into FeatureCache.

**Root cause:** Correct causal batch computation is not feasible without redesigning the data access layer. The honest answer is NULL.

### Group 4 — HMM prob/entropy (hmm_regime_prob, hmm_entropy): Window too small

`compute_batch()` passes `bars[max(0, i-50):i+1]` (50-bar hard window) to `refresh_regime()`. With 50 bars, the GaussianHMM either fails the `min_bars_warmup` check and returns early (leaving fields at 0.000) or fits a degenerate single-state solution (returning 1.000/0.000).

**Root cause:** `MIN_WINDOW = 50` was set for bounded-window per-bar features, then incorrectly reused for the regime refresh call.

---

## Design: Two-Track Fix

### Track A — Fix causally (4 features in 3 groups)

All three groups have correct causal computation available from data already in `market_data_ohlcv`.

#### Fix 1: Cross-asset — incremental alignment

**Change:** In `_compute_symbol_tf`, replace the one-shot `cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, config)` call with a date-indexed lookup. Pre-build a `date → bar_index` map for each of SPY/TLT/SHY daily series. For each bar at timestamp T, advance the cross-asset position to the most recent daily bar ≤ T and call `update_cross_asset()` incrementally (with the slice up to that index). This builds the deque history correctly over time with zero look-ahead.

**Invariant:** Cross-asset value at bar T uses only SPY/TLT/SHY bars with `timestamp.date() <= T.date()`.

#### Fix 2: CTF — add `update_ctf_from_bars()` + batch HTF loading

**New method on FeatureCache:**
```python
def update_ctf_from_bars(self, htf_bars: list[dict], config: FeatureFactoryConfig) -> None
```
Computes `ctf_momentum`, `ctf_vwap_align`, `ctf_regime_align` from the most recent HTF bar:
- `ctf_momentum`: HTF RSI relative to 50 midpoint, normalized to [-1, +1]
- `ctf_vwap_align`: sign of (HTF close - HTF session VWAP), approximated from HTF OHLCV
- `ctf_regime_align`: HTF HMM regime agreement (from cache.hmm_regime_prob threshold)

**In `_compute_symbol_tf`:** Load HTF bars from DB (5m/15m → 1h, 1h/1d → 1d). Build a sorted list of HTF bar timestamps. For each bar at timestamp T, if T crosses a new HTF bar boundary, call `update_ctf_from_bars()` with the HTF bars up to that boundary.

**Invariant:** CTF value at bar T uses only HTF bars with `timestamp <= T`.

#### Fix 3: HMM window — pass full available history

**Change:** In `compute_batch()`, replace:
```python
window_start = max(0, i - MIN_WINDOW)
cache.refresh_regime(bars[window_start : i + 1], config)
```
with:
```python
regime_window = min(i + 1, config.hurst_window)  # APR-backed, default 500
cache.refresh_regime(bars[max(0, i - regime_window) : i + 1], config)
```

`MIN_WINDOW = 50` remains for the bounded per-bar feature window. The regime refresh gets its own window from the existing APR key `feature.hurst.window` (already seeded, default 500 bars).

### Track B — NULL (4 VP/SR features)

`poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist` are emitted as NULL from the batch path. NULL is the correct representation of "not computable from this data context." The IC engine already handles NULL — features with insufficient non-null observations are skipped.

**Schema change:** Migration to make these 4 columns nullable in `feature_vectors` (remove NOT NULL + default constraints).

**Batch path:** `_vector_to_params()` emits `None` for these 4 fields when in batch mode. Live path behavior unchanged — I3 session state continues to populate them.

**IC impact:** These features will have non-null IC scores only from live data going forward. Acceptable: session VP and SR are inherently intraday features, and the batch IC corpus (from OHLCV history) cannot measure them without look-ahead.

---

## Files Changed

| File | Change |
|------|--------|
| `src/intelligence/feature_cache.py` | Add `update_ctf_from_bars()` method |
| `src/intelligence/feature_factory.py` | Fix HMM window in `compute_batch()` |
| `services/backfill_feature_factory.py` | Incremental cross-asset alignment, HTF bar loading + CTF update loop, NULL VP/SR in batch |
| New migration (next available) | Make 4 VP/SR columns nullable in `feature_vectors` |

---

## Migration Plan

1. Apply migration (nullable VP/SR columns)
2. Mark 16 complete `(symbol, tf)` pairs as `status='pending'` in `backfill_status` (force recompute of already-computed pairs)
3. Run `backfill_feature_factory --compute-only` (all 58 symbols × 4 TFs; no IBKR fetch needed, all fetch_complete=true)
4. Validate: query `feature_vectors` for std(vix_z) > 0, std(ctf_momentum) > 0, std(hmm_regime_prob) > 0; poc_dist_atr IS NULL expected
5. Re-run IC pipeline: `regime_writer → forward_return_writer → ic_engine`

---

## Success Criteria

- `std(vix_z) > 0` across all symbols and TFs
- `std(ctf_momentum) > 0` across all symbols and TFs  
- `std(hmm_regime_prob) > 0` across all symbols and TFs
- `poc_dist_atr IS NULL` for all rows (correct — not fake 0.0)
- `va_position IS NULL` for all rows
- No feature with `std = 0` except cross-sectional rank features (nullable by design, populated in Phase 139)
- IC engine completes full 58-symbol run without NaN explosions

---

## What This Is NOT

- Not a live pipeline change — live path behavior is unchanged
- Not a new feature — fixes existing broken computation
- Not a schema redesign — minimal DDL (4 columns to nullable)
- Not a performance optimization — correctness only
