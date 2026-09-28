-- Migration 385: primary key inventory for public tables without a PK (D-37, D-08, phase 186 plan 05)
--
-- Inventory re-run 2026-09-28 against production (relkind r/p, schema public, no
-- pg_index.indisprimary row): exactly the 11 tables below, matching the plan's
-- interfaces block. Disposition per table, with the D-08 grep evidence summary
-- (grep -rnw over src services scripts tests production/systemd production/grafana
-- docs/operations docs/foundation, migrations and baseline dumps excluded):
--
-- | Table                      | Rows      | Compression | Disposition                              |
-- |----------------------------|-----------|-------------|------------------------------------------|
-- | ctx_events                 | 0         | enabled     | none here; 186-11 drops the table        |
-- | feature_ic_scores_history  | 49,568,124| enabled     | none here; 186-22 drops the table        |
-- | market_data_ohlcv          | ~674M     | enabled     | kept: unique index = PK equivalent (A1)  |
-- | dlq_events                 | 0         | enabled     | PRIMARY KEY (id, routed_at)              |
-- | integrity_monitor          | 299       | disabled    | PRIMARY KEY (id, evaluated_at)           |
-- | drift_monitor              | 0         | enabled     | DROPPED (sole code ref: reset list)      |
-- | alpha_multiplier_shadow    | 0         | enabled     | id IDENTITY + PRIMARY KEY (id, ts)       |
-- | service_health_events      | 0         | enabled     | id IDENTITY + PRIMARY KEY (id, ts)       |
-- | signal_lineage             | 0         | enabled     | id IDENTITY + PRIMARY KEY (id, ts)       |
-- | signal_transform_log       | 0         | enabled     | id IDENTITY + PRIMARY KEY (id, ts)       |
-- | transform_graduation       | 0         | plain table | PRIMARY KEY (transform_id, version, key) |
--
-- Grep evidence: ctx_events -> services/context_writer.py (186-11 drops);
-- feature_ic_scores_history -> services/ic_engine.py ~1423/~1460 INSERTs (old chain,
-- 186-22 drops); market_data_ohlcv -> bar_writer + many readers (boundary-test
-- allow-lists); dlq_events -> services/dlq_writer.py + systemd unit (inactive);
-- integrity_monitor -> src/core/integrity_monitor.py + live readers
-- (feature_lifecycle, forward_return_writer, vocabulary_drift, ops scripts);
-- drift_monitor -> ONLY infrastructure_reset_pipeline_data.py list entry (line ~66)
-- plus prose in docs/operations/operations-database.md (updated in this commit);
-- alpha_multiplier_shadow -> dormant I8 (src/core/ai/lineage.py, alpha prompts,
-- kafka topic setup); service_health_events -> services/service_auditor.py INSERT
-- (named columns); signal_lineage -> services/lineage_writer.py INSERT (named
-- columns, ON CONFLICT DO NOTHING; unit active) + alpha_swarm/ai_stats readers;
-- signal_transform_log -> src/core/ml/transform_recorder.py INSERT (named columns)
-- + graduation_analyzer; transform_graduation -> repository UPSERT with
-- ON CONFLICT (transform_id, transform_version, segment_key) + graduation_writer.
-- Every INSERT names its columns, so the new identity/defaulted id column cannot
-- break a writer.
--
-- A1 probe (scratch hypertable, 2026-09-28, BEGIN...ROLLBACK): ADD CONSTRAINT
-- ... PRIMARY KEY USING INDEX on a hypertable fails with exactly:
--   ERROR: hypertables do not support adding a constraint using an existing index
-- (consistent with migration 193's finding). So market_data_ohlcv stays on its
-- recorded unique index market_data_ohlcv_pkey_idx ("timestamp", symbol, timeframe),
-- UNIQUE over all-NOT-NULL columns including the partition column: the PK
-- equivalent. transform_graduation is a PLAIN table, so its PK is added normally --
-- but uq_transform_graduation turned out to be a UNIQUE CONSTRAINT (contype 'u'),
-- not an adoptable bare index ("index ... is already associated with a constraint"),
-- so the constraint is replaced by an equivalent PRIMARY KEY over the same columns
-- in one ALTER; ON CONFLICT (transform_id, transform_version, segment_key) infers
-- the PK, so the repository's UPSERT target is unchanged.
--
-- Timescale 2.27.1 rejects ADD COLUMN ... GENERATED ... AS IDENTITY on
-- columnstore-enabled hypertables ("cannot add column with constraints to a
-- hypertable that has columnstore enabled"; observed live in the dry run). The four
-- identity-column tables therefore toggle compression off and back on inside this
-- transaction. No chunk is compressed or decompressed (these tables have 0 chunks
-- total), so migration 312's decompress/recompress VACUUM rule (D-16) does not
-- apply -- confirmed by tests/unit/test_compressed_hypertable_migration_vacuum_check.py.
-- Compression restored to the exact prior settings (read from
-- timescaledb_information.compression_settings 2026-09-28):
--   alpha_multiplier_shadow  segmentby symbol,        orderby ts DESC NULLS FIRST
--   service_health_events    segmentby service,       orderby ts DESC NULLS FIRST
--   signal_lineage           segmentby symbol,        orderby ts DESC NULLS FIRST
--   signal_transform_log     segmentby segment_key,   orderby ts DESC NULLS FIRST
-- Postgres warns "column id should be used for segmenting or ordering" on re-enable;
-- harmless for a synthetic surrogate that exists only to make the PK unique by
-- construction.
--
-- Every step is re-runnable (IF EXISTS / IF NOT EXISTS / pg_constraint guards /
-- table-existence guards) because the integration conftest replays this file on
-- the schema baseline.
--
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -v ON_ERROR_STOP=1 -f production/migrations/385_primary_key_inventory.sql

BEGIN;

-- 1. drift_monitor: empty, no writer anywhere in code. Dropped; its tuple is
--    removed from infrastructure_reset_pipeline_data.py in this same commit.
DROP TABLE IF EXISTS drift_monitor;

-- 2. transform_graduation (plain table): replace the UNIQUE constraint with an
--    equivalent PRIMARY KEY over the same columns.
DO $$
BEGIN
    IF to_regclass('public.transform_graduation') IS NOT NULL THEN
        ALTER TABLE transform_graduation DROP CONSTRAINT IF EXISTS uq_transform_graduation;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'transform_graduation_pkey') THEN
            ALTER TABLE transform_graduation
                ADD CONSTRAINT transform_graduation_pkey
                PRIMARY KEY (transform_id, transform_version, segment_key);
        END IF;
    END IF;
END $$;

-- 3. dlq_events (compression enabled, but ADD CONSTRAINT on existing columns is
--    accepted by 2.27.1 -- dry-run verified): surrogate PK over the existing
--    sequence id plus the partition column. dlq_events_dedup_idx stays the
--    ON CONFLICT target; the sequence makes (id, routed_at) unique by construction.
DO $$
BEGIN
    IF to_regclass('public.dlq_events') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'dlq_events_pkey') THEN
        ALTER TABLE dlq_events ADD CONSTRAINT dlq_events_pkey PRIMARY KEY (id, routed_at);
    END IF;
