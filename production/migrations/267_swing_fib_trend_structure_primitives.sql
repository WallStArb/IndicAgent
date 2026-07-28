-- Migration 267: Swing/Fib/Trend/Session Structure Primitives — Phase 165 Plan 01
--
-- Establishes the complete data contract for 41 Phase 165 swing/fib/trend/session
-- primitives ported from 5 archived v2.x i3_structure plugins: swing_detector.py,
-- trend_structure.py, swing_momentum.py, fibonacci_zones.py, session_levels.py.
-- Adds 41 new feature_vectors columns (ALL ATR-distance / bounded / count /
-- categorical -- NEVER a raw price level or raw bar index, per D-02/D-04: the
-- dropped names are swing_high, swing_low, swing_high_idx, swing_low_idx,
-- fib_swing_high, fib_swing_low, fib_236, fib_382, fib_500, fib_618, fib_786,
-- nearest_fib_level, nearest_session_level, and the raw prior_session_*/
-- overnight_*/weekly_*/asian_session_* levels), 41 matching feature_registry
-- rows, and feature.swing.*/feature.trend_structure.*/feature.swing_momentum.*/
-- feature.fib.*/feature.session_levels.* APR keys for every hardcoded numeric
-- constant found in the 5 archived plugin files (migrate-as-you-go, CLAUDE.md).
--
-- This plan (Phase 165 Plan 01) is contract-only: all 41 FeatureVector fields
-- are threaded through _build_feature_vector as None placeholders. Plans 02-04
-- replace the placeholders with real computed values -- no schema/registry/
-- persistence churn in the compute plans.
--
-- D-01 nullable-field fix: unlike a literal port, every field here is
-- `float | None` with NO numeric default. The archived swing_detector.py/
-- trend_structure.py emit fake-plausible numeric placeholders
-- (trend_direction=0.0, price_position=0.5, swing_high_type=0.0) whenever
-- insufficient data exists to measure anything real -- the exact
-- silent-wrong-answer shape that made poc_dist_atr/va_position/sr_support_dist/
-- sr_resist_dist sit at constant defaults and score ic_value=0 across 5,510
-- cells before Phase 163 caught it (todo 153). Every NULL condition is spelled
-- out per-column below and in the COMMENT ON COLUMN text.
--
-- Migration numbering: verified next-free via
-- `ls production/migrations/ | sort -V | tail -3` at execution time --
-- 266_smc_institutional_footprint.sql (Phase 164) was the prior max, so 267 is
-- confirmed free (no collision this time, unlike migration 255's 243->255 or
-- migration 266's 259->266 renumbering).
--
-- Column type: DOUBLE PRECISION, matching every feature_vectors column added
-- since migration 201 (no `real` columns exist in this table). ADD COLUMN with
-- a NULL default against the compressed hypertable is metadata-only (no
-- decompress_chunk() step). Historical backfill of these 41 columns is
-- deferred to the single consolidated 163/164/165 `backfill_feature_factory.py
-- --compute-only --refresh` pass (todo 176), not this migration.
--
-- feature_registry.group_name: 'session' (live CHECK constraint
-- feature_registry_group_name_check enumerates {momentum, volume, volatility,
-- structure, session, oscillator, calendar, cross_tf, macro, regime, control};
-- 'session' is a member, confirmed live, matches 165-CONTEXT.md's canonical_refs).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 41 new swing/fib/trend/session columns
-- ---------------------------------------------------------------------------

-- Swing Detection (7, Plan 02, D-01/D-02)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_high_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_low_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_high_type DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_low_type DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_pattern DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_high_age_bars DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_low_age_bars DOUBLE PRECISION;
-- Trend Structure (6, Plan 02, D-01 nullable-fix)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS trend_direction DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS trend_strength DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS trend_leg_count DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS structure_integrity DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS price_position DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS trend_duration_bars DOUBLE PRECISION;
-- Swing Momentum (8, Plan 03, D-03/D-15)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_amplitude_ratio DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_amplitude_expanding DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_amplitude_intensity DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_velocity_bars DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_velocity_bias DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS struct_energy DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS struct_accel_bias DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS swing_volume_confirmation DOUBLE PRECISION;
-- Fibonacci Zones (4, Plan 03, D-04/D-05)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_fib_ratio DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_fib_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS fib_cluster_strength DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS in_fib_discount_zone DOUBLE PRECISION;
-- Session Levels (16, Plan 04, D-07/D-08/D-09/D-13)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS prior_session_high_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS prior_session_low_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS prior_session_close_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS overnight_high_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS overnight_low_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS overnight_range_pct DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS opening_gap_pct DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS weekly_pivot_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS weekly_r1_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS weekly_r2_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS weekly_s1_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS weekly_s2_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_level_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS asian_session_high_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS asian_session_low_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS gap_filled DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.swing_high_dist_atr IS
    '(most recent confirmed swing high price - close) / ATR. NULL when no confirmed swing high exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_low_dist_atr IS
    '(close - most recent confirmed swing low price) / ATR. NULL when no confirmed swing low exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_high_type IS
    '+1.0 higher-high, -1.0 lower-high (vs. the prior confirmed swing high). NULL when fewer than 2 confirmed swing highs exist in the lookback window. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_low_type IS
    '+1.0 higher-low, -1.0 lower-low (vs. the prior confirmed swing low). NULL when fewer than 2 confirmed swing lows exist in the lookback window. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_pattern IS
    '+1.0 when (higher-high AND higher-low), -1.0 when (lower-high AND lower-low), 0.0 when mixed. NULL when swing_high_type or swing_low_type is NULL. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_high_age_bars IS
    'Bars elapsed since the most recent confirmed swing high. NULL when no confirmed swing high exists. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_low_age_bars IS
    'Bars elapsed since the most recent confirmed swing low. NULL when no confirmed swing low exists. Phase 165.';
COMMENT ON COLUMN feature_vectors.trend_direction IS
    'Dominant swing-leg direction: +1.0 bullish-leg majority, -1.0 bearish-leg majority, 0.0 tie. D-01 nullable fix: NULL (not the archived plugin''s fake 0.0 placeholder) when fewer than 2 confirmed swing highs OR fewer than 2 confirmed swing lows exist in the lookback window -- the archived numeric default is the bug being fixed, not the contract. Phase 165.';
COMMENT ON COLUMN feature_vectors.trend_strength IS
    'Dominant-leg fraction, ATR/price-range scaled, clamped [0,1]. NULL under the same insufficient-swing-count condition as trend_direction (D-01). Phase 165.';
COMMENT ON COLUMN feature_vectors.trend_leg_count IS
    'Count of dominant-direction swing legs in the lookback window. NULL under the same insufficient-swing-count condition as trend_direction (D-01). Phase 165.';
COMMENT ON COLUMN feature_vectors.structure_integrity IS
    '1 - overlap_count / max_overlaps, bounded [0,1] -- measures swing-leg overlap/choppiness. NULL under the same insufficient-swing-count condition as trend_direction (D-01). Phase 165.';
COMMENT ON COLUMN feature_vectors.price_position IS
    '(close - recent swing low) / recent swing range, bounded [0,1]. D-01 nullable fix: NULL (not the archived plugin''s fake 0.5 placeholder) under the same insufficient-swing-count condition as trend_direction. D-12: incremental-IC evaluation MUST screen this against va_position (Phase 163) and premium_discount_pct (Phase 164) as well as bb_pct_b/price_percentile/stoch_k -- three independent implementations of "where is price within the recent range" now exist across two phases. Phase 165.';
COMMENT ON COLUMN feature_vectors.trend_duration_bars IS
    'Bars elapsed since the start of the current directional swing streak. NULL under the same insufficient-swing-count condition as trend_direction (D-01). Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_amplitude_ratio IS
    'Last swing ATR-amplitude / mean ATR-amplitude of the last 3 swings. Unbounded (a single outsized swing can exceed the recent mean by any factor) -- not bounded [0,1], unlike several sibling fields. NULL when fewer than feature.swing_momentum.max_extremes confirmed swing extremes exist. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_amplitude_expanding IS
    '1.0 when the last 3 swing amplitudes are monotonically increasing else 0.0. NULL when fewer than feature.swing_momentum.max_extremes confirmed swing extremes exist. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_amplitude_intensity IS
    'linear_ramp(swing_amplitude_ratio, feature.swing_momentum.intensity_ramp_lo, feature.swing_momentum.intensity_ramp_hi) when swing_amplitude_expanding else 0.0, bounded [0,1]. NULL under the same insufficient-extremes condition as swing_amplitude_ratio. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_velocity_bars IS
    'Bars elapsed for the most recent swing leg. NULL under the same insufficient-extremes condition as swing_amplitude_ratio. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_velocity_bias IS
    '+1.0 accelerating, -1.0 decelerating, 0.0 stable -- D-03 numeric encoding of the archived plugin''s string enum swing_velocity_trend. NULL under the same insufficient-extremes condition as swing_amplitude_ratio. Phase 165.';
COMMENT ON COLUMN feature_vectors.struct_energy IS
    'clamp(swing_amplitude_ratio * speed_factor / feature.swing_momentum.energy_divisor, 0, 1). NULL under the same insufficient-extremes condition as swing_amplitude_ratio. Phase 165.';
COMMENT ON COLUMN feature_vectors.struct_accel_bias IS
    '+1.0 when higher-high AND higher-low swing pattern, -1.0 when lower-high AND lower-low, 0.0 when mixed. NULL under the same insufficient-extremes condition as swing_amplitude_ratio. Phase 165.';
COMMENT ON COLUMN feature_vectors.swing_volume_confirmation IS
    'Mean volume over the most recent confirmed swing leg / mean volume over the lookback window (D-15, zero-marginal-cost addition off computation already happening). NULL under the same insufficient-extremes condition as swing_amplitude_ratio. Phase 165.';
COMMENT ON COLUMN feature_vectors.nearest_fib_ratio IS
    'Which of the 5 canonical Fibonacci retracement ratios (0.236/0.382/0.500/0.618/0.786, APR-exempt definitional constants) is nearest to close, encoded as the ratio value itself. NULL when swing_range <= 0 or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.nearest_fib_dist_atr IS
    'abs(close - nearest fib retracement level) / ATR. NULL when swing_range <= 0 or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.fib_cluster_strength IS
    'Fraction of fib-level pairs within the clustering threshold (feature.fib.cluster_atr_divisor), bounded [0,1]. NULL when swing_range <= 0 or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.in_fib_discount_zone IS
    '1.0 when fib_500 <= close <= fib_786 (the "discount zone" between the 50% and 78.6% retracement levels) else 0.0. NULL when swing_range <= 0 or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.prior_session_high_dist_atr IS
    '(prior session high - close) / ATR. NULL when no completed prior session exists (cold start) or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.prior_session_low_dist_atr IS
    '(close - prior session low) / ATR. NULL when no completed prior session exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.prior_session_close_dist_atr IS
    '(close - prior session close) / ATR. NULL when no completed prior session exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.overnight_high_dist_atr IS
    '(overnight-block high - close) / ATR. NULL when no completed overnight block exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.overnight_low_dist_atr IS
    '(close - overnight-block low) / ATR. NULL when no completed overnight block exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.overnight_range_pct IS
    '(overnight-block high - overnight-block low) / overnight-block low. NULL when no completed overnight block exists. Phase 165.';
COMMENT ON COLUMN feature_vectors.opening_gap_pct IS
    '(current session open - prior session close) / prior session close. NULL when no completed prior session exists (cold start). Phase 165.';
COMMENT ON COLUMN feature_vectors.weekly_pivot_dist_atr IS
    '(close - weekly pivot) / ATR, weekly pivot = (prior week high + prior week low + prior week close) / 3. NULL when no completed prior ISO week exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.weekly_r1_dist_atr IS
    '(weekly R1 - close) / ATR, weekly R1 = 2*pivot - prior week low. NULL when no completed prior ISO week exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.weekly_r2_dist_atr IS
    '(weekly R2 - close) / ATR, weekly R2 = pivot + (prior week high - prior week low). NULL when no completed prior ISO week exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.weekly_s1_dist_atr IS
    '(close - weekly S1) / ATR, weekly S1 = 2*pivot - prior week high. NULL when no completed prior ISO week exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.weekly_s2_dist_atr IS
    '(close - weekly S2) / ATR, weekly S2 = pivot - (prior week high - prior week low). NULL when no completed prior ISO week exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.nearest_level_dist_atr IS
    'abs(close - nearest of the 7 session/weekly levels [prior session high/low/close, weekly pivot/R1/R2/S1/S2]) / ATR. NULL when no level is available or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.asian_session_high_dist_atr IS
    '(Asian-session high - close) / ATR, Asian session = 20:00-04:00 ET (feature.session_levels.asia_start_et_hour/asia_end_et_hour). NULL when no Asian session data exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.asian_session_low_dist_atr IS
    '(close - Asian-session low) / ATR. NULL when no Asian session data exists or ATR <= 0. Phase 165.';
COMMENT ON COLUMN feature_vectors.gap_filled IS
    '1.0 when session_low <= prior_session_close <= session_high at any point since the current session opened (the opening gap has been "filled") else 0.0 (D-13, zero-marginal-cost addition off session-boundary state already tracked). NULL when no completed prior session close exists. Phase 165.';

-- ---------------------------------------------------------------------------
-- 2. feature_registry: 41 new rows (group_name='session', tier='2_theory',
--    added_phase='165')
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase)
VALUES
    ('swing_high_dist_atr', 'session', '2_theory',
     '(nearest confirmed swing high - close) / ATR', 'z_scored', false, false, 'active', '165'),
    ('swing_low_dist_atr', 'session', '2_theory',
     '(close - nearest confirmed swing low) / ATR', 'z_scored', false, false, 'active', '165'),
    ('swing_high_type', 'session', '2_theory',
     'higher-high (+1) / lower-high (-1) vs prior confirmed swing high', 'bounded_signed', false, false, 'active', '165'),
    ('swing_low_type', 'session', '2_theory',
     'higher-low (+1) / lower-low (-1) vs prior confirmed swing low', 'bounded_signed', false, false, 'active', '165'),
    ('swing_pattern', 'session', '2_theory',
     'HH+HL (+1) / LH+LL (-1) / mixed (0)', 'bounded_signed', false, false, 'active', '165'),
    ('swing_high_age_bars', 'session', '2_theory',
     'bars since most recent confirmed swing high', 'unbounded_ratio', false, false, 'active', '165'),
    ('swing_low_age_bars', 'session', '2_theory',
     'bars since most recent confirmed swing low', 'unbounded_ratio', false, false, 'active', '165'),
    ('trend_direction', 'session', '2_theory',
     'dominant swing-leg direction: +1 bullish / -1 bearish / 0 tie', 'bounded_signed', false, false, 'active', '165'),
    ('trend_strength', 'session', '2_theory',
     'dominant-leg fraction, ATR/price-range scaled, [0,1]', 'bounded_unsigned', false, false, 'active', '165'),
    ('trend_leg_count', 'session', '2_theory',
     'count of dominant-direction swing legs', 'unbounded_ratio', false, false, 'active', '165'),
    ('structure_integrity', 'session', '2_theory',
     '1 - overlap_count / max_overlaps, [0,1]', 'bounded_unsigned', false, false, 'active', '165'),
    ('price_position', 'session', '2_theory',
     '(close - recent swing low) / recent swing range, [0,1]', 'bounded_unsigned', false, false, 'active', '165'),
    ('trend_duration_bars', 'session', '2_theory',
     'bars since start of current directional swing streak', 'unbounded_ratio', false, false, 'active', '165'),
    ('swing_amplitude_ratio', 'session', '2_theory',
     'last swing ATR-amplitude / mean of last 3 amplitudes', 'unbounded_ratio', false, false, 'active', '165'),
    ('swing_amplitude_expanding', 'session', '2_theory',
     '1 if last 3 amplitudes monotonically increasing else 0', 'bounded_unsigned', false, false, 'active', '165'),
    ('swing_amplitude_intensity', 'session', '2_theory',
     'linear_ramp(amplitude_ratio) when expanding else 0, [0,1]', 'bounded_unsigned', false, false, 'active', '165'),
    ('swing_velocity_bars', 'session', '2_theory',
     'bars elapsed for the most recent swing leg', 'unbounded_ratio', false, false, 'active', '165'),
    ('swing_velocity_bias', 'session', '2_theory',
     'accelerating (+1) / decelerating (-1) / stable (0)', 'bounded_signed', false, false, 'active', '165'),
    ('struct_energy', 'session', '2_theory',
     'clamp(amplitude_ratio * speed_factor / energy_divisor, 0, 1)', 'bounded_unsigned', false, false, 'active', '165'),
    ('struct_accel_bias', 'session', '2_theory',
     'HH+HL (+1) / LH+LL (-1) / mixed (0)', 'bounded_signed', false, false, 'active', '165'),
    ('swing_volume_confirmation', 'session', '2_theory',
     'mean volume over most recent swing leg / mean volume over lookback', 'unbounded_ratio', false, false, 'active', '165'),
    ('nearest_fib_ratio', 'session', '2_theory',
     'nearest of 0.236/0.382/0.500/0.618/0.786 to close', 'bounded_unsigned', false, false, 'active', '165'),
    ('nearest_fib_dist_atr', 'session', '2_theory',
     'abs(close - nearest fib retracement level) / ATR', 'unbounded_ratio', false, false, 'active', '165'),
    ('fib_cluster_strength', 'session', '2_theory',
     'fraction of fib-level pairs within cluster threshold, [0,1]', 'bounded_unsigned', false, false, 'active', '165'),
    ('in_fib_discount_zone', 'session', '2_theory',
     '1 if fib_500 <= close <= fib_786 else 0', 'bounded_unsigned', false, false, 'active', '165'),
    ('prior_session_high_dist_atr', 'session', '2_theory',
     '(prior session high - close) / ATR', 'z_scored', false, false, 'active', '165'),
    ('prior_session_low_dist_atr', 'session', '2_theory',
     '(close - prior session low) / ATR', 'z_scored', false, false, 'active', '165'),
    ('prior_session_close_dist_atr', 'session', '2_theory',
     '(close - prior session close) / ATR', 'z_scored', false, false, 'active', '165'),
    ('overnight_high_dist_atr', 'session', '2_theory',
     '(overnight-block high - close) / ATR', 'z_scored', false, false, 'active', '165'),
    ('overnight_low_dist_atr', 'session', '2_theory',
     '(close - overnight-block low) / ATR', 'z_scored', false, false, 'active', '165'),
    ('overnight_range_pct', 'session', '2_theory',
     '(overnight high - overnight low) / overnight low', 'unbounded_ratio', false, false, 'active', '165'),
    ('opening_gap_pct', 'session', '2_theory',
     '(session open - prior session close) / prior session close', 'z_scored', false, false, 'active', '165'),
    ('weekly_pivot_dist_atr', 'session', '2_theory',
     '(close - weekly pivot) / ATR', 'z_scored', false, false, 'active', '165'),
    ('weekly_r1_dist_atr', 'session', '2_theory',
     '(weekly R1 - close) / ATR', 'z_scored', false, false, 'active', '165'),
    ('weekly_r2_dist_atr', 'session', '2_theory',
     '(weekly R2 - close) / ATR', 'z_scored', false, false, 'active', '165'),
    ('weekly_s1_dist_atr', 'session', '2_theory',
     '(close - weekly S1) / ATR', 'z_scored', false, false, 'active', '165'),
    ('weekly_s2_dist_atr', 'session', '2_theory',
     '(close - weekly S2) / ATR', 'z_scored', false, false, 'active', '165'),
    ('nearest_level_dist_atr', 'session', '2_theory',
     'abs(close - nearest of 7 session/weekly levels) / ATR', 'unbounded_ratio', false, false, 'active', '165'),
    ('asian_session_high_dist_atr', 'session', '2_theory',
     '(Asian-session high - close) / ATR', 'z_scored', false, false, 'active', '165'),
    ('asian_session_low_dist_atr', 'session', '2_theory',
     '(close - Asian-session low) / ATR', 'z_scored', false, false, 'active', '165'),
    ('gap_filled', 'session', '2_theory',
     '1 if session range crossed prior session close since open else 0', 'bounded_unsigned', false, false, 'active', '165')
ON CONFLICT (feature_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. APR keys: feature.swing.* (2) + feature.trend_structure.* (2) +
--    feature.swing_momentum.* (9) + feature.fib.* (2) +
--    feature.session_levels.* (2) = 17 keys, one per hardcoded numeric
--    constant found in the 5 archived i3_structure plugin files
--    (migrate-as-you-go, CLAUDE.md). All values are [conventional]: copied
--    verbatim from the archived plugins' own hardcoded defaults, NOT
--    [rca_analysis]. Not ML learning targets.
--
--    The 5 Fibonacci retracement ratios themselves (0.236/0.382/0.500/0.618/
--    0.786) are APR-EXEMPT -- definitional mathematical constants, same
--    exemption class as "the 5 in momentum_z_5" per CLAUDE.md's APR spec.
--    Do not "fix" this by adding them as config keys.
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.swing.pivot_window',
    'int',
    '5',
    2, 50,
    '[conventional] find_peaks/find_troughs pivot detection neighbor window, shared by swing_detector.py AND trend_structure.py (same underlying call, same value, Plan 02). Deliberately NOT unified with feature.sr.window=10 (Phase 163), which scopes a different S/R clustering operation. Matches the archived plugins'' own neighbor=5 default. Phase 165. Not an ML learning target.'
),
(
    'feature.swing.lookback_bars',
    'int',
    '120',
    20, 1000,
    '[conventional] Bounded causal lookback window (bars) for the shared swing-detection pivot pass (Plan 02). Matches the archived swing_detector.py''s InputSpec(lookback=120). Phase 165. Not an ML learning target.'
),
(
    'feature.trend_structure.atr_strength_divisor',
    'float',
    '5.0',
    0.5, 50.0,
    '[conventional] Divisor in trend_strength = dominant_fraction * (price_range/ATR) / divisor (Plan 02). Matches the archived trend_structure.py''s hardcoded 5.0 divisor. Phase 165. Not an ML learning target.'
),
(
    'feature.trend_structure.range_lookback_bars',
    'int',
    '20',
    5, 200,
    '[conventional] Bar window for the high[-N:]/low[-N:] price-range component of trend_strength''s ATR normalization (Plan 02) -- a second, independent hardcoded constant in trend_structure.py that 165-RESEARCH.md''s Finding A found the prior survey missed (separate from the 5.0 divisor and from feature.swing.pivot_window). Matches the archived file''s hardcoded high[-20:]/low[-20:] slice. Phase 165. Not an ML learning target.'
),
(
    'feature.swing_momentum.confirm_n',
    'int',
    '3',
    1, 20,
    '[conventional] Confirmation-bar count for swing_momentum.py''s own hand-rolled _detect_extremes() (Plan 03) -- deliberately separate from feature.swing.pivot_window (D-06/RESEARCH Finding B: different algorithm, self-contained by design per the archived plugin''s own docstring). Matches the archived plugin''s _CONFIRM_N=3. Phase 165. Not an ML learning target.'
),
(
    'feature.swing_momentum.max_extremes',
    'int',
    '6',
    4, 20,
    '[conventional] Maximum tracked swing extremes for swing_momentum.py (Plan 03). MUST stay EVEN -- represents complete swings (6 = 3 complete swings, an unpaired trailing extreme would be a half-swing). Matches the archived plugin''s _MAX_EXTREMES=6. Phase 165. Not an ML learning target.'
),
(
    'feature.swing_momentum.lookback_bars',
    'int',
    '60',
    20, 1000,
    '[conventional] Bounded causal lookback window (bars) for swing_momentum.py''s _detect_swing_extremes (Plan 03). Matches the archived plugin''s min_lookback/InputSpec(lookback=60). Phase 165. Not an ML learning target.'
),
(
    'feature.swing_momentum.reference_bars',
    'int',
    '20',
    1, 200,
    '[conventional] Reference-window bar count for swing_momentum.py''s velocity/reference calculations (Plan 03). Matches the archived plugin''s _REFERENCE_BARS=20. Phase 165. Not an ML learning target.'
),
(
    'feature.swing_momentum.speed_factor_min',
    'float',
    '0.1',
    0.01, 10.0,
    '[conventional] Lower clamp bound for swing_momentum.py''s speed_factor (Plan 03). Matches the archived plugin''s clamp(..., 0.1, 3.0). Phase 165. Not an ML learning target.'
),
(
    'feature.swing_momentum.speed_factor_max',
    'float',
    '3.0',
    0.1, 100.0,
    '[conventional] Upper clamp bound for swing_momentum.py''s speed_factor (Plan 03). Matches the archived plugin''s clamp(..., 0.1, 3.0). Phase 165. Not an ML learning target.'
),
(
    'feature.swing_momentum.energy_divisor',
    'float',
    '3.0',
    0.1, 100.0,
    '[conventional] Divisor in struct_energy = clamp(amplitude_ratio * speed_factor / divisor, 0, 1) (Plan 03). Matches the archived plugin''s hardcoded /3.0 divisor. Phase 165. Not an ML learning target.'
),
(
    'feature.swing_momentum.intensity_ramp_lo',
    'float',
    '1.0',
    0.0, 100.0,
    '[conventional] Lower bound of the linear_ramp mapping amplitude_ratio to bounded [0,1] swing_amplitude_intensity (Plan 03). Matches the archived plugin''s linear_ramp(amplitude_ratio, 1.0, 2.0). Phase 165. Not an ML learning target.'
),
(
    'feature.swing_momentum.intensity_ramp_hi',
    'float',
    '2.0',
    0.0, 100.0,
    '[conventional] Upper bound of the linear_ramp mapping amplitude_ratio to bounded [0,1] swing_amplitude_intensity (Plan 03). Matches the archived plugin''s linear_ramp(amplitude_ratio, 1.0, 2.0). Phase 165. Not an ML learning target.'
),
(
    'feature.fib.cluster_atr_divisor',
    'float',
    '2.0',
    0.1, 100.0,
    '[conventional] ATR divisor defining the fib-level clustering threshold for fib_cluster_strength (Plan 03). Matches the archived fibonacci_zones.py''s hardcoded atr_14 / 2.0. Phase 165. Not an ML learning target.'
),
(
    'feature.fib.cluster_fallback_divisor',
    'float',
    '20.0',
    0.1, 1000.0,
    '[conventional] Fallback divisor for the fib-clustering threshold, used only when ATR is unavailable (Plan 03). Matches the archived fibonacci_zones.py''s hardcoded swing_range / 20.0. Phase 165. Not an ML learning target.'
),
(
    'feature.session_levels.asia_start_et_hour',
    'int',
    '20',
    0, 23,
    '[conventional] ET hour marking the start of the Asian trading session (Plan 04). Matches the archived session_levels.py''s hour-mask constant (20:00 ET). Phase 165. Not an ML learning target.'
),
(
    'feature.session_levels.asia_end_et_hour',
    'int',
    '4',
    0, 23,
    '[conventional] ET hour marking the end of the Asian trading session (Plan 04). Matches the archived session_levels.py''s hour-mask constant (04:00 ET). Phase 165. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.swing.pivot_window', '5', 1),
    ('feature.swing.lookback_bars', '120', 1),
    ('feature.trend_structure.atr_strength_divisor', '5.0', 1),
    ('feature.trend_structure.range_lookback_bars', '20', 1),
    ('feature.swing_momentum.confirm_n', '3', 1),
    ('feature.swing_momentum.max_extremes', '6', 1),
    ('feature.swing_momentum.lookback_bars', '60', 1),
    ('feature.swing_momentum.reference_bars', '20', 1),
    ('feature.swing_momentum.speed_factor_min', '0.1', 1),
    ('feature.swing_momentum.speed_factor_max', '3.0', 1),
    ('feature.swing_momentum.energy_divisor', '3.0', 1),
    ('feature.swing_momentum.intensity_ramp_lo', '1.0', 1),
    ('feature.swing_momentum.intensity_ramp_hi', '2.0', 1),
    ('feature.fib.cluster_atr_divisor', '2.0', 1),
    ('feature.fib.cluster_fallback_divisor', '20.0', 1),
    ('feature.session_levels.asia_start_et_hour', '20', 1),
    ('feature.session_levels.asia_end_et_hour', '4', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.swing.pivot_window', 1, '5', 'migration_267', 'Seed shared swing-detection pivot window, Phase 165 [conventional]'),
    (NOW(), 'feature.swing.lookback_bars', 1, '120', 'migration_267', 'Seed swing-detection causal lookback, Phase 165 [conventional]'),
    (NOW(), 'feature.trend_structure.atr_strength_divisor', 1, '5.0', 'migration_267', 'Seed trend-strength ATR normalization divisor, Phase 165 [conventional]'),
    (NOW(), 'feature.trend_structure.range_lookback_bars', 1, '20', 'migration_267', 'Seed trend-strength price-range lookback, Phase 165 [conventional]'),
    (NOW(), 'feature.swing_momentum.confirm_n', 1, '3', 'migration_267', 'Seed swing-momentum confirmation-bar count, Phase 165 [conventional]'),
    (NOW(), 'feature.swing_momentum.max_extremes', 1, '6', 'migration_267', 'Seed swing-momentum max tracked extremes, Phase 165 [conventional]'),
    (NOW(), 'feature.swing_momentum.lookback_bars', 1, '60', 'migration_267', 'Seed swing-momentum causal lookback, Phase 165 [conventional]'),
    (NOW(), 'feature.swing_momentum.reference_bars', 1, '20', 'migration_267', 'Seed swing-momentum reference-window bars, Phase 165 [conventional]'),
    (NOW(), 'feature.swing_momentum.speed_factor_min', 1, '0.1', 'migration_267', 'Seed swing-momentum speed-factor lower clamp, Phase 165 [conventional]'),
    (NOW(), 'feature.swing_momentum.speed_factor_max', 1, '3.0', 'migration_267', 'Seed swing-momentum speed-factor upper clamp, Phase 165 [conventional]'),
    (NOW(), 'feature.swing_momentum.energy_divisor', 1, '3.0', 'migration_267', 'Seed swing-momentum struct_energy divisor, Phase 165 [conventional]'),
    (NOW(), 'feature.swing_momentum.intensity_ramp_lo', 1, '1.0', 'migration_267', 'Seed swing-momentum intensity ramp lower bound, Phase 165 [conventional]'),
    (NOW(), 'feature.swing_momentum.intensity_ramp_hi', 1, '2.0', 'migration_267', 'Seed swing-momentum intensity ramp upper bound, Phase 165 [conventional]'),
    (NOW(), 'feature.fib.cluster_atr_divisor', 1, '2.0', 'migration_267', 'Seed fib-cluster ATR divisor, Phase 165 [conventional]'),
    (NOW(), 'feature.fib.cluster_fallback_divisor', 1, '20.0', 'migration_267', 'Seed fib-cluster fallback divisor, Phase 165 [conventional]'),
    (NOW(), 'feature.session_levels.asia_start_et_hour', 1, '20', 'migration_267', 'Seed Asian session start ET hour, Phase 165 [conventional]'),
    (NOW(), 'feature.session_levels.asia_end_et_hour', 1, '4', 'migration_267', 'Seed Asian session end ET hour, Phase 165 [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
