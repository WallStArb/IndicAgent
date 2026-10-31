# Data fill and corpus rerun plan

**Status:** operative 2026-10-31. Supersedes the program-level sequencing in
`2026-09-02-personal-scale-edge-determination-plan.md`, `2026-09-24-edge-proof-program.md` and
`2026-09-24-feature-lifecycle-evidence-ledger-design.md` (each condensed and archived as a stub
2026-10-31, todo 568, under `docs/plans/archive/`). The adopted research sequence itself stays
`2026-09-26-unified-research-to-production-design.md` section 16 and the critical path in
`.planning/STATE.md`; this doc adds the data-fill plan and the rerun gates on top of them.

**Author:** Claude (Opus 5.5), data-lane session indicagent-31
**Informed by:** owner directives 2026-10-31 (raw coverage target: 5m 2006-2026 every symbol,
deepest daily per name, Alpaca and IBKR; history depth outranks freshness; recent-data catch-up
only at feature-calc time) and the measured state of 2026-10-31.

## The sequencing principle

Fill by dependency, not by vendor. Start the first counted looks the moment their own inputs
are clean; never serialize the corpus rerun behind the 5m fill. No active family reads 5m
(todo 445), so the daily lane unblocks in days while the 5m fill runs in weeks behind it. The
5m fill is not background work: it is the feature-depth program itself (stage 2 computes 5m and
its derived 15m/1h over whatever history canonical holds, and stage-2b/2c units extend per-name
feature history as backfill data lands), which makes the fetcher wedge (todo 538) the binding
constraint on feature depth.

## Phase A: fill (parallel lanes)

1. **1d completion (critical path, days).**
   - `unserved_primary` refusal fix in `daily_rule.py` (session lane; records the 22 D-191-Q
     by-design IBKR gaps instead of skipping silently).
   - D7 dated-tolerance rule (todo 524 mechanism, session lane; releases the todo 573 waves:
     18 restatement-skew names, 14 truncation names as dated exceptions; ETHA and CTVA wait for
     an archive re-fetch).
   - Owner gate 1: the 27 `compute_eligible_1d=false` names. Assistant verifies each name's
     ineligibility reason and files the evidence; promotion lands together with todo 491's S0
     universe snapshot, before the first counted run.
   - Owner gate 2: D-191-Q arbitration on the 22 IBKR-symbol-row names. Default: extend IBKR
     symbol rows where the vendor serves, recorded refusal where it does not.
   - Stage-2b: the 573-released names build as their own unit on the same pin when stage 2
     drains. No rerun of the 1,252.
2. **5m pre-2016 campaign (weeks, parallel, not blocking the daily lane).**
   - Decision point 2026-11-01 from the new pacing logs (commit a23af3551): pacing means a
     config fix; the wedge means a bounded todo 538 session (the 2026-10-31 py-spy stack is the
     starting evidence).
   - Target: of 1,160 pre-2016 names, 81 reach their daily start today, 280 partial, 799 none.
     Per-name floors where IBKR serves nothing are recorded as evidence (todo 537's pattern).
   - Contention default: the 186-26 rebuild keeps the host; the campaign gets full rate
     (~175 req/h at concurrency 4) once stage 2 drains.
3. **Freshness is automated** (nightly Alpaca 04:40 UTC, derivation timers 05:20/05:45 UTC,
   IBKR update lane) and is explicitly not a priority until feature-calc time.

## Phase B: optimize (only what the rerun feels)

- IC measure block width (todo 471) measured before 186-28 names the tf set.
- Dead 1d columns declared (todo 564) and the concept-layer reset (todo 571, owner-approved)
  after the rebuild, so the rerun's registry is clean.
- Kernel cleanups (472, 474, 477) ride the rebuild's commit cadence, not ahead of it. Nothing
  is optimized before the requirement questions above are answered (Musk order).

## Phase C: rerun gates (the counted sequence)

191-23 integrity checks -> 186-27 swap -> S0 snapshot with the promoted universe pinned and
hashed (todo 491; blocks the first counted look) -> `oos_start` write-once and forward-span
purge (todo 439 part 2) -> 184 S0 panel -> families under E17/StepM (section 16 order: daily
families 441 + 423, then 440, then feature families, then regime-segmented). Every look counted
from there; the search space grows with the panel, so the count-every-look framework scales
with it.

## Decision points

| Gate | Owner needed | Default if silent |
|---|---|---|
| 27 ineligibles promotion | Yes, with evidence file | Verify + hold; promote at the S0-snapshot gate |
| D-191-Q arbitration (22 names) | Yes, one approval | Extend where IBKR serves, refusal where not |
| Pacing vs wedge (2026-11-01 logs) | No | Config fix if pacing; 538 session if wedge |
| Rebuild vs backfill contention | No | Rebuild wins; campaign crawls, full rate after stage 2 |
