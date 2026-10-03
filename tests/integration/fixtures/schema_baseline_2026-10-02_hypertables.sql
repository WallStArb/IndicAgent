-- Chunk stubs: the schema-only dump restores _timescaledb_internal chunk tables as
-- plain inheritance children of public hypertables, which makes create_hypertable
-- refuse ("already partitioned", the exact tolerated-error class that silently
-- no-ops registration). Drop every inheritance child of a public table first: the
-- stubs are empty after a schema-only restore. Then re-register each hypertable with
-- production's exact chunk_time_interval (bigint microseconds, straight from
-- _timescaledb_catalog.dimension.interval_length), then re-apply compression
-- attributes (segmentby/orderby) from the production catalog. Compression/addiction
-- policies are intentionally NOT re-added.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.oid::regclass::text AS child
           FROM pg_inherits i
           JOIN pg_class c ON c.oid = i.inhrelid
           JOIN pg_class p ON p.oid = i.inhparent
           WHERE p.relnamespace = 'public'::regnamespace
  LOOP EXECUTE format('DROP TABLE IF EXISTS %s', r.child); END LOOP;
END $$;

-- Compressed-hypertable storage stubs: the schema-only dump also restores every
-- production _timescaledb_internal._compressed_hypertable_N table as a plain
-- (empty) heap table, since pg_dump --schema-only has no notion of "extension
-- internal state" and dumps the whole catalog. ALTER TABLE ... SET
-- (timescaledb.compress) below picks its own next free N and collides with
-- whichever stub already holds that number. Drop every such stub first; each is
-- empty post-restore same as the chunk stubs above.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.oid::regclass::text AS tbl
           FROM pg_class c
           WHERE c.relnamespace = '_timescaledb_internal'::regnamespace
             AND c.relname LIKE '\_compressed\_hypertable\_%'
  LOOP EXECUTE format('DROP TABLE IF EXISTS %s', r.tbl); END LOOP;
END $$;

SELECT create_hypertable('public.alpha_multiplier_shadow'::regclass, 'ts'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.concept_transition_log'::regclass, 'triggered_at'::name, chunk_time_interval => 7776000000000);
SELECT create_hypertable('public.config_history'::regclass, 'timestamp'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.dlq_events'::regclass, 'routed_at'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.feature_ic_scores'::regclass, 'training_window_end'::name, chunk_time_interval => 2592000000000);
SELECT create_hypertable('public.feature_ic_scores_v2'::regclass, 'training_window_end'::name, chunk_time_interval => 2592000000000);
SELECT create_hypertable('public.feature_vectors'::regclass, 'bar_ts'::name, chunk_time_interval => 7776000000000);
SELECT create_hypertable('public.feature_vectors_v2'::regclass, 'bar_ts'::name, chunk_time_interval => 31104000000000);
SELECT create_hypertable('public.integrity_monitor'::regclass, 'evaluated_at'::name, chunk_time_interval => 7776000000000);
SELECT create_hypertable('public.intelligence_features'::regclass, 'ts'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.intelligence_metrics'::regclass, 'measured_at'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.llm_calls'::regclass, 'called_at'::name, chunk_time_interval => 2592000000000);
SELECT create_hypertable('public.macro_features'::regclass, 'ts'::name, chunk_time_interval => 86400000000);
SELECT create_hypertable('public.market_data_ohlcv'::regclass, 'timestamp'::name, chunk_time_interval => 7776000000000);
SELECT create_hypertable('public.memory_calibration_spc'::regclass, 'ts'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.memory_episodes_labeled'::regclass, 'ts'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.memory_episodes_raw'::regclass, 'ts'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.ml_signal_training'::regclass, 'ts'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.ohlcv_intraday_raw_archive'::regclass, 'timestamp'::name, chunk_time_interval => 7776000000000);
SELECT create_hypertable('public.remediation_ledger'::regclass, 'timestamp'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.service_health_events'::regclass, 'ts'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.signal_events'::regclass, 'ts'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.signal_lineage'::regclass, 'ts'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.signal_metrics_dq_failures'::regclass, 'created_at'::name, chunk_time_interval => 604800000000);
SELECT create_hypertable('public.signal_transform_log'::regclass, 'ts'::name, chunk_time_interval => 604800000000);

ALTER TABLE public.alpha_multiplier_shadow SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol', timescaledb.compress_orderby = 'ts');
ALTER TABLE public.config_history SET (timescaledb.compress, timescaledb.compress_segmentby = 'config_key');
ALTER TABLE public.dlq_events SET (timescaledb.compress, timescaledb.compress_orderby = 'routed_at');
ALTER TABLE public.feature_ic_scores SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,tf', timescaledb.compress_orderby = 'training_window_end');
ALTER TABLE public.feature_ic_scores_v2 SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,tf', timescaledb.compress_orderby = 'training_window_end');
ALTER TABLE public.feature_vectors SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,tf', timescaledb.compress_orderby = 'bar_ts');
ALTER TABLE public.feature_vectors_v2 SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,tf', timescaledb.compress_orderby = 'bar_ts');
ALTER TABLE public.intelligence_features SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,tf', timescaledb.compress_orderby = 'ts');
ALTER TABLE public.llm_calls SET (timescaledb.compress, timescaledb.compress_segmentby = 'model,call_type', timescaledb.compress_orderby = 'called_at');
ALTER TABLE public.macro_features SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol', timescaledb.compress_orderby = 'ts');
ALTER TABLE public.market_data_ohlcv SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,timeframe', timescaledb.compress_orderby = 'timestamp');
ALTER TABLE public.memory_calibration_spc SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id,stat_name', timescaledb.compress_orderby = 'ts');
ALTER TABLE public.memory_episodes_labeled SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,hmm_regime', timescaledb.compress_orderby = 'ts');
ALTER TABLE public.ml_signal_training SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,timeframe,setup_plugin', timescaledb.compress_orderby = 'ts');
ALTER TABLE public.ohlcv_intraday_raw_archive SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,timeframe', timescaledb.compress_orderby = 'timestamp');
ALTER TABLE public.remediation_ledger SET (timescaledb.compress, timescaledb.compress_segmentby = 'action');
ALTER TABLE public.service_health_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'service', timescaledb.compress_orderby = 'ts');
ALTER TABLE public.signal_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,tf', timescaledb.compress_orderby = 'ts');
ALTER TABLE public.signal_lineage SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol', timescaledb.compress_orderby = 'ts');
ALTER TABLE public.signal_metrics_dq_failures SET (timescaledb.compress, timescaledb.compress_segmentby = 'setup_plugin,reason_code', timescaledb.compress_orderby = 'created_at');
ALTER TABLE public.signal_transform_log SET (timescaledb.compress, timescaledb.compress_segmentby = 'segment_key', timescaledb.compress_orderby = 'ts');
