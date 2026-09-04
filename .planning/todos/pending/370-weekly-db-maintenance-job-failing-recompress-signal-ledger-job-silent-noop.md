---
status: pending
priority: P1
filed: 2026-09-04
updated: 2026-09-04
source: docs/reference/ refresh pass, batch 3 (db-maintenance.md) — surfaced as a side finding, not a documentation issue itself
---

# Two scheduled TimescaleDB jobs are broken against the live v3.0 schema — `weekly_db_maintenance` fails every run, `recompress_signal_ledger` silently no-ops

## What

Two `timescaledb_information.jobs` procedures target objects that no longer exist in their
pre-v3.0 shape. Both verified live via `timescaledb_information.job_stats`/`job_errors` and
`pg_get_functiondef()`, not assumed from the docs.

### Job 1020, `weekly_db_maintenance` — fails every run, 1243/1243 failures

```sql
CREATE OR REPLACE PROCEDURE public.weekly_db_maintenance(IN job_id integer, IN config jsonb)
LANGUAGE plpgsql AS $procedure$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY signal_stats_daily;
  ANALYZE intelligence_features;
  ANALYZE signal_ledger;
  ANALYZE llm_calls;
  ANALYZE market_data_ohlcv;
  ANALYZE signal_features;
  ANALYZE drift_monitor;
  ANALYZE signal_performance_segmented;
  ANALYZE setup_performance;
  PERFORM pg_stat_statements_reset();
  RAISE NOTICE 'Weekly maintenance complete at %', now();
END;
$procedure$
```

`timescaledb_information.job_stats` confirms `total_runs=1243, total_successes=0,
total_failures=1243, last_run_status='Failed'` (weekly schedule, so this has been failing since
close to when the job was first scheduled — roughly 24 years' worth of weekly attempts,
suggesting this job's `total_runs` count includes retries/backoff, not literally 1243 distinct
weeks, but the point stands: it has never once succeeded).

Root cause, confirmed by checking each referenced object's existence
(`pg_class.relname`/`relkind`): the **first statement fails outright** —
`signal_stats_daily` does not exist anywhere in the schema (no matching `pg_class` row at all,
materialized or otherwise), so `REFRESH MATERIALIZED VIEW CONCURRENTLY signal_stats_daily`
errors immediately and the procedure aborts before any later statement runs. Independently,
even if that were fixed, three more statements would fail: `signal_features` and
`signal_performance_segmented` also don't exist anywhere in the schema, and `signal_ledger` is
now a plain `VIEW` (`relkind='v'`, renamed from `signal_ledger_full` in Phase 130 per
`docs/foundation/canonical-truth-registry.md`) — `ANALYZE` on a view is not a valid target for
maintenance in this form (this project doesn't `ANALYZE` views; the underlying tables it joins
are what carry statistics).

### Job 1021, `recompress_signal_ledger` — reports Success every run but silently does nothing

```sql
CREATE OR REPLACE PROCEDURE public.recompress_signal_ledger(IN job_id integer, IN config jsonb)
LANGUAGE plpgsql AS $procedure$
DECLARE
  chunk_row record;
BEGIN
  FOR chunk_row IN
    SELECT chunk_schema, chunk_name
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'signal_ledger'
      AND is_compressed = true
      AND range_end < NOW() - INTERVAL '1 day'
  LOOP
    CALL recompress_chunk(format('%I.%I', chunk_row.chunk_schema, chunk_row.chunk_name)::regclass);
  END LOOP;
END;
$procedure$
```

`job_stats` shows `total_runs=96, total_successes=96, total_failures=0,
last_run_status='Success'` — looks completely healthy. It isn't: `signal_ledger` is a view, not
a hypertable (see above), so `WHERE hypertable_name = 'signal_ledger'` never matches any row in
`timescaledb_information.chunks`, the `FOR` loop body never executes, and the procedure
"succeeds" having recompressed zero chunks, every single run, since whenever `signal_ledger`
stopped being a hypertable. This is exactly the silent-success failure mode CLAUDE.md's design
mindset calls out as worse than a loud crash — job 1020 at least reports failure; this one
doesn't.

## Impact

- Job 1020: weekly planner-statistics refresh and `pg_stat_statements` reset have not run
  successfully, ever, against the current schema. Stale planner stats on `market_data_ohlcv`,
  `llm_calls`, `setup_performance`, `intelligence_features`, `drift_monitor` are a plausible
  (unverified) contributor to slow-query surprises — worth keeping in mind if another
  `docs/foundation/performance-investigation-sop.md`-shaped investigation turns up an
  unexplained plan regression on one of these tables.
- Job 1021: whatever compression-maintenance role this job was meant to serve for the
  archived-but-still-real `signal_ledger`-backed hypertables (its underlying `signal_events`/
  `trade_frames`/`trade_executions` tables) has not actually run in a long time, silently.

Neither job threatens live data integrity today (1020 does read-only maintenance work and
fails cleanly; 1021 no-ops harmlessly) — this is a hygiene/observability gap, not an active
incident.

## Fix options (decision needed, not made here)

1. **Retire both jobs** if the v2.x-era objects they maintain (`signal_stats_daily`,
   `signal_features`, `signal_performance_segmented`, and `signal_ledger`'s underlying
   hypertables) are archived and no longer need this maintenance cadence —
   `SELECT delete_job(1020); SELECT delete_job(1021);`.
2. **Rewrite both** against the live v3.0 table set (`feature_vectors`, `forward_returns`,
   `feature_ic_scores`, `alpha_frames`, `alpha_events`, per
   `docs/foundation/timescaledb-compressed-column-migration.md`'s live-table list) if periodic
   `ANALYZE`/recompress maintenance on those tables is actually wanted and not already covered
   by TimescaleDB's own compression policies (`docs/reference/gotchas.md`'s Database section
   already documents that a compression *policy* job can silently compress zero chunks too —
   worth checking those aren't in the same state before assuming a manual recompress job is
   still needed at all).

Whoever picks this up should check TimescaleDB's built-in compression policies on the live
v3.0 hypertables first (`SELECT * FROM timescaledb_information.jobs WHERE proc_name =
'policy_compression'`) before deciding option 2 is even necessary — it may be that automatic
compression already covers what job 1021 was trying to do manually.

## Verification

- `timescaledb_information.job_stats` / `jobs` joined on `job_id IN (1020, 1021)`, live query,
  2026-09-04.
- `pg_get_functiondef(p.oid)` for both `weekly_db_maintenance` and `recompress_signal_ledger`
  procedures, live query, 2026-09-04.
- `pg_class.relname`/`relkind` check confirming `signal_stats_daily`, `signal_features`,
  `signal_performance_segmented` don't exist and `signal_ledger` is `relkind='v'`.
