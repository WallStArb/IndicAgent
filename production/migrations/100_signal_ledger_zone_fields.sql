-- Migration 100: confirm entry_zone_low / entry_zone_high columns exist on signal_ledger
-- These columns were added in migration 095. This migration is a no-op safety check.
-- Run before deploying the signal_writer_agent zone field fix (Plan 107.5-02).
--
-- DDL only — no DML. Backfill of historical NULLs is in 107.5-03-PLAN.md (separate DML script).

BEGIN;

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS entry_zone_low  numeric,
    ADD COLUMN IF NOT EXISTS entry_zone_high numeric;

COMMIT;
