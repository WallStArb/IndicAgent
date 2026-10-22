---
status: pending
priority: P2
filed: 2026-10-18
source: plan 191-17 execution, rider finding (plan 16 review P3-6) (2026-10-18)
owner: 2026-10-18
---

# Weekly parity lane is rank-starved behind the deep 5m backfill

## What

The weekly IBKR 15m/1h parity draw (the standing vendor-basis evidence for the derived grid,
plan 191-11) is eligible and queued but never executes while deep 5m backfill work exists. The
week-42 draw (9 names: EPD, FXC, ARRY, FSLR, GEV, PM, RSG, THRM, BMY) sat at queue positions
177-194 of 3025 in the 2026-10-18T07:45Z dry run
(`logs/ibkr_history_fetcher_dryrun_20261018T074520.tsv`), all SLA-breached and unheld, while
the nightly run budget is consumed by higher-ranked backfill/gap_fill items (2026-10-18 06:00Z
run: n_items 12 = backfill 7 + gap_fill 5, budget_exhausted). No 15m/1h parity `ohlcv_request`
row exists since 2026-10-10 except plan 16's explicit URA run, so `ohlcv_load` has no parity
destination rows for week 42. D7 `grid_parity` fails 1683 of 3058 subjects, which is this gap
showing up as a condition.

## Why now

Plan 191-17 (close) was asked to confirm the week-42 parity draw executed end to end (plan 16
review P3-6); it did not, and the deep backfill queue is only now being worked down (the deep 5m backfill and
the 1d deepening are nearly done). Without a change, the parity lane waits behind whatever deep
work comes next, and the weekly vendor-basis cadence the design promises (one draw per ISO week
per eligible name) silently stops.

## Fix direction

Rank or reserve: either give the parity lane a per-run item floor (like a mini-budget, so a
weekly lane cannot be starved by an unbounded lane) or rank parity items ahead of backfill
items when their ISO-week window is open and unspent. Measure first: with the deep backfill
queue at 1274 items, estimate weeks-to-execution at the observed per-run budget before choosing.
Keep the hold semantics (coverage head >= ISO week start) unchanged.

## Scope guard

No change to the write path, the selection policy, or the parity hold rule; this is queue
ranking/budgeting only, in the fetcher's priority queue.
