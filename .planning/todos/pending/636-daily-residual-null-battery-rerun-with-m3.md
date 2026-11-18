---
status: pending
priority: P1
filed: 2026-11-18
source: B-S review (todo 609): amendment A2 requires the B2 size gate to rerun with the sixth member, and nothing enforces it
---

# Rerun the daily residual E17 H0 battery with M3 before the family registers

## What

`null_battery_daily_residual.MEMBERS` now lists M3 (`residual_momentum_12_1_continuity`) with the spec. `static_gate` is computed from
the scenarios, not from a recorded battery result, so the rerun that A2 requires (size at 0.05, 0.01 and 0.00167 over 1,000
simulations per cell, six members and the equal-weight book at full size, B3 minimum detectable IC for M3) is a manual step that can be
skipped silently.

## Done when

- The battery is run on the six-member family and its result is recorded where the static gate or the run preflight reads it, so a
  registration without it is refused.
- The recorded result names the spec hash of `daily_residual_h5.yaml` and the core twin.

## Why it matters

A precondition of the first counted daily family (E23, A2).

## Result of the first block and the pre-declared replication (2026-11-18, recorded before block 2 launches)

Block 1 (seed-base 0, run at e20c908c2 in two parts, 1,000 simulations per cell): the S1 cell and every M3 and book arm hold; two arms fail in `daily_static_means` at the deepest level, `reversal_5` and `reversal_5_skip1` at alpha 0.00167 (6 against a bound of 5). The base commit bd476c5f4 (five members, none of the I1, B-H or B-S changes) on the identical seeds gives the same 6 and 6, so the exceedance is a property of the draw, not of M3 or of any landed change. Files: `logs/e17_daily_residual_m3_e20c908c2/`, `logs/e17_daily_base_check/`.

Pre-declared before block 2 launches (lead ruling 2026-11-18): the whole battery (all eight cells, no cell picked) reruns once on seed-base 1,000,000 in a single driver call, at the same commit. Both blocks are kept in the record. The pass criterion is the pooled counts of the two blocks (2,000 simulations per cell): per cell, arm and alpha, the rejections of block 1 and block 2 summed and compared with the 0.99 binomial bound at n = 2,000 (123, 31 and 8 at alpha 0.05, 0.01 and 0.00167), with no other rule. Block 1, block 2 and pooled counts are reported separately. If the pooled run fails anywhere the family waits; a failure postpones the run and is never a verdict (E17). The gate is not changed. Expected arm-level exceedances of a correct statistic over a full run: the daily battery has 6 gating cells and 7 arms (six members and the book) at 3 alpha levels, 126 tests; at n = 1,000 each test exceeds its bound with probability 0.0074, 0.0069 and 0.0073, so the expected count is 0.91 and the probability of at least one exceedance, treating the tests as independent (they are positively correlated, which lowers it), is about 0.60. At n = 2,000 each test exceeds with probability 0.0095, 0.0078 and 0.0074. If that calibration looks wrong to the owner it is a separate proposal, not a change made here.
