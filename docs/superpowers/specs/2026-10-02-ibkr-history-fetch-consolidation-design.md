# IBKR history fetch consolidation: one fetcher, one ledger, one queue

Status: approved design, pre-plan
Author: Claude (session 2026-10-02), reviewed and approved by Brandon

## Problem

Today, four independent things decide when and what to fetch from IBKR history, and
negotiate access to the single allowed IBKR history connection only via a two-tier DB
lease (`src/core/resource_lease.py`, `ibkr_history_stream`):

- `indicagent-nightly-backfill.timer` -> `infrastructure_nightly_backfill.py` (priority tier)
- `logs/backfill_ops/intraday_chain.sh` -> `intraday_htf_lane.sh` / `intraday_5m_lane.sh`
  (bulk tier), each with its own bash retry loop, stall watchdog, and git-tracked
  symbol-list text file
- `ops_d1_bootstrap.py`, `ops_venue_study.py` (manual debug tools, also take the lease)
- `infrastructure_run_historical_pipeline.py`'s own `_reorder_contracts_by_gap`, which
  scores "what needs fetching" against `ohlcv_intraday_raw_archive` depth, not the
  depth actually visible in `market_data_ohlcv_tradeable` -- so a fully-backfilled
  symbol (e.g. BBY, 130k+ rows of 15m history) can score identically to a genuinely
  empty symbol and win an alphabetical tie-break, fetching already-complete data first.

Incident, 2026-10-02: the nightly job silently hung (`reqHistoricalDataAsync` has no
per-request timeout -- confirmed as todo 488, filed independently the same day) and
held the priority lease for hours. The bulk-tier HTF lane (the todo-449 campaign
backfilling 698 names' 15m/1h/5m history) was correctly, but uselessly, starved behind
it the whole time -- lease arbitration worked exactly as designed and still produced a
multi-hour stall with zero bars written, because the thing being arbitrated for was
broken, not just slow.

Separately, the lane that *was* writing data was storing to
`ohlcv_intraday_raw_archive`, not the `market_data_ohlcv` grid table research actually
reads -- the promotion between them lags, silently, with no lag metric. A coverage
check against the grid table alone (`market_data_ohlcv_tradeable`) can therefore be
wrong: HPQ showed 0 rows in the grid view while holding 35k+ rows in the archive.

None of this is a pacing problem. IBKR's single-stream, rate-limited constraint is real
and not going away. The actual defect is architectural: multiple independent processes
each decide what they need and negotiate for a shared resource after the fact, instead
of one process deciding, correctly, up front.

## Goal

Exactly one process ever opens an IBKR history connection. It is timeframe- and
dimension-agnostic (1d, 1h, 15m, 5m, 1m, futures-roll-aware -- all are just arguments,
the way `infrastructure_run_historical_pipeline.py` already works today), reads a
single ground-truth coverage ledger to decide what to fetch next, and writes that
ledger atomically with the bars it fetches so the ledger can never drift from what is
actually stored.

Not in scope: a provider abstraction for a hypothetical second OHLCV vendor (YAGNI --
there is no second OHLCV provider today, and IBKR's single-connection/rate-limit
constraints are not representative of what a future REST-based vendor would need
anyway). The fetcher stays IBKR-specific and stays strictly behind the existing
`src/providers/ibkr.py` boundary (the only file allowed to import `ib_async`).

Not in scope: an always-on daemon. This is bursty batch work, not a stream; the
existing `BaseBatch` oneshot pattern (`bar_derivation.py`, `forward_return_writer.py`,
`ic_engine.py`) already fits it exactly, including the lighter D-06
`job_completed_total{job,status}` contract instead of `BaseDaemon`'s 5-signal contract
meant for continuously-running services.

Not in scope: Kafka as a hop between fetch and persistence. That pattern exists in this
codebase for the live streaming path, where compute and persistence are genuinely
separate concurrent daemons. A oneshot batch job has no concurrent consumer to decouple
from -- adding a topic here would be unjustified complexity with no payoff.

## Design

### Ground truth: `ohlcv_coverage` (migration 430)

```sql
CREATE TABLE ohlcv_coverage (
    symbol              text NOT NULL,
    timeframe           text NOT NULL,
    earliest_timestamp  timestamptz,
    latest_timestamp    timestamptz,
    row_count           bigint NOT NULL DEFAULT 0,
    last_fetched_at     timestamptz,
    last_fetch_status   text,               -- 'ok' | 'no_data' | 'error'
    consecutive_failures integer NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, timeframe)
);
```

This is **not** a second source of truth competing with `ohlcv_request` (the existing,
correct, per-window answered-request log read by `_request_coverage.py`) or with the
bar tables themselves. It is a materialized rollup, written by exactly one place,
purely so prioritization is an O(1) read instead of a full-table scan per symbol per
run -- todo 387 measured the current full-window `detect_gaps()` scan at ~500ms per
symbol against a 20-year window, independent of the IBKR rate limiter, and that cost
scales with universe size (233 and growing) every single night.

The row for a symbol/timeframe can never exist without the bars it describes, because
it is written in the *same transaction* as the bar insert and the request-log insert,
reusing `_intraday_persist.py`'s existing atomic pattern (`SET LOCAL ROLE` per writer,
one top-level transaction) with a third write added to it:

