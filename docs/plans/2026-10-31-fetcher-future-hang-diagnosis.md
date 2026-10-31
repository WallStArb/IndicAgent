# The unresolved-future hang family: fetcher wedge and the stage 2 factory reclassification

Status: diagnosis, 2026-10-31. Author: data lane session (indicagent-93). Informed by: py-spy
dumps and cgroup reads taken by indicagent-9f (fetcher dumps preserved at
`logs/todo538_fetched_dump_20261031_2135z.txt` and `..._2145z.txt`; the 21:20Z factory dump was
NOT saved to disk and reaches this doc only as the verbatim stack quoted in the factory
section below), the factory and fetcher logs (the factory log is
`/home/bg/dev/indicagent-186-26/logs/backfill_feature_factory.log`, the pinned tree's own copy;
the main checkout has an unrelated same-named 1d log), and `feature_vectors_v2` counts.
Read-only: no code landed against either site; both are in live import closures (the fetcher
is the owner's P0 unit, the factory runs the pinned rebuild). Fixes land in a stop window
after this is reviewed (todo 538).

## The family, one sentence each

- **Fetcher (todo 538, real and reproducible):** the main task awaits an IBKR-API future that
  never resolves while the gateway TCP connection stays ESTABLISHED; the loop is alive, the
  await is protocol-level, and the run idles at zero CPU until killed.
- **Factory (186-26 stage 2, reclassified, not a wedge):** the main process parks in
  `result()` between group writes, gaps from 17 minutes up to about 91, by design. The 2026-10-31 21:20Z
  "wedge" was a healthy run killed 18 minutes into a normal gap, on health signals that do not
  apply to a group-batched rebuild.

## Factory: what actually happened (all times UTC)

The 13:45Z stage 2 launch (1,252 names, 8 workers, MemoryMax 14G) was healthy all day:

- 252 `unit_loaded` events between 15:43Z and 21:02Z (84 names x 5m/15m/1h), whose row counts
  sum to exactly what `feature_vectors_v2` holds now (27,003,853 / 9,126,474 / 2,448,550).
  The morning 12:06Z run wrote 0 units before the connection-death kill, so every current
  intraday row is from this run.
- Inter-burst compute gaps of 1005s, 5483s (91 min), 4982s (83 min) and 3130s (52 min): the
  main waits in `result()` while 8 workers compute the next group; `_write_group` writes only
  when a whole group's units finish. Main-in-`result()` with zero main CPU is the designed
  idle, not a hang.
- The 21:20Z dump (relayed verbatim by indicagent-9f; the raw dump was not saved) shows a
  healthy pool shape:
  `MainThread: wait (threading.py:369) <- result (concurrent/futures/_base.py:445) <-
  _write_group (backfill_feature_factory.py:1473) <- run_rebuild_stage (:1695) <- main (:1856)`,
  and `Thread-1 (executor management thread): select (selectors.py:398) <- wait
  (multiprocessing/connection.py:1187) <- wait_result_broken_or_wakeup
  (concurrent/futures/process.py:416)`. A dead pool would EOF its worker sentinels and fail
  the futures with BrokenProcessPool instead of hanging; direct children were only the
  resource tracker and the forkserver. Worker liveness under the forkserver was not enumerated
  before the kill; that is the one missing measurement, and it changes nothing above because
  the cadence was normal.
- The run was stopped at 21:20Z, 18 minutes after its last write. That kill was a mistake
  driven by three misread signals, recorded here as such: "workers busy" claimed from main-pid
  children (Python 3.14 pools parent workers to the forkserver), "silent since relaunch" read
  from the wrong log and without the group-cadence baseline, and "zero rows written" from a
  snapshot taken after the writes had already landed.
- One real anomaly remains open: the killed unit's `memory.peak` sat exactly at the MemoryMax
  14G cap with 645 `memory.events` max hits and `oom_kill 0`. One-shot caveat: these were read
  from the transient unit `feature-rebuild-intraday.service`'s cgroup shortly before the stop,
  and `memory.peak` resets at cgroup teardown, so the numbers are not re-checkable; the
  protocol below re-reads them per run. Groups completed under the cap all day, so it is not
  proven harmful, but it is the standing risk: a 5m group whose workers plus main overflow the
  cap thrashes in direct reclaim, and that would look like ever-lengthening gaps ending in a
  genuine stuck-workers hang.

### Factory health protocol (supersedes process-presence checks)

1. Anchor on writes: `feature_vectors_v2` row counts and distinct symbols advancing, or fresh
   `unit_loaded`/`bulk_load_complete` events in the pinned tree's
   `logs/backfill_feature_factory.log`. State the evidence in the report.
2. Worker liveness: enumerate children of the FORKSERVER pid (main's direct children are only
   the resource tracker and the forkserver on Python 3.14), with per-worker CPU.
3. Cadence baseline: inter-group gaps up to about 91 minutes are healthy; a wedge claim needs
   roughly 2.5 hours without a write (about 1.7x the longest observed gap) with the unit
   active, or worker CPU collapse.
4. Read the cgroup: `memory.current`, `memory.peak`, `memory.events` for the unit. Peak pinned
   at MemoryMax with collapsed worker CPU is the real stall signature; peak alone is not.
5. py-spy the workers (not just the main) before stopping anything on a genuine criterion.

## Fetcher: the wedge mechanism

Facts from the 2026-10-31 occurrence (dump at 21:35Z, pid 1710629, run started 21:25:32Z):

- Healthy runs log `batch_computer.pool_open` within 0-6s of `fetcher_lock.acquired`. This run
  logged nothing after the acquire: about 10 minutes of silence at the first dump (21:35Z), 17
  or so by the second (21:45Z). Honest corollary: the diagnosis's own earlier 10-minute
  watchdog bound would have fired before the first dump was taken, which is why the proposed
  abort bound is 30 minutes with pacing counted as progress.
- The event loop is ALIVE: epoll wait with a 144.25s timeout, 14 timer handles scheduled, the
  outer task (`run_until_complete`'s Task) unresolved. This is not CPU starvation and not a
  dead loop.
- The gateway TCP socket is ESTABLISHED (fd 18, 127.0.0.1:56292 -> 7497). This is loopback: no
  packet loss, no half-open transport. The connection is up and the gateway is not talking.
- No `Disconnected` event, no error, lock held.
- Other threads are idle by design (OTel readers, one asyncio executor worker).

Comparison dumps 5 minutes apart (21:35Z and 21:45Z): sched_count stays 14 and the epoll
timeout ADVANCES (144.25s to 146.76s), so the same timer set re-arms on a recurring cycle
while the outer task never resolves. The loop is not frozen; it idles on its own period. The
pacing-wait logging from a23af3551 does not fire, so whatever sleeps there bypasses that
path. Correction to the run-shape reading: `batch_computer.pool_open` fired 0.1s BEFORE the
lock acquire (they co-occur at 21:25:32Z), so the wedge sits after pool_open, in planning,
connect or the first request; the fetcher's own sleeps (inter_item_pause_s 2.0,
hist_pacing_wait_release_s 60.0) are not the ~145s sleeper, and its timeout drifts upward, so
it is not a fixed retry period either. Naming it needs the timer's callback: the next dump
should capture the `_run_once` frame's TimerHandle `_callback` and `_when` (py-spy locals
one frame deeper), which identifies the sleeper directly.

