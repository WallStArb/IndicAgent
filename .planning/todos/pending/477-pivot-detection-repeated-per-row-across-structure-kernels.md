---
status: pending
priority: P3
filed: 2026-09-30
source: plan 186-15 review (efficiency)
---

# Pivot detection runs about five times per row across the structure kernels

## What

The swing, sweep, pool and BOS/CHoCH kernels each call `find_peaks` and `find_troughs` on the same
window for every row: about five pivot passes per row, roughly 10 percent of `compute_batch` time
(measured in the 186-15 review).

## Options

1. Leave it: 10 percent, and the kernels stay independent.
2. A shared derived input in the registry (`contract/derived_inputs.py`): one kernel-like
   producer of the per-row pivot sets, declared as an input by the four consumers, so the registry
   computes it once and the memory check covers it.

## Recommendation

Option 2, optional and low priority: only worth doing with the 186-25 rebuild if the rebuild time
matters. It must be bit-identical (the same `find_peaks` call on the same window), proven by the
golden fixtures and an equality test on random series.

## Steps

1. Measure the pivot share on the parity sample first.
2. Add `derived_inputs.py` to the contract and declare the producer.
3. Switch the four kernels and compare exactly.
