# 001 — Feature Cache Batch Path Primitives Fix (Groups 2+3+4)

**Priority: High — corpus will need a re-run after this lands; do ASAP.**
**Plan doc:** `docs/plans/2026-06-24-feature-cache-batch-fix-design.md`
**Note:** Group 1 (cross-asset vix_z/flight_quality/yield_slope_z) was fixed in Phase 139.

---

## Problem

12 feature primitives in `feature_vectors` return constant placeholder values (0.000 or 1.000)
via the batch path. Three root-cause groups remain after todo 003 is addressed:

**Group 2 — CTF (ctf_momentum, ctf_vwap_align, ctf_regime_align)**
- `FeatureCache` has no `update_ctf_from_bars()` method; batch path never loads HTF bars.
- Fields stay at default 0.000 for every bar in the corpus.

**Group 3 — Volume Profile / SR (poc_dist_atr, va_position, sr_support_dist, sr_resist_dist)**
- Causal batch computation requires 1m intraday bars per session — architectural complexity
  not justified for batch. The honest answer is NULL.

**Group 4 — HMM prob/entropy (hmm_regime_prob, hmm_entropy)**
- `compute_batch()` passes a hard 50-bar window to `refresh_regime()`. GaussianHMM with 50
  bars either fails the `min_bars_warmup` check (returns 0.000) or fits degenerate single-state
  (returns 1.000/0.000). Fix: pass full available history.

Silent constant values produce misleading IC scores and contaminate training corpus.

---

## Implementation

### Fix 1: CTF — add `update_ctf_from_bars()` + HTF loading in batch

**New method on `FeatureCache`:**
```python
def update_ctf_from_bars(self, htf_bars: list[dict], config: FeatureFactoryConfig) -> None:
    # Computes ctf_momentum, ctf_vwap_align, ctf_regime_align from most recent HTF bar:
    # ctf_momentum: HTF RSI relative to 50 midpoint, normalized to [-1, +1]
    # ctf_vwap_align: sign of (HTF close - HTF session VWAP), approx from HTF OHLCV
    # ctf_regime_align: HTF HMM regime agreement (from cache.hmm_regime_prob threshold)
```

**In `_compute_symbol_tf`:** Load HTF bars from DB (5m/15m → 1h; 1h/1d → 1d). Build
sorted HTF timestamp list. For each bar T, if T crosses a new HTF bar boundary, call
`update_ctf_from_bars()` with HTF bars up to that boundary. Invariant: CTF at bar T uses
only HTF bars where `timestamp <= T`.

### Fix 2: VP/SR — NULL in batch path

Migration to make `poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist`
nullable in `feature_vectors` (remove NOT NULL + default 0.0 constraints).

In `compute_batch()`, set these four fields to `None` rather than reading from cache.
IC engine already handles NULL — features with insufficient non-null observations are skipped.

### Fix 3: HMM window — pass full available history

In `compute_batch()`, replace:
```python
regime_bars = bars[max(0, i - 50):i + 1]
```
with:
```python
regime_bars = bars[:i + 1]
```

---

## Files

| File | Change |
|------|--------|
| `src/intelligence/feature_cache.py` | Add `update_ctf_from_bars()` |
| `src/intelligence/feature_factory.py` | Fix HMM window in `compute_batch()` |
| `services/backfill_feature_factory.py` | HTF loading + CTF update loop, NULL VP/SR in batch |
| New migration | Make 4 VP/SR columns nullable in `feature_vectors` |

---

## Post-Fix Steps

1. Apply migration (nullable VP/SR columns)
2. Mark all computed `(symbol, tf)` pairs `status='pending'` in `backfill_status`
3. Re-run `backfill_feature_factory --compute-only` (all 58 symbols × 4 TFs)
4. Validate:
   - `std(ctf_momentum) > 0` across all symbols and TFs
   - `std(hmm_regime_prob) > 0` across all symbols and TFs
   - `poc_dist_atr IS NULL` for all rows
5. Re-run IC pipeline: `regime_writer → forward_return_writer → ic_engine`

---

## Success Criteria

- No feature with `std = 0` except cross-sectional rank features and the 4 VP/SR columns
- `std(ctf_momentum) > 0`, `std(hmm_regime_prob) > 0` across all symbols/TFs
- `poc_dist_atr IS NULL` everywhere (not 0.0)
- IC engine completes 58-symbol run without NaN explosions
