---
status: pending
priority: P2
filed: 2026-11-14
source: server tuning survey 2026-11-14 (pg_stat_statements temp_blks_written), ruled by the lead 2026-11-14
---

# ohlcv_coverage zero-no-raw UPDATE spills 68 GB of temp files: fix the query shape, not work_mem

## What

`pg_stat_statements` (queryid 8615117687644723819, 4 calls, 230 s total) shows the `UPDATE ohlcv_coverage c SET earliest_timestamp = ..., row_count = ... WHERE c.provider = ... AND NOT EXISTS (SELECT 1 FROM ohlcv_raw m ...)` statement writing 68 GB of temp files. It is `_ZERO_NO_RAW_SQL` in `services/ohlcv_coverage_writer.py`. The `NOT EXISTS` anti-join against `ohlcv_raw` (403M+ Massive rows plus IBKR) is planned as a hash anti join that materializes far more than the per-symbol, per-timeframe existence it needs. Total temp spill on the database is 112 GB across 3,492 files; this statement is 60% of it, a second join (`bar_date` listing vs tradeable, 8 GB) is next.

work_mem is not the fix (it is already 256 MB; a spill this size means the plan reads the raw side wholesale). The fix is the query shape: probe `ohlcv_raw` per candidate (symbol, timeframe, provider) through its index (LATERAL or a correlated EXISTS the planner can drive from the small `ohlcv_coverage` side), or build the set of series that do hold raw once with a skip-scan style `SELECT DISTINCT symbol, timeframe, vendor` and anti-join against that small set.

## Scope

- Read the plan with `EXPLAIN (ANALYZE, BUFFERS)` for a realistic symbol list and one provider; record the temp blocks written before and after.
- Rewrite `_ZERO_NO_RAW_SQL` (and `_REFRESH_1D_SQL` if it shares the shape) so the temp spill is near zero with an identical row result; add a unit test pinning equal results on a fixture with and without raw rows.

## Gates

- Same rows written as before the rewrite on the full live ledger (row-for-row compare of `ohlcv_coverage` after a scoped run on a copy or in a rolled-back transaction).
- `pg_stat_statements` temp_blks_written for the statement drops to near zero; standard code gate (`/simplify`, `/review`, unit suite).

## Boundary

`services/ohlcv_coverage_writer.py` is imported by step 7. Do not edit it until step 7 is done and the lead says the lane is quiet (CLAUDE.md: never edit a module a live or resumable fingerprinted run imports). Work waits; plan and measure on a copy only if the lead allows.
