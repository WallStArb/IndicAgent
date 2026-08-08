---
status: pending
priority: P2
filed: 2026-08-08
source: Phase 171 candidate-regime-axes investigation
  (`171-CANDIDATE-REGIME-AXES-FINDINGS.md` §6.1, §6.4, R3) -- two of four tested
  candidate regime axes carry real persistent signal but are the wrong shape for an HMM
  regime; they belong in the feature vector instead.
---

# Add systematic-dominance and volume-price-confirmation statistics as continuous feature primitives, then measure IC separation across their own buckets

## What

The candidate-regime-axes sweep measured, per (symbol, tf), what fraction of each candidate
statistic's variation is real rather than estimation error (correlation of the statistic
across adjacent **disjoint** windows -- sampling noise cannot contribute). Two of the four
candidates carry substantial real signal:

| statistic | best window | signal fraction (1d / 1h) | cells positive |
|---|---|---|---|
| rolling R-squared + beta vs SPY | 60 (1d), 120 (1h) | 0.401 / 0.213 | 32/32 |
| rolling corr(abs(return), rel_volume) + corr(return, rel_volume) | 250 | 0.375 / 0.310 | 15/16, 16/17 |

Both were rejected **as HMM regime axes** -- an HMM on either is largely a threshold split,
and identifiability moves in the opposite direction from signal quality (volume_price:
signal fraction rises 0.06 -> 0.32 with window while HMM identifiability falls 32/34 ->
27/34). See the findings doc §5.3 for the mechanism.

They are still worth having as continuous columns.

## What to do

1. Add to `FeatureVector` / `feature_vectors` in the next Phase-151-style primitive
   expansion:
   - `market_r_squared_*` and `market_beta_*` versus a benchmark (SPY as the simple
     universal reference; a per-`regime_group` peer average is a separate refinement that
     was deliberately NOT built into the identifiability test, so it is untested).
   - `volume_confirmation_*` = rolling corr(|return|, rel_volume), and
     `volume_direction_*` = rolling corr(return, rel_volume), at a ~250-bar window.
     `rel_volume` should reuse `_build_obs_matrix`'s own definition (log volume minus its
     20-bar rolling mean) so this measures production's existing volume anomaly.
   - Use gradient scale qualifiers per the naming spec, with the window as an APR key --
     the windows above are probe-selected, not calibrated.
2. Then answer the question that has never been asked of ANY regime axis in this project
   (`171-REGIME-DECOMPOSITION-FINDINGS.md` §7.3 condition (iii)): **does IC actually
   differ across this statistic's own quantile buckets?** A Phase-144 D-05-shaped
   separation test.
3. Only if (2) passes does a discrete cut earn its place -- and then as **deterministic
   quantile tiering** via the `build_tiers()` mechanism `cross_sectional_regime_model`
   already uses (no EM, no seed, no local optima, no identifiability question by
   construction), never as an HMM `regime_*` column.

## Do not

Do not build `regime_systematic` or `regime_volume_price` as HMM columns. Do not build the
other two tested candidates (return-persistence / variance ratio, and skew / tail
asymmetry) in any form -- both measured a signal fraction indistinguishable from zero at
windows of 20, 60, 120 and 250 bars on 17 symbols and two timeframes.
