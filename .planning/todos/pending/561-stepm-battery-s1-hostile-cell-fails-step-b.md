---
status: pending
priority: P0
filed: 2026-10-29
source: step B run of 2026-10-28 (logs/research/stepm_null_battery_s4000_stepb_20261028.json), pre-registered rule in 187-05-BATTERY.md
---

# StepM null battery: the s1_hostile cell fails step B, so no selection is attested

## What

The one fresh 4,000-session StepM battery (seed base 20,000,000, 1,000 simulations per cell, E17 v1
as todo 549 decided) was judged by the rule written down before it ran: each gating cell at most 74
family-wise rejections of 1,000 (binomial 0.9995 quantile at fwer 0.05), pooled gating rate at most 6%.

| Result | Value |
|---|---|
| Pooled gating rate | 5.34% (passes, tolerance 6%) |
| Gating cells that hold | 15 of 16 (rejections 41 to 58, one at 56) |
| Failing gating cell | `s1_hostile`: 89 of 1,000 (8.9%), median min adjusted p 0.468 |
| Diagnostic cells | `s1_slot_stress` 947 of 1,000 (documents a known limit, does not gate); others 55 to 59 |

The record's `failures` is `["s1_hostile"]`, so `select_books.py` refuses it as an attestation and
StepM selection stays blocked. By the pre-registered rule the failure is not rerun on other seeds to
find a pass; this todo names the cell instead.

## Context

- The same cell held in the 2026-10-27 run (base seed 0, 60 of 1,000 against a 67 bound). Two runs of the
  same cell at 60 and 89 are consistent with a true size near 7%, not 5%: an over-rejection, not a
  one-run fluke (89 is 5.6 binomial sd above 5%; 60 is 1.4 above).
- Step A's per-arm E17 size in this cell was about 5.3% (the cell mean of its arms was inside 4.7% to
  5.5% pooled over cells), so the excess is in the StepM layer or in S1's interaction with it, not in E17.
- `s1_hostile` sends hostile noise through `runner.compute_residuals` (S1's 252-session loadings and
  the forward-horizon lag), the stage the other gating cells skip.

## Plan

1. Diagnose before deciding: per-arm E17 size and arm correlation in `s1_hostile` against `hostile`
   (the same noise without S1); StepM's size at this cell under the block mean and bootstrap
   studentization. Exploratory seeds (not base 20,000,000), not a counted look.
2. If the cause is a real StepM or S1 defect, fix it and write a new pre-registered step B for a new
   fresh run (new seed base), judged on that run only.
3. If the cell is a limit of the synthetic S1 stage rather than of StepM, the owner decides whether it
   is a diagnostic cell, in writing, before any new run, with the reason.
4. Either way the attestation is a new complete run; `select_books.py` is unchanged.

## Done when

`select_books.py` accepts a complete step B record, or the owner records why the cell is diagnostic.

## Diagnostic 1 (2026-10-29, exploratory seeds from 30,000,000, not a counted look)

`stepm_null_battery.py --cells s1_hostile,hostile --sims 600 --seed-base 30000000`, 4,000 sessions:

| Cell | Family-wise rejections | Size | 99% interval |
|---|---|---|---|
| hostile (no S1) | 29 of 600 | 4.83% | [2.6, 7.1] |
| s1_hostile | 31 of 600 | 5.17% | [2.8, 7.5] |

On these seeds S1 does not inflate StepM's size. That sits uneasily with 89 of 1,000 (8.9%) in step B and 60
of 1,000 (6.0%) on the 2026-10-27 seeds: all three runs together are 180 of 2,600 (6.9%, 99% interval about
[5.5, 8.4]), the 91 of 1,600 that exclude the failing run are 5.7% ([4.4, 7.0]). 600 simulations cannot
separate a true size of 5% from 6 to 7%, so a 3,000-simulation exploratory run on `s1_hostile` alone
(seed base 40,000,000) is under way (unit `stepm-diag-561b`, output
`logs/research/diag_561b_s1_hostile_3000.json`). If its interval contains 5%, the step B failure is a tail
draw of a cell whose bound (0.9995 quantile) leaves little room; the response is a new pre-registered run
with more simulations on that cell (the binomial bound tightens with n), not a rerun of step B's seeds.
