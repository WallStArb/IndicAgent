-- Migration 266: SMC Institutional Footprint Primitives — Phase 164 Plan 01
--
-- Establishes the data contract for 8 archived v2.x SMC (Smart Money Concepts)
-- plugins ported to v3 FeatureFactory primitives: order blocks, breaker/mitigation
-- blocks, fair value gaps, liquidity sweeps, liquidity pools, supply/demand zones,
-- BOS/CHoCH, AMD cycle. Adds 36 new feature_vectors columns (ALL ATR-distance /
-- bounded / count / ordinal per the field-by-field raw-price audit in
-- 164-RESEARCH.md — NEVER a raw _top/_bottom/_level/_midpoint column, the exact
-- D-16 mistake Phase 163 had to correct after the fact), 36 matching
-- feature_registry rows, and feature.smc.* APR keys for every hardcoded numeric
-- constant found in the 8 archived plugin files (migrate-as-you-go, CLAUDE.md).
--
-- This plan (Phase 164 Plan 01) is contract-only: all 36 FeatureVector fields
-- are threaded through _build_feature_vector as None placeholders. Plans 02-04
-- replace the placeholders with real computed values -- no schema/registry/
-- persistence churn in the compute plans.
--
-- Migration numbering note: this plan's own text names the file
-- "259_smc_institutional_footprint.sql", but 259 was claimed by a concurrent
-- session's todo-183 fix (259_ic_max_cell_rows_recalibration.sql) before this
-- phase executed -- confirmed and documented in 164-RESEARCH.md's Open Question 3
-- as an expected, anticipated collision (same class as migration 255's own
-- 243-vs-255 renumbering note). 266 is the verified next-free number as of this
-- plan's actual execution (`ls production/migrations/ | sort -V | tail -3`
-- showed 265_hmm_n_components_description_drift_fix.sql as the prior max).
--
-- Column type: DOUBLE PRECISION, matching every feature_vectors column added
-- since migration 201 (migration 255's header documents this convention; no
-- `real` columns exist in this table). ADD COLUMN with a NULL default against
-- the compressed hypertable is metadata-only (no decompress_chunk() step).
--
-- feature_registry.group_name note: 164-RESEARCH.md's A5 assumption
-- recommended 'smart_money' as the group_name value (matching the archived
-- plugins' own capability_tags). Live schema inspection at execution time
-- found `feature_registry_group_name_check` CHECK-constrains group_name to
-- {momentum, volume, volatility, structure, session, oscillator, calendar,
-- cross_tf, macro, regime, control} -- 'smart_money' is not a member and the
-- first apply attempt failed with a CHECK-constraint violation. Corrected to
-- 'structure' (closest semantic fit -- order blocks/zones/BOS-CHoCH are
-- literally market-structure primitives), matching this migration's actual
-- execution. FEATURE_VECTOR_DOMAIN's Python-side tag (feature_factory.py,
-- unconstrained) still uses "smart_money" per A5 -- that is a separate,
-- unconstrained screening vocabulary from the DB's group_name enum.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 36 new smart-money columns
-- ---------------------------------------------------------------------------

-- Order Blocks (4)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ob_bull_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ob_bear_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ob_strength DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ob_mitigated_flag DOUBLE PRECISION;
-- Breaker / Mitigation (3)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS breaker_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS breaker_block_active DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ob_mitigation_pct DOUBLE PRECISION;
-- Fair Value Gap (3)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS fvg_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS fvg_size_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS fvg_open_count DOUBLE PRECISION;
-- Liquidity Sweeps (4)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS sweep_detected DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS sweep_strength DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS reclaim_velocity DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_last_sweep DOUBLE PRECISION;
-- Liquidity Pools (5)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bsl_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ssl_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bsl_touches DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ssl_touches DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS pool_count DOUBLE PRECISION;
-- Supply / Demand Zones (7)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS demand_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS supply_dist_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS demand_freshness DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS supply_freshness DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS active_demand_zones DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS active_supply_zones DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS zone_friction_score DOUBLE PRECISION;
-- BOS / CHoCH (6)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bos_strength DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS choch_strength DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bos_direction DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS choch_direction DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS smc_trend_direction DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_last_shift DOUBLE PRECISION;
-- AMD Cycle (4)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS amd_phase DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS amd_manipulation_detected DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS amd_distribution_direction DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS manip_strength DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.ob_bull_dist_atr IS
    'abs(close - nearest bullish order block midpoint) / ATR. NULL when no active bullish OB exists. Phase 164.';
COMMENT ON COLUMN feature_vectors.ob_bear_dist_atr IS
    'abs(close - nearest bearish order block midpoint) / ATR. NULL when no active bearish OB exists. Phase 164.';
