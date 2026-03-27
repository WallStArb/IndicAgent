-- production/migrations/051_feature_snapshots_shadow.sql
-- Shadow table for parity validation — mirrors intelligence_features.
-- Written by FeatureSnapshotWriterAgent (consumer group: feature_snapshot_writer_group).
-- Compared against intelligence_features by ParityAuditorAgent on 5-minute schedule.
-- DROP after parity certification and primary-write cutover.

-- IMPORTANT: Use INCLUDING DEFAULTS INCLUDING CONSTRAINTS only — NOT INCLUDING ALL.
-- INCLUDING ALL copies indexes and partitioning constraints from the source
-- hypertable, which causes TimescaleDB to reject the subsequent create_hypertable
-- call ("table already has a partitioning structure"). TimescaleDB recreates
-- indexes itself after create_hypertable — do not pre-copy them.
CREATE TABLE IF NOT EXISTS feature_snapshots_shadow (
    LIKE intelligence_features INCLUDING DEFAULTS INCLUDING CONSTRAINTS
);

-- TimescaleDB hypertable — same chunk interval as source.
-- Skip if already created (idempotent).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'feature_snapshots_shadow'
    ) THEN
        PERFORM create_hypertable(
            'feature_snapshots_shadow', 'ts',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        );
    END IF;
END $$;

-- Parity audit log: row-level divergences between the two tables.
CREATE TABLE IF NOT EXISTS feature_parity_violations (
    id          BIGSERIAL PRIMARY KEY,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ts          TIMESTAMPTZ NOT NULL,
    symbol      TEXT        NOT NULL,
    tf          TEXT        NOT NULL,
    field       TEXT        NOT NULL,  -- which column diverged
    legacy_val  TEXT,                  -- from intelligence_features
    shadow_val  TEXT,                  -- from feature_snapshots_shadow
    run_id      UUID        NOT NULL   -- links rows from same audit cycle
);

CREATE INDEX ON feature_parity_violations (detected_at DESC);
CREATE INDEX ON feature_parity_violations (symbol, tf, detected_at DESC);

-- Unique constraint required by ON CONFLICT (ts, symbol, tf) DO NOTHING in FeatureRepository.
-- TimescaleDB does not copy primary keys from LIKE source — must create explicitly.
CREATE UNIQUE INDEX IF NOT EXISTS feature_snapshots_shadow_ts_symbol_tf_idx
    ON feature_snapshots_shadow (ts, symbol, tf);
