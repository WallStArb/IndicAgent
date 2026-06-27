# 030 — Ensemble Trainer: Redesign to Consume Cross-Sectional IC

**Priority: CRITICAL — current corpus pipeline blocker; steps 5-6 cannot run until fixed**
**Gate: None — must fix before ensemble_trainer can be run**
**Source:** Corpus pipeline state analysis 2026-06-27; see STATE.md ensemble trainer blocker

---

## Problem

`ensemble_trainer.py` strata query filters `is_pooled=false AND ic_sharpe_hac IS NOT NULL`
and returns 0 rows. Per-symbol per-regime IC data structurally cannot satisfy this gate:
`sharpe_min_windows=30 × window_size=2000 = 60,000 subsampled bars required per cell`, but
per-symbol per-regime at 5m has ~1,500. Structurally impossible regardless of corpus size.

The Phase 138 decision "pooled=diagnostic; Phase 139 reads WHERE is_pooled=false" predates
the cross-sectional equity model (added Phase 140.5-P4). That note referred to the
per-symbol `_pooled` sentinel rows, not true cross-sectional data. Needs revisiting.

Cross-sectional IC rows (symbol='POOLED', is_pooled=true, regime != '_pooled') ARE
the correct source — 58 symbols × regime gives ~126K subsampled bars at 5m → ~220 windows,
well above the 30-window gate. These are reliable, pooled across the universe.

---

## Fix

**Strata query** — change to read cross-sectional IC:

```sql
-- Before (returns 0 rows):
SELECT DISTINCT symbol, tf, regime
FROM feature_ic_scores
WHERE is_pooled = false AND passes_walkforward = true
  AND reliable = true AND ic_sharpe_hac IS NOT NULL AND regime IS NOT NULL

-- After (reads cross-sectional universe model):
SELECT DISTINCT tf, regime
FROM feature_ic_scores
WHERE symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'
  AND passes_walkforward = true AND reliable = true
  AND ic_sharpe_hac IS NOT NULL AND regime IS NOT NULL
```

**`_process_stratum()`** — change feature_vectors load from per-symbol to universe:

```python
# Before: loads one symbol's feature_vectors
rows = await conn.fetch(
    "SELECT ... FROM feature_vectors WHERE symbol = $1 AND tf = $2 AND regime = $3",
    symbol, tf, regime
)

# After: loads all 58 symbols' feature_vectors for (tf, regime)
rows = await conn.fetch(
    "SELECT ... FROM feature_vectors WHERE tf = $1 AND regime = $2",
    tf, regime
)
```

**Ensemble weights** — universe-level weights per (tf, regime) applied to all 58 ETFs
at scoring time. One rigorous cross-sectional model vs 58 noisy per-symbol models.

**alpha_ensemble schema** — `symbol` column should become nullable or use 'UNIVERSE'
sentinel (parallel to 'POOLED' in feature_ic_scores) since weights are no longer
per-symbol.

---

## Scope

- `services/ensemble_trainer.py` — strata query + `_process_stratum()` + `_meta_eligible()`
- Migration — update `alpha_ensemble` schema if needed (symbol nullable or UNIVERSE sentinel)
- After fix: run `ensemble_trainer` → `alpha_publisher` to complete corpus pipeline steps 5-6
