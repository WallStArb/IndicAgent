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

## Update 2026-10-31 (evening): the factory "wedge" was a misdiagnosis; the fetcher wedge is real and now has a with-locals specimen

The 186-26 stage-2 factory instance is WITHDRAWN. Session 9f stopped a healthy run on 2026-10-31
about 21:22Z after reading "no worker children, zero DB writes, main parked in result()" as a
wedge. Cadence analysis (93): the run loaded 252 units 15:43Z-21:02Z in bursts separated by
52-91 minute compute gaps; main zero-CPU parked in `result()` at
`backfill_feature_factory.py:1473` is what a healthy run looks like mid-gap, and pool workers
parent to the forkserver, so children-of-main shows none even when 8 are computing. The kill
discarded one in-flight group's compute. Lesson recorded in STATE.md: stage-2 health is
burst-cadence of unit_loaded events plus full worker CPU, never DB-write continuity.

The fetcher wedge is confirmed and reproduced live: the 21:25:32Z run (pid 1710629) acquired the
lock and logged nothing for 25+ minutes (healthy runs log batch_computer.pool_open within 0-6 s;
today's comparable silences 1971 s and 3617 s, the latter self-recovered). Specimen captured with
locals 21:35Z before restart: `logs/todo538_fetched_dump_20261031_2135z.txt` (+5 min comparison
dump at ..._2145z.txt). Findings: the event loop is ALIVE (epoll wait, timeout 144.25 s,
sched_count 14) under an unresolved Task, and the gateway TCP socket is ESTABLISHED, so the hang
is protocol-level or a dropped callback resolution, not transport. The 144 s timer keeps
rescheduling, which fits 93's memory-pressure-alternative only weakly; the primary mechanism is
an unresolved ib_async request future or a lost resolver callback. The doc's diagnosis should add
instrumentation that names the awaited task (periodic asyncio task dump, or logging the awaited
coroutine at lock acquire). Comparison dump (+5 min): sched_count stays 14 and the epoll timeout
went 144.25 s -> 146.76 s, so the same handles re-arm on a recurring ~145 s cycle: an unlogged
retry loop, not a one-shot wait. Diagnosis doc:
docs/plans/2026-10-31-fetcher-future-hang-diagnosis.md (c8c0b12b9). Discriminator probe result 22:07Z (PM): the gateway auth probe (clientId 44,
outside the fetcher family, no FetcherLock) authenticated and answered during the 21:25Z wedge,
so the gateway session was serving new clients while the fetcher's own session sat silent:
convicts the fetcher-side await/dropped-callback mechanism over a stuck gateway session.

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

## Diagnosis written (data lane, 2026-10-31 evening)

`docs/plans/2026-10-31-fetcher-future-hang-diagnosis.md` is the full read. Headlines: the
fetcher wedge is protocol-level (loop alive, TCP ESTABLISHED on loopback, no reply, no error;
an await with no timeout), not transport and not CPU; the fix direction is the post-acquire
watchdog that names the pending tasks, a teardown timeout, and per-request timeouts (APR
bounds, owner sign-off before the edit window). The same evening's factory "wedge" was
reclassified: the 13:45Z stage 2 run was healthy (252 units, rows summing exactly to the
database, group gaps of 52-91 minutes), the 21:20Z stop was a mistake driven by main-pid
worker checks and a missing cadence baseline, and the diagnosis doc carries the corrected
health protocol (write-anchored, forkserver-children liveness, cgroup reads, 2.5h wedge
criterion). Next occurrence of the fetcher wedge: py-spy the main (done 21:35Z for the
21:25:32Z run) plus the gateway discriminator probe (fresh clientId request; docker stats on
ib-gateway) before any restart.
