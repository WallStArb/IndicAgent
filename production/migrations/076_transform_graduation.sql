-- Migration 076: transform_graduation analytical table
--
-- Phase 72 Phase 1: per-(transform_id, version, segment_key) statistical evidence.
-- Written by GraduationWriterAgent (UPSERT). Read at pipeline startup
-- (Phase 2) to populate graduation_cache for compose_confidence().

CREATE TABLE IF NOT EXISTS transform_graduation (
    transform_id          TEXT NOT NULL,
    transform_version     TEXT NOT NULL,
    segment_key           TEXT NOT NULL,
    n                     INT NOT NULL,
    spearman_rho          DOUBLE PRECISION,
    spearman_p            DOUBLE PRECISION,
    calibration_max_error DOUBLE PRECISION,
    cvar_bottom_decile    DOUBLE PRECISION,
    mde                   DOUBLE PRECISION,
    val_rho               DOUBLE PRECISION,
    overfitting_risk      BOOLEAN,
    sharpe_delta          DOUBLE PRECISION,
    is_graduated          BOOLEAN NOT NULL DEFAULT FALSE,
    evaluated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at            TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_transform_graduation UNIQUE (transform_id, transform_version, segment_key)
);

CREATE INDEX IF NOT EXISTS idx_transform_graduation_lookup
    ON transform_graduation (is_graduated, transform_id);

COMMENT ON TABLE transform_graduation IS
    'Phase 72: per-segment Renaissance-grade graduation evidence. Not a hypertable.';
COMMENT ON COLUMN transform_graduation.expires_at IS
    'evaluated_at + 90 days. Graduation must re-prove each quarter.';
