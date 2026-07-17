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

-- ── Factor-series measurement contract seeding (D-02, D-04, D-05, D-06, D-12) ──
--
-- USE REAL LIVE TAG NAMES (verified live 2026-07-16/17) -- the `_beta`-suffixed shorthand
-- in CONTEXT.md/RESEARCH.md is NOT what the live schema calls these rows.

BEGIN;

-- Single-symbol beta_regression (D-02).
UPDATE tag_vocabulary SET factor_series='TLT', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='rate_sensitive';
UPDATE tag_vocabulary SET factor_series='UUP', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='dollar_strength';
UPDATE tag_vocabulary SET factor_series='FXI', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='china_demand';

-- Long-short beta_regression (encoded as 'LONG-SHORT' so the Plan 04 service parses on
-- the hyphen and calls the shared long_short constructor).
UPDATE tag_vocabulary SET factor_series='HYG-IEF', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='credit_risk';
UPDATE tag_vocabulary SET factor_series='TIP-IEF', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='inflation';
UPDATE tag_vocabulary SET factor_series='IEF-SHY', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='yield_curve';
UPDATE tag_vocabulary SET factor_series='XLE-SPY', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='oil_price';   -- (was "oil_beta")

-- Vol proxy sentinel (D-02/D-08 -- 'volatility' is vol_beta's natural home, kept despite
-- zero holders). 'SPY_REALIZED_VOL' is a sentinel, not a tradeable symbol -- the Plan 04
-- service maps it to breadth_vol's SPY-realized-vol proxy.
UPDATE tag_vocabulary SET factor_series='SPY_REALIZED_VOL', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='volatility';

-- NEW equity-beta concept -- no existing live tag means "this instrument's beta to SPY"
-- (high_beta is a DIFFERENT exposure concept, verified live, must NOT be reused).
INSERT INTO tag_vocabulary (tag, category, description)
    VALUES ('equity_beta', 'sensitivity',
            'Sensitivity (OLS beta) of the instrument''s daily returns to the broad equity '
            'market (SPY); general equity-market-beta, empirically measured.');
UPDATE tag_vocabulary SET factor_series='SPY', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='equity_beta';

-- D-05 free-rider single-symbol proxies (measurable at near-zero marginal cost under the
-- F8 full-matrix loop). Confirmed live 2026-07-17: SMH 3,652 / FXY 4,876 / EEM 5,035
-- tradeable-view bars -- all clear the 252-day lookback by a wide margin.
UPDATE tag_vocabulary SET factor_series='SMH', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='semi_cycle';
UPDATE tag_vocabulary SET factor_series='FXY', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='yen_carry';
UPDATE tag_vocabulary SET factor_series='EEM', measurement_type='beta_regression',
    lookback_days=252, loading_threshold=0.2, half_life_days=180
    WHERE tag='em_flows';

-- OPTION A self-describing sweep (D-12): every remaining row (no factor_series set above)
-- becomes definitional. Resolves the Plan 04 null-factor_series hazard -- the whole schema
-- becomes self-describing: measurement_type='beta_regression' AND factor_series IS NOT NULL
-- <=> a measurable Phase-1 tag; measurement_type='definitional' <=> everything else.
UPDATE tag_vocabulary SET measurement_type='definitional' WHERE factor_series IS NULL;

-- D-06: fed_policy and geopolitical are already caught by the sweep above (factor_series
-- NULL); additionally record an owner annotation (TAG-03). tag_vocabulary has no dedicated
-- owner column -- append to description.
UPDATE tag_vocabulary SET description = description || ' [Owner: project_owner]'
    WHERE tag IN ('fed_policy', 'geopolitical');

-- D-04: seed NO gold-sensitivity tag -- GLD remains a factor-series input only.
-- D-12: no new stratification tags beyond equity_beta -- no tech_beta / GICS-sector rows.

COMMIT;
