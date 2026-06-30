---
**Created:** 2026-06-29
**Area:** intelligence
**Type:** capability expansion
**Priority:** P1 near-term; P2-P3 medium; P4-P5 gated
**Effort:** P1 = 1 session; P2 = 1 session; P3 = 2 sessions; P4/P5 = gated
**Risk:** P1/P2 low (additive); P3 medium (new data pipeline); P4/P5 gated
**Gate:** Todo 026 P0 (Numba JIT) must ship first — multi-dimensional IC is too slow without it
---

# 030 — Regime Stratification Alternatives

**Plan:** `docs/plans/2026-06-29-regime-stratification-alternatives.md`

The HMM is a means to an end: conditioning IC measurement on regime. The regime
layer's job is stratification. Multiple orthogonal stratification dimensions can coexist,
each adding a conditioning axis that sharpens IC estimates in ways HMM alone cannot.

## Summary

| Priority | Dimension | What HMM Misses | Table | Effort |
|---|---|---|---|---|
| P1 | Realized vol percentile | Causal, directly tradeable state variable | `feature_vectors.volatility_regime` | 1 session |
| P2 | Cross-sectional dispersion | Macro vs stock-picker market | `market_regimes` | 1 session |
| P3 | Factor regime (momentum/value/quality) | Which factor is driving returns | `market_regimes` | 2 sessions |
| P4 | HMM variants (IOHMM, Hamilton, factor-augmented) | Better state transition modeling | replaces `regime_writer` | Gated on todo 026 P4 |
| P5 | Microstructure regime (OFI, spread) | Intraday liquidity state | `feature_vectors` | Gated on V2 |

## Architecture

Each stratification dimension produces independent labels per bar. IC engine runs
stratified by any combination:

```
IC(feature, symbol, tf, hmm_state, volatility_regime, dispersion_regime, lookahead)
```

The combination that minimizes CI width per feature is itself learned, not assumed.

## Naming gap (also captured here)

The glossary defines `regime` as HMM state only. As stratification dimensions multiply,
we need: `stratification dimension` (the concept), `Regime Stratification Layer` (the layer name).
These should be added to the glossary when P1 ships.

## Dependencies

- Todo 026 P0 (Numba JIT) — prerequisite for multi-dimensional IC compute to be feasible
- Todo 028 (IC engine improvements) — fix IC foundation before multiplying its dimensions
- Todo 029 (feature scoring beyond IC) — MI and R²_OOS are parallel extensions
- P5 gated on V2 Microstructure feature vector (order flow / bid-ask data)
