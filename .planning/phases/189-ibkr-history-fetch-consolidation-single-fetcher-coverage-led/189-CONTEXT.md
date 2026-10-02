# Phase 189: IBKR history fetch consolidation - Context

**Gathered:** 2026-10-02
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md), itself produced via superpowers:brainstorming (architectural path) with the user over the same session, approved section by section.

<domain>
## Phase Boundary

Replace today's four independent IBKR-history-fetch actors (nightly timer script, bulk
HTF/5m lane bash scripts + chain + watchdogs, two manual ops debug tools) and their
two-tier DB lease arbitration with exactly one timeframe- and dimension-agnostic
oneshot fetcher, a single `ohlcv_coverage` ground-truth ledger, and a deterministic
priority queue. Covers all timeframes (1d, 1h, 15m, 5m, 1m) and all dimensions
(backfill, compute_1d, futures roll-aware) via the same `--timeframes`/`--dimension`
argument surface `infrastructure_run_historical_pipeline.py` already exposes -- no
per-timeframe scripts.

Trigger incident: 2026-10-02, the nightly backfill silently hung (no per-request IBKR
timeout) and held the priority lease for hours while the bulk-tier todo-449 intraday
campaign (698 names needing 15m/1h/5m) starved behind it, correctly per the lease
design, uselessly in practice. Separately, the bulk lane's writes landed in
`ohlcv_intraday_raw_archive` while coverage checks read `market_data_ohlcv_tradeable`,
so the two disagreed (HPQ: 35k+ archive rows, 0 grid rows) -- no single source of truth
for "do we have this data."

</domain>

<decisions>
## Implementation Decisions

### Scope
- All three problems in one phase: coordination (lease -> singleton), prioritization
  (reorder scored against the wrong table), visibility (archive/grid ledger split).
- Timeframe- and dimension-agnostic: one script, not one script per timeframe. This
  absorbs `infrastructure_run_historical_pipeline.py` entirely (1d, futures-roll,
  everything), not just the intraday campaign scripts.
- IBKR-specific, not a multi-provider abstraction (YAGNI -- no second OHLCV provider
  exists; IBKR's single-connection/rate-limit constraints are not representative of a
  hypothetical future REST vendor). Stays strictly behind the existing
  `src/providers/ibkr.py` boundary (only file allowed to import `ib_async`).
- No always-on daemon. This is bursty batch work; use the existing `BaseBatch` oneshot
  pattern (`src/core/agent/base_batch.py`, as used by `bar_derivation.py`,
  `forward_return_writer.py`, `ic_engine.py`) with the D-06 `job_completed_total`
  contract, not `BaseDaemon`'s 5-signal always-running contract.
- No Kafka hop between fetch and persistence. A oneshot batch job has no concurrent
  consumer to decouple from; writer classes are called in-process.

### Ground truth: `ohlcv_coverage` (migration 430)
- One row per `(symbol, timeframe)`: `earliest_timestamp`, `latest_timestamp`,
  `row_count`, `last_fetched_at`, `last_fetch_status` ('ok'|'no_data'|'error'),
  `consecutive_failures`.
- This is a materialized rollup, NOT a competing ground truth against `ohlcv_request`
  (the existing per-window answered-request log, `_request_coverage.py`) or the bar
  tables. It exists so prioritization is O(1) instead of a full-table scan per symbol
  per run (todo 387 measured ~500ms/symbol against a 20yr window, scaling with
  universe size).
- Written atomically in the SAME transaction as the bar insert and request-log insert,
  by extending `_intraday_persist.py`'s existing `SET LOCAL ROLE` multi-writer
  transaction pattern with a third write. The coverage row for a symbol/TF can never
  exist without the bars it describes.
- A legitimate `no_data` answer (venue-boundary cases: TLT/AMD/PEP, already handled
  correctly by `_request_coverage.py`) sets `last_fetch_status='no_data'` and must
  NEVER increment `consecutive_failures` -- that counter is reserved for genuine
  failures (timeout, connection drop) only.

