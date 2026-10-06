-- 439: market_data_ohlcv real-rows swap (todo 462 step 6, phase 185 plan 25).
--
-- Part 1: the APR keys scripts/ops/bars/ops_real_rows_swap.py reads. Until this file is applied
-- the script falls back to the same defaults and prints `"source": "default"` beside each value,
-- so the fallback is never silent.
--
-- Part 2: market_data_ohlcv_new, the empty target of the copy, structurally identical to
-- market_data_ohlcv: the same columns and NOT NULL constraint names, hypertable partitioning
-- (`timestamp`, 90-day chunks, no default index), compression settings (segmentby symbol,
-- timeframe; orderby "timestamp" ASC), indexes, grants and storage options. Its indexes carry a
-- `_rebuilt` suffix until the swap renames them; the COMMENT marker `real_rows_swap_439` names
-- the rebuilt table in every state (before, after and after a rollback). The script checks the
-- two tables' shapes match before it copies and again before it swaps.
--
-- What is not here, by design: the copy, the per-(symbol, timeframe) count and digest proof, the
-- rename, the dependent views and the compression policy are run by the script, because each
-- step depends on the one before it passing. The swap transaction renames market_data_ohlcv to
-- market_data_ohlcv_old and market_data_ohlcv_new to market_data_ohlcv, and recreates every view
-- that depends on the table from its own definition (CREATE OR REPLACE, so view grants survive):
-- today market_data_ohlcv_tradeable, market_data_ohlcv_scrub_input and market_data_5m. It moves
-- the compression policy (same compress_after and schedule_interval) to the rebuilt table and
-- unschedules the original's. The old table is dropped only after the post-swap checks pass,
-- then `VACUUM market_data_ohlcv;` reclaims the heap pages the copy's compress_chunk calls left
-- behind (docs/foundation/timescaledb-compressed-column-migration.md).
--
-- Re-running this file is safe in every state: part 1 is ON CONFLICT DO NOTHING; part 2 creates
-- nothing when market_data_ohlcv_new already exists or market_data_ohlcv is already the rebuilt
-- table.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.real_rows_swap.disk_margin',
    'float',
    '2',
    1, 10,
    '[initial_estimate] Multiplier on the estimated peak size of the real-rows copy (the real rows uncompressed, before their chunks compress) that free disk must cover before the market_data_ohlcv swap may run (scripts/ops/bars/ops_real_rows_swap.py). Covers WAL, index builds and the estimate''s error (row-share apportioning of chunk bytes). Not an ML learning target.'
),
(
    'infra.real_rows_swap.statement_timeout_s',
    'int',
    '600',
    10, 86400,
    '[initial_estimate] statement_timeout in seconds for each preflight and verify statement of the market_data_ohlcv real-rows swap. A per-chunk count measured 0.1 to 0.4 s on 2026-10-06; a per-symbol digest of a 20-year 5m series is the longest statement. Not an ML learning target.'
),
(
    'infra.real_rows_swap.masked_audit_max_age_hours',
    'int',
    '48',
    1, 720,
    '[conventional] Oldest D7 masked-slot fact (plan 185-23, integrity_monitor masked_slots_derived_symbols) the real-rows swap accepts as proof that no derived 15m/1h slot is masked. The audit runs nightly, so 48 hours tolerates one missed night. Not an ML learning target.'
),
(
    'infra.real_rows_swap.copy_statement_timeout_s',
    'int',
    '7200',
    60, 86400,
    '[initial_estimate] statement_timeout in seconds for each write-path statement of the market_data_ohlcv real-rows swap: one chunk-window INSERT ... SELECT, one compress_chunk, one per-timeframe count through a dependent view in the post-swap checks. The largest 90-day window holds tens of millions of real rows. Not an ML learning target.'
),
(
    'infra.real_rows_swap.lock_timeout_s',
    'int',
    '30',
    1, 3600,
    '[initial_estimate] lock_timeout in seconds for the ACCESS EXCLUSIVE locks the real-rows swap and its rollback take on market_data_ohlcv and the table it exchanges with. A wait this long means a reader or writer is still attached; the swap aborts with nothing renamed rather than queueing every reader behind it. Not an ML learning target.'
),
(
    'infra.real_rows_swap.stats_flush_wait_s',
    'int',
    '11',
    0, 120,
    '[conventional] Seconds the swap waits, holding its exclusive locks, before re-reading the original table''s write counters (pg_stat n_tup_ins/upd/del over the hypertable and its chunks): another backend may hold a committed write''s counts unflushed for up to PostgreSQL''s 10 s idle stats interval. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.real_rows_swap.disk_margin', '2', 1),
    ('infra.real_rows_swap.statement_timeout_s', '600', 1),
    ('infra.real_rows_swap.masked_audit_max_age_hours', '48', 1),
    ('infra.real_rows_swap.copy_statement_timeout_s', '7200', 1),
    ('infra.real_rows_swap.lock_timeout_s', '30', 1),
    ('infra.real_rows_swap.stats_flush_wait_s', '11', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.real_rows_swap.disk_margin', 1, '2', 'migration_439',
     'Initial value: free disk must cover twice the copy peak [initial_estimate]'),
    (NOW(), 'infra.real_rows_swap.statement_timeout_s', 1, '600', 'migration_439',
     'Initial value: ten minutes per preflight or verify statement [initial_estimate]'),
    (NOW(), 'infra.real_rows_swap.masked_audit_max_age_hours', 1, '48', 'migration_439',
     'Initial value: accept a masked-slot fact up to two days old [conventional]'),
    (NOW(), 'infra.real_rows_swap.copy_statement_timeout_s', 1, '7200', 'migration_439',
     'Initial value: two hours per copy, compress or post-check statement [initial_estimate]'),
    (NOW(), 'infra.real_rows_swap.lock_timeout_s', 1, '30', 'migration_439',
     'Initial value: wait at most 30 s for the swap''s exclusive locks [initial_estimate]'),
    (NOW(), 'infra.real_rows_swap.stats_flush_wait_s', 1, '11', 'migration_439',
     'Initial value: one PostgreSQL stats idle flush interval (10 s) plus 1 s [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;

-- Part 2: the rebuilt table, empty. Not a hypertable copy of the old chunks: the copy lands real
-- rows only, window by window, through scripts/ops/bars/ops_real_rows_swap.py --copy.
DO $$
BEGIN
    IF to_regclass('public.market_data_ohlcv_new') IS NOT NULL THEN
        RAISE NOTICE '439: market_data_ohlcv_new exists; left as is';
        RETURN;
    END IF;
    IF coalesce(obj_description('public.market_data_ohlcv'::regclass, 'pg_class'), '')
           LIKE 'real_rows_swap_439%' THEN
        RAISE NOTICE '439: market_data_ohlcv is already the rebuilt table; nothing to create';
        RETURN;
    END IF;

    CREATE TABLE market_data_ohlcv_new (
        "timestamp" timestamptz CONSTRAINT market_data_ohlcv_timestamp_not_null NOT NULL,
        symbol text CONSTRAINT market_data_ohlcv_symbol_not_null NOT NULL,
        timeframe text CONSTRAINT market_data_ohlcv_timeframe_not_null NOT NULL,
        open double precision CONSTRAINT market_data_ohlcv_open_not_null NOT NULL,
        high double precision CONSTRAINT market_data_ohlcv_high_not_null NOT NULL,
        low double precision CONSTRAINT market_data_ohlcv_low_not_null NOT NULL,
        close double precision CONSTRAINT market_data_ohlcv_close_not_null NOT NULL,
        volume bigint CONSTRAINT market_data_ohlcv_volume_not_null NOT NULL,
        source text,
        base text,
        price_sanity_status text
    ) WITH (autovacuum_vacuum_scale_factor = 0.05, autovacuum_analyze_scale_factor = 0.02);

    PERFORM create_hypertable(
        'market_data_ohlcv_new',
        by_range('timestamp', INTERVAL '90 days'),
        create_default_indexes => false
    );

    CREATE UNIQUE INDEX market_data_ohlcv_pkey_idx_rebuilt
        ON market_data_ohlcv_new ("timestamp", symbol, timeframe);
    CREATE INDEX idx_ohlcv_symbol_tf_time_rebuilt
        ON market_data_ohlcv_new (symbol, timeframe, "timestamp" DESC);

    ALTER TABLE market_data_ohlcv_new SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'symbol, timeframe',
        timescaledb.compress_orderby = '"timestamp" ASC'
    );

    GRANT SELECT, INSERT, UPDATE, DELETE ON market_data_ohlcv_new TO bar_derivation_writer;

    COMMENT ON TABLE market_data_ohlcv_new IS
        'real_rows_swap_439: market_data_ohlcv rebuilt from its real rows, synthetic_fill '
        'placeholders left behind (todo 462 step 6, plan 185-25, migration 439).';
END $$;