COMMENT ON COLUMN feature_vectors.ob_strength IS
    'Order block strength score from impulse-move volume magnitude, bounded [0,1]. Phase 164.';
COMMENT ON COLUMN feature_vectors.ob_mitigated_flag IS
    '1.0 if the nearest order block has been price-mitigated (fully traded through) else 0.0. Phase 164.';
COMMENT ON COLUMN feature_vectors.breaker_dist_atr IS
    'abs(close - nearest breaker block midpoint) / ATR, derived stateless from order_blocks'' active-OB list within the same compute pass. NULL when no breaker exists. Phase 164.';
COMMENT ON COLUMN feature_vectors.breaker_block_active IS
    '1.0 if a breaker block (mitigated order block acting as flipped support/resistance) is currently active/relevant else 0.0. Phase 164.';
COMMENT ON COLUMN feature_vectors.ob_mitigation_pct IS
    'Fraction of the nearest order block''s range price has retraced, [0,1]: 0.0=fresh, 1.0=fully mitigated (void). Phase 164.';
COMMENT ON COLUMN feature_vectors.fvg_dist_atr IS
    '(close - nearest open fair value gap midpoint) / ATR. NULL when no open FVG exists. Phase 164.';
COMMENT ON COLUMN feature_vectors.fvg_size_atr IS
    '(FVG top - FVG bottom) / ATR for the nearest open fair value gap. NULL when none exists. Phase 164.';
COMMENT ON COLUMN feature_vectors.fvg_open_count IS
    'Count of currently-open (unfilled) fair value gaps in the lookback window. Phase 164.';
COMMENT ON COLUMN feature_vectors.sweep_detected IS
    '1.0 if a liquidity sweep (wick beyond a swing level, then reclaim) fired on this bar else 0.0. Phase 164.';
COMMENT ON COLUMN feature_vectors.sweep_strength IS
    'Bounded [0,1] strength of the most recent liquidity sweep, from wick-beyond depth relative to price (linear_ramp-clamped). Phase 164.';
COMMENT ON COLUMN feature_vectors.reclaim_velocity IS
    'Bounded [0,1] speed of price reclaim following a liquidity sweep. Phase 164.';
COMMENT ON COLUMN feature_vectors.bars_since_last_sweep IS
    'Bar count since the most recent liquidity sweep detection. Phase 164.';
COMMENT ON COLUMN feature_vectors.bsl_dist_atr IS
    '(nearest buy-side liquidity pool level - close) / ATR. NULL when none exists. Phase 164.';
COMMENT ON COLUMN feature_vectors.ssl_dist_atr IS
    '(close - nearest sell-side liquidity pool level) / ATR. NULL when none exists. Phase 164.';
COMMENT ON COLUMN feature_vectors.bsl_touches IS
    'Touch count for the nearest buy-side liquidity pool (equal-highs cluster or session high). Phase 164.';
COMMENT ON COLUMN feature_vectors.ssl_touches IS
    'Touch count for the nearest sell-side liquidity pool (equal-lows cluster or session low). Phase 164.';
COMMENT ON COLUMN feature_vectors.pool_count IS
    'Total distinct liquidity pools (equal-high/equal-low clusters + session high/low) found in the lookback window. PWH/PWL/PDH/PDL descoped -- single-timeframe compute() has no daily-bar access (164-RESEARCH.md). Phase 164.';
COMMENT ON COLUMN feature_vectors.demand_dist_atr IS
    '(close - nearest demand zone midpoint) / ATR. NULL when no active demand zone exists. Phase 164.';
COMMENT ON COLUMN feature_vectors.supply_dist_atr IS
    '(nearest supply zone midpoint - close) / ATR. NULL when no active supply zone exists. Phase 164.';
COMMENT ON COLUMN feature_vectors.demand_freshness IS
    'Bounded [0,1] freshness/decay score of the nearest demand zone (unretested = 1.0, decaying with retest count and age). Phase 164.';
COMMENT ON COLUMN feature_vectors.supply_freshness IS
    'Bounded [0,1] freshness/decay score of the nearest supply zone. Phase 164.';
COMMENT ON COLUMN feature_vectors.active_demand_zones IS
    'Count of currently-active (untouched-to-invalidation) demand zones in the lookback window. Phase 164.';
COMMENT ON COLUMN feature_vectors.active_supply_zones IS
    'Count of currently-active supply zones in the lookback window. Phase 164.';
COMMENT ON COLUMN feature_vectors.zone_friction_score IS
    'Bounded [0,1] composite: freshness * strength * (1/(1+dist_atr)) of the higher-friction nearest zone (demand or supply). Phase 164.';
COMMENT ON COLUMN feature_vectors.bos_strength IS
    'ATR-normalized break-of-structure magnitude: (break close - broken swing level) / ATR, clamped >= 0. Phase 164.';
