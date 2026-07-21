# 161: counterfactual_tracker per-row UPDATE throughput is ~28-84 rows/sec -- full corpus is multi-day

**Filed:** 2026-07-21, investigating why 143.1-08's backfill made zero progress across 3 attempts (~18h cumulative).

## Context

Two real bugs were found and fixed in `services/counterfactual_tracker.py` (commits on
`worktree-agent-acc3e6a78746c2514`):

1. `_execute_inner` used `ProcessPoolExecutor.map(..., chunksize=1)`, which yields results in
   submission order, not completion order. A slow head-of-line symbol/tf partition stalled
   every later-ordered symbol's flush even after that worker finished computing -- and because
   nothing ever committed, every restart re-scanned every symbol from scratch. Fixed with
   `as_completed()` over submitted futures.
2. `_flush_worker_results` passed one symbol's *entire* result set (BTAL alone: 89,781 rows) to
   a single `executemany()` call. asyncpg wraps that whole call in one implicit transaction, so
   nothing committed until the entire symbol finished -- measured live, BTAL's transaction was
   still open past 8 minutes with zero rows visible. Fixed by chunking to
   `infra.counterfactual_tracker.chunk_size` (APR, migration 240, default 5000), committing
   each chunk separately.

Both fixes are correct and necessary, but after applying both and restarting, the process was
STILL making effectively no visible progress. Direct benchmarking (bypassing the worker pool
entirely, isolated to one `asyncpg` connection) found the real cause: the per-row UPDATE
against `alpha_frames` is fundamentally slow, independent of batching strategy.

## Measurements (2026-07-21, live, `RSP` symbol's open frames)

- Naive `executemany()`, 2000 rows, single UPDATE column (`measured_at` only): **28.3 rows/sec**
- Set-based bulk UPDATE via `UNNEST($1::text[], $2::timestamptz[], ...)` + `FROM (...) v`
  join, one round trip for all 2000 rows: **83.7 rows/sec** -- only ~3x, not the 100-1000x a
  genuine round-trip-bound workload would show.
- `EXPLAIN (ANALYZE, BUFFERS)` on a single-row UPDATE: **Execution Time: 0.86ms**, actual
  index scan hits only 3 buffers. Planning was 265ms but that's a cold/uncached artifact of a
  fresh `psql` session re-planning from scratch -- asyncpg's `executemany()` reuses one
  prepared plan across the whole batch, so this isn't the live bottleneck.

Since single-row execution is sub-millisecond and bulk UNNEST barely helps, the bottleneck is
neither statement planning nor round-trip count. Leading hypothesis, NOT yet confirmed: poor
buffer-cache locality. `alpha_frames` has **1034 chunks** (`bar_ts` chunk_time_interval =
7 days) spanning 2006-2026; one symbol's full-history closed-frame set is scattered across
potentially hundreds of those chunks (each a physically separate table+index on disk), so
consecutive rows in a batch essentially never hit an already-warm page -- i.e. this may be a
genuine disk-I/O-bound workload dressed up as a "slow UPDATE."

At the measured 28-84 rows/sec ceiling, the full 23.16M-row open-frame backlog
(`143.1-08-challenger` + `143.1-08-champion`) is **~76-227 hours (3.2-9.5 days)** even with
both bugs above fixed. That's why 3 backfill attempts spanning ~18h never got anywhere close
to done, quite apart from the zero-commit bug.

## What this needs (not done here -- stopped to avoid more live guessing against production data)

- Confirm/refute the chunk-locality hypothesis: `iostat`/`pg_stat_io` during a real run: is
  this CPU-bound, lock-bound, or genuinely disk-read-bound?
- If confirmed, options to evaluate: (a) larger `chunk_time_interval` for `alpha_frames` going
  forward (doesn't help the already-created 1034 chunks), (b) process symbols/tfs in
  `bar_ts`-sorted write order so a batch touches fewer chunks at a time, (c) drop
  `alpha_frames_status_open_idx` (the partial index) during the bulk backfill and rebuild after
  (removes per-UPDATE index-maintenance cost, though the benchmark above didn't touch `status`
  so this wasn't isolated), (d) accept the cost and just budget multiple days for one full
  backfill run, since this is a one-time historical catch-up, not a recurring cadence (D-09,
  no recurring ensemble_ic_engine cadence is in scope per the file's own docstring).
- Whichever fix is chosen, re-run the same live-measured-throughput benchmark script pattern
  used here (`/tmp/.../bench_update.py`, `/tmp/.../bench_unnest.py` -- not preserved, scratch)
  before declaring it fixed; don't assume from theory alone given how small the UNNEST win was.

## Status

Process is currently STOPPED (not running). The two correctness fixes are committed and safe
to keep. Do not restart the backfill expecting it to finish in a reasonable time until this
throughput question is resolved -- it will "work" (make real, committed progress) but at a pace
that won't clear the corpus for days.
