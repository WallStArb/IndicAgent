# Database — TimescaleDB Operations

**Version:** 2.9
**Last Updated:** 2026-06-07
**Status:** current

---

## Purpose

TimescaleDB operations: tables, migrations, backfill, compression, backup, and advanced gotchas for IndicAgent's cold storage layer.

**Architecture:** Real-time pipeline never touches the database directly. Writers consume Kafka topics and persist to TimescaleDB: `indicagent-feature-writer`, `indicagent-signal-writer`, `indicagent-lifecycle-writer`, `indicagent-lineage-writer`, `indicagent-ctx-writer`, `indicagent-llm-writer`, `indicagent-swarm-ledger-writer`, `indicagent-signal-metrics-writer`.

---

## Tables

| Table | Purpose | Retention |
|-------|---------|-----------|
| `market_data_ohlcv` | Raw OHLCV — ground truth, never wipe | Forever |
| `intelligence_features` | Full feature vectors per bar (ML training dataset) | Forever |
| `signal_ledger` | I7 signals — fire-time fields | Forever |
| `signal_outcomes` | Mutable lifecycle fields (activation, exit, pnl_r) — JOIN via `signal_id` | Forever |
| `macro_features` | Macro/cross-asset feature vectors per bar | Forever |
| `llm_calls` | Full LLM audit log per call | Forever |
| `llm_model_scores` | Per-model win rate / avg pnl_r (refreshed 15min) | Forever |
| `setup_performance` | Per-setup rolling 30d stats (sample_size ≥ 30 gate) | Forever |
| `signal_lineage` | Swarm lineage events per signal | Forever |
| `signal_ai_enrichment` | Swarm aggregate adjustments | Forever |
| `shadow_registry` | Shadow governance enrollment + eval stats per plugin/agent | Forever |
| `cis_weights` | CIS calibration weights | Rebuilt nightly |
| `swarm_agent_weights` | Swarm agent performance weights | Rebuilt weekly |

**Never delete `market_data_ohlcv`.** Every bar is a labeled training sample. All downstream tables can be rebuilt from bar data via replay.

**Checkpoint files** (not DB): `cache/pipeline_checkpoint.json` (plugin states + Kalman), `cache/bar_replay_checkpoint.json` (live replay cursor). These are in-process state only — delete to force cold restart.

### Key Columns

| Table | Primary Time Column | Notes |
|-------|-------------------|-------|
| `market_data_ohlcv` | `timestamp` | Not `ts` |
| `intelligence_features` | `ts` | Not `feature_ts` |
| `signal_ledger` | `timestamp` | JOIN via `(symbol, feature_ts, feature_tf)` |
| `llm_calls` | `called_at` | Composite PK with `call_id` |

---

## Connection

```bash
# From host
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent

# From Docker
docker exec -it timescaledb psql -U postgres indicagent

# Common queries
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "<query>"
```

---

## Migrations

Migrations live in `production/migrations/` and are numbered sequentially.

### Apply all migrations (first-time setup)

```bash
bash scripts/infrastructure/setup/infrastructure_db_setup.sh
```

### Apply a single migration

```bash
# Method 1: Direct
docker exec timescaledb psql -U postgres -d indicagent -f /path/to/migration.sql

# Method 2: Via docker cp (for complex migrations)
docker cp file.sql timescaledb:/tmp/file.sql
docker exec timescaledb psql -U postgres -d indicagent -f /tmp/file.sql
```

**Gotcha:** `docker exec timescaledb psql ... -f /dev/stdin <<'EOF'` does NOT work. Always copy the file first.

### Migration version

```sql
SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1;
```

---

## Backfill and Gap-Fill

### Full pipeline reset (reset_pipeline_data.py)

Wipes all intelligence-derived tables and re-runs full fetch + replay. Use when signal logic, stop/target geometry, or lifecycle logic changes substantially enough that historical P&L is no longer trustworthy.

```bash
# Dry run — prints row counts, exits without touching data
python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py

# Full reset: wipe + fetch + replay (stop pipeline first)
sudo systemctl stop indicagent-intelligence-pipeline
python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --confirm

# Wipe only — skip re-fetch and replay
python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --confirm --wipe-only

# More workers for faster replay
python scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py --confirm --workers 8
```

