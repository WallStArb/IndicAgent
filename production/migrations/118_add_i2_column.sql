-- Migration 118: add dedicated i2 JSONB column to intelligence_features
--
-- Date: 2026-06-12
-- Description: Add dedicated i2 JSONB column to intelligence_features;
--   backfill from market_context (minus cross_asset); clean market_context
--   to contain only the cross_asset nested object going forward.
--
-- Note: IF NOT EXISTS guard used because migration 013 (2026-03-01) made a
--   prior ADD COLUMN attempt on another instance; guard prevents failure on
--   duplicate application.
--
-- Backfill note: 72,648 live rows are affected by the UPDATE statements.
--   Historical rows have market_context='{}' and are correctly skipped
--   (i2 starts as '{}' for them, populated on next feature_replay.py run).
--
-- Rollout order: apply BEFORE deploying feature_writer (Plan 4) and BEFORE
--   intelligence_pipeline restart (Plan 1) — column must exist before any
--   service reads or writes it.

-- Statement 1: Add column (online DDL, no table lock at column add)
ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS i2 JSONB NOT NULL DEFAULT '{}';

-- Statement 2: Backfill live rows
-- I2 composite fields are all flat keys in market_context. cross_asset is the
-- only nested object and is NOT an I2 field. The subtraction operator removes it.
UPDATE intelligence_features
SET i2 = (market_context - 'cross_asset')
WHERE market_context != '{}'::jsonb;

-- Statement 3: Clean market_context to cross-asset only
-- After this UPDATE, market_context contains only the cross_asset nested object
-- (or '{}' if cross_asset was never present for that row). Separation is clean.
UPDATE intelligence_features
SET market_context = CASE
    WHEN market_context ? 'cross_asset'
        THEN jsonb_build_object('cross_asset', market_context -> 'cross_asset')
    ELSE '{}'::jsonb
END
WHERE market_context != '{}'::jsonb;
