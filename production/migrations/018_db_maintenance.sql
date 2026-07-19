-- 017_db_maintenance.sql
-- DB maintenance: drop unused/duplicate indexes, enable query monitoring,
-- tune autovacuum on high-write tables. Idempotent.

-- 1. Drop duplicate unique constraints on hypertables
--    market_data_ohlcv had two unique constraints on (timestamp, symbol, timeframe).
--    uq_market_data_ohlcv_ts_symbol_tf is kept; the auto-generated one is dropped.
ALTER TABLE market_data_ohlcv
    DROP CONSTRAINT IF EXISTS market_data_ohlcv_timestamp_symbol_timeframe_key;

--    technical_indicators had two unique constraints on (timestamp, symbol, timeframe, indicator_name).
--    uq_technical_indicators_ts_symbol_tf_name is kept; the auto-generated one is dropped.
ALTER TABLE technical_indicators
    DROP CONSTRAINT IF EXISTS technical_indicators_timestamp_symbol_timeframe_indicator_n_key;

-- 2. Drop unused GIN indexes on intelligence_features
--    These were created speculatively for JSONB containment queries (@>) but have never
--    been executed (idx_scan = 0). Each GIN index adds write overhead on every bar insert.
--    Drop all tier GIN indexes; re-add with jsonb_path_ops if containment queries are needed.
DROP INDEX IF EXISTS idx_intel_features_i1_gin;
DROP INDEX IF EXISTS idx_intel_features_i2_gin;
DROP INDEX IF EXISTS idx_intel_features_i3_gin;
DROP INDEX IF EXISTS idx_intel_features_i4_gin;
DROP INDEX IF EXISTS idx_intel_features_i5_gin;
DROP INDEX IF EXISTS idx_intel_features_i6_gin;
DROP INDEX IF EXISTS idx_intel_features_smc_gin;

-- 3. Enable pg_stat_statements for query performance monitoring
--    Requires shared_preload_libraries = 'timescaledb,pg_stat_statements' in postgresql.conf
--    and a DB restart before this extension can be created.
DO $$ BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
EXCEPTION WHEN others THEN
    RAISE NOTICE 'pg_stat_statements skipped (%): add it to shared_preload_libraries and restart first', SQLERRM;
END $$;

-- 4. Tune autovacuum for high-write hypertables
--    Default thresholds (20% dead tuples, 10% changes) are too coarse for hot tables.
--    ALTER TABLE on the parent sets defaults for new chunks only; existing chunks need
--    the same settings applied individually.
ALTER TABLE intelligence_features SET (
    autovacuum_vacuum_scale_factor  = 0.05,
    autovacuum_analyze_scale_factor = 0.02
);
ALTER TABLE signal_ledger SET (
    autovacuum_vacuum_scale_factor  = 0.05,
    autovacuum_analyze_scale_factor = 0.02
);

-- Apply autovacuum settings to all existing chunks of these hypertables
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT chunk_schema, chunk_name
        FROM timescaledb_information.chunks
        WHERE hypertable_name IN ('intelligence_features', 'signal_ledger')
          AND hypertable_schema = 'public'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I SET (autovacuum_vacuum_scale_factor = 0.05, autovacuum_analyze_scale_factor = 0.02)',
            r.chunk_schema, r.chunk_name
        );
    END LOOP;
END $$;

-- 5. Drop legacy v1.0 tables superseded by intelligence_features
--    'features' (raw I1 vectors) and 'intelligence' (composites/regimes) were the original
--    schema from 001_create_features_intelligence.sql. Both were replaced by the tiered
--    intelligence_features hypertable. Neither table was ever queried in production code.
DROP TABLE IF EXISTS features;
DROP TABLE IF EXISTS intelligence;
