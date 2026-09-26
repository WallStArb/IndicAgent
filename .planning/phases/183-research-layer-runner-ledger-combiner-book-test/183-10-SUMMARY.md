---
phase: 183
plan: 10
status: complete
---

# 183-10 summary: first real-data runs (family 1 evidence, book v1)

Executed inline from worktree `../indicagent-183-02` (subagents unavailable until the weekly
limit resets). Every number below is copied from the `research_run` rows.

## Task 1: family 1 member evidence (completed)

Run group `5a564f09-ecc5-4b38-bdb9-41008cc1e54d`, spec `b828c285a369b97f...`, code `531da089d`,
snapshot `81fa9178ca4ad603...` (`logs/phase183/snapshots/panel_81fa9178ca4ad603`), 6 workers,
started 2026-09-25 18:49 EDT, last member finished 19:52 (about 1 hour; the 3.5-hour projection
was made under heavier load).

| Member | run_id | HAC timing t | Gross Sharpe | Shift permutation p |
|---|---|---|---|---|
| same_slot_lag1 | a72b6e93 | 13.53 | 3.81 | 0.00022 |
| same_slot_mean5 | c6c340d7 | 18.32 | 5.28 | 0.00022 |
| same_slot_mean20 | 48913529 | 18.56 | 5.21 | 0.00022 |
| same_slot_mean40 | 37ee0e70 | 18.41 | 4.77 | 0.00022 |

Turnover about 26x gross per session; the cost band (diagnostic only) puts 1 bp per side at
about 65% a year against about 4.7% gross. Evidence JSON:
`logs/phase183/runs/b828c285a369b97f_<member>.json`.

## Task 2: book v1 screen test (refused, uncharged)

run_id `ba36e5b7-f301-47d9-a67b-314263457307`, group `a683f4a5`, spec `4cf8d2e98e5e140c`, code
`562a031c9`, same snapshot, started 19:57 EDT, refused 20:37. Power: plant 0.015625 (achieved IC
0.00198515), underpowered 0 of 51 (curtailed from R = 100). Evidence JSON:
`logs/phase183/runs/4cf8d2e98e5e140c_book_v1.json`. Budget: 0 of M = 30 charged.

## Task 3: records

Construction verdict ledger family 1 row and the prereg status pointer, f40cac50f.

## Deviations and what they found

1. **Shift-null diagnostics defective (fixed 562a031c9).** `np.median` over shifts went NaN on
   almost every session because the circular shift rolled the warmup's NaN alpha into scored
   sessions; sub-period excess, bootstrap interval and null shape were wrong in the four evidence
   records. Decision statistics unaffected. `nanmedian`, regression test, repro_frozen
   bit-identical.
2. **Book v1's refusal came from the statistic (todo 432, now E17).** E16's timing series is
   biased under H0 for own-history members (mean40 H0 t about -2.6) and gave the book no power
   at IC 0.002. Diagnosed on synthetic panels through the real power harness; adopted as E17 by
   the owner; built (33ca32107); family 1's records annotated by migration 377.
3. **E17's H0 battery** (null_battery.py, 1,000 simulations per cell) found a tail limit at large
   static cell means with volatility clustering and an S1 residual-target credit of order
   a^2 var(beta_hat); both negligible at the measured sizes. Owner decision: option C (measured
   sizes as a checked precondition, todo 447). Rejected alternatives recorded in E17.
4. **Equal-weight combiner** (5f3de6ca1) per E17's owner decision, behind the `Combiner`
   protocol.

## Next

Todo 447 (measured-size precondition), then todo 442 (attempts 1a-1c under the unified design,
E18). Todo 448 carries this lane's dependencies for phases 186 and 187.
