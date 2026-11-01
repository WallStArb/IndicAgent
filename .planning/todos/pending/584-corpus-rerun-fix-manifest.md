---
status: pending
priority: P0
filed: 2026-11-01
source: lead orchestrator (indicagent-4f), owner sequence 2026-11-01: data -> all fixes -> corpus rerun -> ensemble research
---

# Corpus rerun: the one list of fixes that must land before the feature recompute

## Decision (2026-11-01 23:10Z)

The 186-26 output on pin `92e588385` carries known stored-value defects (564 `hma_slope_z` is a
0.0 fill on every 1d row; 583 HMM NULL on whole names; 474 neutral fills where the quantity is
undefined). It cannot be swapped in by 186-27, so the corpus is recomputed once more at a new pin.
Stage 2 was paused at 650/1,252 intraday names (kill-and-resume safe; command and env in
`data/scratch/186-26/`) so the intraday screen could run on finished output and no more compute is
spent on superseded rows. Fixes land on main now: the pinned run tree is a separate worktree, so
the "wait for the kernel-edit window" constraint no longer applies.

One pin move, one rerun. Every item below that changes a stored value lands before the pin moves;
anything found after the pin moves waits for the following rerun.

## Batch (stored values change)

| # | Item | Source | State |
|---|---|---|---|
| 1 | `hma_slope_z` NaN while the slope history is short; parity golden updated | 564 | root-caused |
| 2 | 1d applicability: intraday-session columns declared out of scope (NaN by declaration); VP/structure group decided per column | 564 done-when 2 | open |
| 3 | HMM whole-name NULL: refusal reasons measured, then gate or input fix | 583 | measuring (indicagent-dc) |
| 4 | Undefined is NaN in kernel fallbacks; genuine zero states keep 0.0 and are declared (option 2; `no_fill` is an invariant, not a preference) | 474 | decided, open |
| 5 | Macro inputs: no fabricated zero without a cross-asset record; previous closes tracked before the first record | 463, 464 | open |
| 6 | Intraday screen findings on the 650 stage-2 names | this todo | screen running |
| 7 | Delete list after migration 543 (dropped-volume path, `volume_reset`, APR key retire) and the config field rename | 564 same-batch | open |
| 8 | Never-computed `rank_z` registry rows retired; candidate stored-column additions decided (a column added after the pin needs another rerun) | 558, 421 | open |

Out of the batch (no stored-value change, or a different path): 475, 473, 582.

Open data-lane decision before the pin: `_PMC_RANGE_START` 2005 vs 2000 (564 same-batch; 41 names
fall below coverage at the 2000 era).

## Done when

1. Items 1-8 landed on main, each through /simplify, /review and the unit suite; `repro_frozen`
   bit-identical where research or statistics moved.
2. A pilot chunk at the new pin passes the column screen with zero unexplained dead columns on
   every timeframe.
3. The rerun is launched at the new pin (1d then intraday), and 186-27 proceeds on its output.
