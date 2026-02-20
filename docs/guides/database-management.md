# Database Management

**Version:** 1.0.0
**Last Updated:** 2026-02-19
**Status:** Current

IndicAgent uses TimescaleDB (a PostgreSQL extension) for warm and cold storage — OHLCV history, indicator values, trading signals, and the signal ledger. DragonflyDB (Redis-compatible) handles hot storage.

---

## Migrations

Migrations live in `production/migrations/` and run in filename order. The setup script applies all of them.

### First-time setup

```bash
# Start infrastructure first
cd production
docker compose up -d
cd ..

# Apply all migrations
bash production/scripts/db_setup.sh
```

The setup script iterates `production/migrations/0*.sql` in order. The default connection is `postgresql://postgres:postgres@localhost:5432/indicagent`. Override with `DATABASE_URL`.

### Run a single migration

```bash
psql -U postgres -d indicagent -f production/migrations/007_fix_compress_orderby_and_retention.sql
```

### Migration inventory

| File | Description |
|------|-------------|
| `001_timescale_schema.sql` | Core hypertables: `market_data_ohlcv`, `technical_indicators`, `trading_signals` |
| `001_create_features_intelligence.sql` | `features` and `intelligence` hypertables |
| `002_timescaledb_hypertables.sql` | Hypertable registration and chunk intervals |
| `003_timescaledb_enable_and_policies.sql` | Enable TimescaleDB extension, initial policies |
| `004_reconcile_core_schema.sql` | Schema reconciliation and index cleanup |
| `005_high_freq_and_caggs.sql` | High-frequency support, continuous aggregates |
| `006_timescale_compression_retention.sql` | Compression + retention (idempotent via 007 if skipped) |
| `007_fix_compress_orderby_and_retention.sql` | Fixes `compress_orderby` to ASC; adds retention policies idempotently |

### Verify schema

```bash
bash production/scripts/db_verify.sh
```

Checks all hypertables, indexes, continuous aggregates, and compression settings.

---

## TimescaleDB Hypertables

All primary tables are hypertables partitioned by `timestamp`. The segment keys let TimescaleDB skip irrelevant chunks during queries.

| Table | Segment By | Compression After |
|-------|-----------|------------------|
| `market_data_ohlcv` | `symbol, timeframe` | 7 days |
| `technical_indicators` | `symbol, timeframe, indicator_name` | 7 days |
| `trading_signals` | `symbol, timeframe, signal_type` | 7 days |
| `signal_ledger` | `symbol, setup_plugin` | 7 days |

**Inspect a hypertable:**

```sql
SELECT table_name, num_chunks, compression_enabled
FROM timescaledb_information.hypertables;
```

---

## Compression

All hypertables compress chunks older than 7 days. Compression reduces storage 80–95% and improves sequential scan performance on historical data.

All tables use `compress_orderby = 'timestamp ASC'` so forward-in-time scans (analytics, continuous aggregate refreshes) read compressed data in storage order.

### Check compression status

```sql
SELECT hypertable_name, total_chunks, number_compressed_chunks
FROM timescaledb_information.hypertable_compression_stats;
```

### View compression settings

```sql
SELECT * FROM timescaledb_information.compression_settings;
```

### Manually compress old chunks

```sql
SELECT compress_chunk(c)
FROM show_chunks('market_data_ohlcv', older_than => INTERVAL '7 days') c;
```

---

## Retention Policies

Data drops automatically once it exceeds its retention window. Use continuous aggregates for longer-range analytics — they have a 365-day retention.

| Table | Retention |
|-------|-----------|
| `market_data_ohlcv` | 90 days |
| `technical_indicators` | 60 days |
| `trading_signals` | 60 days |
| `signal_ledger` | 365 days |
| `backtesting_data_5m` | 365 days |
| `ohlcv_15m` | 365 days |

**Check active retention jobs:**

```sql
SELECT application_name, schedule_interval, next_start
FROM timescaledb_information.jobs
WHERE application_name ILIKE '%retention%';
```

---

## Continuous Aggregates

Continuous aggregates pre-compute OHLCV rollups for fast dashboard and backtest queries. They refresh automatically as new data arrives.

| View | Interval | Retention |
|------|----------|-----------|
| `ohlcv_15m` | 15 minutes | 365 days |
| `ohlcv_1h` | 1 hour | 365 days |
| `ohlcv_4h` | 4 hours | 365 days |
| `ohlcv_1d` | 1 day | 365 days |
| `backtesting_data_5m` | 5 minutes | 365 days |

**Inspect all aggregates:**

```sql
SELECT view_name, materialization_hypertable_name, compression_enabled
FROM timescaledb_information.continuous_aggregates;
```

**Manual refresh (e.g., after restoring data):**

```sql
CALL refresh_continuous_aggregate('ohlcv_15m', NULL, NULL);
```

---

## Backups

TimescaleDB data lives in the Docker volume `timescale-data`. Back up with `pg_dump`.

### Create a backup

```bash
pg_dump -U postgres -h localhost -d indicagent -Fc -f indicagent_$(date +%Y%m%d).dump
```

### Restore

```bash
pg_restore -U postgres -h localhost -d indicagent indicagent_20260219.dump
```

After restoring from an older dump, reapply any missing migrations:

```bash
bash production/scripts/db_setup.sh
```

---

## Useful Diagnostics

```sql
-- Chunk count and size per hypertable
SELECT hypertable_name,
       num_chunks,
       pg_size_pretty(total_bytes) AS total_size
FROM timescaledb_information.hypertable_detailed_size(NULL);

-- Active background jobs
SELECT application_name, schedule_interval, last_run_status, next_start
FROM timescaledb_information.jobs
ORDER BY application_name;
```

---

**Reference:** `production/migrations/` | `production/scripts/db_setup.sh` | `production/scripts/db_verify.sh`
