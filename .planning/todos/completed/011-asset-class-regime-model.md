# 011 — Asset-Class Regime Model for IC Stratification

**Numbering note (2026-07-12):** this file's heading previously read "# 006" from before a
renumbering pass that never updated the inline copy — normalized to 011 (the filename /
completed-folder key). Unrelated to `pending/011-alpha-events-is-shadow-column.md`, which
happens to share the same number.

**Priority: PROMOTED — now Phase 140.5 P4. Elevated from "medium/future" to pre-Phase 141 prerequisite after Jim Simons lens review: per-symbol HMM labels are incomparable across symbols; IC stratification cannot pool observations without cross-sectional regime labels. See ROADMAP.md Phase 140.5 P4 for full design.**

## Problem

`feature_vectors.regime` is populated by per-symbol HMM fitted on each symbol's own
log-return + realized vol. This means:

- "trending_up" on SPY and "trending_up" on TLT are independent, incomparable labels
- IC stratification cannot pool observations across symbols within a regime
- The HMM inputs (5D) are symbol-idiosyncratic — they do not capture what a regime
  means for a given asset class

## What Renaissance Would Do

Regimes are a property of the market (or market segment), not of individual instruments.
A single regime label per (asset_class, timestamp) enables cross-sectional IC pooling —
the statistical engine that makes large-universe IC scoring meaningful.

## Proposed Architecture

One regime model per asset class, fitted on asset-class-level signals:

| Asset class | Regime inputs |
|---|---|
| equity | Breadth (% names above 200MA), factor returns (growth/value/momentum), VIX term structure |
| futures | Commodity factor returns, DXY, roll yield |
| fx | Carry factor, relative monetary policy proxy, DXY |

Output: `market_regimes` table — `(asset_class, tf, ts, regime_label, regime_prob_vector)`

IC engine joins on `(asset_class, tf, bar_ts)` instead of reading `feature_vectors.regime`.
Per-symbol HMM features (`hmm_regime`, `hmm_regime_prob`, etc.) remain in `feature_vectors`
as predictive features — they capture idiosyncratic momentum — but are no longer the
IC stratification key.

## Gate

Current corpus is 58 equity ETFs only — the benefit is real but marginal at this scale.
Trigger: expanding beyond equities, or v3.0 ensemble shows regime instability (IC scores
that don't hold out-of-sample across regimes).
