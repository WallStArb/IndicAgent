# Asset-Class Regime Model for IC Stratification

## Problem

`feature_vectors.regime` is populated by per-symbol HMM fitted on each symbol's own
log-return + realized vol. This means:

- "trending_up" on SPY and "trending_up" on TLT are independent, incomparable labels
- IC stratification cannot pool observations across symbols within a regime
- The HMM inputs (2 signals) are too sparse to capture what a regime actually means
  for a given asset class

## What Renaissance Would Do

Regimes are a property of the market (or market segment), not of individual instruments.
A single regime label per (asset_class, timestamp) enables cross-sectional IC pooling —
the statistical engine that makes large-universe IC scoring meaningful.

Markets are fundamentally segmented: equities, rates, and commodities have different
drivers and regime definitions should reflect that.

## Proposed Architecture

One regime model per asset class, fitted on asset-class-level signals:

| Asset class | Regime inputs |
|---|---|
| equity | Breadth (% names above 200MA), factor returns (growth/value/momentum), VIX term structure |
| futures | Commodity factor returns, DXY, roll yield |
| fx | Carry factor, relative monetary policy proxy, DXY |

Output: a `market_regimes` table — `(asset_class, tf, ts, regime_label, regime_prob_vector)`

IC engine joins on `(asset_class, tf, bar_ts)` instead of reading `feature_vectors.regime`.

Per-symbol HMM features (`hmm_regime`, `hmm_regime_prob`, etc.) remain in `feature_vectors`
as predictive features — they capture idiosyncratic momentum — but are no longer the
IC stratification key.

## Why Not Now

Current corpus is 58 equity ETFs only. The benefit is real but marginal at this scale.
The payoff grows with universe size — especially when futures and FX are added, where
mixing per-symbol regimes across asset classes would actively mislead IC scoring.

## Trigger

Revisit when expanding beyond equities, or when the v3.0 ensemble shows regime
instability (IC scores that don't hold out-of-sample across regimes).
