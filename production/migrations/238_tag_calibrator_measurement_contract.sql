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

-- ── APR keys: alpha.tag_calibrator.* (7 total, F9 rename) ─────────────────────
--
-- 3-table seed pattern (config_schema / config_state / config_history), each
-- ON CONFLICT DO NOTHING, following migration 235's exact pattern.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.tag_calibrator.fdr_alpha',
    'float',
    '0.05',
    0.001, 0.5,
    '[conventional] Benjamini-Hochberg FDR alpha applied run-level across the full measured tag matrix. Statistical governance threshold, not an ML learning target.'
),
(
    'alpha.tag_calibrator.expiry_consecutive_fails',
    'int',
    '3',
    1, 10,
    '[initial_estimate] Consecutive failing runs required before an empirical instrument_tags row is expired (valid_to set); prevents single-run FDR-flicker expiry under weekly re-runs with ~97% window overlap. Not an ML learning target.'
),
(
    'alpha.tag_calibrator.discovery_oos_days',
    'int',
    '63',
    5, 500,
    '[initial_estimate] Out-of-sample days required before a newly discovered (gap-annotated) empirical tag is promoted to a live instrument_tags row. Not an ML learning target.'
),
(
    'alpha.tag_calibrator.min_sample_n',
    'int',
    '60',
    10, 5000,
    '[initial_estimate] Minimum paired-return sample size required before a (symbol, factor_series) loading is measured at all. Not an ML learning target.'
),
(
    'alpha.tag_calibrator.hac_max_lag',
    'int',
    '5',
    1, 60,
    '[conventional] Newey-West Bartlett-kernel max lag for the HAC-adjusted standard error on each measured loading. Not an ML learning target.'
),
(
    'alpha.tag_calibrator.half_life_min_days',
    'int',
    '30',
    1, 3650,
    '[initial_estimate] Lower bound for a per-tag_vocabulary-row half_life_days value; guards against a pathologically fast decay being configured. Not an ML learning target.'
),
(
    'alpha.tag_calibrator.half_life_max_days',
    'int',
    '365',
    1, 3650,
    '[initial_estimate] Upper bound for a per-tag_vocabulary-row half_life_days value; guards against a pathologically slow (effectively permanent) decay being configured. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.tag_calibrator.fdr_alpha', '0.05', 1),
    ('alpha.tag_calibrator.expiry_consecutive_fails', '3', 1),
    ('alpha.tag_calibrator.discovery_oos_days', '63', 1),
    ('alpha.tag_calibrator.min_sample_n', '60', 1),
    ('alpha.tag_calibrator.hac_max_lag', '5', 1),
    ('alpha.tag_calibrator.half_life_min_days', '30', 1),
    ('alpha.tag_calibrator.half_life_max_days', '365', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.tag_calibrator.fdr_alpha', 1, '0.05', 'migration_238', 'Initial value: run-level BH-FDR alpha [conventional]'),
    (NOW(), 'alpha.tag_calibrator.expiry_consecutive_fails', 1, '3', 'migration_238', 'Initial value: expiry hysteresis gate [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.discovery_oos_days', 1, '63', 'migration_238', 'Initial value: discovery-mode OOS gate [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.min_sample_n', 1, '60', 'migration_238', 'Initial value: minimum sample size for measurement [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.hac_max_lag', 1, '5', 'migration_238', 'Initial value: Newey-West HAC max lag [conventional]'),
    (NOW(), 'alpha.tag_calibrator.half_life_min_days', 1, '30', 'migration_238', 'Initial value: half-life lower bound [initial_estimate]'),
    (NOW(), 'alpha.tag_calibrator.half_life_max_days', 1, '365', 'migration_238', 'Initial value: half-life upper bound [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
