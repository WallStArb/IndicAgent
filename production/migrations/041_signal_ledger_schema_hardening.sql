-- Migration: signal_ledger schema hardening
-- Phase 39 — DB foundation for ML training data quality
-- Idempotent: all ADD COLUMN and ADD CONSTRAINT use IF NOT EXISTS / DO NOTHING guards

-- Temporarily increase decompression limit for large UPDATE on compressed hypertable
SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;  -- Unlimited

BEGIN;

-- 1. Regular column: effective_ts (populated by trigger)
-- COALESCE(signal_computed_at, feature_ts) — the canonical "when this signal was produced"
-- Fallback approach: regular column + trigger (generated columns not supported with compression)
ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS effective_ts timestamptz;

-- 2. Regular column: pipeline_lag_ms (populated by trigger)
-- EXTRACT(EPOCH FROM (signal_computed_at - feature_ts)) * 1000
-- Instruments pipeline latency at the row level — "instrument everything"
-- NULL when signal_computed_at IS NULL (pending signals not yet processed by aggregator)
ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS pipeline_lag_ms double precision;

-- 3. Migrate legacy status values BEFORE adding constraint
-- Legacy values stopped_out, target_*_hit were active signals with outcomes captured elsewhere
-- This must run BEFORE adding the CHECK constraint or it will fail validation
UPDATE signal_ledger
SET status = 'active'
WHERE status IN ('stopped_out', 'target_1_hit', 'target_2_hit', 'target_3_hit');

-- 4. CHECK constraint: status must be a known value
-- Complements the code-level SignalStatus enum from Phase 39.1
-- Values: 'pending', 'active', 'regime_suppressed' (active lifecycle states)
--   'expired' (legacy terminal state — historical data only)
-- Note: Legacy status values (stopped_out, target_*_hit) were migrated to 'active'
--   with their outcome captured in the outcome column
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'signal_ledger'::regclass
      AND conname = 'chk_signal_ledger_status'
  ) THEN
    ALTER TABLE signal_ledger
      ADD CONSTRAINT chk_signal_ledger_status
      CHECK (status IN ('pending', 'active', 'regime_suppressed', 'expired'));
  END IF;
END $$;

-- 4. CHECK constraint: direction must be -1 (SHORT) or 1 (LONG)
-- Note: direction column is smallint, not text (plan assumption corrected)
-- Values: -1 = SHORT, 1 = LONG (from position_sizer.py documentation)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'signal_ledger'::regclass
      AND conname = 'chk_signal_ledger_direction'
  ) THEN
    ALTER TABLE signal_ledger
      ADD CONSTRAINT chk_signal_ledger_direction
      CHECK (direction IN (-1, 1));
  END IF;
END $$;

-- 5. Trigger function to populate effective_ts and pipeline_lag_ms
CREATE OR REPLACE FUNCTION update_signal_ledger_derived_columns()
RETURNS TRIGGER AS $$
BEGIN
  NEW.effective_ts := COALESCE(NEW.signal_computed_at, NEW.feature_ts);

  IF NEW.signal_computed_at IS NOT NULL AND NEW.feature_ts IS NOT NULL THEN
    NEW.pipeline_lag_ms := EXTRACT(EPOCH FROM (NEW.signal_computed_at - NEW.feature_ts)) * 1000.0;
  ELSE
    NEW.pipeline_lag_ms := NULL;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 6. Drop trigger if exists (for idempotency)
DROP TRIGGER IF EXISTS trg_signal_ledger_derived_columns ON signal_ledger;

-- 7. Create trigger to fire on INSERT and UPDATE
CREATE TRIGGER trg_signal_ledger_derived_columns
  BEFORE INSERT OR UPDATE ON signal_ledger
  FOR EACH ROW
  EXECUTE FUNCTION update_signal_ledger_derived_columns();

-- 8. Backfill existing rows
-- Update all existing rows to populate the new derived columns
UPDATE signal_ledger
SET
  effective_ts = COALESCE(signal_computed_at, feature_ts),
  pipeline_lag_ms = CASE
    WHEN signal_computed_at IS NOT NULL AND feature_ts IS NOT NULL
    THEN EXTRACT(EPOCH FROM (signal_computed_at - feature_ts)) * 1000.0
    ELSE NULL
  END
WHERE effective_ts IS NULL OR pipeline_lag_ms IS NULL;

COMMIT;
