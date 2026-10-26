-- 509: symbol-led index on ohlcv_revision. The table's only index was its pkey, led by
-- load_id, but every recurring reader filters (symbol, timeframe, timestamp): the nightly
-- restatement detector, the bar derivation revision reads, and the Tradier residue harness
-- (191-19). Each per-symbol query seq-scanned the full 4.6M-row / 1.4 GB table. Supabase
-- Postgres best-practices audit 2026-10-26 (query-missing-indexes rule).
-- CONCURRENTLY: the table is written by the nightly loads; no exclusive lock. psql only
-- (cannot run inside the migration runner's transaction).

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ohlcv_revision_symbol_tf_ts
    ON public.ohlcv_revision USING btree (symbol, timeframe, "timestamp" DESC);
