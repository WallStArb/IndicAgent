<!-- generated-by: gsd-doc-writer -->
# Database Maintenance Runbook

**Version:** 3.0
**Last Updated:** 2026-09-04
**Status:** current

TimescaleDB handles most routine maintenance automatically (compression, retention). This doc covers what is automated, what requires manual intervention, and the scheduled cadence for health checks. Compressed-hypertable column type migrations follow a separate, mandatory pattern — see `docs/foundation/timescaledb-compressed-column-migration.md` (the `VACUUM` after recompress step) — this doc does not duplicate that content. Diagnosing a slow batch job against a hypertable (chunk count, compression status) follows `docs/foundation/performance-investigation-sop.md` — this doc covers scheduled/routine maintenance, not incident diagnosis.

**v2.x/v3.0 note:** `intelligence_features`, `signal_events`, `trade_frames`, `trade_executions`, and the `signal_ledger` view are the v2.x Signal Ledger Architecture — **archived, no live consumer as of 2026-07-02** (per root `CLAUDE.md`), confirmed empty (0 rows, live-checked 2026-09-04). Their compression/retention jobs are still scheduled (harmless no-ops on empty tables) but the maintenance guidance below focuses on the live v3.0 tables: `market_data_ohlcv`, `feature_vectors`, `alpha_events`, `forward_returns`, `llm_calls`.

## Data Retention Philosophy

**We do not drop signal-bearing data. Ever.**

Storage is trivially cheap. Historical feature vectors, alpha events, and LLM call logs are irreplaceable labeled training data. Patterns we can't see today may be discoverable in 2 years with better models. Retention policies exist for log files and infrastructure/audit tables — not intelligence data.

## Automated Policies (no action needed)

Live-verified 2026-09-04 (`timescaledb_information.jobs`/`hypertables`):

| Table | Compression | Retention | Notes |
|-------|-------------|-----------|-------|
| `market_data_ohlcv` | policy_compression (12h check) | **none — keep forever** | Ground truth; needed for feature re-derivation |
| `feature_vectors` | policy_compression (12h check) | **none — keep forever** | The ML training dataset (298 primitives/bar, v3.0) |
| `alpha_events` | policy_compression (12h check) | **none — keep forever** | Sole `AlphaPublisher` output; emission audit trail |
| `forward_returns` | policy_compression (12h check) | **none — keep forever** | IC measurement inputs |
| `llm_calls` | policy_compression (12h check) | **none — keep forever** | Model performance history |
| `intelligence_features`, `signal_events`, `signal_lineage`, `signal_transform_log`, `ctx_events`, `alpha_multiplier_shadow`, `macro_features`, `ml_signal_training`, `config_history`, `remediation_ledger`, `dlq_events`, `service_health_events` | policy_compression (12h) | `policy_retention` (1 day, several of these) | Infra/audit tables or archived v2.x — 1-day retention is correct for these, not a violation of the "keep forever" rule |

No continuous aggregates are currently defined on this database (`timescaledb_information.continuous_aggregates` returns 0 rows, live-checked 2026-09-04). `market_data_5m` is a **plain view** over `market_data_ohlcv` (computed on read, not materialized/refreshed) — do not confuse it with a continuous aggregate. There is no `ohlcv_15m`/`ohlcv_1h`/`ohlcv_4h`/`ohlcv_1d`/`market_data_15m` object of any kind in the live schema; a prior version of this doc referenced them and was wrong.

Check all TimescaleDB background jobs are running (the historical `application_name`/`hypertable_name` join is ambiguous in TimescaleDB 2.27.1 — qualify columns):
```sql
SELECT j.job_id, j.application_name, j.hypertable_name, j.schedule_interval,
       j.next_start, s.last_run_status
FROM timescaledb_information.jobs j
JOIN timescaledb_information.job_stats s USING (job_id)
ORDER BY j.hypertable_name;
```

