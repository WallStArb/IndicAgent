---
status: pending
priority: P2
filed: 2026-07-31
source: reviewing in-flight ic_engine recompute output while it runs (parallel-track review, not the recompute's own scope)
---

# `BIL` shows implausibly high per-symbol IC on ordinary/calendar features across many
# regime cells -- small-N/low-variance instability signature, isolated to this one symbol

## Problem

Spot-checking the in-flight `ic_engine` recompute's live output (`feature_ic_scores`,
`training_window_end = 2025-12-24 05:15:00+00`), `BIL` (a near-zero-volatility short-duration
Treasury-bill ETF, barely moves day to day) shows `ic_value` in the 0.5-0.73 range on plain
features -- `range_pct_slow`, `sr_resist_dist`, `dist_from_high_fast/slow`, and even a pure
calendar feature (`week_of_month_sin`) -- across multiple `1h`/`1d` regime cells
(`flat_wide`, `steep_wide`, `inverted_tight`, etc.), all `passes_ci_gate=true`.

A calendar feature showing IC=0.56 for a cash-like instrument with no real seasonal return
structure is not plausible as genuine signal. Checked `n_independent` behind these values:
116-160 -- thin per-symbol-regime cells. This is the classic small-N/low-variance
instability signature (a large point estimate that still manages to clear a CI on a thin
cell), not a real measured effect.

**Confirmed isolated to BIL.** Swept all symbol/tf combinations for `ic_value > 0.3 AND
n_independent < 200` (non-canary, non-pooled features only): only `BIL` at `1d` (157/1464
cells) and `BIL` at `1h` (119/3904 cells) cross that bar. No other symbol in the corpus shows
this pattern at any meaningful rate.

## Why this matters

- `BIL` is presumably eligible for the same per-symbol IC-based feature scoring / ensemble
  eligibility path as every other symbol (`ic_engine.py`) -- if these cells pass gates on
  spurious grounds, anything downstream that reads per-symbol (non-pooled) IC for `BIL`
  specifically inherits noise dressed as signal.
- Consistent with this project's near-zero-volatility-instrument failure mode: thin effective
  N combined with tiny raw variance can produce unstable rank-IC point estimates that
  nonetheless clear a bootstrap/Fisher-z CI by chance, especially compounded across many
  regime x lookahead cells (multiple-comparisons exposure even before BH-FDR is applied
  per-cell).

## Hypotheses (none yet confirmed)

1. **Low raw-variance instrument + thin regime cell**: BIL's genuinely tiny price variance
   inflates rank-IC's sensitivity to a handful of extreme observations, and regime
   stratification further thins an already-small effective N. Testable by comparing BIL's
   forward-return variance / effective N against other low-vol symbols (`SHY`, `IEF`) that do
   NOT show this pattern.
2. **Regime mis-assignment specific to BIL**: if BIL's HMM/regime labels are noisy or
   near-degenerate (few genuine regime transitions for a near-flat instrument), cells could be
   thinner and less representative than the `n_independent` count alone suggests.
3. **Instrument-specific data quality issue** (stale/flat-carry-forward bars,
   `market_data_ohlcv_tradeable` volume filter interacting oddly with BIL's low turnover) --
   check whether BIL's tradeable-bar count/composition looks normal relative to peers.

## Fix

Not diagnosed. Next step once the in-flight `ic_engine` pass completes: check whether BH-FDR
(`passes_fdr`) filters these BIL cells out even though `passes_ci_gate` doesn't -- if FDR
already catches it, this may just be a "the raw CI gate alone is too permissive for thin
cells" observation rather than a live-path bug. If FDR doesn't catch it either, trace
Hypothesis 1 first (cheapest, read-only) before assuming a regime-assignment or data-quality
bug.

## References

- `feature_ic_scores` -- read-only query, see this todo's filing session for the exact SQL
- `services/ic_engine.py` -- per-symbol IC computation path
- CLAUDE.md's performance-investigation-SOP -- prior precedent for symbol-specific
  low-volatility-instrument measurement artifacts (different bug shape, same root category:
  don't trust an extreme per-symbol point estimate without checking N/variance first)
