---
**Created:** 2026-06-28
**Area:** intelligence
**Type:** new_feature
**Priority:** P2
**Effort:** 1-2 days
**Benefit:** Adds cross-sectional rank features (momentum/volume/volatility) for ensemble input
**Risk:** low (new columns only)
**Gate:** Phase 141 complete + feature_vectors stable (OPEN) — do after Phase B corpus re-run confirms cross-sectional columns are useful
---

# 013 — Cross-Sectional Rank Features (momentum_rank_z, volume_rank_z, volatility_rank_z)

**Priority: Medium — free alpha, schema already exists, columns are NULL**
**Gate: Phase 141 complete + feature_vectors stable (OPEN) — do after Phase B corpus re-run confirms cross-sectional columns are useful**
**Source:** `docs/plans/2026-06-26-renaissance-optimization-roadmap.md` (ALPHA-003)

---

## Problem

`FeatureVector` has three cross-sectional rank fields (`momentum_rank_z`, `volume_rank_z`,
`volatility_rank_z`) that are always `None` in both `compute()` and `compute_batch()`.
The schema columns exist in `feature_vectors` but are never populated. Cross-sectional
momentum (top-decile relative momentum continuing) has documented IC ~0.03-0.05 in
liquid ETF universes — free alpha on an unused column.

---

## Fix

Cross-sectional ranks require all 58 symbols' values for a given bar_ts to be available
simultaneously. Two viable approaches:

**Option A — Batch post-processing (recommended):**
After `backfill_feature_factory` completes a symbol pass, run a second pass that:
1. For each `bar_ts`, loads `momentum_z_fast`, `vol_ratio`, `volatility_z` for all
   58 symbols from `feature_vectors`.
2. Computes percentile z-scores: `(rank - mean_rank) / std_rank` where
   `std_rank = N / sqrt(12)` (uniform distribution).
3. UPSERTs `momentum_rank_z`, `volume_rank_z`, `volatility_rank_z` back into
   `feature_vectors`.

Can run as a standalone script: `production/scripts/compute_cross_sectional_ranks.py`.
No streaming dependency — pure batch join across symbols at each bar_ts.

**Option B — IntelligencePipeline aggregation (future):**
Wire into the live streaming path after FeatureVectorWriter publishes — collect all
symbol feature_vectors for the same bar_ts, compute ranks, re-publish. Deferred until
streaming is re-enabled.

---

## Scope

- `production/scripts/compute_cross_sectional_ranks.py` — new oneshot batch script
- Step 7 in `corpus_pipeline_run.sh` (add after step 6 alpha_publisher)
- No schema migration needed — columns already exist as nullable float

Apply Option A first; revisit Option B when streaming path re-enables.
