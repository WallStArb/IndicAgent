-- Migration 291: Theory-Motivated Interaction Layer -- Phase 151 Plan 06
--
-- Registers and adds columns for 10 curated, theory-motivated compound
-- features -- the Theory-Motivated Interaction Layer proper. Each is a
-- SINGLE operation (a product) on exactly 2 numeric tier-0 columns, each
-- carrying a one-sentence finance-theory hypothesis in feature_registry
-- .formula_short. ROADMAP's design rules for this layer are explicit: a
-- curated layer, NOT a combinatorial factory -- a ~30K compound candidate
-- pool run through BH-FDR at alpha=0.05 produces ~1,500 expected false
-- discoveries and destroys the correction's power guarantees (the deferred
-- todo 019 design, rejected on statistical-power grounds before this phase
-- existed). Combined with plan 151-05's 5 named candidates and the 8
-- pre-existing live rows, this migration brings the tier=1_interaction
-- population to 23 -- well inside the <=50 cap.
--
-- Migration numbering note: re-verified next-free at execution time
-- (2026-08-05) against both `ls production/migrations/` (highest existing
-- prefix: 290) and `config_history` (no changed_by='migration_291' row
-- exists) before this file's apply -- 291 is genuinely free, no collision
-- with the 287/287 duplicate-prefix pair already tracked separately by
-- todo 260 (not this migration's concern).
--
-- Resolution of 151-RESEARCH.md Open Question 2 (categorical-regime
-- encoding): ROADMAP's candidate-source list names "momentum x
-- low_vol_regime" and "mean-reversion x regime label," but market_regimes
-- and feature_vectors.regime are categorical STRINGS, not numeric
-- FeatureVector columns -- a product needs two numeric operands. Resolved
-- via option (a) from RESEARCH.md: numeric-proxy substitution. Every "x
-- regime" candidate below uses an existing numeric tier-0 regime proxy
-- (hv_ratio for volatility expansion/contraction, adx for trend strength,
-- hurst/variance_ratio_fast for persistence/mean-reversion, vix_z for
-- market-wide volatility, yield_slope_z for term-structure regime). This
-- keeps every compound a persisted numeric column that partial_spearman_ic
-- can screen directly, and avoids opening a second stratification surface
-- alongside the one ic_engine already owns.
--
-- Redundancy pre-check (recorded here, full verdicts in 151-06-SUMMARY.md):
-- queried all 282 live feature_registry rows before writing any code. None
-- of the 10 proposed feature_name values collided with an existing row
-- (verified live). None of the 10 compounds duplicates an existing
-- tier=1_interaction row's exact parent pair -- specific attention paid to
-- the near-neighbour risk the plan itself calls out: a momentum_z_fast *
-- atr_z product would sit uncomfortably close to the existing
-- ret_vol_ratio_fast (ret_lag_fast / atr_z) / ret_vol_product_fast
-- (ret_lag_fast * volume_z) pair -- exactly why hv_ratio (volatility
-- EXPANSION/CONTRACTION) is the chosen volatility-regime proxy here rather
-- than atr_z (volatility LEVEL), and why momentum_z_fast (a z-scored
-- momentum window return) rather than ret_lag_fast (a raw lagged return)
-- is the momentum parent throughout. None of the 3 nullable cross-sectional
-- rank fields (volatility_rank_z/momentum_rank_z/volume_rank_z) is used as
-- a parent -- confirmed live tier='0_atomic' but None at FeatureFactory
-- .compute() time (Phase 139 enrichment-only), which would make any product
-- built on them None for every row the factory writes.
--
-- All 13 named parents verified live tier='0_atomic' AND bound as a local
-- at the FeatureFactory.compute()/compute_batch() constructor call site
-- (via _build_feature_vector, the single shared FeatureVector(...)
-- construction point both paths funnel through).
--
-- No new APR keys in this migration -- every compound is parameterless by
-- the single-operation design rule (a tunable window/threshold/scaling
-- constant would violate it and require an APR key this plan deliberately
-- does not add).
--
-- Finite-guard idiom (Codex code-review MEDIUM finding addressed): each
-- compound is guarded via _guard_counted(), a COUNTED tripwire (increments
-- a named module-level counter on substitution, reported once per
-- compute_batch() call, never per row) -- not a plain
-- np.nan_to_num(..., posinf=0.0, neginf=0.0), which would silently and
-- invisibly collapse a substitution with no trace. Explicit range clipping
-- was deliberately rejected: a float64 product of two z-scores cannot
-- reach +-inf short of roughly 1e154 per factor (structurally unreachable
-- for a real z-score), so math.isfinite firing here is a tripwire against a
-- genuine numerical anomaly, never a value-shaping clamp on an
-- "extreme but valid" number -- and a clip range would itself be a tunable
-- numeric constant the single-operation design rule forbids.
--
-- Column type: DOUBLE PRECISION for all 10 new columns, matching every
-- other feature_vectors column added since migration 201. ADD COLUMN IF
-- NOT EXISTS with no DEFAULT is metadata-only against the compressed
-- hypertable -- no decompression step required (confirmed via migration
-- 197/206/216/255/266/267/287/288/289/290 precedent).
--
-- normalization/linear_ready match the vol_body_product precedent
-- (unbounded_ratio / false) for products of z-scores.
--
-- Phase 170 parity (Section 4 below, added retroactively: this plan was
-- written 2026-07-24, before Phase 170 shipped its dual-write cutover
-- 2026-08-04/05): ic_engine.py's _apply_feature_transitions runs a PARITY
-- PRECONDITION on every corpus pass (Phase 170 Plan 06, T-170-17) that
-- hard-stops if any feature_registry row lacks a concept_registry
-- counterpart. These are tier='1_interaction' rows with real
-- parent_features, so concept_parent edges are required too (migration
-- 283's L-8 join table -- a single parent_concept_id FK cannot represent
-- this). Field mapping matches migration 284's feature-domain seed and
-- migration 290's own Section 4 exactly (derived from the feature_registry
-- rows this migration's own Section 3 just inserted, never re-typed
-- literals, so the tables cannot drift).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 10 new columns
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS momentum_vol_regime_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS momentum_trend_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS breakout_volume_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS reversion_hurst_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS quarter_momentum_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS variance_ratio_momentum_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS illiquidity_momentum_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS yield_slope_momentum_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vix_reversion_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS efficiency_volume_product DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.momentum_vol_regime_product IS
    'momentum_z_fast * hv_ratio. Momentum carries more strongly when realized volatility is contracting than when it is expanding (low-volatility anomaly, Frazzini & Pedersen 2014). Phase 151.';
