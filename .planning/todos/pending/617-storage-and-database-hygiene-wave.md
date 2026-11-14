---
status: pending
priority: P2
filed: 2026-11-14
source: lead survey 2026-11-14 (disk, pg_total_relation_size, hypertable_compression_stats, pg_stat_user_indexes); owner asked for disk cleanup, database optimization and compression
---

# Storage and database hygiene wave: reclaim bloat, drop dead indexes, finish compression, cut temp spill

## What

Survey on ubuntu1, 2026-11-14. Disk is not under pressure (218 GB used of 1.9 TB, 13 percent). The timescale volume is 103 GB for a 93 GB database; `data/massive/files` is 82 GB (the permanent raw archive, kept as is); `logs/` is 1.7 GB, of which `logs/phase181` (1.3 GB) and `logs/phase179` are read by `repro_frozen --logs`, so they stay.

Compression already works: `ohlcv_raw` 126 GB to 16 GB and `market_data_ohlcv` 90 GB to 13 GB. What is uncompressed is the live chunks only (`ohlcv_raw` three chunks, 3.8 GB; `market_data_ohlcv` one 90-day chunk, 1.9 GB; `integrity_monitor` 527 MB). The compression policies (60 days and 30 days) compress them once the chunk range ends and ages out, so no manual compression is owed except the items below.

The real waste is elsewhere:

- `ohlcv_revision` (8.8 GB, a plain table): `ohlcv_revision_pkey` is 3.2 GB with 6 scans total, `idx_ohlcv_revision_symbol_tf_ts` is 1.5 GB with 86,030 scans. Indexes are larger than the heap (4.7 GB vs 4.1 GB).
- `bar_quality_flag` (4.5 GB): 14.9 percent dead tuples (1.87M of 12.5M), `n_dead_tup` stale since the last bulk load.
- `ohlcv_load` (3.8 GB) and `reference_raw` (1.2 GB): heap-heavy, small indexes; check whether old rows are summary-only and compressible.
- Temp spill: 112 GB cumulative `temp_bytes`; 68 GB is the `ohlcv_coverage` zero-no-raw UPDATE (todo 616).
- Postgres exporter per-chunk scrape cost (todo 443), huge pages (runbook Part G), unit-scoped recompress for renamed units (todo 589).

## Scope

All items that touch the database or a table a fingerprinted writer imports wait for the step 7 quiet window. Nothing here edits a module a live run imports.

1. Indexes (read-only first): for each large index on `ohlcv_revision`, `bar_quality_flag`, `ohlcv_load`, `bar_session_choice`, `market_regimes`, list the code that reads it and the `idx_scan` count over a full nightly cycle. Drop only an index with no reader and no uniqueness role; keep `ohlcv_revision_pkey` (uniqueness) but check whether a narrower key is enough.
2. Bloat: after step 7 Part D, run `VACUUM (ANALYZE)` on `bar_quality_flag`, `ohlcv_revision`, `bar_session_choice`; measure with `pgstattuple`; rewrite a table only if measured bloat exceeds 20 percent (`pg_repack` or `VACUUM FULL` in the quiet window, standby lag checked first).
3. Compression: confirm each policy still matches the chunk size after the rebuild; compress `integrity_monitor` (add a policy, the hypertable has none); evaluate making `ohlcv_revision` and `bar_quality_flag` hypertables with compression only if the write path stays a single serial writer (single_writer invariant) and the measured gain is above 50 percent of the 13 GB.
4. Temp spill: land 616; re-read `pg_stat_statements` temp_blks_written afterwards.
5. Fold in 443 (exporter scrape and idle-in-transaction timeout), 589 and runbook Part G (huge pages), scheduled by the lead in the same window.
6. Docker: list unused images with `docker image ls`, keep the previous timescaledb and compose images for rollback, prune the rest (about 6 GB reclaimable; confirm which before pruning).
7. Record the before and after sizes in `docs/operations/operations-database.md` and replace the stale numbers in `.planning/STATE.md`.

## Gates

- Before and after `pg_total_relation_size` for every touched relation, recorded in the landing commit.
- Every migration or DDL is committed in the same breath as its live application; compressed-hypertable column type changes end with `VACUUM <table>;`.
- Standby streams cleanly after each step (`pg_stat_replication` lag small); `ops_pg_settings_baseline.py` shows no drift.
- Dropped index: no query-plan regression on the nightly capture and `ops_selection_gate.py --compare` unchanged.
- Standard code gate (`/simplify`, `/review`, unit suite exit code) for any code change.

## Boundaries

No work while a fingerprinted run or step 7 load is live (the 5m Massive dry run is live today). One heavy job at a time, launched detached with `setsid`. Raw market data is permanent: nothing here deletes `ohlcv_raw` rows or Massive files. Irreversible steps (`VACUUM FULL`, index drop, `pg_repack`) are lead decisions recorded here; anything outward-facing goes to the owner once.
