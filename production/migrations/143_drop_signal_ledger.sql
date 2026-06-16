-- Migration 143: Phase 130 — Drop signal_ledger monolith and signal_outcomes
--
-- This migration runs AFTER the 48-hour verification window confirms all writers
-- are clean on the 3-table schema (signal_events / trade_frames / trade_executions).
--
-- Sequence per D-04:
--   1. DROP TABLE signal_outcomes (no dependents)
--   2. DROP TABLE signal_ledger CASCADE (drops any remaining dependent objects)
--   3. ALTER VIEW signal_ledger_full RENAME TO signal_ledger
--
-- After this migration:
--   - Any code querying 'signal_ledger' hits the JOIN view (signal_events + trade_frames + trade_executions)
--   - Any code querying 'signal_ledger_full' will break (view no longer exists by that name)
--
-- Reference: .planning/phases/130-script-rewriting/130-CONTEXT.md §D-04

BEGIN;

-- Step 1: Drop signal_outcomes (has no dependents after Phase 130 rewrites)
DROP TABLE IF EXISTS signal_outcomes;

-- Step 2: Drop signal_ledger monolith (CASCADE drops any remaining dependent objects)
DROP TABLE IF EXISTS signal_ledger CASCADE;

-- Step 3: Rename backward-compat view to canonical name
ALTER VIEW signal_ledger_full RENAME TO signal_ledger;

COMMIT;

-- Verification queries:
--   SELECT to_regclass('signal_ledger') IS NOT NULL AS view_exists;
--   SELECT to_regclass('signal_outcomes') IS NULL AS outcomes_dropped;
--   SELECT COUNT(*) FROM pg_views WHERE viewname='signal_ledger_full';  -- should be 0