### Priority function (pure, deterministic, reads only `ohlcv_coverage` + APR config)
```
rank(symbol, timeframe) = (
    consecutive_failures > infra.backfill.max_consecutive_failures,     -- excluded, lowest
    staleness_days <= infra.backfill.max_staleness_days_before_preempt, -- SLA band first
    -1 if timeframe in priority_tf_order else 0,    -- 15m/1h before 5m (todo 449, owner decision)
    -coverage_gap_days,                              -- zero/largest gap first
    -staleness_days,                                 -- nightly freshness falls out of this, no special-casing
    symbol                                            -- deterministic tie-break
)
```
- `coverage_gap_days` keeps the correct insight from the existing
  `_reorder_contracts_by_gap` (each symbol's own proven depth, via its deepest TF or 1d
  history, stands in as the ceiling -- a young ETF's inception wall doesn't look like a
  fetchable gap) but reads it from `ohlcv_coverage`, not a raw scan of
  `ohlcv_intraday_raw_archive` alone.
- The SLA band (`infra.backfill.max_staleness_days_before_preempt`, APR-backed, same
  pattern as existing `alert.lag.*` thresholds) exists specifically so a permanent
  bulk-priority policy cannot silently starve nightly freshness indefinitely once the
  active backlog clears. This was identified as a real gap during design review (strict
  lexicographic gap-first ordering with no fairness floor) and is a hard requirement,
  not optional polish.
- Nightly freshness is NOT a separate code path or timer -- a fully-backfilled symbol
  whose `latest_timestamp` is yesterday naturally has `staleness_days=1` and ranks
  accordingly through the same function.

### End-to-end flow
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

### Failure handling
- Every IBKR history call wrapped in `asyncio.wait_for` (fixes todo 488's root cause:
  `reqHistoricalDataAsync` has no timeout today, so a dropped socket wedges the process
  in `select` forever).
- Timeout -> disconnect/reconnect, bounded retry (`infra.ibkr.history_request_retries`),
  then record and move to the next queue item -- never block the run on one name.
- Gateway down at startup: fail fast, `job_completed_total{status="failure"}`, exit; the
  systemd timer's next scheduled fire is the retry. No bash polling loop.
- `consecutive_failures` beyond `infra.backfill.max_consecutive_failures` excludes a
  symbol/TF from ranking entirely (replaces todo 484's proposed separate
  `quarantined.symbols` file with a column already being written).

### Shared-lock migration for manual ops tools
- `ops_d1_bootstrap.py` and `ops_venue_study.py` (manual debug tools) currently take
  the old tiered `ResourceLease` for the same IBKR connection. They must move to the
  SAME `pg_try_advisory_lock` key the new fetcher uses (fail-fast, "fetcher is running,
  try again"), or they will silently recreate the exact contention bug one level later.
  `resource_lease.py`'s generic `ResourceLease`/`Tier` class is NOT deleted (reusable
  primitive) -- only this one key's usage is retired.

### Cutover and cleanup (explicit deletions, not deprecation)
1. Migration 430: `ohlcv_coverage`, backfilled once from existing `ohlcv_request` +
   archive + `market_data_ohlcv` state so the ledger starts accurate.
2. Build `scripts/infrastructure/backfill/ibkr_history_fetcher.py` (absorbs
   `infrastructure_run_historical_pipeline.py` entirely).
3. Dry-run the new ranking against current state (read-only, no IBKR calls) before it
   is allowed to touch IBKR.
4. Cutover at a clean stop point: disable `indicagent-nightly-backfill.timer`, stop the
   lane chain, point a new systemd timer at the fetcher.
5. DELETE: `infrastructure_nightly_backfill.py`, `intraday_htf_lane.sh`,
   `intraday_5m_lane.sh`, `intraday_chain.sh` and their git-tracked symbol-list files,
   `_reorder_contracts_by_gap`, the `ibkr_history_stream` lease usage (keep
   `resource_lease.py` itself). Retire stale tests: `test_resource_lease.py`'s
   lease-specific cases, `test_nightly_lease.py`, `test_grid_lane_guard.py`.
6. Close these pending todos against the shipped implementation (not just reference
   them): 488 (nightly hang/no request timeout -- fixed by bounded calls), 452
   (lane-script convergence -- superseded, lane scripts deleted not converged), 387
   (gap-detection cost/staleness observability -- fixed by the ledger), 455 (drop 1m
   from nightly defaults -- folded into new default-timeframe set), 484 (HTF lane
   quarantine file -- superseded by `consecutive_failures` column).
7. Update `CLAUDE.md`'s historical-backfill section and
   `docs/operations/operations-database.md` to describe the new fetcher instead of the
   lease/lane system.

### Testing
- `PriorityQueue.rank()`: pure function, unit-testable with fixture `ohlcv_coverage`
  rows, no DB -- SLA-preemption ordering, tf-class ordering, failure-threshold
  exclusion, deterministic tie-break, `no_data` never increments `consecutive_failures`.
