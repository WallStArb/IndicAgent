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

COMMIT;