END $$;

-- 4. integrity_monitor (compression disabled): surrogate PK over the existing
--    sequence id plus the partition column. The expression unique index
--    integrity_monitor_idempotency_uq stays the ON CONFLICT target.
DO $$
BEGIN
    IF to_regclass('public.integrity_monitor') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'integrity_monitor_pkey') THEN
        ALTER TABLE integrity_monitor ADD CONSTRAINT integrity_monitor_pkey PRIMARY KEY (id, evaluated_at);
    END IF;
END $$;

-- 5-8. Empty columnstore hypertables with writers in dormant I8 / registry code:
--    identity id + PK (id, ts), with the compression toggle 2.27.1 needs.
DO $$
BEGIN
    IF to_regclass('public.alpha_multiplier_shadow') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                   WHERE hypertable_schema = 'public' AND hypertable_name = 'alpha_multiplier_shadow'
                     AND compression_enabled) THEN
            ALTER TABLE alpha_multiplier_shadow SET (timescaledb.compress = false);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = 'alpha_multiplier_shadow'
                         AND column_name = 'id') THEN
            ALTER TABLE alpha_multiplier_shadow ADD COLUMN id bigint GENERATED BY DEFAULT AS IDENTITY;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'alpha_multiplier_shadow_pkey') THEN
            ALTER TABLE alpha_multiplier_shadow ADD CONSTRAINT alpha_multiplier_shadow_pkey PRIMARY KEY (id, ts);
        END IF;
        IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                   WHERE hypertable_schema = 'public' AND hypertable_name = 'alpha_multiplier_shadow') THEN
            ALTER TABLE alpha_multiplier_shadow SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'symbol',
                timescaledb.compress_orderby = 'ts DESC NULLS FIRST'
            );
        END IF;
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.service_health_events') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                   WHERE hypertable_schema = 'public' AND hypertable_name = 'service_health_events'
                     AND compression_enabled) THEN
            ALTER TABLE service_health_events SET (timescaledb.compress = false);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = 'service_health_events'
                         AND column_name = 'id') THEN
            ALTER TABLE service_health_events ADD COLUMN id bigint GENERATED BY DEFAULT AS IDENTITY;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'service_health_events_pkey') THEN
            ALTER TABLE service_health_events ADD CONSTRAINT service_health_events_pkey PRIMARY KEY (id, ts);
        END IF;
        IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                   WHERE hypertable_schema = 'public' AND hypertable_name = 'service_health_events') THEN
            ALTER TABLE service_health_events SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'service',
                timescaledb.compress_orderby = 'ts DESC NULLS FIRST'
            );
        END IF;
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.signal_lineage') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                   WHERE hypertable_schema = 'public' AND hypertable_name = 'signal_lineage'
                     AND compression_enabled) THEN
            ALTER TABLE signal_lineage SET (timescaledb.compress = false);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = 'signal_lineage'
                         AND column_name = 'id') THEN
            ALTER TABLE signal_lineage ADD COLUMN id bigint GENERATED BY DEFAULT AS IDENTITY;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'signal_lineage_pkey') THEN
            ALTER TABLE signal_lineage ADD CONSTRAINT signal_lineage_pkey PRIMARY KEY (id, ts);
        END IF;
        IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                   WHERE hypertable_schema = 'public' AND hypertable_name = 'signal_lineage') THEN
            ALTER TABLE signal_lineage SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'symbol',
                timescaledb.compress_orderby = 'ts DESC NULLS FIRST'
            );
        END IF;
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.signal_transform_log') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                   WHERE hypertable_schema = 'public' AND hypertable_name = 'signal_transform_log'
                     AND compression_enabled) THEN
            ALTER TABLE signal_transform_log SET (timescaledb.compress = false);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = 'signal_transform_log'
                         AND column_name = 'id') THEN
            ALTER TABLE signal_transform_log ADD COLUMN id bigint GENERATED BY DEFAULT AS IDENTITY;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'signal_transform_log_pkey') THEN
            ALTER TABLE signal_transform_log ADD CONSTRAINT signal_transform_log_pkey PRIMARY KEY (id, ts);
        END IF;
        IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                   WHERE hypertable_schema = 'public' AND hypertable_name = 'signal_transform_log') THEN
            ALTER TABLE signal_transform_log SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'segment_key',
                timescaledb.compress_orderby = 'ts DESC NULLS FIRST'
            );
        END IF;
    END IF;
END $$;

COMMIT;
