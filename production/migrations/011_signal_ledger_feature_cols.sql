-- Add feature linkage columns to signal_ledger
-- Version: 1.0.0
-- Last Updated: 2026-02-23
-- Status: Current
--
-- Purpose:
--   Enables JOIN from signal_ledger to intelligence_features on (symbol, feature_ts, feature_tf).
--   A signal with feature_ts IS NOT NULL was generated from a known IntelligenceEvent — the full
--   feature context is available in intelligence_features for ML training.
--
-- Design decisions:
--   - Both columns NULLABLE — historical signals (before Phase 2) will have NULL feature_ts/feature_tf.
--     This is correct behavior; do NOT add NOT NULL constraints.
--   - Partial index only covers rows with feature linkage (post-Phase 2 signals) — avoids
--     indexing the potentially large set of NULL rows from pre-Phase-2 backfill.
--   - safe to run on an existing signal_ledger hypertable with data (ADD COLUMN IF NOT EXISTS,
--     nullable columns with no default are TimescaleDB-safe for existing chunks)

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS feature_ts  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS feature_tf  TEXT;

-- Partial index — only covers rows that have feature linkage (post-Phase 2 signals)
CREATE INDEX IF NOT EXISTS idx_ledger_feature_ts
    ON signal_ledger (feature_ts)
    WHERE feature_ts IS NOT NULL;
