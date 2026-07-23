-- Migration 255: VP/SR Structural Primitives — Phase 163 Plan 01
--
-- Closes todo 153's schema half: adds 17 new structural feature_vectors columns
-- (12 ATR-normalized/bounded volume-profile fields per D-13/D-16/D-17/D-18, plus 5
-- S/R strength/age/count fields per D-19) alongside the original 4 (poc_dist_atr,
-- va_position, sr_support_dist, sr_resist_dist), which stay unchanged. No raw price
-- levels (poc_price/vah/val/poc_price_rolling/vah_rolling/val_rolling/
-- nearest_hvn_level/nearest_lvn_level) are persisted -- D-16, cross-sectional IC
-- requires stationary, symbol-comparable inputs.
--
-- Migration numbering note: this plan's own text names the file
-- "243_vp_structural_primitives.sql", but 243 was already claimed by a concurrent
-- session's todo-162 fix (243_frame_min_stop_price_fraction.sql, merged to main
-- before this phase executed) and the sequence has since advanced through 254
-- (Phase 166). 255 is the verified next-free number as of this plan's execution --
-- same collision class as migration 216's own numbering note (222/223 vs its
-- original 221 assumption).
--
-- Column type note: this plan's text also specifies `real` (float32) for the new
-- columns, citing migration 201's feature_vectors float64->float32 conversion. Live
-- schema inspection (information_schema.columns) shows migration 201 only converted
-- the 156 columns it explicitly listed -- every column added afterward (migration
-- 197's Renaissance primitives via a since-superseded assumption, migration 216's
-- canary columns) was added as `double precision` and never retroactively
-- converted. All 156+ pre-existing feature_vectors columns are `double precision`
-- today, zero `real` columns exist. This migration follows the columns' actual live
-- type (`double precision`) for consistency with every other column in the table,
-- not the plan's stale assumption.
--
-- feature_registry column note: this plan's text describes an `is_bounded`/
-- `is_directional` column-pair format matching a stale draft of migration 169's
-- schema. The live feature_registry table (confirmed via \d feature_registry) has
-- no such columns -- the real columns are feature_name/group_name/tier/
-- formula_short/normalization/linear_ready/requires_htf/status/added_phase (plus
-- governance columns added by later migrations). This migration inserts rows
-- against the real schema. normalization values follow the live table's existing
-- enum-like convention (z_scored/bounded_unsigned/unbounded_ratio -- there is no
-- CHECK constraint on this column, but 'none' has zero precedent anywhere in the
-- table); the 5 S/R comparable-scalar/count fields use 'unbounded_ratio', matching
-- the existing convention for non-negative unbounded comparable scalars
-- (vol_ratio, garch_ratio) rather than inventing an unprecedented value.
--
-- feature_vectors is a compressed TimescaleDB hypertable. ADD COLUMN with a NULL
-- default is metadata-only (no chunk rewrite, no decompression required) --
-- confirmed via migration 197/206/216 precedent (all used ADD COLUMN IF NOT EXISTS
-- directly against the compressed hypertable with no decompress_chunk() step,
-- unlike migration 201's ALTER COLUMN TYPE which does require decompression). New
-- columns backfill on the next corpus run; no full-table UPDATE here.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 17 new structural columns (12 VP + 5 S/R)
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_hvn_above_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_hvn_below_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_lvn_above_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_lvn_below_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS price_in_value_area DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS in_lvn DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS va_width_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS distance_to_vah_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS distance_to_val_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_hvn_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS poc_rolling_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS poc_session_rolling_divergence_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS resistance_strength DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS support_strength DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS resistance_age_bars DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS support_age_bars DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS sr_level_count DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.nearest_hvn_above_dist_atr IS
    '(nearest HVN bucket price above close - close) / ATR. NULL when no HVN above exists in the session profile. Phase 163.';
COMMENT ON COLUMN feature_vectors.nearest_hvn_below_dist_atr IS
    '(close - nearest HVN bucket price below close) / ATR. NULL when no HVN below exists. Phase 163.';
COMMENT ON COLUMN feature_vectors.nearest_lvn_above_dist_atr IS
    '(nearest LVN bucket price above close - close) / ATR. NULL when no LVN above exists. Phase 163.';
COMMENT ON COLUMN feature_vectors.nearest_lvn_below_dist_atr IS
    '(close - nearest LVN bucket price below close) / ATR. NULL when no LVN below exists. Phase 163.';
COMMENT ON COLUMN feature_vectors.price_in_value_area IS
    '1.0 if VAL <= close <= VAH (session value area) else 0.0. Phase 163.';
COMMENT ON COLUMN feature_vectors.in_lvn IS
    '1.0 if close''s current volume bucket is at/below the LVN threshold (liquidity-void flag, distinct from price_in_value_area per D-17) else 0.0. Phase 163.';
COMMENT ON COLUMN feature_vectors.va_width_atr IS
    '(session VAH - VAL) / ATR. Exact algebraic identity distance_to_vah_atr + distance_to_val_atr (D-17) -- kept as a standalone day-type/balance-vs-trend indicator; known collinearity documented, not silently present. Phase 163.';
COMMENT ON COLUMN feature_vectors.distance_to_vah_atr IS
    '(session VAH - close) / ATR. Phase 163.';
COMMENT ON COLUMN feature_vectors.distance_to_val_atr IS
    '(close - session VAL) / ATR. Phase 163.';
COMMENT ON COLUMN feature_vectors.nearest_hvn_dist_atr IS
    'abs(close - nearest HVN bucket price overall) / ATR. Legacy undirected distance (predates the directional above/below split). Phase 163.';
COMMENT ON COLUMN feature_vectors.poc_rolling_dist_atr IS
    '(close - rolling-track POC price) / ATR. Rolling-track equivalent of poc_dist_atr; diverges from it intraday since the rolling window is a fixed trailing slice while the session window grows from 09:30 ET (D-18). Phase 163.';
COMMENT ON COLUMN feature_vectors.poc_session_rolling_divergence_atr IS
    '(session POC price - rolling-track POC price) / ATR. Session dislocation from the multi-day value anchor (open-drive/trend-day vs balance-day signal). Exact algebraic identity poc_rolling_dist_atr - poc_dist_atr (D-18) -- known collinearity documented, not silently present. Phase 163.';
COMMENT ON COLUMN feature_vectors.resistance_strength IS
    'Volume-weighted resistance cluster strength: sum of min(2.0, member_volume/mean_volume) per cluster member, capped per member, unbounded in aggregate across cluster size. Comparable scalar, not ATR-normalized (not a distance). Phase 163 (D-19).';
COMMENT ON COLUMN feature_vectors.support_strength IS
    'Volume-weighted support cluster strength, same formula as resistance_strength. Phase 163 (D-19).';
COMMENT ON COLUMN feature_vectors.resistance_age_bars IS
    'Bars since the nearest resistance cluster''s most recent touch. Phase 163 (D-19).';
COMMENT ON COLUMN feature_vectors.support_age_bars IS
    'Bars since the nearest support cluster''s most recent touch. Phase 163 (D-19).';
COMMENT ON COLUMN feature_vectors.sr_level_count IS
    'Total distinct resistance+support clusters found in the S/R lookback window. Structural-complexity / consolidation-vs-trending indicator. Phase 163 (D-19).';

-- ---------------------------------------------------------------------------
-- 2. feature_registry: 17 new rows (real schema: feature_name, group_name, tier,
--    formula_short, normalization, linear_ready, requires_htf, status,
--    added_phase -- not the is_bounded/is_directional pair this plan's own text
--    describes, see header note)
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase)
VALUES
    ('nearest_hvn_above_dist_atr', 'session', '2_theory',
     '(nearest HVN price above close - close) / ATR', 'z_scored', false, false, 'active', '163'),
    ('nearest_hvn_below_dist_atr', 'session', '2_theory',
     '(close - nearest HVN price below close) / ATR', 'z_scored', false, false, 'active', '163'),
    ('nearest_lvn_above_dist_atr', 'session', '2_theory',
     '(nearest LVN price above close - close) / ATR', 'z_scored', false, false, 'active', '163'),
    ('nearest_lvn_below_dist_atr', 'session', '2_theory',
     '(close - nearest LVN price below close) / ATR', 'z_scored', false, false, 'active', '163'),
    ('price_in_value_area', 'session', '2_theory',
     '1.0 if VAL <= close <= VAH else 0.0', 'bounded_unsigned', false, false, 'active', '163'),
    ('in_lvn', 'session', '2_theory',
     '1.0 if close bucket volume <= LVN threshold else 0.0', 'bounded_unsigned', false, false, 'active', '163'),
    ('va_width_atr', 'session', '2_theory',
     '(VAH - VAL) / ATR', 'z_scored', false, false, 'active', '163'),
    ('distance_to_vah_atr', 'session', '2_theory',
     '(VAH - close) / ATR', 'z_scored', false, false, 'active', '163'),
    ('distance_to_val_atr', 'session', '2_theory',
     '(close - VAL) / ATR', 'z_scored', false, false, 'active', '163'),
    ('nearest_hvn_dist_atr', 'session', '2_theory',
     'abs(close - nearest HVN price) / ATR (legacy, undirected)', 'z_scored', false, false, 'active', '163'),
    ('poc_rolling_dist_atr', 'session', '2_theory',
     '(close - rolling-track POC price) / ATR', 'z_scored', false, false, 'active', '163'),
    ('poc_session_rolling_divergence_atr', 'session', '2_theory',
     '(session POC price - rolling-track POC price) / ATR', 'z_scored', false, false, 'active', '163'),
    ('resistance_strength', 'session', '2_theory',
     'volume-weighted resistance cluster strength (capped per-member sum)', 'unbounded_ratio', false, false, 'active', '163'),
    ('support_strength', 'session', '2_theory',
     'volume-weighted support cluster strength (capped per-member sum)', 'unbounded_ratio', false, false, 'active', '163'),
    ('resistance_age_bars', 'session', '2_theory',
     'bars since nearest resistance cluster last touch', 'unbounded_ratio', false, false, 'active', '163'),
    ('support_age_bars', 'session', '2_theory',
     'bars since nearest support cluster last touch', 'unbounded_ratio', false, false, 'active', '163'),
    ('sr_level_count', 'session', '2_theory',
     'total distinct S/R clusters in lookback window', 'unbounded_ratio', false, false, 'active', '163')
