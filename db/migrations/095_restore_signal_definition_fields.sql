-- Phase v2.8: restore signal definition fields dropped by 093.
-- entry_price/stop_loss/targets/entry_zone_low/high define WHAT a signal is.
-- They belong in signal_ledger, not only in intelligence_features JSONB.
-- Nullable so existing rows are unaffected; new signals populate on deploy.

BEGIN;

ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS entry_price     NUMERIC,
  ADD COLUMN IF NOT EXISTS stop_loss       NUMERIC,
  ADD COLUMN IF NOT EXISTS targets         JSONB,
  ADD COLUMN IF NOT EXISTS entry_zone_low  NUMERIC,
  ADD COLUMN IF NOT EXISTS entry_zone_high NUMERIC;

COMMIT;
