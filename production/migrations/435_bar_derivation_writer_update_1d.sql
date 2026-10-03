-- 435: UPDATE on market_data_ohlcv for bar_derivation_writer (phase 185 plan 18).
--
-- Migration 383 granted the writer SELECT, INSERT, DELETE on market_data_ohlcv, which
-- covers the grid stage (delete and rewrite a segment). The daily stage upserts
-- (INSERT ... ON CONFLICT DO UPDATE, 185-01 measurement b) and needs UPDATE; the first
-- pilot apply on 2026-10-03 failed every symbol with "permission denied for table
-- market_data_ohlcv", writing nothing. Unit tests cannot see grants.
--
-- Table level, not column level: market_data_ohlcv is a compressed hypertable and
-- TimescaleDB propagates a column grant to the compressed hypertable, which has no
-- open/high/low/close columns ("column open of relation _compressed_hypertable_31
-- does not exist"). The upsert's SET clause assigns only value columns and source; the
-- key columns are never assigned. Idempotent.

BEGIN;

GRANT UPDATE ON market_data_ohlcv TO bar_derivation_writer;

COMMIT;
