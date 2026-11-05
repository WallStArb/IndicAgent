-- Chunk stubs: the schema-only dump restores _timescaledb_internal chunk tables as plain
-- inheritance children of public hypertables, which makes create_hypertable refuse ("already
-- partitioned"). Drop every inheritance child of a public table first (empty after a
-- schema-only restore), then re-register each hypertable with production's chunk interval
-- and compression attributes. Policies are intentionally not re-added.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.oid::regclass::text AS child
           FROM pg_inherits i
           JOIN pg_class c ON c.oid = i.inhrelid
           JOIN pg_class p ON p.oid = i.inhparent
           WHERE p.relnamespace = 'public'::regnamespace
  LOOP EXECUTE format('DROP TABLE IF EXISTS %s', r.child); END LOOP;
END $$;

-- Compressed-hypertable storage stubs: the dump also restores every
-- _timescaledb_internal._compressed_hypertable_N as an empty heap table, which collides with
-- the N that SET (timescaledb.compress) picks. Drop them first.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.oid::regclass::text AS tbl
           FROM pg_class c
           WHERE c.relnamespace = '_timescaledb_internal'::regnamespace
             AND c.relname LIKE '\_compressed\_hypertable\_%'
  LOOP EXECUTE format('DROP TABLE IF EXISTS %s', r.tbl); END LOOP;
END $$;

SELECT create_hypertable('public.borrow_availability_snapshots'::regclass, 'as_of'::name, chunk_time_interval => 7776000000000);
SELECT create_hypertable('public.concept_transition_log'::regclass, 'triggered_at'::name, chunk_time_interval => 7776000000000);
SELECT create_hypertable('public.config_history'::regclass, 'timestamp'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.dlq_events'::regclass, 'routed_at'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.feature_ic_scores'::regclass, 'training_window_end'::name, chunk_time_interval => 2592000000000);
SELECT create_hypertable('public.feature_vectors'::regclass, 'bar_ts'::name, chunk_time_interval => 31104000000000);
SELECT create_hypertable('public.integrity_monitor'::regclass, 'evaluated_at'::name, chunk_time_interval => 7776000000000);
SELECT create_hypertable('public.macro_features'::regclass, 'ts'::name, chunk_time_interval => 86400000000);
SELECT create_hypertable('public.market_data_ohlcv'::regclass, 'timestamp'::name, chunk_time_interval => 7776000000000);
SELECT create_hypertable('public.ohlcv_raw'::regclass, 'timestamp'::name, chunk_time_interval => 2592000000000);
SELECT create_hypertable('public.remediation_ledger'::regclass, 'timestamp'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.service_health_events'::regclass, 'ts'::name, chunk_time_interval => 604800000000);

ALTER TABLE public.config_history SET (timescaledb.compress, timescaledb.compress_segmentby = 'config_key');
ALTER TABLE public.dlq_events SET (timescaledb.compress, timescaledb.compress_orderby = 'routed_at DESC');
ALTER TABLE public.feature_ic_scores SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,tf', timescaledb.compress_orderby = 'training_window_end DESC');
ALTER TABLE public.feature_vectors SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,tf', timescaledb.compress_orderby = 'bar_ts');
ALTER TABLE public.macro_features SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol', timescaledb.compress_orderby = 'ts DESC');
ALTER TABLE public.market_data_ohlcv SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,timeframe', timescaledb.compress_orderby = 'timestamp');
ALTER TABLE public.ohlcv_raw SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,timeframe,vendor', timescaledb.compress_orderby = 'timestamp');
ALTER TABLE public.remediation_ledger SET (timescaledb.compress, timescaledb.compress_segmentby = 'action');
ALTER TABLE public.service_health_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'service', timescaledb.compress_orderby = 'ts DESC');
