# 077 — Outcome-target refinements: residual (beta-hedged), overnight/intraday decomposition

**Status (moved to deferred/, 2026-07-10):** Measurement-time transforms meant for the v3.15 corpus-rerun batch window, not standalone. Revive alongside that batch.

**L3-1 split out 2026-07-11:** vol-normalized return target moved to standalone todo
`097-vol-normalized-return-target-pooled-ic.md`, folded into Phase 143.1 as Component F — it's
unblocked today (unlike L3-2's Phase 145 gate) and rides the same corpus re-run 143.1 is already
doing for its Fisher-z CI and sign-symmetric eligibility fixes. L3-2 and L3-4 below remain
deferred to the v3.15/Phase 150 batch as originally scoped.

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §6 (L3-2, L3-4).
All are measurement-time transforms — joins computed inside the measurement layer, never
new columns in the canonical `forward_returns` fact table, so Invariant 1 and the one-writer
contract stay intact.
**Priority:** high for L3-2 (directly sharpens the POOLED-strata IC the whole ensemble keys
on); low-medium for L3-4 (diagnostic).
**Gate:** L3-2 needs Phase 145's measured betas. L3-4 is unblocked today but diagnostic-only.

## L3-2 — Residual (beta-hedged) return target

`return_x(symbol) - beta * return_x(SPY)`, beta from Phase 145's Instrument Tag Calibrator
(`stratification-instrument-tag-calibrator.md`, already committed to producing measured, FDR-corrected
factor betas). This is the outcome definition T3 actually requires: a cross-sectional edge is a
claim about *idiosyncratic* mispricing, and measuring candidate features (todo 073) against raw
returns lets market-timing leak into what looks like relative-value IC. Verdict: features whose
IC survives against raw returns but dies against residual returns are market-timing features
wearing relative-value costume. Sequence into the same v3.15 batched rerun as Phase 145 lands.

## L3-4 — Overnight/intraday decomposition of the forward horizon

142.5 decomposed backward-looking returns (`open_ret`, `intraday_ret`). The same split on the
*forward* horizon (how much of `return_fast` accrues overnight vs in-session) shows where alpha
lives and whether it's capturable under different execution styles — overnight and intraday alpha
have different cost/risk profiles. Measurement-time computation from `market_data_ohlcv`
opens/closes; report as an IC-diagnostics decomposition column, not a gate.
