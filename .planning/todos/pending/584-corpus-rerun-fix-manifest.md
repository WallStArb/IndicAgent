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
| 1 | `hma_slope_z` NaN while the slope history is short; parity golden updated | 564 | implementing (subagent) |
| 2 | 1d applicability (design D1): intraday-session columns declared out of scope (NaN by declaration); VP/structure group decided per column | 564 done-when 2 | open |
| 3 | HMM whole-name NULL: refusal reasons measured, then gate or input fix | 583 | measuring (indicagent-dc) |
| 4 | Undefined is NaN (design D1) in kernel fallbacks; genuine zero states keep 0.0 and are declared (option 2; `no_fill` is an invariant, not a preference) | 474 | decided, open |
| 5 | Macro inputs: no fabricated zero without a cross-asset record; previous closes tracked before the first record | 463, 464 | open |
| 6 | Intraday screen findings on the 650 stage-2 names | this todo | screen running |
| 7 | Delete list after migration 543 (dropped-volume path, `volume_reset`, APR key retire) and the config field rename | 564 same-batch | implementing (subagent) |
| 8 | Add-list per design D2 (558's eight rows); never-computed `rank_z` registry rows retired | 558, 421 | open |
| 9 | Pilot gate tool (design D3) | this todo | open |
| 10 | Calendar start 2000 (`_PMC_RANGE_START`); the 41 newly failing names backfilled or named holds | 564 same-batch, owner restart conditions | landed 2026-11-01 (data lane); the 41 are named verdict-gate holds for this rerun, see below |
| 11 | Proven-span start per name (design D4), closes 532: names held only for early-history holes (the 41 from item 10, AAOI, AGL, ACMR, ADPT and the like) enter the rerun from their proven start | 532, item 10 | landed 2026-11-01 (data lane), ledger E19; 189 of 205 failing names return, all 41 |

Out of the batch (no stored-value change, or a different path): 475, 473, 582.

Calendar start: the owner's restart conditions (STATE.md, "Decisions waiting on the owner") name
calendar start 2000 as part of this batch, so `_PMC_RANGE_START` moves to 2000; the 41 names that
fall below coverage at the 2000 era become named holds or get their 2000-2004 holes backfilled
first (data lane).

Item 10 disposition (data lane, 2026-11-01, indicagent-82). `_PMC_RANGE_START` is 2000-01-01, so
`first_session("NYSE")` and the 1d session_coverage era start at 2000-01-03. No per-name proven-span
start exists: the rebuild's `series_start` is the first loaded bar, and `session_coverage` anchors at
max(first bar, era start), so a hole after the first bar fails the name (todo 532 is the verdict-
definition change, a methodology-ledger entry). A `bar_hold` row is the wrong tool for the 41: the
daily stage skips a held name whatever the scope, which would also stop the backfill's results
reaching it. The disposition is the existing gate: at the next audit the 41 fail session_coverage
at the 2000 era, the verdict gate excludes them from this rerun and names them, and the list is
`191-SESSION-COVERAGE-ERA-2000-NEWLY-FAILING.tsv`. Measured on live data: every missing 2000-2004
session is name-specific (0 of 986 distinct dates are vendor-wide); for 39 of the 41 no vendor holds
a raw row for the missing dates; AIZ (21) and PAR (31) have Tradier rows that canonical does not
select, which is the D-191-Q policy (1d before 2016 is IBKR alone; Tradier is not a source, and its
consolidated volume is a different basis), not a selection defect. Follow-ups: (a) a 1d
2000-01-01..2004-12-31 IBKR pass for the 41, queued behind the pre-2016 campaign once the history
farm is live (fetch depth today is about 2006, so these dates were never requested); picked up by
the next rerun; (b) the per-name proven-span start (denominator and panel start declared per name,
the first session after the last pre-2005 hole), which closes todo 532 and goes through the
methodology ledger.

Owner restart conditions this rerun must also meet: all timeframes, including the 229 D7-hold
names and the 16 recent listings; phase 191 plans 22 and 23 (done); the 1d gaps of todo 566; a
fixed, written universe.

## Design (lead, 2026-11-01)

### D1. One null rule for every stored column (items 2 and 4)

Today each kernel module picks its own convention for "undefined": VP returns 0.0 and 0.5, SR,
sweep and pool return 0.0, swing and session levels return None. A reader cannot tell a measured
zero from a missing value. The rule that replaces them:

1. A stored value is a measurement or NaN. NaN has exactly two meanings, and the registry tells
   them apart: not applicable on this timeframe (declared, rule 3) or undefined at this row
   (warmup, no object exists, a refused fit).
2. 0.0 is stored only where zero is the measured state: event flags and counts over a fully
   observed window (`sweep_detected`, `in_lvn`, `price_in_value_area` where the value area is
   defined, `sr_level_count`, `pool_count`, touch counts). The distance, strength, age, velocity
   or position of an object that does not exist is NaN. "Bars since event" with no event in the
   observed history is NaN (right-censored), never 0.
3. Timeframe applicability is declared once, on the kernel: `Kernel.intraday_only:
   frozenset[str]` (outputs undefined on a whole-session bar). `compute_kernels` writes those
   outputs as NaN on 1d in one place, and every in-kernel `tf == "1d"` suppression branch
   (`_NEUTRAL_VP_EXTRA`'s 1d path, `_SESSION_LEVELS_DAILY_SUPPRESSED`, the calendar session
   flags) is deleted. The registry exposes `applicable_outputs(tf)`; the S0 read (184) and the
   column screen consume it, so a declared column is excluded, not "dead".
4. `Kernel.zero_is_state: frozenset[str]` names the outputs where rule 2 allows 0.0. A
   registry-wide unit test feeds each kernel a series where no object exists (flat price,
   too-short history) and asserts every output outside `zero_is_state` is NaN.

Scope of 1d `intraday_only`: the session-anchored VP fields, the session-time and killzone
columns (`hour_of_day_*`, `minute_of_hour_*`, `in_ny_session`, `in_london_kz`, `in_overlap`,
`power_hour`, `session_time_pos`, `opening_range`), the overnight and Asian session distances,
the intraday return divergences, and the AMD phase family. A column that is constant on 1d
without being a session concept (`sweep_detected`, `manip_strength`, `hmm_vol_prob_elevated`)
is investigated, not declared away: if it cannot fire on a daily bar by construction it is
declared; otherwise it is a defect.

### D2. The add-list rides this pass (item 8)

558's eight-row add-list (decided 2026-11-01 with its spec pin-downs) enters as registry
`candidate` rows in this batch: the owner's rule is that new columns ride the next pass, and this
is it. The three never-computed `rank_z` rows retire. `redundancy_group` is filled after the
rerun from measured correlations.

### D3. The pilot gate: catch the next defect in a pilot chunk, not after a corpus pass

The 564 and 583 defects share one shape: a column whose first finite row comes far later than
its declared memory, or never. The gate measures that directly. It extends
`ops_feature_column_screen.py` (same single grouped pass, two more aggregates per column) and
runs on a pilot chunk at the new pin, before the full rerun:

- G1 dead columns per (tf, name): any dead column outside `applicable_outputs(tf)` fails.
- G2 warmup gap per (tf, name, column): first finite row index minus declared
  `feature_memory_bars`; a gap beyond tolerance fails (this is what would have caught
  `hma_slope_z` at 7,560 rows and HMM on AAPL at 5,470).
- G3 fill audit: the exact-0.0 share of post-warmup rows per column, outside `zero_is_state`;
  a share above tolerance fails for review.
- G4 causality: the existing `causality_probe` on pilot real data at three truncation points.
- G5 determinism: two pilot units computed twice, bit-identical.

Pilot set, about 40 names over all four timeframes, chosen to break things: SPY and two other
ETFs, AAPL, MSFT, HON, SCCO (583), KO, JPM, XOM, five of the 16 recent listings, five D7-hold
names, five thin names, a volume-basis-seam name, a spin-off, and one name with a pre-2016 IBKR
5m segment. The pass fails loudly; nothing launches on a red gate.

### D4. Proven-span start (item 11)

A hole in early history is missing depth, not a defect in the name; it becomes a correctness
problem only where a rolling window spans it. Excluding the whole name throws away its clean
later decades and tilts the universe toward names with complete early data. Rule: a name's
proven start is the earliest session `s` at which the existing session-coverage verdict over
`[s, last session]` passes its threshold. The verdict anchors there instead of at
`max(first bar, era start)`; the rebuild computes from that start and the panel declares it.
The start depends on bar presence only, never on returns. It is recorded per name with the
verdict, and the change is a methodology-ledger entry. The 2000-2004 backfill for the 41 moves
a proven start earlier in a later pass; it never blocks this one.

### Sequencing

Implementers work one at a time per shared file: items 1 and 7 (running) touch `registry.py`,
so D1 (items 2 and 4) starts after they land. Item 5 (`macro.py`) and the add-list's new kernel
module (item 8) do not collide and run beside them. Item 3's fix waits for the 583 measurement.
The D3 gate tool is independent and is built now.

## Done when

1. Items 1-11 landed on main, each through /simplify, /review and the unit suite; `repro_frozen`
   bit-identical where research or statistics moved.
2. The pilot chunk at the new pin passes gates G1 to G5 (design D3) on every timeframe.
3. The rerun is launched at the new pin (1d then intraday), and 186-27 proceeds on its output.