**Tables wiped** (bar data preserved): `intelligence_features`, `signal_ledger`, `signal_outcomes`, `signal_lineage`, `signal_transform_log`, `signal_metrics*`, `signal_ai_enrichment`, `macro_features`, `llm_calls`, `llm_model_scores`, `setup_performance`, `swarm_agent_weights`, `cis_weights`, `tod_multipliers`, `confidence_calibration`, `calibration_curves`, `drift_monitor`, `drift_state`, `pattern_reliability`, `transform_graduation`, `ml_discovery_runs`, `memory_*`. Shadow registry enrollment kept; eval stats reset.

### Lifecycle replay (lifecycle_replay.py)

Evaluates signal outcomes for all signals that lack them, by replaying `market_data_ohlcv` bars chronologically. Run after any full replay to compute pnl_r, mae, mfe, exit_reason.

```bash
# Normal run — fills in missing outcomes only
python -u scripts/debug/replay/debug_lifecycle_replay.py --workers 8

# Reset + replay (for corrupt outcomes — stop pipeline first)
sudo systemctl stop indicagent-intelligence-pipeline
python -u scripts/debug/replay/debug_lifecycle_replay.py --reset --confirm --workers 8

# Dry run to verify schema compatibility
python -u scripts/debug/replay/debug_lifecycle_replay.py --symbols ESM6 --timeframes 5m --dry-run

# Specific symbols only
python -u scripts/debug/replay/debug_lifecycle_replay.py --reset --confirm --symbols ESM6,NQM6
```

**After replay:** `setup_performance` and `swarm_agent_weights` are empty — they repopulate on next scheduled runs (nightly ml-training at 11pm; weekly ml-orchestrator on Monday).

### Gap-fill after downtime

Fetches only the missing recent bars and replays only that window. Safe — `ON CONFLICT DO NOTHING` means existing rows are never touched.

```bash
# Step 1: Fetch missing OHLCV bars
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py \
  --fetch-only --symbols EURUSD,BTCUSD --days 2

# Step 2: Replay only those 2 days through I1→I7
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py \
  --replay-only --symbols EURUSD,BTCUSD --days 2
```

### Default TF fetch depths

| TF | Depth | Contract |
|----|-------|---------|
| 1m | 14 days | Named |
| 5m | 90 days | Named (chunked) |
| 15m | 180 days | Continuous adjusted |
| 1h | 365 days | Continuous adjusted |
| 1d | 2555 days (7yr) | Continuous adjusted |

### Full replay without re-fetching OHLCV

Re-runs I1→I7 from existing DB bars.

```bash
# Idempotent — only fills gaps
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --replay-only --symbols SYM,SYM

# Clean re-generate — deletes existing signals then replays
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --replay-only --clean --symbols SYM,SYM
```

---

## Compression

Chunks older than 7 days are compressed automatically. Compression reduces storage 80–95%.

### Check compression status

```sql
SELECT hypertable_name, total_chunks, number_compressed_chunks
FROM timescaledb_information.hypertable_compression_stats;
```

### Manually compress

```sql
-- After large backfill
SELECT compress_chunk(c)
FROM show_chunks('intelligence_features', older_than => INTERVAL '7 days') c;
```

### Bulk UPDATE on compressed data

Decompresses chunks by default and can hit tuple limits. Disable limit for large updates:

```sql
SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;
-- then run your UPDATE
```

### `CREATE INDEX CONCURRENTLY`

Not supported on hypertables — omit `CONCURRENTLY`.

### Recompress after backfill

After any large backfill, check for anomalously large compressed chunks:

```sql
SELECT chunk_name, pg_size_pretty(total_bytes)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'market_data_ohlcv'
ORDER BY total_bytes DESC
LIMIT 10;

-- Recompress a specific chunk
CALL recompress_chunk('_timescaledb_internal._hyper_1_42_chunk');
```

---

## VACUUM

