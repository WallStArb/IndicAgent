-- Migration 068: Pipeline Hardening & Institutional Foundation
-- Phase 68: Add bar_id trace, attribution columns, unique constraint, clean slate
--
-- DESTRUCTIVE: TRUNCATE signal_ledger removes ALL existing signals.
-- Rationale: All historical signals bypassed regime type filtering
-- (regime_type was numeric HMM value, not plugin class attribute).
-- Keeping them would poison analysis. Clean data starts fresh.

BEGIN;

-- bar_id UUID trace columns
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS bar_id UUID;
ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS bar_id UUID;

-- Attribution vector columns (5-point confidence waterfall)
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS pre_regime_confidence FLOAT;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS pre_tod_confidence FLOAT;

-- HMM regime label (string: "ranging"/"trend"/"unknown")
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS hmm_regime_label TEXT;

-- Agreement count columns (replacing removed confidence boost)
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS n_agreeing_signals INT;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS n_opposing_signals INT;

-- TRUNCATE first: remove duplicates before adding unique constraint.
-- All existing signals had regime_type = numeric HMM value (0/1/2)
-- instead of plugin class attribute ("trend"/"mean_reversion"/"any").
-- Must TRUNCATE before ADD CONSTRAINT or duplicates will cause constraint to fail.
TRUNCATE TABLE signal_ledger;

-- Unique constraint: one signal per (symbol, bar, timeframe, plugin)
-- ADD CONSTRAINT IF NOT EXISTS is not valid PostgreSQL 15 syntax — use DO block.
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_signal_ledger_identity'
    ) THEN
        ALTER TABLE signal_ledger
            ADD CONSTRAINT uq_signal_ledger_identity
            UNIQUE (symbol, feature_ts, feature_tf, setup_plugin);
    END IF;
END $$;

-- Indexes for bar_id lookups
CREATE INDEX IF NOT EXISTS idx_signal_ledger_bar_id ON signal_ledger (bar_id);
CREATE INDEX IF NOT EXISTS idx_intel_features_bar_id ON intelligence_features (bar_id);

COMMIT;
