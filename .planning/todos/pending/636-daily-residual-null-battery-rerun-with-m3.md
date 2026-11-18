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

## Outcome of the pre-declared replication (2026-11-18): the pooled run FAILS, the family waits

Block 2 (seed-base 1,000,000, whole battery, one driver call, 1,000 simulations per cell, e20c908c2; `logs/e17_daily_residual_m3_block2/block2.json`) fails on its own in the same cell and the same two arms as block 1, at alpha 0.05 instead of 0.00167: `daily_static_means/reversal_5` 68 against a bound of 67 and `reversal_5_skip1` 72 against 67. Pooled over the two blocks (2,000 simulations per cell, bounds 123, 31 and 8, the declared and only criterion) the same two arms fail at alpha 0.05:

| Arm (cell `daily_static_means`) | Block 1 at 0.05 | Block 2 at 0.05 | Pooled at 0.05 (bound 123) | Pooled at 0.00167 (bound 8) |
|---|---|---|---|---|
| reversal_5 | 59 | 68 | 127 (6.35 percent) | 7 |
| reversal_5_skip1 | 57 | 72 | 129 (6.45 percent) | 8 |

Every other arm and cell holds pooled, M3 and the equal-weight book included, and the S1 cell holds. The two arms exceed the 5 percent level in both independent blocks, and the base commit bd476c5f4 (five members, before any I1, B-H or B-S change) gives the same block-1 counts on identical seeds, so this is a size excess of the five-session reversal members under static per-name mean returns that predates the amendment, not a result of M3 or of anything landed since. By the declaration the daily residual family waits: no pass record is bound (`battery_pass.make_record` refuses a failing pooled result), a real run is refused by `runner.static_gate`, and the failure postpones the run and is never a verdict on the hypothesis (E17). The gate is not changed.

Open for the owner (a decision, not a quiet change): whether the reversal members' excess size under static means is a statistic defect to fix (a design change to the static-mean handling of the E17 statistic, which moves the frozen verdicts and needs a methodology-change entry), or whether the family registers without its reversal members (a counted amendment: the momentum members M1, M2, M3 and the book hold), or the gate's calibration is to be reviewed (a separate proposal, since a correct statistic is expected to fail a full battery about 60 percent of the time at 126 independent tests, and here the same two arms fail in two blocks, which is not chance). H-C is not affected: its battery passes and its record is on main.

## Ruling (2026-11-18): the gate is family-wise; the battery reruns on fresh seeds

An independent analysis found the statistic calibrated (reversal_5 at 4.99 percent over 17,000 fresh simulations, spread ratio 0.999, no growth with static-mean size). The gate moves to a Bonferroni bound over the battery's gating tests (ledger E17 amendment 2026-11-18); the family keeps all five reversal and momentum members plus M3. Because the change follows a failure, the pass is not taken from blocks 1 and 2: `DECLARED_REPLICATIONS["daily_residual"]` is now `(2_000_000,)` and the whole battery runs once on seed base 2,000,000 with 2,000 simulations per cell, then `bind_battery_pass.py` binds it. Blocks 1 and 2 stay above as history.
