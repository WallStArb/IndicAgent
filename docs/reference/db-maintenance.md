# Database Maintenance Runbook

Last updated: 2026-03-07

TimescaleDB handles most routine maintenance automatically (compression, retention, continuous aggregate refresh). This doc covers what is automated, what requires manual intervention, and the scheduled cadence for health checks.

## Data Retention Philosophy

**We do not drop signal-bearing data. Ever.**

Storage is trivially cheap. Historical signal outcomes, feature vectors, and LLM call logs are irreplaceable labeled training data. Patterns we can't see today may be discoverable in 2 years with better models. Retention policies exist for log files and confirmed-unused legacy tables — not intelligence data.

The only table with a retention policy is `technical_indicators` (legacy unused EAV table, no signal value).

## Automated Policies (no action needed)

| Table | Compression | Retention | Notes |
|-------|-------------|-----------|-------|
| `market_data_ohlcv` | after 7d | **none — keep forever** | Ground truth; needed for feature re-derivation |
| `intelligence_features` | after 7d | **none — keep forever** | The ML training dataset |
| `signal_ledger` | after 7d | **none — keep forever** | Labeled outcomes; irreplaceable training signal |
| `llm_calls` | after 7d | **none — keep forever** | Model performance history |
| `technical_indicators` | after 7d | 60d | Confirmed unused legacy EAV — only exception |

Continuous aggregate refresh:
- `ohlcv_15m`, `ohlcv_1h`: every 1–5 min
- `ohlcv_4h`: every 15 min
- `ohlcv_1d`: every 1 hr
- `market_data_5m`, `market_data_15m`: every 1 min

Check all jobs are running:
```sql
SELECT job_id, application_name, hypertable_name, schedule_interval,
       next_start, last_run_status
FROM timescaledb_information.job_stats
JOIN timescaledb_information.jobs USING (job_id)
ORDER BY hypertable_name;
```

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
- `dead_pct > 10%` on any live table → run `VACUUM ANALYZE <table>;` manually
- `last_autoanalyze` null or older than 1 week on an active table → run `ANALYZE <table>;`
- `last_autovacuum` null on a table with writes → check autovacuum is running: `SELECT * FROM pg_stat_progress_vacuum;`

Note: `VACUUM` cannot run inside a transaction block. Run as standalone:
```bash
docker exec timescaledb psql -U postgres -d indicagent -c "VACUUM ANALYZE intelligence_features;"
```

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
- Index with `idx_scan = 0` after 2+ weeks of live traffic → candidate for removal (confirm query patterns first)
- Index size > 500MB → check for bloat with `pgstattuple` extension

---

## Monthly: Chunk and Storage Audit (~5 min)

```sql
-- Total size per hypertable
SELECT hypertable_name,
       pg_size_pretty(before_compression_total_bytes) AS uncompressed,
       pg_size_pretty(after_compression_total_bytes) AS compressed,
       round(100.0 * (1 - after_compression_total_bytes::float /
             nullif(before_compression_total_bytes, 0)), 1) AS compression_pct
FROM timescaledb_information.hypertable_compression_stats
ORDER BY after_compression_total_bytes DESC NULLS LAST;

-- Number of chunks per hypertable
SELECT hypertable_name, count(*) AS chunks,
       sum(is_compressed::int) AS compressed_chunks
FROM timescaledb_information.chunks
GROUP BY hypertable_name
ORDER BY hypertable_name;
```

If compression_pct < 50% on a table that should be compressing, check that the compression job ran:
```sql
SELECT * FROM timescaledb_information.job_stats WHERE job_id IN (
  SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression'
);
```

---

## Monthly: JSONB Index Review

The `intelligence_features` table has GIN indexes on `i7` and `i8`. These are used for containment queries (`@>`). As data volume grows, verify they're being used:

```sql
SELECT indexrelname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes
WHERE relname = 'intelligence_features'
ORDER BY idx_scan DESC;
```

If `idx_intel_features_i7_gin` / `idx_intel_features_i8_gin` show 0 scans after months of data, consider whether queries actually use JSONB containment or extract fields directly. If the latter, the GIN indexes can be dropped.

---

## As-Needed: After Large Backfills

After running `historical_backfill.py` for multiple days/symbols, run:

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "ANALYZE market_data_ohlcv;"
docker exec timescaledb psql -U postgres -d indicagent -c "ANALYZE intelligence_features;"
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

## Autovacuum Tuning (applied in migration 022)

High-write hypertables have tighter autovacuum thresholds than Postgres defaults:

| Table | vacuum_scale_factor | analyze_scale_factor |
|-------|--------------------|--------------------|
| `intelligence_features` | 5% (default 20%) | 2% (default 10%) |
| `signal_ledger` | 5% | 2% |
| `llm_calls` | 5% | 2% |

This ensures stats stay fresh as these tables grow rapidly during live market hours.

---

## Scheduled Maintenance Summary

| Cadence | Task | Who |
|---------|------|-----|
| Continuous | Chunk compression, retention, cagg refresh | TimescaleDB jobs (automated) |
| Weekly | Slow query review + pg_stat_statements_reset | Manual (Friday/Sunday) |
| Weekly | Vacuum health check | Manual — act if dead_pct > 10% |
| Weekly | Index scan count check | Manual — flag zero-scan indexes |
| Monthly | Chunk/storage audit | Manual |
| Monthly | JSONB index review | Manual |
| After backfills | ANALYZE + manual compress old chunks | Manual |

---

## Quick Reference: DB Shell

```bash
docker exec timescaledb psql -U postgres -d indicagent
```

## Key Tables

| Table | Purpose | Hypertable | Writes |
|-------|---------|-----------|--------|
| `intelligence_features` | Full feature vectors, ML dataset | Yes (7d chunk) | Every bar (~1m) |
| `signal_ledger` | I7 signals + lifecycle outcomes | Yes (7d chunk) | Per signal |
| `llm_calls` | LLM audit log, outcome backfill | Yes (7d chunk) | Per narrative |
| `market_data_ohlcv` | Raw OHLCV cold storage | Yes (1d chunk) | Backfill only |
| `technical_indicators` | Legacy EAV indicator store | Yes (1d chunk) | Unused |
| `setup_performance` | Adaptive aggregator weights | No | Nightly (job) |
| `cis_weights` | CIS bucket weights | No | Infrequent |
| `llm_model_scores` | Per-model performance scores | No | Every 15 min |
