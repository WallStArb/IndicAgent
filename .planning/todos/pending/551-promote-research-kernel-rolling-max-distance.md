---
status: pending
priority: P3
filed: 2026-10-27
source: plan 184-02 (184-REVIEWS row 10)
gate: phase 186-27 done (the rebuild's import closure unfreezes)
---

# Promote research kernel `rk_high_dist` into the 186 registry

## What

Plan 184-02 built `rk_high_dist_w{window}` in `src/intelligence/features/research_kernels/rolling.py` (factory
`rolling_max_distance_kernel`) under the 186 Kernel contract but outside `kernels/`, because `kernels/`, `_primitives.py`
and `registry.py` sit in the 186-26 rebuild's import closure and cannot be edited while the rebuild
is live or resumable. A research kernel may exist only for a (statistic, window) no stored column
carries, and only until the registry can own it (184-REVIEWS row 10): two implementations of one
concept that evolve independently is the failure this todo closes.

Stored equivalent: `high_52w_dist` (`kernels/price.py` `_high_52w_dist_series_full`, an O(n x window) loop). The research copy is a vectorized sliding max and NaN before warmup instead of 0.0.

## Plan

1. After 186-27 swaps the rebuilt table in, move the vectorized compute into `kernels/` as a
   registry kernel. Replace `_high_52w_dist_series_full` with the sliding max under the parity test, or add the research windows as stored columns.
2. Keep the parity test in `tests/unit/intelligence/test_research_kernels.py` as the gate
   (bit-equal float32 at and after warmup against the original where one exists).
3. Point `kernel_source` members at the stored column, delete the research copy, its
   `STORED_EQUIVALENTS` row and its family entry, and update the `research kernel` glossary entry
   if the package empties.

## Done when

No research kernel duplicates a registry concept; `research_kernels` holds this family no longer.