-- 496: market_data_ohlcv_v2, the (vendor, kind) rebuild target (phase 191 plan 12, design doc
-- step 7 first half).
--
-- Part 1: the five APR keys scripts/ops/bars/ops_canonical_vendor_kind_swap.py reads. Until this
-- file is applied the script falls back to the same defaults and prints "default" beside each
-- value, so the fallback is never silent.
--
-- Part 2: market_data_ohlcv_v2, the empty target of the copy, structurally identical to
-- market_data_ohlcv (same columns and NOT NULL constraint names, hypertable partitioning
-- (`timestamp`, 90-day chunks, no default index), compression settings (segmentby symbol,
-- timeframe; orderby "timestamp" ASC), indexes, grants and storage options) except that `source`
-- is replaced by `vendor text NOT NULL` and `kind text NOT NULL`. The shared columns keep the
-- live table's constraint names so plan 14's index and constraint renames stay mechanical; the
-- two new columns carry their own names. Indexes carry a `_rebuilt` suffix until the swap
-- renames them. The live table's NOT VALID `market_data_ohlcv_no_synthetic_fill` check names a
-- column v2 does not have and is not carried: vendor is NOT NULL and the copy maps every source
-- label through vendor_kind.LABEL_TO_VENDOR_KIND, so a synthetic_fill label aborts the build
-- before any row lands (an unmapped label is a preflight blocker, not a constraint).
--
-- What is not here, by design: the copy, the per-(symbol, timeframe) count and digest proof, the
-- selection-gate run on v2, the rename, the dependent views and the compression policy are run
-- by the script, because each step depends on the one before it passing. Plan 12 builds and
-- proves v2; plan 14 swaps the names, recreates every dependent view from its own definition and
-- moves the compression policy; plan 17 drops the kept original and runs the bare
-- `VACUUM market_data_ohlcv;` (docs/foundation/timescaledb-compressed-column-migration.md).
--
-- Re-running this file is safe in every state: part 1 is ON CONFLICT DO NOTHING; part 2 creates
-- nothing when market_data_ohlcv_v2 already exists.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.canonical_swap.disk_margin',
    'float',
    '2',
    1, 10,
    '[initial_estimate] Multiplier on the estimated peak size of the market_data_ohlcv_v2 copy (the table''s rows uncompressed, before their chunks compress) that free disk must cover before the vendor/kind build may run (scripts/ops/bars/ops_canonical_vendor_kind_swap.py). Covers WAL, index builds and the estimate''s error (row-share apportioning of chunk bytes). Not an ML learning target.'
),
(
    'infra.canonical_swap.statement_timeout_s',
    'int',
    '600',
    10, 86400,
    '[initial_estimate] statement_timeout in seconds for each preflight and prove statement of the market_data_ohlcv_v2 build. Per-chunk grouped counts measured 0.1 to 0.4 s on 2026-10-06 (migration 439 era); a per-symbol digest of a 20-year 5m series is the longest statement. Not an ML learning target.'
),
(
    'infra.canonical_swap.copy_statement_timeout_s',
    'int',
    '7200',
    60, 86400,
    '[initial_estimate] statement_timeout in seconds for each write-path statement of the market_data_ohlcv_v2 build: one 90-day window INSERT ... SELECT with the source-to-(vendor, kind) mapping, one compress_chunk, one per-window count. The largest 90-day window holds tens of millions of rows. Not an ML learning target.'
),
(
    'infra.canonical_swap.lock_timeout_s',
    'int',
    '30',
    1, 3600,
    '[initial_estimate] lock_timeout in seconds for the ACCESS EXCLUSIVE locks plan 14''s swap and rollback take on market_data_ohlcv and market_data_ohlcv_v2. A wait this long means a reader or writer is still attached; the swap aborts with nothing renamed rather than queueing every reader behind it. Seeded here so the build''s gates read one APR family. Not an ML learning target.'
),
(
    'infra.canonical_swap.stats_flush_wait_s',
    'int',
    '11',
    0, 120,
    '[conventional] Seconds plan 14''s swap waits, holding its exclusive locks, before re-reading the original table''s write counters (pg_stat n_tup_ins/upd/del over the hypertable and its chunks): another backend may hold a committed write''s counts unflushed for up to PostgreSQL''s 10 s idle stats interval. Seeded here so the build''s gates read one APR family. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.canonical_swap.disk_margin', '2', 1),
    ('infra.canonical_swap.statement_timeout_s', '600', 1),
    ('infra.canonical_swap.copy_statement_timeout_s', '7200', 1),
    ('infra.canonical_swap.lock_timeout_s', '30', 1),
    ('infra.canonical_swap.stats_flush_wait_s', '11', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.canonical_swap.disk_margin', 1, '2', 'migration_496',
     'Initial value: free disk must cover twice the copy peak [initial_estimate]'),
    (NOW(), 'infra.canonical_swap.statement_timeout_s', 1, '600', 'migration_496',
     'Initial value: ten minutes per preflight or prove statement [initial_estimate]'),
    (NOW(), 'infra.canonical_swap.copy_statement_timeout_s', 1, '7200', 'migration_496',
     'Initial value: two hours per copy, compress or count statement [initial_estimate]'),
    (NOW(), 'infra.canonical_swap.lock_timeout_s', 1, '30', 'migration_496',
     'Initial value: wait at most 30 s for plan 14''s exclusive locks [initial_estimate]'),
    (NOW(), 'infra.canonical_swap.stats_flush_wait_s', 1, '11', 'migration_496',
     'Initial value: one PostgreSQL stats idle flush interval (10 s) plus 1 s [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;

-- Part 2: the v2 table, empty. Not a hypertable copy of the old chunks: the copy lands every
-- row window by window, mapped to (vendor, kind), through
-- scripts/ops/bars/ops_canonical_vendor_kind_swap.py --build.
DO $$
BEGIN
    IF to_regclass('public.market_data_ohlcv_v2') IS NOT NULL THEN
        RAISE NOTICE '496: market_data_ohlcv_v2 exists; left as is';
        RETURN;
    END IF;

    CREATE TABLE market_data_ohlcv_v2 (
        "timestamp" timestamptz CONSTRAINT market_data_ohlcv_timestamp_not_null NOT NULL,
        symbol text CONSTRAINT market_data_ohlcv_symbol_not_null NOT NULL,
        timeframe text CONSTRAINT market_data_ohlcv_timeframe_not_null NOT NULL,
        open double precision CONSTRAINT market_data_ohlcv_open_not_null NOT NULL,
        high double precision CONSTRAINT market_data_ohlcv_high_not_null NOT NULL,
        low double precision CONSTRAINT market_data_ohlcv_low_not_null NOT NULL,
        close double precision CONSTRAINT market_data_ohlcv_close_not_null NOT NULL,
        volume bigint CONSTRAINT market_data_ohlcv_volume_not_null NOT NULL,
        vendor text CONSTRAINT market_data_ohlcv_v2_vendor_not_null NOT NULL,
        kind text CONSTRAINT market_data_ohlcv_v2_kind_not_null NOT NULL,
        base text,
        price_sanity_status text
    ) WITH (autovacuum_vacuum_scale_factor = 0.05, autovacuum_analyze_scale_factor = 0.02);

    PERFORM create_hypertable(
        'market_data_ohlcv_v2',
        by_range('timestamp', INTERVAL '90 days'),
        create_default_indexes => false
    );

    CREATE UNIQUE INDEX market_data_ohlcv_pkey_idx_rebuilt
        ON market_data_ohlcv_v2 ("timestamp", symbol, timeframe);
    CREATE INDEX idx_ohlcv_symbol_tf_time_rebuilt
        ON market_data_ohlcv_v2 (symbol, timeframe, "timestamp" DESC);

    ALTER TABLE market_data_ohlcv_v2 SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'symbol, timeframe',
        timescaledb.compress_orderby = '"timestamp" ASC'
    );

    GRANT SELECT, INSERT, UPDATE, DELETE ON market_data_ohlcv_v2 TO bar_derivation_writer;

    COMMENT ON TABLE market_data_ohlcv_v2 IS
        'vendor_kind_swap_496: market_data_ohlcv_v2, canonical rebuilt with vendor and kind '
        'replacing source (phase 191 plan 12, migration 496). Built and proven equal by '
        'scripts/ops/bars/ops_canonical_vendor_kind_swap.py; plan 14 swaps the names.';
END $$;
