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

## Update 2026-10-31: same wedge, mid-run, under rebuild load

The wedge is not teardown-only. On 2026-10-31, with the 186-26 stage-2 rebuild running (8
workers, from 09:38 EDT), two fetcher runs wedged mid-run: the 08:14 EDT run after 2h12m (last
item logged 10:26 EDT, killed by the unit watchdog at 11:01), the 11:17 EDT run 45 s after
"IBKR connected" (killed 12:02). Both with near-zero CPU (3-45 s CPU over hours), the
unfinished-future signature. The watchdog + timer self-healed both times (run lost, about 15
min gap), so the pre-2016 5m backfill (534) continues but each wedge costs a run plus the
gap, and the correlation with the rebuild's host load is unexplained. Under the same load,
pacing waits log nothing (todo 485), which blinds diagnosis. Next occurrence: py-spy dump
(needs sudo) BEFORE killing, and note whether the rebuild is running.

## Update 2026-10-31 (evening): second wedge site, the 186-26 stage-2 factory

Same unfinished-future family, different process. The stage-2 relaunch (13:38Z) loaded nothing
for 7.5h: main thread parked in `result()` at `backfill_feature_factory.py:1473`
(`_write_group`) waiting on a process-pool future that never resolved; only the resource
tracker and forkserver children existed, no compute workers ever started. No cgroup OOM
(`oom_kill 0`, though memory.peak sat exactly at the MemoryMax 14G cap 645 times). py-spy
dump taken 21:20Z before killing (sudo, per the note above). Recovered by
`systemctl --user stop` + the same pinned launch script at 21:25Z; stop was clean (no orphans,
no stuck `pg_stat_activity` backends). Suspicion for the diagnosis: a forkserver/pool startup
failure parked the main on a future no worker would ever complete, so the hang is not limited
to the fetcher's asyncio teardown, it is "main waits on an executor future with no live
worker". Session indicagent-93 owns the written diagnosis (both sites) once its APR commit
lands; the fix direction above extends to a startup/worker-death watchdog for the factory's
pool.

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
