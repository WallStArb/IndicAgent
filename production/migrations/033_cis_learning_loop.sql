-- Migration 033: CIS learning loop schema foundation — Phase 31
--
-- Sections:
--   1. cis_weights cluster extension (asset_cluster column + new unique index)
--   2. signal_features hypertable (per-signal feature snapshots for ML)
--   3. signal_ledger is_shadow column (shadow-mode infrastructure)
--
-- Also renames n_training_samples → sample_size on cis_weights to align
-- with setup_performance naming convention and the Phase 31 read path.
--
-- All statements are idempotent (IF NOT EXISTS / IF EXISTS).
-- Do NOT use CONCURRENTLY — not supported on hypertables (CLAUDE.md).

-- ============================================================
-- Section 1: cis_weights cluster extension
-- ============================================================

-- Add asset_cluster column for per-cluster weight segmentation.
-- Default 'global' preserves all existing rows as the global cluster.
ALTER TABLE cis_weights ADD COLUMN IF NOT EXISTS asset_cluster TEXT NOT NULL DEFAULT 'global';

-- Rename n_training_samples → sample_size for naming consistency.
-- Only rename if the old column name still exists (idempotent).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'cis_weights' AND column_name = 'n_training_samples'
    ) THEN
        ALTER TABLE cis_weights RENAME COLUMN n_training_samples TO sample_size;
    END IF;
END $$;

-- Drop old unique index (version, symbol, timeframe) — no longer the clustering key.
DROP INDEX IF EXISTS idx_cis_weights_version_symbol;

-- New unique index: (asset_cluster, timeframe, version) — the natural query key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cis_weights_cluster_tf_version
    ON cis_weights (asset_cluster, timeframe, version);

-- ============================================================
-- Section 2: signal_features hypertable
-- ============================================================

-- Per-signal feature snapshot table.
-- Stores the raw feature values and bucket contributions at the time of
-- each I7 signal fire. Enables downstream ML to train on actual inputs.
-- Hypertable on computed_at: 7-day chunks (2× the 1m signal density window).
-- NOTE: TimescaleDB requires the partitioning column (computed_at) to be part
-- of any unique constraint. The primary key therefore includes computed_at.
-- Uniqueness on (signal_id, feature_name) is enforced via the hypertable
-- chunk-level constraint: a given signal fires only once per bar, so
-- (signal_id, feature_name, computed_at) is naturally unique.
CREATE TABLE IF NOT EXISTS signal_features (
    signal_id           UUID          NOT NULL,
    computed_at         TIMESTAMPTZ   NOT NULL,
    feature_name        TEXT          NOT NULL,
    feature_value       DOUBLE PRECISION,
    feature_bucket      TEXT,
    bucket_contribution DOUBLE PRECISION,
    PRIMARY KEY (signal_id, feature_name, computed_at)
);

-- Create hypertable only if the table was just created (idempotent via if_not_exists).
SELECT create_hypertable(
    'signal_features',
    'computed_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Lookup index: fetch all features for a given signal_id ordered by time.
CREATE INDEX IF NOT EXISTS idx_signal_features_signal_id
    ON signal_features (signal_id, computed_at DESC);

-- ============================================================
-- Section 3: signal_ledger shadow column
-- ============================================================

-- is_shadow marks signals fired in shadow mode (no live execution).
-- Partial index on (is_shadow=TRUE) keeps the index small — only shadow
-- signals are queried via this index; live signals use existing indexes.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_signal_ledger_shadow
    ON signal_ledger (is_shadow, symbol, timeframe) WHERE is_shadow = TRUE;
