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

## RESOLVED 2026-07-21

Chunk-locality/disk-I/O hypothesis was REFUTED, not confirmed. `iostat -x 1` during a live
1500-row UPDATE burst showed the NVMe drive under 3% util the whole time, and
`pg_stat_activity.wait_event_type`/`wait_event` were EMPTY throughout with `state='active'` --
the backend was on-CPU the entire time, not waiting on I/O or locks. This ruled out disk
entirely and pointed at the hypertable abstraction itself.

Isolating test (systematic-debugging Phase 3, minimal single-variable change): identical 599
rows, identical connection, only the target table changed.

- `UPDATE alpha_frames ...` (through the hypertable): **29.1 rows/sec**
- `UPDATE _timescaledb_internal._hyper_94_67200_chunk ...` (direct to the underlying chunk
  table the rows actually live in): **10,423.5 rows/sec** -- **358x**

Root cause: TimescaleDB's per-execution chunk-routing/exclusion overhead against
`alpha_frames`' 1034 chunks, paid on every single parameterized execution regardless of
asyncpg's prepared-statement reuse across an `executemany()` batch. Not disk I/O (confirmed
via iostat), not raw row-update cost (a single `EXPLAIN ANALYZE` showed 0.86ms execution),
not commit/fsync frequency (the earlier chunked-commit fix already ruled that shape out).

**Fix shipped:** `services/counterfactual_tracker.py` now loads `alpha_frames`' chunk range
table once per run (`_load_chunk_index`, one query against
`timescaledb_information.chunks`), resolves each row's `bar_ts` to its schema-qualified chunk
table via binary search (`_route_chunk`), and `_flush_worker_results` groups each symbol's
rows by resolved chunk, issuing UPDATEs directly against
`_timescaledb_internal.<chunk>` instead of through the hypertable. A row whose `bar_ts`
resolves to no known chunk falls back to writing through `alpha_frames` rather than being
dropped, reported once as an aggregate count (never per-row). Only `chunk_schema`/`chunk_name`
values matching TimescaleDB's own internal naming convention are trusted for SQL
interpolation (table names can't be bound as query parameters) -- covered by a regression
test using a deliberately malicious `chunk_name` to prove the filter holds.

**Live end-to-end verification** (real production functions, not mocks; a symbol untouched
by any prior benchmark): 1500 rows in 0.232s = **6,472.5 rows/sec**. Full 23.16M-row
143.1-08 backlog: was 3.2-9.5 days, now under 2 hours.

## Status

Fix committed. Backfill restarting for real with all three fixes in place (ordering,
chunked-commit visibility, direct-chunk write routing).
