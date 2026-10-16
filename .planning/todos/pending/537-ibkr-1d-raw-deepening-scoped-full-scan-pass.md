---
status: pending
priority: P1
filed: 2026-10-16
source: ohlcv_raw depth measurement 2026-10-16; todo 535 item 42 remainder; phase 191 plan 20 precondition
owner: data
---

# IBKR 1d raw deepening: one scoped full-scan pass of the fetcher

Runbook: `docs/plans/2026-10-16-ibkr-1d-raw-deepening.md` (measured gap, gates, invocation,
completion). Summary: 1,135 of 1,529 names have unadjusted ibkr 1d raw starting later than their
own ibkr head floor (median floor 2000-01-03); about 3.66M missing sessions. The planner already
handles this via `--full-scan`; the weekly gap-fill cadence alone would take months. One scoped
pass (`--dimension compute_1d --timeframes 1d --full-scan`) after plan 14 closes cutover window
two deepens the plane in roughly 2 days of interleaved stream time.

## Open

1. Execute the pass per the runbook gates (window closed, fetcher import surface clean, no
   running fetcher). A gate-check is scheduled in the session that filed this todo; it launches
   the pass the moment the gates open and kills it if a cutover window re-opens (plan 24
   interlock).
2. On completion, re-run the todo 535 item 42 basis follow-up scan and restore the eligible
   damaged names to the unadjusted ibkr basis.
3. Record the new first-bar facts so plan 20's Tradier deletion loses no history IBKR serves.

## Done when

The cohort query in the runbook is stable across two passes with no bars fetched, R6 and D7 stay
clean, the selection gate exits 0, and the basis follow-up scan has run.
