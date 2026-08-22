---
status: pending
priority: P3
filed: 2026-08-22
source: /simplify's altitude-angle review of the autocorr vectorization fix in
  scripts/analysis/per_symbol_regime_candidates_stage2_orthogonality.py
---

# Stage 2's `_single_window_hurst` is now the dominant remaining cost in `_compute_candidates`

## What

`_compute_candidates`'s `autocorr_raw` component was rewritten from a per-window Python
callback (`.rolling().apply(lambda w: pd.Series(w).autocorr(lag=L))`, 34.0s at n=392K)
to a vectorized `series.rolling(W-L).corr(series.shift(L))` (0.029s at the same N, exact
equivalence proven algebraically and verified via an independent oracle test).

`hurst_raw` still uses the identical anti-pattern shape: `log_ret.rolling(window=
_HURST_WINDOW, min_periods=_HURST_WINDOW).apply(_single_window_hurst, raw=True)`, where
`_single_window_hurst` computes a rescaled-range (R/S) statistic per window. This sits in
the exact same function, called inside the same 200x null-arm falsification loop
(`per_symbol_regime_candidates_stage3_falsification.py`'s `_N_NULL_REPLICATES = 200`)
that motivated the autocorr fix. It is now the largest remaining per-call cost in
`_compute_candidates`.

## Why not fixed in the same pass

Unlike autocorr (a Pearson-correlation identity with an exact closed-form pandas-native
equivalent), the R/S statistic has no direct vectorized pandas primitive -- `deviations
= cumsum(window - mean)`, `r = deviations.max() - deviations.min()` is a per-window
range-of-cumulative-sum computation. Vectorizing it needs custom sliding-window
engineering (e.g. `numpy.lib.stride_tricks.sliding_window_view` plus a vectorized
running max/min), a materially different and riskier change than autocorr's one-line
algebraic swap. Bundling it into the autocorr commit would have been scope creep on a
provably-exact single-call fix.

## Fix (if picked up)

1. Benchmark `_single_window_hurst`'s actual cost at production scale (392K rows) to
   confirm it's worth the engineering effort before starting -- measure, don't guess.
2. If confirmed material, vectorize via `sliding_window_view` (windows share overlapping
   data, so a stride-tricks view avoids materializing all subwindows) + vectorized
   `np.cumsum` along axis + vectorized max/min/std reductions per window.
3. Needs its own TDD pass with an independent-oracle equivalence test (same discipline
   as the autocorr fix) -- the R/S statistic's NaN/degenerate-window guard (`s < 1e-12
   or r < 1e-12`) must survive the vectorization exactly.

## Related, lower priority

`scripts/analysis/per_symbol_trend_candidates_stage1_pilot.py:85`'s `_rolling_autocorr`
still has the identical unvectorized per-window-callback shape this todo's sibling fix
(autocorr in Stage 2) just retired -- a different script (Stage 1 pilot, not Stage 2/3),
not touched by that fix. Only worth revisiting if Stage 1 is ever re-run at full-corpus
scale (it was a bounded pilot, not currently in any hot loop).
