-- Migration 075: signal_transform_log hypertable
--
-- Phase 72 Phase 1 dual-write log. Every pipeline transform (math + LLM)
-- writes one row per signal per transform per version. Replaces in-place
-- confidence mutation with an additive, evaluable record.

CREATE TABLE IF NOT EXISTS signal_transform_log (
    ts                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id         UUID NOT NULL,
    transform_id      TEXT NOT NULL,
    transform_version TEXT NOT NULL DEFAULT 'v1',
    dag_order         SMALLINT NOT NULL,
    segment_key       TEXT NOT NULL DEFAULT '__global__',
    multiplier        DOUBLE PRECISION NOT NULL,
    metadata          JSONB,
    is_shadow         BOOLEAN NOT NULL DEFAULT TRUE
);

SELECT create_hypertable('signal_transform_log', 'ts', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS idx_stl_identity
    ON signal_transform_log (signal_id, transform_id, transform_version);

CREATE INDEX IF NOT EXISTS idx_stl_eval
    ON signal_transform_log (transform_id, segment_key, ts);

COMMENT ON TABLE signal_transform_log IS
    'Phase 72: per-signal per-transform multiplier log. Hypertable. Write-only in Phase 1.';
COMMENT ON COLUMN signal_transform_log.multiplier IS
    'Transform output. Composes via product. 0.0 = signal killed.';
COMMENT ON COLUMN signal_transform_log.is_shadow IS
    'Write-time snapshot of shadow status. Source of truth is transform_graduation.is_graduated.';
