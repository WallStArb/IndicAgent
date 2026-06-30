# 033 — Refine 7 Zero-IC Features

**Status:** pending  
**Gate:** Complete Phase B corpus re-run first — some zero-IC readings may be measurement artifacts from the pre-fix ic_engine. Re-evaluate after corrected corpus.

## Features

momentum_rank_z, volume_rank_z, volatility_rank_z, poc_dist_atr, va_position, sr_support_dist, sr_resist_dist

## Proposed Improvements

### Cross-sectional ranks (momentum_rank_z, volume_rank_z, volatility_rank_z)

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