ON CONFLICT (feature_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. APR keys: feature.session_vp.* (5) + feature.sr.* (3)
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.session_vp.value_area_pct',
    'float',
    '0.70',
    0.10, 0.99,
    '[conventional] Cumulative-volume fraction defining the session value area (VAH/VAL) in the ported ctx_VolumeProfile histogram. Standard market-profile convention. Phase 163. Not an ML learning target.'
),
(
    'feature.session_vp.n_buckets',
    'int',
    '50',
    10, 200,
    '[conventional] Number of price buckets in the session volume-weighted histogram. Matches ctx_VolumeProfile''s existing default. Phase 163. Not an ML learning target.'
),
(
    'feature.session_vp.hvn_threshold',
    'float',
    '0.80',
    0.50, 0.99,
    '[conventional] Volume-hist quantile threshold (top 20% by default) above which a bucket is classified a high-volume node (HVN). Matches ctx_VolumeProfile''s existing default. Phase 163. Not an ML learning target.'
),
(
    'feature.session_vp.lvn_threshold',
    'float',
    '0.20',
    0.01, 0.50,
    '[conventional] Volume-hist quantile threshold (bottom 20% by default) at/below which a bucket is classified a low-volume node (LVN). Matches ctx_VolumeProfile''s existing default. Phase 163. Not an ML learning target.'
),
(
    'feature.session_vp.rolling_window',
    'int',
    '480',
    50, 2000,
    '[conventional] Rolling-track window (bars) for the multi-day POC/VAH/VAL anchor (poc_rolling_dist_atr, poc_session_rolling_divergence_atr). Matches ctx_VolumeProfile''s documented _ROLLING_WINDOW; unlike the archived plugin (capped at <=390 bars in practice by its own InputSpec(lookback=390)), this phase''s stateless bars[-N:] slicing genuinely reaches the full 480-bar window (D-18). Phase 163. Not an ML learning target.'
),
(
    'feature.sr.window',
    'int',
    '10',
    2, 50,
    '[conventional] find_peaks/find_troughs pivot detection window for support/resistance clustering (Plan 03). Matches support_resistance.py''s existing default. Phase 163. Not an ML learning target.'
),
(
    'feature.sr.cluster_atr_mult',
    'float',
    '0.5',
    0.05, 5.0,
    '[conventional] ATR multiple defining the pivot-clustering radius for support/resistance (Plan 03). Matches support_resistance.py''s existing default. Phase 163. Not an ML learning target.'
),
(
    'feature.sr.lookback_by_tf',
    'json',
    '{"1m":60,"5m":60,"15m":80,"1h":120,"1d":60}',
    null, null,
    '[conventional] Per-timeframe bounded lookback window (bars) for support/resistance clustering (Plan 03). Matches support_resistance.py''s existing _LOOKBACK_BY_TF shape. JSON dict keyed by tf string. Phase 163. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.session_vp.value_area_pct', '0.70', 1),
    ('feature.session_vp.n_buckets', '50', 1),
    ('feature.session_vp.hvn_threshold', '0.80', 1),
    ('feature.session_vp.lvn_threshold', '0.20', 1),
    ('feature.session_vp.rolling_window', '480', 1),
    ('feature.sr.window', '10', 1),
    ('feature.sr.cluster_atr_mult', '0.5', 1),
    ('feature.sr.lookback_by_tf', '{"1m":60,"5m":60,"15m":80,"1h":120,"1d":60}', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.session_vp.value_area_pct', 1, '0.70', 'migration_255',
     'Seed session-VP value-area cumulative-volume fraction, Phase 163 [conventional]'),
    (NOW(), 'feature.session_vp.n_buckets', 1, '50', 'migration_255',
     'Seed session-VP histogram bucket count, Phase 163 [conventional]'),
    (NOW(), 'feature.session_vp.hvn_threshold', 1, '0.80', 'migration_255',
     'Seed session-VP HVN quantile threshold, Phase 163 [conventional]'),
    (NOW(), 'feature.session_vp.lvn_threshold', 1, '0.20', 'migration_255',
     'Seed session-VP LVN quantile threshold, Phase 163 [conventional]'),
    (NOW(), 'feature.session_vp.rolling_window', 1, '480', 'migration_255',
     'Seed session-VP rolling-track window, Phase 163 D-18 [conventional]'),
    (NOW(), 'feature.sr.window', 1, '10', 'migration_255',
     'Seed S/R pivot detection window, Phase 163 [conventional]'),
    (NOW(), 'feature.sr.cluster_atr_mult', 1, '0.5', 'migration_255',
     'Seed S/R clustering ATR multiple, Phase 163 [conventional]'),
    (NOW(), 'feature.sr.lookback_by_tf', 1, '{"1m":60,"5m":60,"15m":80,"1h":120,"1d":60}', 'migration_255',
     'Seed S/R per-tf lookback windows, Phase 163 [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
