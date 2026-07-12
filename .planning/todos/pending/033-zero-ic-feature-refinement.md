# 033 — Refine 7 Zero-IC Features

**Status:** pending  
**Gate:** Complete Phase B corpus re-run first — some zero-IC readings on the remaining 4 features may be measurement artifacts from the pre-fix ic_engine. Re-evaluate after corrected corpus. **Note (2026-07-01):** also gated on todo 034/026's regime-label validation for any of the 4 that are regime-stratified — don't conclude a feature is dead until re-measured post-034/026.

## Features

**Correction (2026-07-01):** `momentum_rank_z`, `volume_rank_z`, `volatility_rank_z` are NOT zero-IC — verified live in the DB, they are `NULL` for every row. They have never been computed. **Cross-reference updated 2026-07-12:** the todo that implements them was originally 013, deleted 2026-07-09 when merged into `.planning/todos/deferred/073-cross-sectional-relative-value-feature-family.md` (now batched into the v3.15/Phase 150 corpus-rerun window, not standalone). These 3 should be removed from this todo's scope entirely until 073 ships and produces actual values to measure. Re-add them here only if IC comes back at/near zero on real (non-null) data.

**Remaining 4 features actually measured as zero-IC:** poc_dist_atr, va_position, sr_support_dist, sr_resist_dist

## Proposed Improvements

### Cross-sectional ranks (momentum_rank_z, volume_rank_z, volatility_rank_z) — DEFERRED, not in this todo's scope

These 2 ideas are kept here as forward-looking notes for whoever picks up todo 073 (see the
2026-07-12 cross-reference update above), since they're improvements to the same feature family
— but they are NOT part of *this* todo (033), which only covers features with real, measured IC.
Do not act on these until 073 ships and produces a baseline measurement.

1. **Peer-group ranking** — current rank is across all 58 ETFs (heterogeneous: equity sectors, fixed income, commodities). Rank within asset-class peer groups instead. Highest-confidence improvement.
2. **Rolling percentile** — replace point-in-time rank with rolling N-bar percentile rank. Smoother, more predictive.

### VP/SMC structural (poc_dist_atr, va_position, sr_support_dist, sr_resist_dist)

1. **Session-phase normalization** — proximity to POC has different predictive value at open vs. close. Normalize or condition on session time bucket.
2. **sr_strength multiplier** — weight S/R distance by number of prior tests at that level. A level tested 5x is qualitatively different from one tested once.
3. **Interaction terms** — poc_dist_atr × hmm_regime_prob may capture regime-conditional mean-reversion better than raw distance.

## Implementation order

1. Phase B corpus re-run (see B1) — determine which features are genuinely low-IC vs. measurement artifact
2. Peer-group ranking for cross-sectional ranks (clearest architectural fix)
3. sr_strength multiplier (adds a new computed field)
4. Session-phase normalization for VP features
5. Interaction terms last (most speculative)