**Two custom (non-TimescaleDB-builtin) jobs exist and need operator attention:**
- **Job 1020, `weekly_db_maintenance` — currently FAILING every run** (1243/1243 failures as of 2026-09-04, live-checked). It calls `REFRESH MATERIALIZED VIEW CONCURRENTLY signal_stats_daily` and `ANALYZE` on `signal_features`/`signal_performance_segmented`, none of which exist in the live schema anymore — this job predates a schema cleanup and was never updated or disabled. Needs a fix (drop the dead references, or `SELECT timescaledb_information.jobs`-based `alter_job`/unschedule) — not something this doc can resolve on its own.
- **Job 1021, `recompress_signal_ledger` — "succeeds" but is a silent no-op.** It loops `timescaledb_information.chunks WHERE hypertable_name = 'signal_ledger'`, but `signal_ledger` is a view (a join over `signal_events`/`trade_frames`/`trade_executions`), not a hypertable — the loop matches zero chunks every run. Harmless (target table is empty/archived) but should be unscheduled along with 1020 rather than left running.

---

## Weekly: Slow Query Review (~5 min)

Run after market hours (Friday evening or Sunday). Catches degraded queries before they impact the live pipeline.

```sql
-- Top 10 slowest queries by total execution time
SELECT calls,
       round(mean_exec_time::numeric, 2) AS mean_ms,
       round(total_exec_time::numeric, 0) AS total_ms,
       rows,
       substring(query, 1, 120) AS query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;

-- Reset after reviewing so next week is a clean window
SELECT pg_stat_statements_reset();
```

If mean_ms > 100ms for any query the live pipeline runs frequently, investigate with EXPLAIN ANALYZE.

---

## Weekly: Vacuum and Statistics Health (~2 min)

Autovacuum handles routine work, but verify it's keeping up:

```sql
SELECT relname,
       last_autovacuum,
       last_autoanalyze,
       n_dead_tup,
       n_live_tup,
       round(100.0 * n_dead_tup / nullif(n_live_tup + n_dead_tup, 0), 1) AS dead_pct
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY n_dead_tup DESC;
```

**Action thresholds:**
- `dead_pct > 10%` on any live table - run `VACUUM ANALYZE <table>;` manually
- `last_autoanalyze` null or older than 1 week on an active table - run `ANALYZE <table>;`
- `last_autovacuum` null on a table with writes - check autovacuum is running: `SELECT * FROM pg_stat_progress_vacuum;`

Note: `VACUUM` cannot run inside a transaction block. Run as standalone:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "VACUUM ANALYZE feature_vectors;"
```

**Compressed-hypertable exception:** a plain `VACUUM ANALYZE` here is for routine dead-tuple cleanup on normal write activity. It is not a substitute for the mandatory bare `VACUUM <table>;` step after any migration that runs `decompress_chunk()` → `ALTER COLUMN TYPE` → `compress_chunk()` on a compressed hypertable — see `docs/foundation/timescaledb-compressed-column-migration.md`. That step reclaims decompressed heap pages left behind by the migration itself; autovacuum is not guaranteed to pick them up promptly.

---

## Weekly: Index Health (~2 min)

```sql
-- Check for bloated or unused indexes
SELECT schemaname, relname AS table, indexrelname AS index,
       idx_scan, pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC;
```

**Action thresholds:**
- Index with `idx_scan = 0` after 2+ weeks of live traffic - candidate for removal (confirm query patterns first)
- Index size > 500MB - check for bloat with `pgstattuple` extension

---

## Monthly: Chunk and Storage Audit (~5 min)

**Gotcha (TimescaleDB 2.27.1):** `timescaledb_information.hypertable_compression_stats` no longer exists as a catalog view — it is now a **function**, `hypertable_compression_stats(regclass)`, taking one hypertable at a time. Cross-hypertable queries need a `LATERAL` join:

```sql
-- Total size + compression ratio per hypertable
SELECT h.hypertable_name, s.total_chunks, s.number_compressed_chunks,
       pg_size_pretty(s.before_compression_total_bytes) AS uncompressed,
       pg_size_pretty(s.after_compression_total_bytes) AS compressed,
       round((100.0 * (1 - s.after_compression_total_bytes::numeric /
             nullif(s.before_compression_total_bytes, 0)))::numeric, 1) AS compression_pct
