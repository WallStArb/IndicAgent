-- Migration 105: add feature_schema_version column to signal_ledger
--
-- Adds a nullable INTEGER column feature_schema_version with NO default.
-- Pre-fix rows must remain NULL (per D-01 contamination boundary contract).
-- Post-deploy rows written by signal_writer / signal_ledger_repository will
-- carry FEATURE_SCHEMA_VERSION = 2 from the originating IntelligenceEvent.

BEGIN;

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS feature_schema_version INTEGER;

COMMIT;
