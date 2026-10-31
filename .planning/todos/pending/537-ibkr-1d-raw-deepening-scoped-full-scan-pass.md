---
status: pending
priority: P1
filed: 2026-10-16
source: ohlcv_raw depth measurement 2026-10-16; todo 535 item 42 remainder; phase 191 plan 20 precondition
owner: data
---

# IBKR 1d raw deepening: one scoped full-scan pass of the fetcher

Runbook: `docs/plans/archive/2026-10-16-ibkr-1d-raw-deepening.md` (measured gap, gates, invocation,
completion). Summary: 1,135 of 1,529 names have unadjusted ibkr 1d raw starting later than their
own ibkr head floor (median floor 2000-01-03); about 3.66M missing sessions. The planner already
handles this via `--full-scan`; the weekly gap-fill cadence alone would take months. One scoped
pass (`--dimension compute_1d --timeframes 1d --full-scan`) after plan 14 closes cutover window
two deepens the plane in roughly 2 days of interleaved stream time.

## Open

1. Done 2026-10-18: the pass ran under the gate script to campaign completion (3 runs, 192
   pre-2015 bars; crontab self-removed). Caveat surfaced by plan 191-19: run 1 ended
   budget-exhausted after 138 items, so 437 names still carry unasked deep spans (plan 19
   readiness); the weekly cycle asks them as slots come due.
2. Scan run 2026-10-23 (results in todo 535 item 51). Restore deferred to the plan 20 owner
   checkpoint: if Tradier deletion is confirmed promptly, scoped ibkr-primary rows are moot
   (deletion serves unadjusted IBKR pre-D); if delayed, LEN (and RTX modulo two isolated late
   corrections) qualify now under the migration 494 gates.
3. Rides with plan 19 Task 2's --measure report (first-bar change per name), which runs when
   readiness exits 0.

## Done when

The cohort query in the runbook is stable across two passes with no bars fetched, R6 and D7 stay
clean, the selection gate exits 0, and the basis follow-up scan has run.
