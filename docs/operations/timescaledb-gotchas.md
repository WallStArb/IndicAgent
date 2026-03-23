# TimescaleDB Advanced Gotchas

Rare or advanced TimescaleDB patterns that are good to know but not needed for day-to-day development. For common gotchas, see `CLAUDE.md`.

## Autovacuum on Hypertables

**`ALTER TABLE hypertable SET (autovacuum_...)` only applies to new chunks.** Cover existing chunks by iterating `timescaledb_information.chunks`:

```sql
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT chunk_schema, chunk_name
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'your_table'
    AND hypertable_schema = 'public'
  LOOP
    EXECUTE format('ALTER TABLE %I.%I SET (autovacuum_vacuum_scale_factor = 0.1);',
      r.chunk_schema, r.chunk_name);
  END LOOP;
END $$;
```

**Important:** Use `record` type (not `text`) to avoid ambiguous column name conflicts with `chunk_name`.

## TRUNCATE Behavior

**`TRUNCATE removes all chunks** — after `TRUNCATE`, `timescaledb_information.chunks` returns 0 rows.** Autovacuum settings on parent automatically apply to all future chunks; no need to iterate existing chunks.

**`set_chunk_time_interval()` applies to new chunks only** — best done while table is empty after TRUNCATE:

```sql
TRUNCATE your_table;
SELECT set_chunk_time_interval('your_table', INTERVAL '1 month');
```

## Materialized Views

**`signal_stats_daily` is a materialized view** — appears in `pg_stat_user_tables` but cannot be TRUNCATEd. Use:

```sql
REFRESH MATERIALIZED VIEW signal_stats_daily;
```

**`signal_performance_segmented` not in `pipeline_reset.py`** — must TRUNCATE separately when doing a full clear.

## Performance Analysis

**`pg_stat_statements`** (enabled 2026-03-05) for slow query analysis:

```sql
SELECT calls, round(mean_exec_time::numeric,2) AS mean_ms, query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
```

**`pg_stat_user_indexes.idx_scan` is always 0 for hypertable parents** — chunk-level indexes are tracked separately. Never use idx_scan=0 to identify unused indexes on hypertables; use pg_stat_statements and EXPLAIN instead.

**`pg_class` shows near-zero size for hypertable parents** — use `hypertable_size('table')` for real sizes and `timescaledb_information.hypertables` for num_chunks.

## Compression

**`compression_enabled=true` ≠ policy exists** — `timescaledb_information.hypertables` shows compression_enabled but doesn't tell you if a job is scheduled. Always verify:

```sql
SELECT hypertable_name, config
FROM timescaledb_information.jobs
WHERE application_name LIKE 'Columnstore%';
```

## Applying Migrations

**`docker exec timescaledb psql ... -f /dev/stdin <<'EOF'` does NOT work.** Always:

```bash
docker cp file.sql timescaledb:/tmp/file.sql
docker exec timescaledb psql -U postgres -d indicagent -f /tmp/file.sql
```

## Hypertable Migration

**Never use pg_dump/restore for hypertables** — chunks do not restore cleanly. Use raw volume copy:

```bash
docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"
```

Also: `pg_dump` with `2>&1` corrupts `--Fc` binary output — always redirect stderr separately.
