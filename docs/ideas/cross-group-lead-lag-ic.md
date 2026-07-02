# Cross-Group Lead-Lag IC

**Status:** Idea. Gated on `regime_group` (Phase 151) shipping.
**Last Updated:** 2026-07-01

## The question

Not "what regime is this group in" (already exists) and not "what regime is this bar in
within one symbol" (HMM/percentile-rank stratification). This is: does **group A's**
regime/state at time T predict **group B's** forward returns at T+N? A cross-asset
lead-lag question, distinct from everything else in the regime-stratification backlog.

## Why it's a different mechanism, not a new stratification dimension

Everything else discussed (P1-P8 percentile-rank, multi-engine HMM, within-group
cross-sectional IC) answers "what state is X in." This answers "does A's state forecast
B's returns" — closer to a cross-asset Granger-causality test than a stratification axis.
Mechanically: reuse the existing IC engine, but the regime/feature source (group A) and
the return target (group B) belong to different `regime_group`s instead of the same one.

## Candidate pairs (economically motivated, not exhaustive)

| Leading | Lagging | Rationale |
|---|---|---|
| Consumer staples / defensive_yield strength | Risk-on assets | Classic risk-off rotation signal |
| Industrial metals strength | Bonds / rates | Growth-expectations channel |
| Rates / bonds | Precious metals | Real-yield channel — theoretically cleanest of this list |
| Rates / bonds | Energy | Rate expectations feed cost-of-carry and demand |
| Energy | Equities | Input-cost / inflation-pressure channel |
| Volatility | Equities | **Caveat:** equity's own regime label is already partly VIX-derived (breadth×vol composite) — the new question is whether *cross-group* volatility state adds predictive power beyond what equity's self-label already captures, not whether volatility matters to equities at all (already known) |

## Dependencies

- Requires `regime_group` (Phase 151) shipped — need labeled peer groups before testing
  group-to-group lead-lag.
- Rates/commodity/fx groups specifically need the ETF universe expansion (Phase 152) and
  the `rates_regime`/commodity groups enabled (already staged in the cross-sectional
  regime model plan, currently disabled by default).

## Open questions (not yet resolved)

- Lag structure: single best lag, or a lag-scan (test N=1..K bars, report best)?
- Multiple-comparisons risk: testing 6+ pairs × multiple lags × multiple TFs is the same
  false-discovery risk already flagged elsewhere in this backlog (BH-FDR correction, same
  as used for cross-sectional IC) — needs the same discipline, not ad hoc pair-by-pair
  testing.
- Whether to use the discrete regime label or a continuous score (e.g. distance from
  regime centroid) as the leading feature — continuous likely has more IC signal but
  loses interpretability.
