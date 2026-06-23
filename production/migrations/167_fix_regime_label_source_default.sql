-- Migration 167: Fix regime_label_source DEFAULT per Phase 138 council review (2026-06-22)
--
-- Council decision: regime_label_source DEFAULT is 'forward_filter' (not 'filtered')
-- in both forward_returns and feature_ic_scores.
--
-- forward_returns was created correctly (migration 160).
-- feature_ic_scores had the wrong DEFAULT 'filtered' but all data rows have the
-- correct value 'forward_filter' because the writer code explicitly set it.
--
-- This migration aligns the schema DEFAULT with the council decision and
-- the actual data, preventing silent incorrect defaults in future writes.

-- Fix feature_ic_scores default
ALTER TABLE feature_ic_scores
    ALTER COLUMN regime_label_source SET DEFAULT 'forward_filter';

-- Add comment documenting the council decision
COMMENT ON COLUMN feature_ic_scores.regime_label_source IS
    'Regime label source: forward_filter = forward-filter HMM only (causal, no future leakage). Council decision 2026-06-22: default is forward_filter, not filtered.';