FROM timescaledb_information.hypertables h,
     LATERAL hypertable_compression_stats(format('%I.%I', h.hypertable_schema, h.hypertable_name)::regclass) s
WHERE h.compression_enabled
ORDER BY s.after_compression_total_bytes DESC NULLS LAST;

-- Number of chunks per hypertable
SELECT hypertable_name, count(*) AS chunks,
       sum(is_compressed::int) AS compressed_chunks
FROM timescaledb_information.chunks
GROUP BY hypertable_name
ORDER BY hypertable_name;
```

Same `chunks`/`is_compressed` diagnostic that `docs/foundation/performance-investigation-sop.md` calls out as a first-class suspect before theorizing about a slow batch job — check chunk count and compression status there before assuming disk-locality or another root cause.

If compression_pct < 50% on a table that should be compressing, check that the compression job ran:
```sql
SELECT j.job_id, j.hypertable_name, s.last_run_status, s.last_successful_finish
FROM timescaledb_information.jobs j
JOIN timescaledb_information.job_stats s USING (job_id)
WHERE j.proc_name = 'policy_compression';
```

---

## Monthly: JSONB Index Review

**Live-verified 2026-09-04: there are currently zero GIN indexes anywhere in the `public` schema** (`SELECT * FROM pg_indexes WHERE indexdef ILIKE '%gin%'` returns no true matches — the archived `idx_intel_features_i7_gin`/`idx_intel_features_i8_gin` indexes this section used to reference do not exist on the live `intelligence_features` table, which itself is empty/archived v2.x). `feature_vectors` (the live v3.0 feature table) stores its 298 primitives as flat typed columns, not JSONB, so it has no GIN-index candidate surface either. `alpha_events.top_features` is the one live JSONB column of note but has no GIN index today.

If a future migration adds a JSONB column that needs containment (`@>`) queries, verify index usage the same way:

```sql
SELECT indexrelname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes
WHERE relname = '<table>'
ORDER BY idx_scan DESC;
```

---

## As-Needed: After Large Backfills

After running `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` for multiple days/symbols, run:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "ANALYZE market_data_ohlcv;"
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "ANALYZE feature_vectors;"
```

Then trigger manual compression on newly-created old chunks (if older than 7d):
```sql
SELECT compress_chunk(c.chunk_name)
FROM timescaledb_information.chunks c
WHERE c.hypertable_name = 'market_data_ohlcv'
  AND c.is_compressed = false
  AND c.range_end < now() - INTERVAL '7 days';
```

---

## Autovacuum Tuning

Live-verified 2026-09-04 via `pg_class.reloptions` (tighter than Postgres defaults of 20%/10%):

| Table | vacuum_scale_factor | analyze_scale_factor | Notes |
|-------|--------------------|--------------------|-------|
| `feature_vectors` | 5% | 2% | Live v3.0 ML training dataset |
| `llm_calls` | 5% | 2% | |
| `market_data_ohlcv` | 5% | 2% | |
| `intelligence_features` | 1% | 0.5% (+ `vacuum_cost_delay=2`) | Archived v2.x, 0 rows — tuning is now moot but harmless |
| `alpha_events`, `forward_returns` | *(none set — Postgres defaults)* | | Not yet tuned; candidates if vacuum lag shows up on these under live write load |

This ensures stats stay fresh as these tables grow rapidly during live market hours. `signal_ledger` is a view, not a table, so it carries no `reloptions` of its own — the row in a prior version of this doc was never valid.

---

## Scheduled Maintenance Summary

