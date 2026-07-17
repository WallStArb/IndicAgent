-- Migration 238: TagCalibrator measurement-contract schema (D-01, D-10)
--
-- Wave 0/Wave 1 boundary migration for Phase 146 (Empirical Instrument Tag Calibrator).
-- This migration MUST land before the TagCalibrator service (Plan 04) -- the ROADMAP had
-- the service before the migration; D-01 corrects that ordering defect.
--
-- Adds the measurement-contract schema columns the calibration engine reads/writes:
--   tag_vocabulary  -- factor_series, measurement_type, lookback_days, loading_threshold,
--                       half_life_days (the generic (symbol, factor_series, measurement_type)
--                       contract, D-12)
--   instrument_tags -- loading, p_value, bh_adjusted_p, passes_fdr, consecutive_fails,
--                       sample_n, estimated_at, valid_from, valid_to (D-10 expiry columns)
--
-- Does NOT touch instrument_annotations (already has valid_from/valid_to, migration 227).
-- Does NOT touch tag_vocabulary.category's CHECK constraint (already the 6-value set,
-- migration 228 -- Pitfall 4, RESEARCH.md).
-- Does NOT add p_value_threshold or min_r2 (deleted per design-doc F1/F2/F3).

BEGIN;

-- ── tag_vocabulary: measurement-contract columns ──────────────────────────────

ALTER TABLE tag_vocabulary
    ADD COLUMN IF NOT EXISTS factor_series text,
    ADD COLUMN IF NOT EXISTS measurement_type text NOT NULL DEFAULT 'beta_regression'
        CHECK (measurement_type IN (
            'beta_regression', 'correlation', 'cross_correlation',
            'mutual_information', 'definitional'
        )),
    ADD COLUMN IF NOT EXISTS lookback_days int NOT NULL DEFAULT 252,
    ADD COLUMN IF NOT EXISTS loading_threshold float,
    ADD COLUMN IF NOT EXISTS half_life_days int NOT NULL DEFAULT 180;

-- ── instrument_tags: expiry (D-10) + empirical-measurement columns ───────────

ALTER TABLE instrument_tags
    ADD COLUMN IF NOT EXISTS loading float,
    ADD COLUMN IF NOT EXISTS p_value float,
    ADD COLUMN IF NOT EXISTS bh_adjusted_p float,
    ADD COLUMN IF NOT EXISTS passes_fdr boolean,
    ADD COLUMN IF NOT EXISTS consecutive_fails int NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sample_n int,
    ADD COLUMN IF NOT EXISTS estimated_at timestamptz,
    ADD COLUMN IF NOT EXISTS valid_from timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS valid_to timestamptz;
    -- weight (existing, CHECK [0,1]) := |loading|, column unchanged.

COMMIT;
