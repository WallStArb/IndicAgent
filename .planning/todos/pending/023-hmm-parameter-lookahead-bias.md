# 023 — HMM Parameter Look-Ahead Bias

**Priority: P2 — Future milestone. Expensive architectural change; run AFTER rolling corpus is stable.**

## Context

`regime_writer` fits GaussianHMM on the full available history, then applies causal
forward-filter for label assignment. The forward-filter is correct, but emission
parameters and transition matrix were estimated using future data relative to any
training bar. This is parameter look-ahead bias — the model "knows" future regimes
when fitting its own parameters.

Excluded from Phase 140 (IC Engine Correctness) due to cost. Phase 140 handles all
other P0/P1/P2 correctness issues.

## Fix

Rolling HMM fit on a growing window. Two options:

**Option A — Growing window refit:** Fit on all data up to bar T, decode only bar T.
True walk-forward with no look-ahead. ~N separate HMM fits per (symbol, tf).

**Option B — Fixed 3-year rolling window:** Fit on trailing 3 years, step forward
by 1 year. Cheaper: ~10-17 refits per (symbol, tf) for 20 years of daily data.

**Recommended:** Option B (3-year rolling window, annual step). Balances correctness
against runtime.

## Cost Estimate

Current regime_writer: 232 fits (58 symbols × 4 TFs), ~10-20 min with 12 workers.

With rolling refit at ~15 fits per cell: ~3,480 fits — roughly 15-20× slower.
Estimated runtime: 3-6 hours. Requires careful parallelism tuning.

## Implementation Notes

- Refactor `label_symbol_tf` to loop over rolling windows
- Emit regime labels only for the out-of-window segment of each fit
- Stitch segments together before writing to `feature_vectors`
- Refit step size and window length → APR: `alpha.hmm.rolling_window_bars`,
  `alpha.hmm.rolling_step_bars`
- All existing `feature_vectors` regime labels must be recomputed — triggers full
  corpus pipeline re-run (all 6 steps)
- Run BIC K-selection (todo 002) before or alongside this — no point optimizing
  K on biased parameters

## Files

- `services/regime_writer.py` — `label_symbol_tf()`, main loop
- `src/core/agent/base_batch.py` — if pool lifecycle changes
