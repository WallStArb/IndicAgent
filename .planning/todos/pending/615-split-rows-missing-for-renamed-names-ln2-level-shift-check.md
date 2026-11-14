---
status: pending
priority: P1
filed: 2026-11-14
source: c6 review of the A11 documentary placements (evidence lists in logs/massive_step7/a11_review_c6/), ruled by the lead 2026-11-14
---

# Split rows missing for renamed names: find every unexplained level shift before the d2-v6 rebuild

## What

The A11 documentary witness placed 1,860 sessions of SGH under PENG (2017-05-24 to 2024-10-15) with
corroboration `level_unexplained`: level median 0.693 and level IQR 0.693, which is ln 2. The cause
is a 2-for-1 split that no `corporate_action` row carries. `corporate_action_current` holds no row
for PENG or SGH at all.

Evidence, read 2026-11-14:

- Massive raw SGH close 57.06 on 2022-02-01, 27.85 on 2022-02-02 (the split day, as traded).
- IBKR PENG (split-adjusted) close 28.53 on 2022-02-01, 27.85 on 2022-02-02; the two tapes agree
  after the split and differ by 2x before it.
- `logs/massive_step7/a11_amend_20261114/documentary_candidates.csv`: PENG, SGH, `placed`,
  `level_unexplained`, 1,859 IBKR pairs, correlation 0.999, `level_iqr` 0.693.

d2-v6 adjusts the Massive 1d rebuild for the splits it knows. A split that is not recorded under the
name's symbol leaves the pre-split SGH tape unadjusted, a factor-2 step inside one name's series.
That is a silent wrong answer in every return across 2022-02-02. The same gap can sit under any name
whose history is placed from a predecessor ticker, because the split rows are keyed by the current
symbol and the Massive split feed is keyed by the ticker of the day.

## What to do

1. Find the names. After the map amendment lands (the new map version installed) and before the
   d2-v6 rebuild at step 7, run a read-only check over every (name, placed file ticker) pair in
   `documentary_placements.csv` and over every name whose Massive 1d rows span more than one file
   ticker: take `log(IBKR close / Massive close)` per session, difference it day to day, and list
   every step whose absolute size is within 0.01 of `ln k` for k in 2, 3, 4, 5, 10, 20 (and 1/k for
   reverse splits) with no `corporate_action` split row for that name within 3 sessions. Where IBKR
   has no overlap (post-2016 or thin), compare the as-traded close ratio across the session
   boundary (previous close to open, about 0.5 for a 2-for-1) against the Massive split feed.
2. For each hit, decide from the Massive splits feed (`reference_raw`, splits endpoint, by the
   ticker of the day) whether the split is real, and record it through the corporate-action path
   (`inferred_by` code, evidence request ids), never by hand edit. PENG gets 2022-02-02, factor 2.
3. Add the check as a gate in the D1 run report so a level step with no split row fails loud, not
   as a corroboration label. Candidate home: the step 7 Part B read-only checks, then the d2-v6
   daily stage report.

## Gate

Before the d2-v6 rebuild at step 7 (Part C). The check lists no name with an unexplained ln k step,
or each listed step has a recorded split row or a written decision that it is an IBKR-side artefact.
`level_unexplained` placements in the documentary run that carry a constant offset with tiny IQR
(CMCSA 0.065, RBCAA 0.049, SPXC/SPW 1.379) are an adjustment-model gap, not this defect; only a step
inside the span counts.

## Related

[614](614-refactor-audit-2026-11-14.md), `docs/plans/2026-11-10-massive-admission-db-design.md` (8c
amendment 2026-11-14), `docs/operations/massive-step7-runbook.md` (A11, Part B and C).
