# 301 - Reconcile manual multi-row VALUES batching vs. chunked executemany() across OHLCV writers

**Filed:** 2026-08-11
**Source:** `/simplify` pass on this session's `store_bars()` batching fix (see
[[project_universe_expansion_and_ibkr_recalibration_2026_08_06]] memory). Two independent
review agents (reuse angle, altitude angle) both flagged the same thing from different
directions -- worth taking seriously as a converged signal, not two independent weak findings.
**Status:** pending, not blocking. The underlying fix (store_bars() batching) is real and
measured, kept as-is -- this todo is about reconciling it with the rest of the codebase, not
undoing it.

**Update 2026-08-12:** `_STORE_BATCH_SIZE` (and `_GAP_CLUSTER_MAX_DAYS`) are now APR-backed
(migration 313, `infra.backfill.ohlcv_insert_batch_size` / `infra.backfill.gap_cluster_max_days`)
following a separate code-review finding on the same diff -- closes the "new hardcoded constant"
angle only. This todo's actual scope (reconciling `store_bars()`'s manual multi-row VALUES
against `forward_return_writer.py`/`ic_engine.py`/`backfill_feature_factory.py`'s chunked
`executemany()` into one shared primitive) is unchanged and still open.

## What

`infrastructure_run_historical_pipeline.py`'s `store_bars()` was changed this session from
`executemany()` (one INSERT statement per row) to a hand-built multi-row VALUES INSERT,
chunked at `_STORE_BATCH_SIZE = 1000`. This was based on a live benchmark against real
psycopg3 (0.0515ms/row -> 0.0265ms/row, ~2x, 20k-row test) -- not theoretical, the numbers are
real and reproducible.

But this diverges from two things already in the codebase:

1. **`services/forward_return_writer.py`** (~line 540-546) solves the identical "batch a bulk
   INSERT ... ON CONFLICT DO NOTHING" problem via chunked `executemany()` calls, not manual
   VALUES-string building.
2. **`services/ic_engine.py`** (~line 4043-4048) has an existing comment arguing *against*
   hand-rolling multi-row VALUES in psycopg3 specifically because "executemany() batches
   internally in psycopg 3.1+ ... isn't a naive N-roundtrip regression." That comment is
   reasoning from psycopg's own changelog, not a live measurement -- this session's benchmark
   is the first actual live test of that claim for a bulk-INSERT shape, and shows a real (if
   more modest than round-trip-elimination alone would suggest) 2x gap remains.
3. **`services/backfill_feature_factory.py:896`** (`_STORE_OHLCV_SQL` via `cur.executemany(...)`)
   writes to the same `market_data_ohlcv` table with the identical one-row-per-statement
   pattern, untouched by this session's fix -- now a second, slower, unreconciled path writing
   to the same table.

## Why this wasn't fixed in the same session

Promoting this properly means either (a) adding a shared `bulk_insert` primitive to
`services/_batch_utils.py` (which already has `bulk_update_by_key`, a COPY-based primitive for
the equivalent UPDATE problem, built after a real incident --
`scripts/ops/corpus/ops_ctf_columns_recompute_15m.py:148-151`, 8.28M single-row UPDATEs took
10+ hours) and pointing every OHLCV writer at it, or (b) re-measuring `forward_return_writer.py`
and `ic_engine.py`'s own workloads to confirm the same ~2x holds there before touching
production hot-path code. Both are real, valuable, multi-file changes well outside the scope of
the connection-drop investigation that motivated this session's fix.

## Fix (not yet implemented)

Best shape is probably a COPY-based `bulk_insert` counterpart to `_batch_utils.py`'s
`bulk_update_by_key` (COPY into a temp table, then `INSERT ... SELECT ... ON CONFLICT DO
NOTHING` from it) -- likely faster than either executemany() or manual VALUES batching for
large row counts, matching the precedent `bulk_update_by_key` already set for the UPDATE case.
Then point `store_bars()`, `forward_return_writer.py`, and `backfill_feature_factory.py`'s
`_STORE_OHLCV_SQL` writer at the shared primitive, and update/remove the now-stale
`ic_engine.py` comment once it's been actually re-measured rather than assumed.

## Where

- `services/_batch_utils.py` -- `bulk_update_by_key` (the COPY-based precedent to follow)
- `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` -- `store_bars()`
  (this session's fix, the comment there points here)
- `services/forward_return_writer.py` ~line 540-546, `services/ic_engine.py` ~line 4043-4048,
  `services/backfill_feature_factory.py:896` -- the other call sites to reconcile
