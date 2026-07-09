# 077 — Outcome-target refinements: vol-normalized, residual (beta-hedged), overnight/intraday decomposition

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §6 (L3-1, L3-2,
L3-4). All are measurement-time transforms — joins computed inside the measurement layer, never
new columns in the canonical `forward_returns` fact table, so Invariant 1 and the one-writer
contract stay intact.
**Priority:** high for L3-1/L3-2 (directly sharpens the POOLED-strata IC the whole ensemble keys
on); low-medium for L3-4 (diagnostic).
**Gate:** L3-2 needs Phase 145's measured betas. L3-1 and L3-4 are unblocked today.

## L3-1 — Vol-normalized return target

`return_x / trailing_sigma(symbol)` (sigma from the existing `atr_z` denominator or a trailing
realized vol). The real payoff is cross-sectional/POOLED measurement, where raw-return ranks are
dominated by whichever symbols run hot — and the ensemble trains exclusively on POOLED strata
(`ensemble_trainer.py:317,430,469,540`), so the pooled IC the whole system keys on is currently
vol-biased. Verdict: re-run POOLED strata with both targets; if qualifying-feature rankings are
materially identical, the transform is unnecessary and dies. Zero new parameters beyond an
existing feature's window; a join + divide inside `ic_engine`'s existing corpus load, no migration.

## L3-2 — Residual (beta-hedged) return target

`return_x(symbol) - beta * return_x(SPY)`, beta from Phase 145's Instrument Tag Calibrator
(`data-instrument-tag-calibrator.md`, already committed to producing measured, FDR-corrected
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
