-- Migration 206: Renaissance Primitives — Phase 142.5
--
-- Shared migration file across Plans 05, 05.5, and 06. Renumbered from the
-- incorrectly planned `db/migrations/177...` — the actual next available
-- migration number, after Phase 143's already-planned 202-205 reservations,
-- is 206. All active migrations live in production/migrations/ (db/migrations
-- only holds legacy 001/120/121).
--
-- This file is created by Plan 05 with the breakout-distance columns (14) and
-- APR seeds (10). Plans 05.5 and 06 append their own sections below — do not
-- assume this file is "done" until Plan 06's section lands (91 columns total,
-- 44 APR seeds, 91 feature_registry rows). See 142.5-PLAN-OUTLINE.md.
--
-- DEPLOYMENT GUARD (Round 2 review M2): do NOT apply this migration to any
-- database (dev, staging, or production) until Plan 06 has appended its
-- remaining columns/seeds/registry rows to this same file. Applying it after
-- Plan 05 alone leaves feature_registry / _REGISTRY_ROW_COUNT inconsistent
-- with the feature_vectors schema.
--
-- All ADD COLUMN statements use IF NOT EXISTS for idempotency. All APR seed
-- inserts use ON CONFLICT (config_key) DO NOTHING (config_schema) and
-- ON CONFLICT (config_key) DO NOTHING (config_state) — matching the exact
-- column signature and idempotency pattern of migration 200
-- (200_hmm_lifecycle_apr_keys.sql). changed_by/reason literals: 'migration-206'.

BEGIN;

-- ---------------------------------------------------------------------------
-- Plan 05: Breakout Distance (14 columns)
--
-- Price structure primitives with no theory: raw distance from recent
-- extremes, range position, and trend purity. Column names match the
-- FeatureVector dataclass field names exactly (src/intelligence/schemas.py).
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS dist_from_high_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS dist_from_high_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS dist_from_low_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS dist_from_low_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS range_pct_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS range_pct_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS new_high_flag DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS new_low_flag DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS stoch_k_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS stoch_k_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS price_percentile_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS price_percentile_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS efficiency_ratio_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS efficiency_ratio_slow DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.dist_from_high_fast IS
    'Distance from rolling high, ATR-normalized: (rolling_high_N - C) / ATR. '
    'Unbounded non-negative. APR: feature.breakout.dist_window_fast.';
COMMENT ON COLUMN feature_vectors.dist_from_high_slow IS
    'Distance from rolling high, ATR-normalized: (rolling_high_N - C) / ATR. '
    'Unbounded non-negative. APR: feature.breakout.dist_window_slow.';
COMMENT ON COLUMN feature_vectors.dist_from_low_fast IS
    'Distance from rolling low, ATR-normalized: (C - rolling_low_N) / ATR. '
    'Unbounded non-negative. APR: feature.breakout.dist_window_fast.';
COMMENT ON COLUMN feature_vectors.dist_from_low_slow IS
    'Distance from rolling low, ATR-normalized: (C - rolling_low_N) / ATR. '
    'Unbounded non-negative. APR: feature.breakout.dist_window_slow.';
COMMENT ON COLUMN feature_vectors.range_pct_fast IS
    'Rolling range as a fraction of price: (rolling_high_N - rolling_low_N) / C. '
    'Unbounded non-negative. APR: feature.breakout.range_window_fast.';
COMMENT ON COLUMN feature_vectors.range_pct_slow IS
    'Rolling range as a fraction of price: (rolling_high_N - rolling_low_N) / C. '
    'Unbounded non-negative. APR: feature.breakout.range_window_slow.';
COMMENT ON COLUMN feature_vectors.new_high_flag IS
    '1.0 if C == rolling_high_N (bar closed at the recent high), else 0.0. '
    'Binary {0,1}. APR: feature.breakout.dist_window_fast.';
COMMENT ON COLUMN feature_vectors.new_low_flag IS
    '1.0 if C == rolling_low_N (bar closed at the recent low), else 0.0. '
    'Binary {0,1}. APR: feature.breakout.dist_window_fast.';
COMMENT ON COLUMN feature_vectors.stoch_k_fast IS
    'Stochastic %K: (C - L_N) / (H_N - L_N). Bounded [0,1]; 0.5 on degenerate '
    'range. APR: feature.breakout.stoch_window_fast.';
COMMENT ON COLUMN feature_vectors.stoch_k_slow IS
    'Stochastic %K: (C - L_N) / (H_N - L_N). Bounded [0,1]; 0.5 on degenerate '
    'range. APR: feature.breakout.stoch_window_slow.';
COMMENT ON COLUMN feature_vectors.price_percentile_fast IS
    'Rolling percentile rank of C_t within the trailing window. Bounded [0,1]. '
    'APR: feature.breakout.percentile_window_fast.';
COMMENT ON COLUMN feature_vectors.price_percentile_slow IS
    'Rolling percentile rank of C_t within the trailing window. Bounded [0,1]. '
    'APR: feature.breakout.percentile_window_slow.';
COMMENT ON COLUMN feature_vectors.efficiency_ratio_fast IS
    'Kaufman efficiency ratio: |C_t - C_t-N| / sum(|C_i - C_i-1|). Bounded '
    '[0,1] (0=chop, 1=linear trend). APR: feature.breakout.efficiency_window_fast.';
COMMENT ON COLUMN feature_vectors.efficiency_ratio_slow IS
    'Kaufman efficiency ratio: |C_t - C_t-N| / sum(|C_i - C_i-1|). Bounded '
    '[0,1] (0=chop, 1=linear trend). APR: feature.breakout.efficiency_window_slow.';

-- Plans 05.5 and 06 append their sections below this line.

COMMIT;