```
BEGIN
  SET LOCAL ROLE ohlcv_observation_writer   -- existing: ohlcv_request rows
  write_request_rows(...)
  SET LOCAL ROLE bar_derivation_writer      -- existing: archive/grid rows
  write_archive_rows(...)
  SET LOCAL ROLE bar_derivation_writer      -- new: coverage rollup
  upsert_coverage(...)
COMMIT
```

A legitimate `no_data` answer (venue-boundary cases like TLT/AMD/PEP, already handled
correctly by `_request_coverage.py`) updates `last_fetch_status='no_data'` and must
**never** increment `consecutive_failures` -- that counter is reserved for genuine
failures (timeout, connection drop), not correct empty results.

### Priority function

Pure, deterministic, reads only `ohlcv_coverage` + APR config -- no live IBKR calls
needed to rank:

```
rank(symbol, timeframe) = (
    consecutive_failures > infra.backfill.max_consecutive_failures,  -- excluded, lowest
    staleness_days <= infra.backfill.max_staleness_days_before_preempt,  -- SLA band first
    -1 if timeframe in priority_tf_order else 0,   -- 15m/1h before 5m (todo 449, owner decision)
    -coverage_gap_days,                             -- zero/largest gap first
    -staleness_days,                                -- nightly freshness falls out of this
    symbol                                           -- deterministic tie-break
)
```

`coverage_gap_days` keeps the correct insight from the existing
`_reorder_contracts_by_gap` (each symbol's own proven depth, via its deepest TF or 1d
history, stands in as the ceiling -- so a young ETF's real inception wall doesn't look
like a fetchable gap) but reads it from `ohlcv_coverage`, not from a raw scan of
`ohlcv_intraday_raw_archive` alone, so it can no longer disagree with what the grid
table shows.

The SLA band exists specifically so a permanent bulk-priority policy cannot silently
starve nightly freshness indefinitely once the active backlog clears -- without it, a
single newly-onboarded zero-coverage symbol could again block freshness updates for
900+ other names for hours, with nothing surfacing it. `max_staleness_days_before_preempt`
is APR-backed (`infra.*` namespace, same pattern as existing `alert.lag.*` thresholds).

### End-to-end flow

One process, one direction, no inter-process hop:

```
pg_try_advisory_lock(fetcher_lock_key)   -- fail fast if already held, exit 0
  -> loop:
       next = PriorityQueue.next(pool)   -- reads ohlcv_coverage, pure ranking
       if none left or budget exhausted: break
       fetch via src/providers/ibkr.py, asyncio.wait_for(timeout=infra.ibkr.history_request_timeout)
         on timeout: reconnect, retry up to infra.ibkr.history_request_retries, else
           record failure, continue to next item (never block the run on one name)
       atomic transaction (_intraday_persist.py, extended):
         write_request_rows -> write_archive_rows -> upsert_coverage
       if dimension requires grid promotion: promote in the same pass
  -> job_completed_total{job="ibkr-history-fetcher", status=...}, exit
pg_advisory_unlock
```

`ops_d1_bootstrap.py` and `ops_venue_study.py` (manual debug tools that also take an
IBKR history lease today) switch to the same `pg_try_advisory_lock` key instead of the
old tiered `ResourceLease`, so they correctly refuse to run while the fetcher holds the
connection instead of silently contending with it. `resource_lease.py`'s generic
`ResourceLease`/`Tier` mechanism is not deleted -- it is a reusable primitive -- only
this one key's usage is retired.