COMMENT ON COLUMN feature_vectors.choch_strength IS
    'ATR-normalized change-of-character magnitude -- same formula as bos_strength for the opposing-trend break. Phase 164.';
COMMENT ON COLUMN feature_vectors.bos_direction IS
    'Directional sign of the most recent break-of-structure: 1.0=bullish, -1.0=bearish, 0.0=none. Phase 164.';
COMMENT ON COLUMN feature_vectors.choch_direction IS
    'Directional sign of the most recent change-of-character: 1.0=bullish, -1.0=bearish, 0.0=none. Phase 164.';
COMMENT ON COLUMN feature_vectors.smc_trend_direction IS
    'Current market-structure trend direction from 2-swing-point sequencing: 1.0=uptrend, -1.0=downtrend, 0.0=undetermined. Phase 164.';
COMMENT ON COLUMN feature_vectors.bars_since_last_shift IS
    'Bar count since the most recent BOS or CHoCH structural shift. Phase 164.';
COMMENT ON COLUMN feature_vectors.amd_phase IS
    'Ordinal-encoded AMD cycle phase (ICT Accumulation/Manipulation/Distribution): 0.0=unknown, 1.0=accumulation, 2.0=manipulation, 3.0=distribution. UTC-hour-boundary derived (feature.smc.amd.*). Phase 164.';
COMMENT ON COLUMN feature_vectors.amd_manipulation_detected IS
    '1.0 if the AMD manipulation phase detected a stop-hunt (breach of the overnight accumulation range, then reversal) else 0.0. Phase 164.';
COMMENT ON COLUMN feature_vectors.amd_distribution_direction IS
    'Directional sign of the AMD distribution-phase move following manipulation: 1.0=bullish, -1.0=bearish, 0.0=none. Phase 164.';
COMMENT ON COLUMN feature_vectors.manip_strength IS
    'Bounded [0,1] magnitude of the AMD manipulation-phase overnight-range breach, clamped (unbounded ratio in the archived source -- 164-RESEARCH.md Pitfall 3). Phase 164.';

