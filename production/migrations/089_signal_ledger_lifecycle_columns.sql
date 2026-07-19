-- Migration 089: Signal Ledger Lifecycle Columns + Clean Start
-- Phase 81: Signal Lifecycle Hardening
-- Date: 2026-05-08
--
-- Adds is_backfill (provenance flag for catch-up signals) and ttl_bars
-- (per-signal TTL window in bars) to support replay auditor and ML training filters.
--
-- TRUNCATE: v0 signal_ledger rows have contaminated entry_price/zones (pre-Phase-79
-- fix) and lack is_backfill provenance. They are not recoverable. Storage cost of
-- contaminated training data exceeds value. After migration, BarReplayProviderAgent
-- regenerates signals from market_data_ohlcv (the ground truth) with v1 schema.
--
-- This migration is irreversible by design.

BEGIN;

-- Step 1: Wipe contaminated v0 history (no backward compatibility — see header)
TRUNCATE TABLE signal_ledger;

-- Step 2: Add new columns with safe defaults
ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS is_backfill BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS ttl_bars    INTEGER NOT NULL DEFAULT 10;

-- Step 3: Index to support replay auditor query:
--   WHERE exit_at IS NULL AND signal_schema_version = 'v1' AND timestamp < NOW() - INTERVAL '2 minutes'
CREATE INDEX IF NOT EXISTS idx_signal_ledger_replay_lookup
  ON signal_ledger (timestamp)
  WHERE exit_at IS NULL;

COMMIT;
