---
status: completed
priority: P2
filed: 2026-10-17
source: plan 191-16 execution, SUMMARY deviation 7 (2026-10-17)
closed: 2026-10-31
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

## Outcome (2026-10-31, closed)

What landed, in order: 8cb51571c (watchdog + bounded teardown + migration 548 APR seeds
`infra.ibkr.stall_tick_s` 60 / `stall_abort_s` 1800 / `teardown_timeout_s` 30, applied live),
c7d8b1ac0 (reserve lane and planning count as forward motion; the item-dispatch tick routed to
`_mark_progress` so an in-flight item's stall checks hold the abort off, which is the pacing
suppression: a healthy 40+ minute deep item, or the 3617 s run that recovered, can never
false-trip the 1800 s abort, while a wedged item is still cancelled by its own stall bound),
7959f2672 (stall bounds read inside the cursor's with block; before that every run fell back to
the seed defaults with a warning). The per-request timeout the diagnosis proposed as a third APR
key was deliberately NOT duplicated: the bound already exists twice (`run_with_stall_bound` on
the provider plan's `request_timeout_s` per item attempt, and the per-request wait_for wrappers
in `src/providers/ibkr.py`); adding an unread `infra.ibkr.request_timeout_s` key would be
redundant mechanism (recorded in migration 548's header).

What the next wedge shows in the log: within 30 minutes of the loop wedging,
`ibkr_history_fetcher.stall_warning` lines start (one per 60 s tick with no progress), then one
`ibkr_history_fetcher.stall_abort` error naming every pending asyncio task with its coroutine
and stack (the dump the 2026-10-31 py-spy dumps had to be taken by hand), and the process exits
1; the timer restarts the lane and the run's loss is bounded at 30 minutes. A wedge during the
leaf-disconnect sequence instead logs `ibkr_history_fetcher.teardown_timeout` (30 s) and fails
the run. A wedge inside an item never reaches the watchdog: the item's own stall bound cancels
it (`ibkr_history_fetcher.item_stalled` warnings, then an error outcome, which is progress
again). The only silent-wedge class left is a wedged timer set, which the systemd WatchdogSec
covers.

Regression tests in `tests/unit/scripts/test_ohlcv_history_fetcher.py` (todo 538 section):
abort + pending-task dump with a structlog capture (built before the capture window, since the
constructor's `setup_service_logging` configure would swap the processor list out), reset on
progress, stage-subprocess pause, slow in-flight item never trips the abort, teardown bound on a
hanging disconnect, dead leaf never blocks the others, APR bounds read with seed defaults.