Futures roll-awareness and the 1d dimension need no special-casing: they are additional
`(symbol, timeframe)` rows through the same ledger and the same priority function.
`get_active_contracts(dimension=...)` selection carries over unchanged.

### Failure handling

- Every IBKR history call is wrapped in `asyncio.wait_for` (todo 488's root-cause fix
  for the 2026-10-02 incident: `reqHistoricalDataAsync` has no timeout today, so a
  dropped socket wedges the process in `select` forever).
- Timeout -> disconnect/reconnect the IBKR client, bounded retry, then record and move
  on. The pipeline already does not block indefinitely on one name (D-05); this closes
  the one path that let it.
- Gateway down at startup: fail fast, `job_completed_total{status="failure"}`, exit --
  the systemd timer's next scheduled fire is the retry. No bash polling loop.
- `consecutive_failures` beyond `infra.backfill.max_consecutive_failures` excludes a
  symbol/TF from ranking entirely (replaces todo 484's proposed separate
  `quarantined.symbols` file with one column on the ledger that is already being
  written anyway).

## Cutover plan

1. Migration 430: `ohlcv_coverage`, backfilled once from existing `ohlcv_request` +
   archive + `market_data_ohlcv` state so the ledger starts accurate, not from a false
   "everything is zero coverage" bootstrap.
2. Build `scripts/infrastructure/backfill/ibkr_history_fetcher.py` (absorbs
   `infrastructure_run_historical_pipeline.py` entirely -- all dimensions, all
   timeframes, parameterized exactly as today via `--timeframes`/`--dimension`, not
   split into per-timeframe scripts).
3. Dry-run the new ranking against current state (read-only, no IBKR calls) and compare
   against today's fetch order before it is allowed to touch IBKR.
4. Cutover at a clean stop point: disable `indicagent-nightly-backfill.timer`, stop the
   lane chain, point a new systemd timer at the fetcher.
5. Delete: `infrastructure_nightly_backfill.py`, `intraday_htf_lane.sh`,
   `intraday_5m_lane.sh`, `intraday_chain.sh` and their git-tracked symbol-list files,
   `_reorder_contracts_by_gap`, the `ibkr_history_stream` lease usage (keep
   `resource_lease.py` itself), stale tests (`test_resource_lease.py`'s lease-specific
   cases, `test_nightly_lease.py`, `test_grid_lane_guard.py`). Update
   `ops_d1_bootstrap.py` / `ops_venue_study.py` to the shared lock key.
6. Close pending todos against the new implementation, not just reference them:
   - 488 (nightly hang / no request timeout) -- fixed by the bounded-call requirement.
   - 452 (lane-script convergence) -- superseded; the lane scripts are deleted, not
     converged into a shared lib.
   - 387 (gap-detection cost / staleness observability) -- fixed by the ledger
     replacing full-table scans, and staleness is now a first-class ranking input.
   - 455 (drop 1m from nightly defaults) -- folded into the new default-timeframe set.
   - 484 (HTF lane quarantine file) -- superseded by `consecutive_failures` column.
7. Update `CLAUDE.md`'s historical-backfill section and
   `docs/operations/operations-database.md` to describe the new single fetcher instead
   of the lease/lane system.

## Testing

- `PriorityQueue.rank()`: pure function, unit-testable against fixture `ohlcv_coverage`
  rows with no DB -- SLA-preemption ordering, tf-class ordering, failure-threshold
  exclusion, deterministic tie-break, and that a `no_data` answer never increments
  `consecutive_failures`.
- One integration test against a real test DB for the atomic three-way write
  (request + archive + coverage): all three commit together; a forced failure mid
  transaction leaves none of them committed. This is the property the whole design
  depends on and gets an explicit test, not inferred coverage.
- Singleton lock test: two concurrent invocations, the second exits immediately without
  touching IBKR.
- Retire `test_resource_lease.py`'s lease-specific cases, `test_nightly_lease.py`,
  `test_grid_lane_guard.py` in the same commit that deletes the code they test.
- CI-clean per repo convention. No `repro_frozen.py` determinism check applies (not
  `src/intelligence/research` or `statistics`).