| Cadence | Task | Who |
|---------|------|-----|
| Continuous | Chunk compression, retention (no continuous aggregates exist) | TimescaleDB jobs (automated) |
| Weekly | Slow query review + pg_stat_statements_reset | Manual (Friday/Sunday) |
| Weekly | Vacuum health check | Manual — act if dead_pct > 10% |
| Weekly | Index scan count check | Manual — flag zero-scan indexes |
| Monthly | Chunk/storage audit | Manual |
| Monthly | JSONB index review | Manual |
| After backfills | ANALYZE + manual compress old chunks | Manual |

---

## Quick Reference: DB Shell

```bash
# Direct psql (always include password and host)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent

# Via Docker
docker exec timescaledb psql -U postgres -d indicagent
```

> **Gotcha:** Plain `psql -U postgres` fails — password and host are required.

## Key Tables

Live-verified against `\dt`/`\dv` and row counts, 2026-09-04. v3.0 tables are the live pipeline; v2.x tables are archived (no live consumer since 2026-07-02 per root `CLAUDE.md`) and confirmed at 0 rows.

| Table | Purpose | Hypertable | Writes | Status |
|-------|---------|-----------|--------|--------|
| `feature_vectors` | 298 orthogonal feature primitives/bar (`FeatureVector`, `src/intelligence/schemas.py`) | Yes (85 chunks) | `FeatureVectorWriter`, every bar | **Live v3.0** — 106M+ rows |
| `alpha_events` | Alpha emission events (sole writer: `AlphaPublisher`) | Yes (81 chunks) | Per qualifying ensemble score | **Live v3.0** — 70M+ rows |
| `forward_returns` | Executable open-to-open forward returns for IC measurement | Yes (85 chunks) | `forward_return_writer` | **Live v3.0** — 103M+ rows |
| `market_data_ohlcv` | Raw OHLCV cold storage (calendar grid; use `market_data_ohlcv_tradeable` view for compute/measurement — see root `CLAUDE.md`) | Yes (258 chunks) | Backfill + live ingestion | **Live v3.0** — 640M+ rows |
| `llm_calls` | LLM audit log, outcome backfill | Yes (1 chunk) | Per LLM call | Low volume (39 rows) — I8 AI stack is dormant-pending-design, not actively firing |
| `setup_performance` | Adaptive aggregator weights (v2.x plugin system) | No | Nightly (job) | Archived alongside I1-I7 |
| `intelligence_features` | v2.x full feature vectors, JSONB tiers (i1-i6/smc) | Yes | none — dormant | **Archived, 0 rows** |
| `signal_events` | v2.x SLA detection layer (one row per I7 plugin fire) | Yes | none — dormant | **Archived, 0 rows** |
| `trade_frames` / `trade_executions` | v2.x SLA hypothesis/execution layers | No | none — dormant | **Archived, 0 rows** |
| `signal_ledger` | v2.x SLA join **view** (`signal_events` + `trade_frames` + `trade_executions`) | No (view) | n/a | **Archived** — not a table, has no rows since its sources are empty |

### signal_ledger (v2.x, archived)

`signal_ledger` is a `CREATE VIEW`, not a base table — it has no columns of its own, no `reloptions`, and cannot be a compression/vacuum target directly (a stale scheduled job, `recompress_signal_ledger`, still queries `timescaledb_information.chunks WHERE hypertable_name = 'signal_ledger'` expecting a hypertable that no longer exists there; see the custom-jobs callout above). The view definition joins `signal_events` (aliased `se`) with `trade_frames` (aliased `tf`) on signal id, surfacing lifecycle fields like `activated_at`, `activation_price`, `targets`, `entry_zone_low`/`entry_zone_high` from `tf.frame_details` JSONB. Since the underlying tables are empty, the view returns zero rows. Do not build new queries against it; it is documented here only so a JOIN found in old code or docs can be traced back to its source tables.