So the awaited future resolves only when an IBKR API message arrives, and none arrives. On
loopback that means the gateway process is alive enough to hold TCP but its API session never
answers and never errors. The log rules out one candidate for THIS occurrence: between the
21:25:32Z acquire and the silence the gateway completed full logon and sync (server version
178, all data farms OK, API connection ready, position and portfolio sync, Synchronization
complete, IBKR connected), so the session was fully quiesced, not mid-handshake. Remaining
candidates: a gateway session that wedges after a clean quiesce (internal gateway deadlock),
or a dropped callback resolution inside ib_async. The next occurrence should record whether
the gateway log also went quiet at the same instant. The earlier teardown variants
(plan 16, twice; the 08:14 EDT and 11:17 EDT runs) and today's mid-run variants (16:50Z run:
pool_open events to 17:07Z then silence, 7s CPU over 4.5h; the 15:17Z run that recovered after
3617s) are the same shape with different durations: an await with no timeout, sometimes
rescued by an external stimulus (a gateway restart delivers the message that resolves it).

The load correlation is downgraded but not dead: the obvious shared-resource path is the
gateway container itself. A JVM under host memory pressure (29G host, 21G in use during the
rebuild) can stall long enough to look exactly like this, and a gateway that answers nobody
convicts it where a gateway that answers a fresh probe exonerates it. The discriminator test
for the next occurrence, in order: (1) open a second plain ib_async connection with a fresh
clientId (<= 50 per the gotchas) and issue a cheap request; (2) read the ib-gateway container's
memory/CPU from docker. A prompt answer on the probe while the fetcher stays stuck convicts
the fetcher-side await (dropped callback); silence on both convicts the gateway session.

### Instrumentation to land (the fix direction, todo 538)

Proposed APR values for the owner surface (initial estimates, not ML targets):
`infra.ibkr.stall_tick_s` 60 (watchdog tick), `infra.ibkr.stall_abort_s` 1800 (abort; a legal
pacing stall is minutes and is logged by a23af3551's pacing line, which the watchdog counts
as progress), `infra.ibkr.request_timeout_s` 300 (per-request bound; typical answers are
seconds, the teardown hang is forever).

1. **Post-acquire watchdog:** a task started at `fetcher_lock.acquired` that every
   `stall_tick_s` logs, while no item completed since its last tick, all pending asyncio tasks
   with their coroutines (`asyncio.all_tasks()`, `task.get_stack()`); after `stall_abort_s` of
   no progress it aborts the run loudly (nonzero exit; systemd restarts, the lock frees, the
   534 lane resumes). The progress signal is item completions OR an open pacing wait: a
   documented-healthy pacing cluster (the limiter is 58 requests per 10 minutes, and a run
   once sat 3617s and recovered) must never trip the abort, so any open
   `hist_pacing_wait_release` window suppresses it. This names the unresolved await directly
   on the very next occurrence, and turns every future wedge into a bounded loss instead of
   hours.
2. **Teardown timeout:** the whole disconnect sequence wrapped in `asyncio.wait_for` (30s) so
   a lost-gateway teardown exits nonzero with a logged cause instead of parking in `select`
   (the todo's original acceptance criterion).
3. **Per-request timeout:** each IBKR history request wrapped in `wait_for` with its own APR
   bound, so one dead session fails one leaf, not the run.
4. The pacing-wait logging from a23af3551 stays; the watchdog complements it (pacing covers
   "IBKR is throttling us", the watchdog covers "IBKR never answers").
5. Regression tests: a teardown with an unresolved future exits within the bound; a request
   future that never resolves trips the watchdog and the pending-task dump reaches the log.

## Decision requests

- Owner sign-off on the watchdog bound and the per-request timeout value (APR seeds) before
  the fetcher edit window (both `ohlcv_history_fetcher.py` and `ibkr.py` sit in the live
  import closure of the running fetcher and rebuild).
- Stage 2 capacity: if the current run pins `memory.current` at the 14G cap again while
  workers stay busy, cut workers 8 to 6 or raise MemoryMax at the next gap; measured worker
  peak RSS for a 5m group is the number that decides.
