-- Migration 155: Foundation hardening — feature_vectors naming remediation + schema expansion + batch_job_checkpoints
--
-- Covers: momentum_z column renaming (5->fast, 20->mid), APR key renaming,
--   council review findings: F2 (feature_factory_version), F7 (bar_close_ts),
--   F8 (batch_job_checkpoints), F9 (cross-sectional nullables), F11 (momentum), F12 (calendar)
--
-- Applied before backfill_feature_factory runs so all columns are correct from the first write.
-- feature_vector_to_insert_params() produces 70-element tuple after this migration.
--
-- Column names encode concept/scale (not tunable period values) consistent with
-- rsi_fast/rsi_mid/rsi_slow and cci_fast/cci_mid/cci_slow patterns.
--
-- All ADD COLUMN statements use IF NOT EXISTS for idempotency.
-- Safe to re-run.

-- ── Naming remediation: momentum_z columns ────────────────────────────────────
-- Column names must encode scale (concept), not period (tunable parameter).
-- Pattern: rsi_fast/rsi_mid/rsi_slow; cci_fast/cci_mid/cci_slow. Momentum follows same.

ALTER TABLE feature_vectors RENAME COLUMN momentum_z_5 TO momentum_z_fast;
ALTER TABLE feature_vectors RENAME COLUMN momentum_z_20 TO momentum_z_mid;

-- ── APR key rename for consistency ────────────────────────────────────────────
-- Period values live in APR, not schema or key names.
-- window_short/long -> window_fast/mid to match the renamed schema columns.

UPDATE config_schema
    SET config_key = 'feature.momentum.window_fast'
    WHERE config_key = 'feature.momentum.window_short';

UPDATE config_state
    SET config_key = 'feature.momentum.window_fast'
    WHERE config_key = 'feature.momentum.window_short';

UPDATE config_schema
    SET config_key = 'feature.momentum.window_mid'
    WHERE config_key = 'feature.momentum.window_long';

UPDATE config_state
    SET config_key = 'feature.momentum.window_mid'
    WHERE config_key = 'feature.momentum.window_long';

-- ── New APR key: momentum slow window ─────────────────────────────────────────
-- Insert if not already present (idempotent with ON CONFLICT DO NOTHING).

INSERT INTO config_schema (config_key, value_type, description)
VALUES (
    'feature.momentum.window_slow',
    'int',
    'Slow-scale momentum z-score lookback window (bars). [initial_estimate]. ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES (
    'feature.momentum.window_slow',
    '60',
    1
)
ON CONFLICT (config_key) DO NOTHING;

-- ── New columns on feature_vectors ────────────────────────────────────────────

-- F2: Algorithm version tracking
ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS feature_factory_version VARCHAR(32) NOT NULL DEFAULT '1.0.0';

COMMENT ON COLUMN feature_vectors.feature_factory_version IS
    'Algorithm version from FEATURE_FACTORY_VERSION in feature_factory.py.
     Bump on any compute change to prevent mixing IC estimates across algorithm versions.
     DEFAULT ''1.0.0'' applies to existing rows written before this migration.';

-- F7: Bar close timestamp for forward return next-bar lookup
ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS bar_close_ts TIMESTAMPTZ;

COMMENT ON COLUMN feature_vectors.bar_close_ts IS
    'Bar close timestamp. For intraday TFs: bar_ts + TF duration.
     For 1d: bar_ts + 1 day (daily bar closes at midnight UTC).
     NULL on pre-migration rows. Consider NOT NULL constraint in Phase 139.';

-- F11: Extended momentum features
ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS momentum_z_slow DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.momentum_z_slow IS
    'Slow-scale return z-score (APR: feature.momentum.window_slow, default 60 bars).
     NULL on pre-migration rows written before 138-P1.';

ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS momentum_reversal_z DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.momentum_reversal_z IS
    '1-bar log return z-score. Concept-named: captures short-term price shock magnitude.
     NULL on pre-migration rows written before 138-P1.';

-- F12: Calendar features
ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS quarter_position DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.quarter_position IS
    'Position within calendar quarter [0, 1]. Captures earnings/rebalancing cycle.
     NULL on pre-migration rows written before 138-P1.';

ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS days_to_month_end DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.days_to_month_end IS
    'Normalized days remaining to month end [0, 1]. Captures window-dressing / month-turn effect.
     NULL on pre-migration rows written before 138-P1.';

-- F9: Cross-sectional rank features (populated by Phase 139 enrichment pass)
ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS momentum_rank_z DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.momentum_rank_z IS
    'Cross-sectional momentum rank z-score across active universe.
     NULL = not yet enriched (populated in Phase 139 enrichment pass).';

ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS volume_rank_z DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.volume_rank_z IS
    'Cross-sectional volume rank z-score across active universe.
     NULL = not yet enriched (populated in Phase 139 enrichment pass).';

ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS volatility_rank_z DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.volatility_rank_z IS
    'Cross-sectional volatility rank z-score across active universe.
     NULL = not yet enriched (populated in Phase 139 enrichment pass).';

-- ── batch_job_checkpoints table ────────────────────────────────────────────────
-- Checkpoint store for BaseBatch subclasses.
-- BaseBatch._write_checkpoint() upserts here; _read_checkpoint() reads at startup.

CREATE TABLE IF NOT EXISTS batch_job_checkpoints (
    job_key   TEXT        PRIMARY KEY,
    state     JSONB       NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE batch_job_checkpoints IS
    'Persistent checkpoint store for BaseBatchComputer subclasses.
     job_key identifies the job (e.g. backfill_feature_factory:SPY:5m).
     state carries arbitrary JSONB (last completed bar_ts, row counts, etc).
     updated_at tracks last write for staleness detection.';

COMMENT ON COLUMN batch_job_checkpoints.job_key IS
    'Unique job identifier. Format: <class_name>:<symbol>:<tf> or <class_name>:<phase>.';

COMMENT ON COLUMN batch_job_checkpoints.state IS
    'Arbitrary JSONB state blob. Schema defined by the BaseBatch subclass.';