-- ---------------------------------------------------------------------------
-- 2. feature_registry: 36 new rows (group_name='smart_money', added_phase='164')
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase)
VALUES
    ('ob_bull_dist_atr', 'structure', '2_theory',
     'abs(close - nearest bullish OB midpoint) / ATR', 'z_scored', false, false, 'active', '164'),
    ('ob_bear_dist_atr', 'structure', '2_theory',
     'abs(close - nearest bearish OB midpoint) / ATR', 'z_scored', false, false, 'active', '164'),
    ('ob_strength', 'structure', '2_theory',
     'order block impulse-volume strength, bounded [0,1]', 'bounded_unsigned', false, false, 'active', '164'),
    ('ob_mitigated_flag', 'structure', '2_theory',
     '1.0 if nearest OB fully mitigated else 0.0', 'bounded_unsigned', false, false, 'active', '164'),
    ('breaker_dist_atr', 'structure', '2_theory',
     'abs(close - nearest breaker block midpoint) / ATR', 'z_scored', false, false, 'active', '164'),
    ('breaker_block_active', 'structure', '2_theory',
     '1.0 if a breaker block is active/relevant else 0.0', 'bounded_unsigned', false, false, 'active', '164'),
    ('ob_mitigation_pct', 'structure', '2_theory',
     'fraction of nearest OB range retraced by price, [0,1]', 'bounded_unsigned', false, false, 'active', '164'),
    ('fvg_dist_atr', 'structure', '2_theory',
     '(close - nearest open FVG midpoint) / ATR', 'z_scored', false, false, 'active', '164'),
    ('fvg_size_atr', 'structure', '2_theory',
     '(FVG top - FVG bottom) / ATR', 'z_scored', false, false, 'active', '164'),
    ('fvg_open_count', 'structure', '2_theory',
     'count of currently-open fair value gaps', 'unbounded_ratio', false, false, 'active', '164'),
    ('sweep_detected', 'structure', '2_theory',
     '1.0 if a liquidity sweep fired this bar else 0.0', 'bounded_unsigned', false, false, 'active', '164'),
    ('sweep_strength', 'structure', '2_theory',
     'liquidity sweep wick-beyond-depth strength, bounded [0,1]', 'bounded_unsigned', false, false, 'active', '164'),
    ('reclaim_velocity', 'structure', '2_theory',
     'speed of post-sweep price reclaim, bounded [0,1]', 'bounded_unsigned', false, false, 'active', '164'),
    ('bars_since_last_sweep', 'structure', '2_theory',
     'bar count since most recent liquidity sweep', 'unbounded_ratio', false, false, 'active', '164'),
    ('bsl_dist_atr', 'structure', '2_theory',
     '(nearest buy-side liquidity level - close) / ATR', 'z_scored', false, false, 'active', '164'),
    ('ssl_dist_atr', 'structure', '2_theory',
     '(close - nearest sell-side liquidity level) / ATR', 'z_scored', false, false, 'active', '164'),
    ('bsl_touches', 'structure', '2_theory',
     'touch count for nearest buy-side liquidity pool', 'unbounded_ratio', false, false, 'active', '164'),
    ('ssl_touches', 'structure', '2_theory',
     'touch count for nearest sell-side liquidity pool', 'unbounded_ratio', false, false, 'active', '164'),
    ('pool_count', 'structure', '2_theory',
     'total distinct liquidity pools in lookback window', 'unbounded_ratio', false, false, 'active', '164'),
    ('demand_dist_atr', 'structure', '2_theory',
     '(close - nearest demand zone midpoint) / ATR', 'z_scored', false, false, 'active', '164'),
    ('supply_dist_atr', 'structure', '2_theory',
     '(nearest supply zone midpoint - close) / ATR', 'z_scored', false, false, 'active', '164'),
    ('demand_freshness', 'structure', '2_theory',
     'nearest demand zone freshness/decay score, bounded [0,1]', 'bounded_unsigned', false, false, 'active', '164'),
    ('supply_freshness', 'structure', '2_theory',
     'nearest supply zone freshness/decay score, bounded [0,1]', 'bounded_unsigned', false, false, 'active', '164'),
    ('active_demand_zones', 'structure', '2_theory',
     'count of active demand zones in lookback window', 'unbounded_ratio', false, false, 'active', '164'),
    ('active_supply_zones', 'structure', '2_theory',
     'count of active supply zones in lookback window', 'unbounded_ratio', false, false, 'active', '164'),
    ('zone_friction_score', 'structure', '2_theory',
     'freshness * strength * 1/(1+dist_atr) of higher-friction nearest zone, bounded [0,1]', 'bounded_unsigned', false, false, 'active', '164'),
    ('bos_strength', 'structure', '2_theory',
     'break-of-structure magnitude / ATR', 'z_scored', false, false, 'active', '164'),
    ('choch_strength', 'structure', '2_theory',
     'change-of-character magnitude / ATR', 'z_scored', false, false, 'active', '164'),
    ('bos_direction', 'structure', '2_theory',
     'BOS direction: 1.0 bullish / -1.0 bearish / 0.0 none', 'none', false, false, 'active', '164'),
    ('choch_direction', 'structure', '2_theory',
     'CHoCH direction: 1.0 bullish / -1.0 bearish / 0.0 none', 'none', false, false, 'active', '164'),
    ('smc_trend_direction', 'structure', '2_theory',
     'swing-structure trend: 1.0 up / -1.0 down / 0.0 neutral', 'none', false, false, 'active', '164'),
    ('bars_since_last_shift', 'structure', '2_theory',
     'bar count since most recent BOS/CHoCH shift', 'unbounded_ratio', false, false, 'active', '164'),
    ('amd_phase', 'structure', '2_theory',
     'ordinal AMD phase: 0=unknown/1=accum/2=manip/3=distribution', 'none', false, false, 'active', '164'),
    ('amd_manipulation_detected', 'structure', '2_theory',
     '1.0 if manipulation-phase stop-hunt detected else 0.0', 'bounded_unsigned', false, false, 'active', '164'),
    ('amd_distribution_direction', 'structure', '2_theory',
     'distribution-phase direction: 1.0 bullish / -1.0 bearish / 0.0 none', 'none', false, false, 'active', '164'),
    ('manip_strength', 'structure', '2_theory',
     'clamped [0,1] AMD manipulation-phase breach magnitude', 'bounded_unsigned', false, false, 'active', '164')
