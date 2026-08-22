---
status: pending
priority: P3
filed: 2026-08-22
source: /simplify's efficiency-angle review of the autocorr vectorization fix in
  scripts/analysis/per_symbol_regime_candidates_stage2_orthogonality.py, cross-referencing
  its sibling script per_symbol_regime_candidates_stage3_falsification.py
---

# Stage 3's `_build_panel` recomputes all 5 Stage 2 candidates, uses only 1

## What

`per_symbol_regime_candidates_stage3_falsification.py`'s `_build_panel()` calls
`_compute_candidates(df)` (Stage 2's function, returns all 5 candidate series: hurst_rank,
autocorr_rank, volatility_pct, skew_tail, volume_pct) once per symbol, but only ever reads
`candidates[candidate_name]` -- the caller already knows which single candidate it wants
before calling. The other 4 of 5 computed series are discarded every call.

This happens inside `main()`'s `for candidate_name in _CANDIDATE_NAMES` loop (once per
candidate, 5x total) AND inside the 200-iteration null-arm Monte Carlo loop for any
candidate that clears its uplift threshold (`_N_NULL_REPLICATES = 200`). Worst case: up
to 200 x 5 x (4/5 wasted) = up to 800 wasted full-candidate computations per symbol.

## Why this wasn't fixed alongside the autocorr vectorization

Different problem, different fix shape. The autocorr fix (this session) sped up ONE
candidate's own algorithm. This is redundant work at the call-site level -- computing 5
candidates to use 1, repeated across a 200x loop -- orthogonal to how fast any individual
candidate's computation is. Today the autocorr fix's own ~1,170x speedup happens to mask
most of this waste for autocorr specifically, but Hurst (still O(window) per-Python-call,
see todo 349) and the other 3 candidates still pay this 5x tax on every wasted call.

## Fix (if picked up)

Restructure `_build_panel()` (or its caller) to compute `_compute_candidates(df)` once
per symbol per panel-build (real or null-arm-permuted), cache the dict, and index into it
for whichever `candidate_name` the current loop iteration needs -- rather than
recomputing all 5 to extract 1. Since `_build_panel` is called once per (candidate_name,
permutation) combination and the OHLCV input `df` is per-symbol (not per-candidate), the
natural fix point is restructuring the loop nesting in `main()` so `_compute_candidates`
runs on the outside (once per symbol per permutation) and `candidate_name` selection moves
to the inside, not recomputing the whole dict per candidate_name iteration.

Needs care around the permutation case: `_build_panel`'s `permute_rng` argument
IID-permutes the OHLCV series differently per call (each call draws its own permutation),
so a naive shared-cache-across-candidate_names would need the SAME permutation reused for
all 5 candidates within one null-arm replicate, not a fresh permutation per candidate --
that's a real Design decision (does the null arm want one shared permutation per replicate
across all candidates, or an independent one per candidate?), not a mechanical
optimization. Read `_build_panel`'s docstring and `_null_arm_seed`'s per-
`(candidate_name, xbar_col, tf)` seeding scheme carefully before changing this -- changing
the permutation-sharing semantics would change the null arm's actual statistical meaning,
not just its speed.

## Not urgent

Stage 3 is a bounded, one-off research script (todos 303/304), not a recurring production
job -- this is real wasted compute but doesn't block any measurement from completing, just
makes it slower than necessary. Todo 349 (Hurst vectorization) is the higher-value fix if
only one gets picked up, since it reduces the wasted-work-per-call cost directly rather
than just the call count.
