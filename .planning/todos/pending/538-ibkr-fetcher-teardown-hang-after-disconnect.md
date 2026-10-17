---
status: pending
priority: P2
filed: 2026-10-17
source: plan 191-16 execution, SUMMARY deviation 7 (2026-10-17)
owner: 2026-10-17
---

# IBKR fetcher teardown hangs after Disconnected: run_until_complete never returns

## What

Twice during phase 191 plan 16 (2026-10-17), a fetcher run with a small default-scoped queue
hung after logging "Disconnected": the main thread sat idle in `select` under
`asyncio.run_until_complete` with an unfinished future, and the process never exited. Both runs
were killed by hand. Loads already applied stayed applied and the advisory lock frees on process
death, so no data or lock leaked, but every later fetcher run is blocked until the process is
killed. The explicit `--timeframes` run and the full 05:47Z run of the same night exit cleanly,
so the trigger is the gateway-loss teardown path of a default-scoped run, not the fetch loop.
py-spy dumps were taken during the plan 16 session; if that scratch is gone, retake on the next
occurrence.

## Why now

The IBKR 1d deepening (todo 537) is driven by its crontab gate script while the owner is away
(about a week from 2026-10-16). A hang stalls that cadence silently until a human kills the
process, and nobody is there to do it.

## Fix direction

Diagnose the teardown path of `scripts/infrastructure/backfill/ohlcv_history_fetcher.py`: the
candidate cause is a gateway-disconnect callback whose future is never resolved, leaving
`run_until_complete` with nothing to wait on but nothing to return either. The likely shape of
the fix is a timeout around the event-loop shutdown so the process exits loudly (stack trace in
the log) instead of hanging, plus a regression test that reproduces the hang's shape (an
unresolved future at disconnect).

## Acceptance

- A fetcher run that loses the gateway mid-teardown exits nonzero with a logged cause within
  seconds, never parks in `select`.
- A unit test pins the teardown timeout against an unresolved future.