ON CONFLICT (feature_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. APR keys: feature.smc.* (39 keys, one per hardcoded numeric constant found
--    in the 8 archived smc_context plugin files -- migrate-as-you-go, CLAUDE.md).
--    All values are [conventional]: copied verbatim from the archived plugins'
--    own hardcoded defaults (unvalidated ICT-community conventions), NOT
--    [rca_analysis]. Not ML learning targets. Namespaced feature.smc.<concept>.*
--    per 164-RESEARCH.md A4. Two plugins' ATR-recompute constants (14-bar window
--    in liquidity_pools.py/supply_demand_zones.py, 20-bar std fallback in
--    supply_demand_zones.py) are deliberately NOT ported -- 164-RESEARCH.md's
--    "Don't Hand-Roll" table flags this as an anti-pattern; the already-computed
--    atr_val (threaded into compute() before this SMC block) is reused instead,
--    matching bos_choch.py's own get_atr(features) pattern. price_in_premium/
--    premium_position (liquidity_pools.py) are out of scope entirely (ROADMAP
--    "explicitly excluded" premium_discount), so their constants are not seeded.
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.smc.order_blocks.lookback',
    'int',
    '100',
    50, 500,
    '[conventional] Trailing bar window scanned for order-block impulse+opposing-candle detection. Matches OrderBlocksPlugin''s InputSpec(lookback=100). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.order_blocks.impulse_bars',
    'int',
    '3',
    1, 10,
    '[conventional] Minimum consecutive same-direction candles defining an impulsive move for order-block detection. Matches OrderBlocksPlugin.impulse_bars. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.order_blocks.significant_move_pct',
    'float',
    '0.003',
    0.0001, 0.05,
    '[conventional] Minimum impulse move size, as a fraction of current price, to qualify as significant. Matches OrderBlocksPlugin''s hardcoded 0.3% threshold. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.order_blocks.opposing_candle_lookback',
    'int',
    '10',
    2, 50,
    '[conventional] Bars scanned backward from an impulse''s start to find the last opposing candle (the order block itself). Matches OrderBlocksPlugin''s hardcoded range(...,10,...). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.breaker.lookback',
    'int',
    '10',
    2, 50,
    '[conventional] Trailing bar window for breaker-block derivation from order_blocks'' active-OB list (stateless recompute, no cross-call self._state). Matches BreakerBlocksPlugin''s InputSpec(lookback=10). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.mitigation.lookback',
    'int',
    '10',
    2, 50,
    '[conventional] Trailing bar window for order-block mitigation-percentage tracking. Matches MitigationBlocksPlugin''s InputSpec(lookback=10). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.fvg.lookback',
    'int',
    '100',
    30, 500,
    '[conventional] Trailing bar window scanned for 3-candle fair-value-gap imbalances. Matches FairValueGapPlugin''s InputSpec(lookback=100). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_sweeps.lookback',
    'int',
    '120',
    60, 500,
    '[conventional] Trailing bar window scanned for liquidity sweeps of swing highs/lows. Matches LiquiditySweepsPlugin''s InputSpec(lookback=120). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_sweeps.swing_neighbor',
    'int',
    '5',
    2, 20,
    '[conventional] find_swing_highs/find_swing_lows neighbor window (bars on each side) for swing-point detection ahead of sweep scanning. Matches LiquiditySweepsPlugin.neighbor. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_sweeps.reclaim_bars',
    'int',
    '3',
    1, 20,
    '[conventional] Bars checked after a sweep for reclaim confirmation (price continuing back through the swept level). Matches LiquiditySweepsPlugin.reclaim_bars. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_sweeps.depth_ramp_max_pct',
    'float',
    '2.0',
    0.1, 10.0,
    '[conventional] Upper bound (percent depth) of the linear_ramp mapping sweep wick-beyond depth to bounded [0,1] sweep_strength. Matches LiquiditySweepsPlugin''s hardcoded linear_ramp(depth, 0, 2.0). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max',
    'float',
    '0.5',
    0.05, 2.0,
    '[conventional] Upper bound of the linear_ramp mapping 1/bars_to_reclaim to bounded [0,1] reclaim_velocity. Matches LiquiditySweepsPlugin''s hardcoded linear_ramp(..., 0, 0.5). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_pools.lookback',
    'int',
    '150',
    60, 500,
    '[conventional] Trailing bar window scanned for liquidity-pool levels (equal-highs/lows, session H/L). Matches LiquidityPoolsPlugin''s InputSpec(lookback=150); the plugin''s separate 1d InputSpec (PWH/PWL/PDH/PDL) is descoped per 164-RESEARCH.md''s cross-timeframe-gap finding. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_pools.swing_neighbor',
    'int',
    '5',
    2, 20,
    '[conventional] find_swing_highs/find_swing_lows neighbor window for equal-highs/equal-lows clustering. Matches LiquidityPoolsPlugin''s hardcoded n=5. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_pools.atr_fallback_pct',
    'float',
    '0.002',
    0.0001, 0.05,
    '[conventional] Fallback ATR-as-fraction-of-price used only when the passed-in atr_val is non-positive. Matches LiquidityPoolsPlugin''s hardcoded current_price * 0.002 fallback. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_pools.equal_level_tolerance_atr_mult',
    'float',
    '0.75',
    0.05, 3.0,
    '[conventional] ATR multiple defining the price-clustering tolerance for equal-highs/equal-lows grouping. Matches LiquidityPoolsPlugin''s hardcoded atr * 0.75. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_pools.session_bars',
    'int',
    '390',
    30, 1000,
    '[conventional] Trailing bar count treated as "current session" for session-high/session-low pool levels (390 = one 1m RTH session). Matches LiquidityPoolsPlugin''s hardcoded high[-390:]. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.liquidity_pools.significance_weights',
    'json',
    '{"eq_highs_3":0.75,"eq_lows_3":0.75,"eq_highs_2":0.60,"eq_lows_2":0.60,"session_high":0.50,"session_low":0.50}',
    null, null,
    '[conventional] Per-level-type significance weights for liquidity-pool selection (nearest-significant-level tie-break). Matches LiquidityPoolsPlugin''s _SIG dict, with pwh/pwl/pdh/pdl entries dropped (PWH/PWL/PDH/PDL descoped, no daily-bar access in compute()''s single-tf signature). JSON dict keyed by level-type string. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.lookback',
    'int',
    '150',
    60, 500,
    '[conventional] Trailing bar window scanned for supply/demand zone (Rally-Base-Drop / Drop-Base-Rally) origins. Matches SupplyDemandZonesPlugin''s InputSpec(lookback=150). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.impulse_atr_mult',
    'float',
    '1.5',
    0.1, 10.0,
    '[conventional] ATR multiple a close-to-close move must exceed to qualify as a zone-forming impulse. Matches SupplyDemandZonesPlugin.impulse_atr_mult. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.base_body_ratio',
    'float',
    '0.5',
    0.05, 1.0,
    '[conventional] Maximum body/range ratio for a candle to qualify as part of a zone''s consolidation base. Matches SupplyDemandZonesPlugin.base_body_ratio. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.base_atr_mult',
    'float',
    '1.0',
    0.05, 10.0,
    '[conventional] ATR multiple a base candle''s range must stay under to qualify as consolidation. Matches SupplyDemandZonesPlugin.base_atr_mult. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.max_base_bars',
    'int',
    '5',
    1, 30,
    '[conventional] Maximum consecutive base candles scanned left of an impulse when forming a zone. Matches SupplyDemandZonesPlugin.max_base_bars. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.zone_height_cap_atr_mult',
    'float',
    '2.5',
    0.1, 10.0,
    '[conventional] ATR multiple capping maximum zone height (prevents degenerate oversized zones). Matches SupplyDemandZonesPlugin.zone_height_cap. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.impulse_overlap_atr_mult',
    'float',
    '0.4',
    0.01, 5.0,
    '[conventional] ATR multiple bounding the allowed high/low overlap between an impulse bar and its predecessor. Matches SupplyDemandZonesPlugin''s hardcoded atr * 0.4 overlap check. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.freshness_decay_k',
    'float',
    '0.5',
    0.01, 5.0,
    '[conventional] Decay-rate constant k passed to freshness_decay(test_count, k) for zone freshness scoring. Matches SupplyDemandZonesPlugin''s hardcoded freshness_decay(zone.test_count, k=0.5). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.strength_premium_align_mult',
    'float',
    '1.20',
    1.0, 2.0,
    '[conventional] Zone-strength multiplier applied when a demand/supply zone aligns with the discount/premium side of the current range. Matches SupplyDemandZonesPlugin''s hardcoded s * 1.20. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.strength_fvg_align_mult',
    'float',
    '1.15',
    1.0, 2.0,
    '[conventional] Zone-strength multiplier applied when a fair-value-gap midpoint falls inside the zone. Matches SupplyDemandZonesPlugin''s hardcoded s * 1.15. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.age_penalty_floor',
    'float',
    '0.70',
    0.1, 1.0,
    '[conventional] Minimum age-penalty multiplier floor for zone strength (oldest zones never decay below this). Matches SupplyDemandZonesPlugin''s hardcoded max(0.70, ...). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.age_penalty_window_bars',
    'int',
    '200',
    20, 2000,
    '[conventional] Bar-age normalization window for the zone-strength age penalty. Matches SupplyDemandZonesPlugin''s hardcoded age / 200. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.age_penalty_max_pct',
    'float',
    '0.30',
    0.01, 1.0,
    '[conventional] Maximum fractional age-penalty applied to zone strength as age approaches age_penalty_window_bars. Matches SupplyDemandZonesPlugin''s hardcoded * 0.30. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.zones.max_tracked_zones',
    'int',
    '5',
    1, 20,
    '[conventional] Maximum nearest zones per side (demand/supply) retained after sorting by distance. Matches SupplyDemandZonesPlugin''s hardcoded [:5] slice. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.bos_choch.lookback',
    'int',
    '120',
    60, 500,
    '[conventional] Trailing bar window scanned for break-of-structure / change-of-character swing breaks. Matches BOSCHoCHPlugin''s InputSpec(lookback=120). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.bos_choch.swing_neighbor',
    'int',
    '5',
    2, 20,
    '[conventional] find_swing_highs/find_swing_lows neighbor window for BOS/CHoCH swing-point detection. Matches BOSCHoCHPlugin.neighbor. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.amd.lookback',
    'int',
    '30',
    2, 200,
    '[conventional] Trailing bar window for AMD cycle overnight-range/manipulation state. Matches AMDCyclePlugin''s InputSpec(lookback=30). Phase 164. Not an ML learning target.'
),
(
    'feature.smc.amd.accum_start_utc_hour',
    'int',
    '20',
    0, 23,
    '[conventional] UTC hour marking the start of the AMD Accumulation phase (20:00 UTC = 8pm ET overnight range start). Matches AMDCyclePlugin._ACCUM_START. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.amd.accum_end_utc_hour',
    'int',
    '24',
    1, 24,
    '[conventional] UTC hour marking the end of the AMD Accumulation phase (24 = wraps at midnight UTC). Matches AMDCyclePlugin._ACCUM_END. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.amd.manip_end_utc_hour',
    'int',
    '10',
    0, 23,
    '[conventional] UTC hour marking the end of the AMD Manipulation phase (00:00-10:00 UTC = midnight-5am ET). Matches AMDCyclePlugin._MANIP_END. Phase 164. Not an ML learning target.'
),
(
    'feature.smc.amd.dist_end_utc_hour',
    'int',
    '21',
    0, 23,
    '[conventional] UTC hour marking the end of the AMD Distribution phase (10:00-21:00 UTC = 5am-4pm ET). Matches AMDCyclePlugin._DIST_END. Phase 164. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.smc.order_blocks.lookback', '100', 1),
    ('feature.smc.order_blocks.impulse_bars', '3', 1),
    ('feature.smc.order_blocks.significant_move_pct', '0.003', 1),
    ('feature.smc.order_blocks.opposing_candle_lookback', '10', 1),
    ('feature.smc.breaker.lookback', '10', 1),
    ('feature.smc.mitigation.lookback', '10', 1),
    ('feature.smc.fvg.lookback', '100', 1),
    ('feature.smc.liquidity_sweeps.lookback', '120', 1),
    ('feature.smc.liquidity_sweeps.swing_neighbor', '5', 1),
    ('feature.smc.liquidity_sweeps.reclaim_bars', '3', 1),
    ('feature.smc.liquidity_sweeps.depth_ramp_max_pct', '2.0', 1),
    ('feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max', '0.5', 1),
    ('feature.smc.liquidity_pools.lookback', '150', 1),
    ('feature.smc.liquidity_pools.swing_neighbor', '5', 1),
    ('feature.smc.liquidity_pools.atr_fallback_pct', '0.002', 1),
    ('feature.smc.liquidity_pools.equal_level_tolerance_atr_mult', '0.75', 1),
    ('feature.smc.liquidity_pools.session_bars', '390', 1),
    ('feature.smc.liquidity_pools.significance_weights', '{"eq_highs_3":0.75,"eq_lows_3":0.75,"eq_highs_2":0.60,"eq_lows_2":0.60,"session_high":0.50,"session_low":0.50}', 1),
    ('feature.smc.zones.lookback', '150', 1),
    ('feature.smc.zones.impulse_atr_mult', '1.5', 1),
    ('feature.smc.zones.base_body_ratio', '0.5', 1),
    ('feature.smc.zones.base_atr_mult', '1.0', 1),
    ('feature.smc.zones.max_base_bars', '5', 1),
    ('feature.smc.zones.zone_height_cap_atr_mult', '2.5', 1),
    ('feature.smc.zones.impulse_overlap_atr_mult', '0.4', 1),
    ('feature.smc.zones.freshness_decay_k', '0.5', 1),
    ('feature.smc.zones.strength_premium_align_mult', '1.20', 1),
    ('feature.smc.zones.strength_fvg_align_mult', '1.15', 1),
    ('feature.smc.zones.age_penalty_floor', '0.70', 1),
    ('feature.smc.zones.age_penalty_window_bars', '200', 1),
    ('feature.smc.zones.age_penalty_max_pct', '0.30', 1),
    ('feature.smc.zones.max_tracked_zones', '5', 1),
    ('feature.smc.bos_choch.lookback', '120', 1),
    ('feature.smc.bos_choch.swing_neighbor', '5', 1),
    ('feature.smc.amd.lookback', '30', 1),
    ('feature.smc.amd.accum_start_utc_hour', '20', 1),
    ('feature.smc.amd.accum_end_utc_hour', '24', 1),
    ('feature.smc.amd.manip_end_utc_hour', '10', 1),
    ('feature.smc.amd.dist_end_utc_hour', '21', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.smc.order_blocks.lookback', 1, '100', 'migration_266', 'Seed order-block scan lookback, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.order_blocks.impulse_bars', 1, '3', 'migration_266', 'Seed order-block impulse-bar count, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.order_blocks.significant_move_pct', 1, '0.003', 'migration_266', 'Seed order-block significant-move threshold, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.order_blocks.opposing_candle_lookback', 1, '10', 'migration_266', 'Seed order-block opposing-candle search window, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.breaker.lookback', 1, '10', 'migration_266', 'Seed breaker-block lookback, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.mitigation.lookback', 1, '10', 'migration_266', 'Seed mitigation-block lookback, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.fvg.lookback', 1, '100', 'migration_266', 'Seed FVG scan lookback, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_sweeps.lookback', 1, '120', 'migration_266', 'Seed liquidity-sweep scan lookback, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_sweeps.swing_neighbor', 1, '5', 'migration_266', 'Seed liquidity-sweep swing-detection neighbor window, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_sweeps.reclaim_bars', 1, '3', 'migration_266', 'Seed liquidity-sweep reclaim-confirmation bar count, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_sweeps.depth_ramp_max_pct', 1, '2.0', 'migration_266', 'Seed liquidity-sweep depth-to-strength ramp ceiling, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max', 1, '0.5', 'migration_266', 'Seed liquidity-sweep reclaim-velocity ramp ceiling, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_pools.lookback', 1, '150', 'migration_266', 'Seed liquidity-pool scan lookback, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_pools.swing_neighbor', 1, '5', 'migration_266', 'Seed liquidity-pool swing-detection neighbor window, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_pools.atr_fallback_pct', 1, '0.002', 'migration_266', 'Seed liquidity-pool ATR fallback fraction, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_pools.equal_level_tolerance_atr_mult', 1, '0.75', 'migration_266', 'Seed liquidity-pool equal-level clustering tolerance, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_pools.session_bars', 1, '390', 'migration_266', 'Seed liquidity-pool session-window bar count, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.liquidity_pools.significance_weights', 1, '{"eq_highs_3":0.75,"eq_lows_3":0.75,"eq_highs_2":0.60,"eq_lows_2":0.60,"session_high":0.50,"session_low":0.50}', 'migration_266', 'Seed liquidity-pool per-level-type significance weights, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.lookback', 1, '150', 'migration_266', 'Seed supply/demand zone scan lookback, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.impulse_atr_mult', 1, '1.5', 'migration_266', 'Seed zone impulse-move ATR multiple, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.base_body_ratio', 1, '0.5', 'migration_266', 'Seed zone base-candle body ratio ceiling, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.base_atr_mult', 1, '1.0', 'migration_266', 'Seed zone base-candle range ATR multiple, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.max_base_bars', 1, '5', 'migration_266', 'Seed zone max consolidation-base bar count, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.zone_height_cap_atr_mult', 1, '2.5', 'migration_266', 'Seed zone height cap ATR multiple, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.impulse_overlap_atr_mult', 1, '0.4', 'migration_266', 'Seed zone impulse-bar overlap ATR multiple, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.freshness_decay_k', 1, '0.5', 'migration_266', 'Seed zone freshness decay-rate constant, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.strength_premium_align_mult', 1, '1.20', 'migration_266', 'Seed zone premium/discount alignment strength multiplier, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.strength_fvg_align_mult', 1, '1.15', 'migration_266', 'Seed zone FVG-alignment strength multiplier, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.age_penalty_floor', 1, '0.70', 'migration_266', 'Seed zone age-penalty floor, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.age_penalty_window_bars', 1, '200', 'migration_266', 'Seed zone age-penalty normalization window, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.age_penalty_max_pct', 1, '0.30', 'migration_266', 'Seed zone age-penalty maximum fraction, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.zones.max_tracked_zones', 1, '5', 'migration_266', 'Seed zone max-tracked-zones-per-side cap, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.bos_choch.lookback', 1, '120', 'migration_266', 'Seed BOS/CHoCH scan lookback, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.bos_choch.swing_neighbor', 1, '5', 'migration_266', 'Seed BOS/CHoCH swing-detection neighbor window, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.amd.lookback', 1, '30', 'migration_266', 'Seed AMD cycle lookback, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.amd.accum_start_utc_hour', 1, '20', 'migration_266', 'Seed AMD accumulation-phase start UTC hour, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.amd.accum_end_utc_hour', 1, '24', 'migration_266', 'Seed AMD accumulation-phase end UTC hour, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.amd.manip_end_utc_hour', 1, '10', 'migration_266', 'Seed AMD manipulation-phase end UTC hour, Phase 164 [conventional]'),
    (NOW(), 'feature.smc.amd.dist_end_utc_hour', 1, '21', 'migration_266', 'Seed AMD distribution-phase end UTC hour, Phase 164 [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
