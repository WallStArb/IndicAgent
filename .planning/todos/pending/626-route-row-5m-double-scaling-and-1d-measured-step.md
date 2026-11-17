---
status: pending
priority: P2
filed: 2026-11-17
source: independent review of bd278686c
---

# A route row measured on 1d is applied to 5m with no guard

## What

A route-named split row (todo 592 operator row, `detail.unadjusted_routes`) is measured on the 1d series
(`calendar_adjusted_step` is the 1d real move) and now also rescales the same (vendor, kind) at every
direct timeframe in selection (bd278686c). Two gaps:

1. If the vendor later restates the series (Alpaca re-serves CLBK's history on the new scale; raw is
   last-wins), selection divides the restated bars by 2.2 again and canonical 5m is double scaled. D7
   `split_continuity` and `unexplained_seam` judge 1d only, so nothing fires. The daily rule has the
   same exposure; its guard is the recorded measurement on the 1d series.
2. The row asserts nothing about 5m: CLBK's 5m was checked by hand (24.465 to 10.915 before the reselect,
   about 11.12 to 10.915 after).

## Requirement first (Musk step 1)

Decide whether the exposure needs a mechanism: how often does a vendor restate after a corporate action
it missed, and does the nightly overlap (`nightly_overlap` restatement rows) already catch it as a
restatement split? If yes, the existing restatement path is the guard and only 5m needs a seam check.

## Scope

1. Ruling written here.
2. Either require a timeframe-named route (`alpaca/sip_rth@5m`) or a 5m-measured step in the row, or extend
   `split_continuity` and `unexplained_seam` to canonical 5m seams of route rows (preferred if the check is
   cheap: one seam per route row).
3. Tests: a restated series (raw at the new scale after the row) fails the check; the CLBK shape passes.

## Gates

Unit suite exit code; independent review; no other name's verdict changes.