COMMENT ON COLUMN feature_vectors.momentum_trend_product IS
    'momentum_z_fast * adx. Momentum persists when directional trend strength is high and decays into noise when the tape is choppy. Phase 151.';
COMMENT ON COLUMN feature_vectors.breakout_volume_product IS
    'dist_from_high_fast * volume_z. A breakout confirmed by abnormal volume continues more often than an unconfirmed one. Phase 151.';
COMMENT ON COLUMN feature_vectors.reversion_hurst_product IS
    'momentum_reversal_z * hurst. Short-term reversal is stronger when the series is anti-persistent (Hurst below 0.5) and weaker when it is trending. Phase 151.';
COMMENT ON COLUMN feature_vectors.quarter_momentum_product IS
    'quarter_position * momentum_z_fast. Quarter-end window dressing and dealer gamma unwind amplify existing momentum into the quarter close. Phase 151.';
COMMENT ON COLUMN feature_vectors.variance_ratio_momentum_product IS
    'variance_ratio_fast * momentum_z_fast. Momentum is informative when the variance ratio indicates trending microstructure and is noise when it indicates mean reversion. Phase 151.';
COMMENT ON COLUMN feature_vectors.illiquidity_momentum_product IS
    'amihud_illiq_z * momentum_z_fast. Illiquidity amplifies price impact, so identical order flow moves price further and momentum persists longer. Phase 151.';
COMMENT ON COLUMN feature_vectors.yield_slope_momentum_product IS
    'yield_slope_z * momentum_z_fast. Term-structure regime conditions equity momentum -- the carry-times-term-structure candidate source. Phase 151.';
COMMENT ON COLUMN feature_vectors.vix_reversion_product IS
    'vix_z * momentum_reversal_z. The short-term reversal premium is larger in high-volatility regimes, where liquidity provision is compensated more. Phase 151.';
COMMENT ON COLUMN feature_vectors.efficiency_volume_product IS
    'efficiency_ratio_fast * volume_z. Directional efficiency confirmed by volume distinguishes a real trend from directionless drift. Phase 151.';

-- ---------------------------------------------------------------------------
-- 2. feature_registry: 10 new rows (tier='1_interaction', added_phase='151')
--    Every row supplies exactly 2 non-empty parent_features. formula_short
--    carries the one-sentence hypothesis (not just the arithmetic) --
--    ROADMAP's design rule requires the hypothesis text in formula_short,
--    what makes a surviving compound explainable rather than an
--    unattributable BH-FDR survivor.
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready,
     requires_htf, status, added_phase, parent_features)
VALUES
('momentum_vol_regime_product', 'volatility', '1_interaction',
 'momentum_z_fast * hv_ratio -- Momentum carries more strongly when realized volatility is contracting than when it is expanding (low-volatility anomaly, Frazzini & Pedersen 2014).',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['momentum_z_fast', 'hv_ratio']),
('momentum_trend_product', 'momentum', '1_interaction',
 'momentum_z_fast * adx -- Momentum persists when directional trend strength is high and decays into noise when the tape is choppy.',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['momentum_z_fast', 'adx']),
('breakout_volume_product', 'structure', '1_interaction',
 'dist_from_high_fast * volume_z -- A breakout confirmed by abnormal volume continues more often than an unconfirmed one.',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['dist_from_high_fast', 'volume_z']),
