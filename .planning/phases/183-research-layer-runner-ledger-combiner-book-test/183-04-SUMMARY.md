---
phase: 183
plan: 04
status: complete
requirements: [D-10, D-12, D-17, D-18, D-22, D-23]
---

# 183-04 summary: S7 ridge combiner and exact power primitives

The wave-1 executor wrote the combiner tests and most of `combiner.py` before stopping on an
API limit; the orchestrator finished, timed and committed it, and wrote `power.py`.

## What was built

- `combiner.py`: `RidgeSpec`, `refit_positions`, `walk_forward_ridge`. One pooled coefficient
  vector per refit, trained on complete (row, name) cases of rows before `p - embargo + 1`,
  standardized on training moments only, from float64 prefix sums differenced per fold.
  Predictions are NaN where any member is NaN (no fill), and only rows with data are
  predicted.
- `power.py`: `b_max` (exact, via Fraction; 6 at K = 4461, -1 below 600 shifts),
  `replicate_passes` (seeded permutation of the full shift set, stops at the deciding
  exceedance, optional abort), `curtail` (fixed-R decision, stops once determined, ignores
  aborted replicates).

## Verification

- `test_combiner.py` (19) and `test_power.py` (8) pass: slow lstsq reference, causality,
  fold-only standardization, complete cases, planted recovery, min_obs, zero sd; b_max against
  brute force for K up to 6000, early stop against the full count on 500 random cases,
  curtailment against fixed R on 300 sequences.
- Full-size ridge pass, 127,400 x 233 x 4 float32 with half the rows empty: 1.56 s at load
  average 29 on 24 cores (phase 182 and other runs sharing the box); the 1.5 s target is for an
  idle machine and was not re-measured idle.

## Deviations

- `replicate_passes` returns a failed outcome without visiting any shift when `bmax < 0`
  (no count can pass), rather than visiting one shift first.
