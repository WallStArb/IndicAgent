# Database Management

**Last Updated:** 2026-03-08

IndicAgent uses TimescaleDB (PostgreSQL + time-series extension) for warm/cold storage and DragonflyDB (Redis-compatible) for hot storage. The real-time pipeline never touches the database directly — only `feature_writer_service` and `llm_writer_service` write to TimescaleDB.

---

## Tables

| Table | Purpose | Retention |
|-------|---------|-----------|
| `market_data_ohlcv` | Raw OHLCV — ground truth, backfill only | Forever |
| `intelligence_features` | Full feature vectors per bar (ML training dataset) | Forever |
| `signal_ledger` | I7 signals + lifecycle outcomes | Forever |
| `llm_calls` | Full LLM audit log per call | Forever |
| `llm_model_scores` | Per-model win rate / avg pnl_r (refreshed 15min) | Forever |
| `setup_performance` | Per-setup rolling 30d stats (sample_size ≥ 30 gate) | Forever |

**Never delete signal/feature data.** Every row is a labeled training sample. Storage is cheap; losing labeled data is permanent.

---

## Migrations

Migrations live in `production/migrations/` and are numbered sequentially.

### Apply all migrations (first-time setup)

```bash
bash production/scripts/db_setup.sh
```

### Apply a single migration

```bash
docker exec timescaledb psql -U postgres -d indicagent -f /path/to/migration.sql
# or connect directly:
docker exec timescaledb psql -U postgres -d indicagent
```

### DB shell

```bash
docker exec timescaledb psql -U postgres -d indicagent
```

---

## Backfill and Gap-Fill

### Full reseed (pipeline_reset)

Stops services, wipes intelligence data for selected symbols, fetches all TF depths from IBKR, replays I1→I7:

```bash
.venv/bin/python production/scripts/pipeline_reset.py [--dry-run] [--keep-ohlcv] [--symbols SYM,SYM]
```

### Gap-fill after downtime

Fetches only the missing recent bars and replays only that window. Safe — `ON CONFLICT DO NOTHING` on both tables means existing rows are never touched.

```bash
# Step 1: fetch missing OHLCV bars (--days caps ALL TF depths, not just 1m)
.venv/bin/python production/scripts/historical_backfill.py \
  --fetch-only --symbols EURUSD,BTCUSD --days 2

# Step 2: replay only those 2 days through I1→I7
.venv/bin/python production/scripts/historical_backfill.py \
  --replay-only --symbols EURUSD,BTCUSD --days 2
```

Default TF fetch depths (when `--days` is omitted):

| TF | Depth | Contract |
|----|-------|---------|
| 1m | 14 days | Named |
| 5m | 90 days | Named (chunked) |
| 15m | 180 days | Continuous adjusted |
| 1h | 365 days | Continuous adjusted |
| 1d | 2555 days (7yr) | Continuous adjusted |

### Full replay without re-fetching OHLCV

Re-runs I1→I7 from existing DB bars. Use `--clean` to wipe signals first (full re-generate), or omit for idempotent insert:

```bash
# Idempotent — only fills gaps in intelligence_features / signal_ledger
.venv/bin/python production/scripts/historical_backfill.py --replay-only --symbols SYM,SYM

# Clean re-generate — deletes existing signals then replays all history
.venv/bin/python production/scripts/historical_backfill.py --replay-only --clean --symbols SYM,SYM
```

---

## Compression

Chunks older than 7 days are compressed automatically. Compression reduces storage 80–95%.

```sql
-- Check compression status
SELECT hypertable_name, total_chunks, number_compressed_chunks
FROM timescaledb_information.hypertable_compression_stats;

-- Manually compress (e.g. after a large backfill)
SELECT compress_chunk(c)
FROM show_chunks('intelligence_features', older_than => INTERVAL '7 days') c;
```

**Bulk UPDATE on compressed data** — decompresses chunks by default and can hit tuple limits:

```sql
SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;
-- then run your UPDATE
```

**`CREATE INDEX CONCURRENTLY`** is not supported on hypertables — omit `CONCURRENTLY`.

---

## VACUUM

Cannot run inside a transaction block. Use a standalone command:

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "VACUUM ANALYZE intelligence_features;"
```

**Autovacuum on hypertables** — `ALTER TABLE` settings only apply to the parent, not existing chunks. To cover all chunks:

```sql
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT chunk_schema, chunk_name FROM timescaledb_information.chunks
           WHERE hypertable_name = 'intelligence_features' AND hypertable_schema = 'public'
  LOOP
    EXECUTE format('ALTER TABLE %I.%I SET (autovacuum_vacuum_scale_factor = 0.01)', r.chunk_schema, r.chunk_name);
  END LOOP;
END $$;
```

---

## Slow Query Analysis

`pg_stat_statements` is enabled. Check top queries by total time:

```sql
SELECT calls, round(mean_exec_time::numeric, 2) AS mean_ms, query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
```

---

## Backups

**Do NOT use `pg_dump` for hypertables** — chunks do not restore cleanly. Use raw Docker volume copy instead:

```bash
# Stop the container first
docker stop timescaledb

# Copy volume (old → new, or to backup location)
docker run --rm \
  -v production_timescale-data:/src:ro \
  -v backup_timescale-data:/dst \
  alpine sh -c "cd /src && cp -a . /dst/"

docker start timescaledb
```

If you must use `pg_dump` (schema only, or non-hypertable data), always redirect stderr separately — `pg_dump ... 2>&1` corrupts `--Fc` binary output:

```bash
pg_dump -U postgres -h localhost -d indicagent -Fc -f backup.dump 2>dump_errors.log
```

---

## Gotchas

### Row count on ohlcv

`market_data_ohlcv` has 10,000+ chunks after a full 7yr backfill. `COUNT(*)` locks all chunks and hits `max_locks_per_transaction`. Use `reltuples` for estimates:

```sql
SELECT reltuples::bigint FROM pg_class WHERE relname = 'market_data_ohlcv';
```

### Parallel query errors in Docker

```sql
SET max_parallel_workers_per_gather = 0;
```

### Table size

`pg_total_relation_size('market_data_ohlcv')` returns near-zero (parent only). Use:

```sql
SELECT pg_size_pretty(hypertable_size('market_data_ohlcv'));
```

### Recompress after backfill

After any large backfill, check for anomalously large compressed chunks and recompress:

```sql
SELECT chunk_name, pg_size_pretty(total_bytes)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'market_data_ohlcv'
ORDER BY total_bytes DESC
LIMIT 10;

-- Recompress a specific chunk:
CALL recompress_chunk('_timescaledb_internal._hyper_1_42_chunk');
```

---

**See also:** `docs/reference/db-maintenance.md` · `production/migrations/`
