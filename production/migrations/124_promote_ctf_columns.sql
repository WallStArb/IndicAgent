-- Migration 124: promote 4 CTF sub-scores to top-level columns in intelligence_features
--
-- Date: 2026-06-14
-- Description: Promote ctf_score, ctf_trend_alignment, ctf_structure_alignment,
--   ctf_regime_agreement from JSONB (cross_timeframe_context) to top-level nullable
--   double precision columns. Backfills from JSONB using NULLIF to handle
--   null/missing/empty-string variants. Strips the 4 keys from the JSONB column
--   to enforce single source of truth (no dual reads).
--
-- PRE-EXECUTION CHECK: Confirm lifecycle_replay.py has completed before running the
--   backfill UPDATE in statement 2. The DDL (statement 1) is safe against a live table.
--   The backfill UPDATE (statement 2) races with active replay inserts. Run:
--   `ps aux | grep lifecycle_replay` — wait for completion before applying statement 2.
--   The WHERE ctf_score IS NULL guard makes statement 2 safe to re-run after replay.
--
-- Rollout order: apply BEFORE deploying updated feature_writer (Plan 02) and BEFORE
--   intelligence_pipeline restart — columns must exist before any service reads or writes them.
--
-- None semantics: NULL = cold-start (I6 not computed yet); 0.0 = genuine neutral alignment.
--   The IS NULL-only ON CONFLICT guard in feature_writer preserves genuine 0.0 readings.

-- Statement 1: Add 4 nullable CTF columns (online DDL, no table lock at column add)
ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS ctf_score double precision,
    ADD COLUMN IF NOT EXISTS ctf_trend_alignment double precision,
    ADD COLUMN IF NOT EXISTS ctf_structure_alignment double precision,
    ADD COLUMN IF NOT EXISTS ctf_regime_agreement double precision;

-- Statement 2: Backfill from cross_timeframe_context JSONB
-- NULLIF converts empty string to NULL (handles rows with "" instead of missing key).
-- The AND cross_timeframe_context ? 'ctf_score' guard skips rows where the key was
-- never present (avoids incorrectly setting columns to NULL from missing data).
UPDATE intelligence_features
SET ctf_score = NULLIF(cross_timeframe_context->>'ctf_score', '')::double precision,
    ctf_trend_alignment = NULLIF(cross_timeframe_context->>'ctf_trend_alignment', '')::double precision,
    ctf_structure_alignment = NULLIF(cross_timeframe_context->>'ctf_structure_alignment', '')::double precision,
    ctf_regime_agreement = NULLIF(cross_timeframe_context->>'ctf_regime_agreement', '')::double precision
WHERE ctf_score IS NULL
  AND cross_timeframe_context ? 'ctf_score';

-- Statement 3: Strip 4 CTF keys from cross_timeframe_context JSONB
-- After this UPDATE, the JSONB column no longer contains ctf_* keys — single source of truth
-- is now the top-level columns. The array form of the - operator removes multiple keys atomically.
UPDATE intelligence_features
SET cross_timeframe_context = cross_timeframe_context
    - ARRAY['ctf_score', 'ctf_trend_alignment', 'ctf_structure_alignment', 'ctf_regime_agreement']
WHERE cross_timeframe_context ? 'ctf_score';
