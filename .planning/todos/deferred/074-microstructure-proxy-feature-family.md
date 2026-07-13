# 074 — OHLCV microstructure proxy family (liquidity/friction, dual-use with cost kernel)

**Status (moved to deferred/, 2026-07-10):** New FeatureFactory feature-family build meant for the v3.15 corpus-rerun batch / Phase 151's remit, not a standalone build. Revive alongside that batch or Phase 151 planning.


**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §3 (L1-2),
executive summary item 4.
**Priority:** high — genuinely orthogonal information family (none of the 152 live features
measure liquidity/friction; closest is `vol_range_ratio`), and dual-use: feeds the canonical
simulator's cost kernel, which today is externally-calibrated constants, not measured data.
**Gate:** none blocking — a `FeatureFactory` addition, batch into next corpus rerun (v3.15 window
per topdown D5 sequencing, alongside the other measurement-shaped items).

## Proposal

| Feature | Estimator | Notes |
|---|---|---|
| `cs_spread_z` | Corwin-Schultz (2012) high-low spread estimator over 2-bar pairs | z-scored per symbol |
| `roll_spread_z` | Roll (1984): `2*sqrt(-cov(Δp_t, Δp_{t-1}))` where cov is negative | rolling window, APR-backed |
| `amihud_z` | Amihud (2002): `mean(abs(ret) / dollar_volume)` | must respect the synthetic-bar session mask (volume=0 rows poison it — todo 035 owns the mask) |
| `spread_regime_pct` | expanding percentile of `cs_spread` | doubles as an L2 stratification candidate |

**Dual use is the point:** the canonical simulator's one build item is a cost kernel
(`platform-canonical-simulator.md`), currently fed by externally calibrated per-tf constants
(`alpha.quant.cost_hurdle.*`, todo 030). Corwin-Schultz gives a *measured, per-symbol,
per-regime* spread from data already owned — the cost kernel's inputs stop being guesses the
moment this family exists.

## Filter check

Falsifiable via standard IC screening; separately, CS spread estimates can be sanity-checked
against todo 030's external spread table (agreement is the estimator's own validation).
Overfitting: 4-6 columns, standard FDR pool. Weak-signal: adds an orthogonal information family;
even zero IC still pays off through the cost kernel. Cost: pure `FeatureFactory` additions except
`amihud_z`'s session-mask dependency (todo 035).