('reversion_hurst_product', 'momentum', '1_interaction',
 'momentum_reversal_z * hurst -- Short-term reversal is stronger when the series is anti-persistent (Hurst below 0.5) and weaker when it is trending.',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['momentum_reversal_z', 'hurst']),
('quarter_momentum_product', 'calendar', '1_interaction',
 'quarter_position * momentum_z_fast -- Quarter-end window dressing and dealer gamma unwind amplify existing momentum into the quarter close.',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['quarter_position', 'momentum_z_fast']),
('variance_ratio_momentum_product', 'volatility', '1_interaction',
 'variance_ratio_fast * momentum_z_fast -- Momentum is informative when the variance ratio indicates trending microstructure and is noise when it indicates mean reversion.',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['variance_ratio_fast', 'momentum_z_fast']),
('illiquidity_momentum_product', 'volume', '1_interaction',
 'amihud_illiq_z * momentum_z_fast -- Illiquidity amplifies price impact, so identical order flow moves price further and momentum persists longer.',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['amihud_illiq_z', 'momentum_z_fast']),
('yield_slope_momentum_product', 'macro', '1_interaction',
 'yield_slope_z * momentum_z_fast -- Term-structure regime conditions equity momentum -- the carry-times-term-structure candidate source.',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['yield_slope_z', 'momentum_z_fast']),
('vix_reversion_product', 'macro', '1_interaction',
 'vix_z * momentum_reversal_z -- The short-term reversal premium is larger in high-volatility regimes, where liquidity provision is compensated more.',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['vix_z', 'momentum_reversal_z']),
('efficiency_volume_product', 'structure', '1_interaction',
 'efficiency_ratio_fast * volume_z -- Directional efficiency confirmed by volume distinguishes a real trend from directionless drift.',
 'unbounded_ratio', false, false, 'active', '151', ARRAY['efficiency_ratio_fast', 'volume_z'])
ON CONFLICT (feature_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Phase 170 parity: concept_registry/concept_gate/concept_parent mirror
--    for this migration's 10 rows (see header note above).
-- ---------------------------------------------------------------------------

INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, control_expectation,
     added_phase, created_at, metadata)
SELECT
    'feature', fr.feature_name, fr.formula_short, fr.status, (fr.status = 'active'),
    fr.group_name, fr.is_control, fr.control_expectation, fr.added_phase, fr.added_at,
    jsonb_strip_nulls(jsonb_build_object(
        'tier', fr.tier, 'formula_short', fr.formula_short, 'normalization', fr.normalization,
        'linear_ready', fr.linear_ready, 'requires_htf', fr.requires_htf,
        'window_apr_keys', to_jsonb(fr.window_apr_keys), 'source_dims', to_jsonb(fr.source_dims),
        'notes', fr.notes, 'apr_namespace', 'feature.'
    ))
FROM feature_registry fr
WHERE fr.feature_name IN (
    'momentum_vol_regime_product', 'momentum_trend_product', 'breakout_volume_product',
    'reversion_hurst_product', 'quarter_momentum_product', 'variance_ratio_momentum_product',
    'illiquidity_momentum_product', 'yield_slope_momentum_product', 'vix_reversion_product',
    'efficiency_volume_product'
)
ON CONFLICT (domain, name) DO NOTHING;

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_metric, min_gate_n,
     fdr_required, fdr_alpha)
SELECT cr.concept_id, 'ic_sharpe_hac', 'bootstrap_ci', fr.min_ic_sharpe, fr.min_ic_n,
       fr.fdr_required, fr.fdr_alpha
FROM feature_registry fr
JOIN concept_registry cr ON cr.domain = 'feature' AND cr.name = fr.feature_name
WHERE fr.feature_name IN (
    'momentum_vol_regime_product', 'momentum_trend_product', 'breakout_volume_product',
    'reversion_hurst_product', 'quarter_momentum_product', 'variance_ratio_momentum_product',
    'illiquidity_momentum_product', 'yield_slope_momentum_product', 'vix_reversion_product',
    'efficiency_volume_product'
)
ON CONFLICT (concept_id) DO NOTHING;

INSERT INTO concept_parent (child_concept_id, parent_concept_id)
SELECT child.concept_id, parent.concept_id
FROM feature_registry fr
CROSS JOIN LATERAL unnest(fr.parent_features) AS pf(parent_name)
JOIN concept_registry child  ON child.domain = 'feature' AND child.name = fr.feature_name
JOIN concept_registry parent ON parent.domain = 'feature' AND parent.name = pf.parent_name
WHERE fr.feature_name IN (
    'momentum_vol_regime_product', 'momentum_trend_product', 'breakout_volume_product',
    'reversion_hurst_product', 'quarter_momentum_product', 'variance_ratio_momentum_product',
    'illiquidity_momentum_product', 'yield_slope_momentum_product', 'vix_reversion_product',
    'efficiency_volume_product'
)
ON CONFLICT DO NOTHING;

COMMIT;