Cannot run inside a transaction block. Use standalone command:

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "VACUUM ANALYZE intelligence_features;"
```

### Autovacuum on hypertables

`ALTER TABLE` settings only apply to the parent, not existing chunks. To cover all chunks:

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

**Important:** Use `record` type (not `text`) to avoid ambiguous column name conflicts with `chunk_name`.

### TRUNCATE Behavior

`TRUNCATE` removes all chunks — after `TRUNCATE`, `timescaledb_information.chunks` returns 0 rows. Autovacuum settings on parent automatically apply to all future chunks.

`set_chunk_time_interval()` applies to new chunks only — best done while table is empty after TRUNCATE:

```sql
TRUNCATE your_table;
SELECT set_chunk_time_interval('your_table', INTERVAL '1 month');
```

---

## Performance Analysis

### Slow query analysis

`pg_stat_statements` is enabled:

```sql
SELECT calls, round(mean_exec_time::numeric, 2) AS mean_ms, query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
```

### Parallel query errors in Docker

```sql
SET max_parallel_workers_per_gather = 0;
```

### Index usage

`pg_stat_user_indexes.idx_scan` is always 0 for hypertable parents — chunk-level indexes are tracked separately. Never use idx_scan=0 to identify unused indexes on hypertables.

### Table size

`pg_total_relation_size()` returns near-zero for hypertable parents. Use:

```sql
SELECT pg_size_pretty(hypertable_size('market_data_ohlcv'));
```

### Row count estimates

`COUNT(*)` locks all chunks on multi-chunk hypertables. Use `reltuples` for estimates:

```sql
SELECT reltuples::bigint FROM pg_class WHERE relname = 'market_data_ohlcv';
```

---

## Backups

**Do NOT use `pg_dump` for hypertables** — chunks do not restore cleanly. Use raw Docker volume copy:

```bash
# Stop container first
docker stop timescaledb

# Copy volume
docker run --rm \
  -v production_timescale-data:/src:ro \
  -v backup_timescale-data:/dst \
  alpine sh -c "cd /src && cp -a . /dst/"

# Start container
docker start timescaledb
```

### Schema-only dump

If you must use `pg_dump` (schema only, or non-hypertable data), always redirect stderr separately — `pg_dump ... 2>&1` corrupts `--Fc` binary output:

```bash
pg_dump -U postgres -h localhost -d indicagent -Fc -f backup.dump 2>dump_errors.log
```

---

## Compression Settings Verification

`compression_enabled=true` ≠ policy exists. Verify:

```sql
SELECT hypertable_name, config
FROM timescaledb_information.jobs
WHERE application_name LIKE 'Columnstore%';
```

---

## Materialized Views

`signal_stats_daily` is a materialized view — appears in `pg_stat_user_tables` but cannot be TRUNCATEd. Use:

```sql
REFRESH MATERIALIZED VIEW signal_stats_daily;
```

`signal_ledger_full` is a view (joins `signal_ledger` + `signal_outcomes`) — cannot be TRUNCATEd. Query it for full lifecycle state; write to the underlying tables directly.

---

## Hypertable Migration

Never use `pg_dump/restore` for hypertables — chunks do not restore cleanly. Use raw volume copy:

```bash
docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"
```

---

## Freshness Checks

```bash
# Latest OHLCV bars
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, tf, MAX(timestamp) as last_bar FROM market_data_ohlcv \
   GROUP BY symbol, tf ORDER BY last_bar DESC LIMIT 5"

# Latest features
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, tf, MAX(ts) as last_feature FROM intelligence_features \
   GROUP BY symbol, tf ORDER BY last_feature DESC LIMIT 5"

# Latest signals
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, timeframe, MAX(timestamp) as last_signal FROM signal_ledger \
   GROUP BY symbol, timeframe ORDER BY last_signal DESC LIMIT 5"
```

---

## See Also

- **Infrastructure:** `docs/operations/operations-infrastructure.md` — Docker, systemd
- **Observability:** `docs/operations/operations-observability.md` — Metrics, dashboards
- **Migrations:** `production/migrations/` — Migration scripts