- One integration test against a real test DB for the atomic three-way write: all three
  commit together; a forced failure mid-transaction leaves none committed. This is the
  property the whole design depends on.
- Singleton lock test: two concurrent invocations, the second exits immediately without
  touching IBKR.
- Retire the three stale lease/lane tests in the same commit that deletes the code they
  test.
- CI-clean per repo convention. No `repro_frozen.py` check applies (not
  `src/intelligence/research` or `statistics`).

### Claude's Discretion
- Exact column types/defaults for `ohlcv_coverage` beyond what's specified.
- Internal module layout within `ibkr_history_fetcher.py` (how `PriorityQueue`, the
  fetch step, and the writer extension are split into files/classes) as long as SoC is
  preserved (ranking is a pure function, I/O isolated in writer classes).
- Whether `infrastructure_run_historical_pipeline.py` is deleted outright or kept
  briefly as a thin deprecated wrapper during cutover -- default to outright deletion
  per the project's "verify then delete, don't flag" convention unless the plan finds a
  concrete reason to keep it temporarily.
- Specific initial APR default values for `infra.ibkr.history_request_timeout`,
  `infra.ibkr.history_request_retries`, `infra.backfill.max_consecutive_failures`,
  `infra.backfill.max_staleness_days_before_preempt` (todo 488 suggested ~300s for the
  timeout as an initial estimate; others are new and need a reasoned initial value,
  marked `[initial_estimate]` per APR provenance convention).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design
- `docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md` - the full approved
  design spec this context is derived from. Read in full before planning.

### Existing patterns to reuse, not reinvent
- `src/core/agent/base_batch.py` - `BaseBatch` oneshot pattern (pool lifecycle, D-06
  completion metric, span instrumentation) the new fetcher extends.
- `scripts/infrastructure/backfill/_intraday_persist.py` - the atomic multi-writer
  transaction pattern (`SET LOCAL ROLE` per writer) to extend with the coverage upsert.
- `scripts/infrastructure/backfill/_request_coverage.py` - the existing `ohlcv_request`
  answered-window tracking; `ohlcv_coverage` derives from this, does not replace it.
- `src/providers/ibkr.py` - the only file allowed to import `ib_async`; the fetcher
  calls through this boundary, never embeds IBKR API calls itself.
- `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` - current
  `_reorder_contracts_by_gap` (keep its gap-ceiling insight, fix its data source) and
  `get_active_contracts(dimension=...)` selection logic (carries over unchanged).
- `src/core/resource_lease.py` - generic `ResourceLease`/`Tier` primitive; retiring only
  the `ibkr_history_stream` key's usage, not the class.

### Pending todos this phase closes
- `.planning/todos/pending/488-nightly-backfill-hang-holds-priority-lease.md`
- `.planning/todos/deferred/452-backfill-orchestration-tooling-convergence.md`
- `.planning/todos/pending/387-nightly-backfill-detect-gaps-cost-scaling-and-staleness-observability.md`
- `.planning/todos/pending/455-drop-1m-from-nightly-backfill-defaults.md`
- `.planning/todos/pending/484-htf-lane-honor-quarantined-symbols-file.md`

### Manual ops tools needing the shared-lock migration
- `scripts/ops/bars/ops_d1_bootstrap.py`
- `scripts/ops/bars/ops_venue_study.py`

### Docs to update post-cutover
- `CLAUDE.md` (historical-backfill section, Core Runtime Files)
- `docs/operations/operations-database.md`

</canonical_refs>

<specifics>
## Specific Ideas

- Migration number: 430 (429 is the highest existing migration as of 2026-10-02).
- Active backfill context at time of filing: todo 449's campaign (698 names needing
  15m/1h/5m) is live; the new fetcher's queue should naturally absorb this backlog
  without a separate "campaign mode."

</specifics>

<deferred>
## Deferred Ideas

- Multi-provider OHLCV abstraction: explicitly rejected as premature (YAGNI) during
  design review -- no second provider exists, and IBKR's constraints are not
  representative of what one would need.
- Always-on daemon shape: explicitly rejected during design review in favor of the
  oneshot `BaseBatch` pattern -- this is bursty batch work, not a continuous stream.
- Kafka hop between fetch and persistence: explicitly rejected -- no concurrent
  consumer exists to decouple from in a oneshot job.

</deferred>

---

*Phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led*
*Context gathered: 2026-10-02 via PRD Express Path*
