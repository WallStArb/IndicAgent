-- Migration 288: Recency/Statistical Atomics -- Phase 151 Plan 03
--
-- Adds todo 180's 11 recency/statistical tier-0 atomic primitives -- the
-- event-recency axis the live 259-row atomic set (as of this session) has
-- zero coverage for. dist_from_high/low_fast/slow (Phase 142.5) cover the
-- MAGNITUDE of distance from a rolling extreme; nothing covers RECENCY.
-- ret_autocorr_1 covers signed-return autocorrelation; nothing covers
-- return-MAGNITUDE autocorrelation (volatility clustering). 11 new
-- feature_vectors columns total: 10 bars_since_* bounded rolling-window
-- recency statistics + abs_ret_autocorr_1.
--
-- Migration numbering note: the plan's own text names the file
-- "261_recency_statistical_atomics.sql" (provisional target as of the
-- plan's 2026-07-24 authoring date). Live inspection at execution time
-- (2026-08-05) shows the sequence has since advanced through 287 (same
-- collision class already documented in migration 255/216/287's own
-- numbering notes) -- 288 is the verified next-free number, checked against
-- both `ls production/migrations/` and `config_history` (no
-- changed_by='migration_288' row exists) before this file's apply.
--
-- Column type: DOUBLE PRECISION for all 11 new columns, matching every
-- other feature_vectors column added since migration 201. ADD COLUMN IF NOT
-- EXISTS with no DEFAULT is metadata-only against the compressed hypertable
-- -- no decompression step required (confirmed via migration 197/206/216/
-- 255/266/267/287 precedent).
--
-- Boundedness (binding design constraint, todo 180 Fable review, restated
-- in 151-RESEARCH.md Pattern 1): every bars_since_* value is BOUNDED in
-- [0, window-1] -- a rolling-window statistic, never an expanding lookback.
-- The saturating convention: bars_since_extreme_move_*/bars_since_vol_spike_*
-- emit window-1 (NOT 0.0, NOT NaN) when no qualifying event occurred inside
-- the trailing window -- 0.0 would falsely assert "an event just happened".
--
-- Phase 170 parity (Section 5 below, same requirement as migration 287's
-- own header note): ic_engine.py's _apply_feature_transitions runs a PARITY
-- PRECONDITION on every corpus pass (Phase 170 Plan 06, T-170-17) that
-- hard-stops if any feature_registry row lacks a concept_registry
-- counterpart. Field mapping matches migration 284's feature-domain seed
-- exactly (derived from the feature_registry rows this migration's own
-- Section 3 just inserted, never re-typed literals, so the two tables
-- cannot drift).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 11 new columns (10 recency + 1 statistical)
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_high_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_high_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_low_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_low_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_52w_high DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_52w_low DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_extreme_move_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_extreme_move_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_vol_spike_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bars_since_vol_spike_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS abs_ret_autocorr_1 DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.bars_since_high_fast IS
    'Bars since rolling-max(high, dist_window_fast) was last attained. Bounded [0, dist_window_fast-1]; 0.0 means the current bar is the extreme. Phase 151.';
COMMENT ON COLUMN feature_vectors.bars_since_high_slow IS
    'Bars since rolling-max(high, dist_window_slow) was last attained. Bounded [0, dist_window_slow-1]; 0.0 means the current bar is the extreme. Phase 151.';
COMMENT ON COLUMN feature_vectors.bars_since_low_fast IS
    'Bars since rolling-min(low, dist_window_fast) was last attained. Bounded [0, dist_window_fast-1]; 0.0 means the current bar is the extreme. Phase 151.';
COMMENT ON COLUMN feature_vectors.bars_since_low_slow IS
    'Bars since rolling-min(low, dist_window_slow) was last attained. Bounded [0, dist_window_slow-1]; 0.0 means the current bar is the extreme. Phase 151.';
COMMENT ON COLUMN feature_vectors.bars_since_52w_high IS
    'Bars since rolling-max(high, high_52w_window) was last attained. Bounded [0, high_52w_window-1]; 0.0 means the current bar is the extreme. Phase 151.';
COMMENT ON COLUMN feature_vectors.bars_since_52w_low IS
    'Bars since rolling-min(low, high_52w_window) was last attained. Bounded [0, high_52w_window-1]; 0.0 means the current bar is the extreme. Phase 151.';
COMMENT ON COLUMN feature_vectors.bars_since_extreme_move_fast IS
    'Bars since |log_ret| > sigma_threshold * rolling_std(|log_ret|, dist_window_fast), fast window. Bounded [0, dist_window_fast-1]; = dist_window_fast-1 (saturating, NOT 0.0/NaN) when no qualifying event occurred inside the rolling window. Phase 151.';
COMMENT ON COLUMN feature_vectors.bars_since_extreme_move_slow IS
    'Bars since |log_ret| > sigma_threshold * rolling_std(|log_ret|, dist_window_slow), slow window. Bounded [0, dist_window_slow-1]; = dist_window_slow-1 (saturating, NOT 0.0/NaN) when no qualifying event occurred inside the rolling window. Phase 151.';
COMMENT ON COLUMN feature_vectors.bars_since_vol_spike_fast IS
    'Bars since rel_volume > vol_spike_threshold, fast window. Bounded [0, dist_window_fast-1]; = dist_window_fast-1 (saturating, NOT 0.0/NaN) when no qualifying event occurred inside the rolling window. Phase 151.';
COMMENT ON COLUMN feature_vectors.bars_since_vol_spike_slow IS
    'Bars since rel_volume > vol_spike_threshold, slow window. Bounded [0, dist_window_slow-1]; = dist_window_slow-1 (saturating, NOT 0.0/NaN) when no qualifying event occurred inside the rolling window. Phase 151.';
COMMENT ON COLUMN feature_vectors.abs_ret_autocorr_1 IS
    'Lag-1 Pearson autocorrelation of |log returns| (volatility clustering) -- distinct from the signed ret_autocorr_1. Bounded [-1, 1] (definitional, no APR). Phase 151.';

-- ---------------------------------------------------------------------------
-- 2. feature_registry: 11 new rows (tier='0_atomic', added_phase='151')
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase)
VALUES
    ('bars_since_high_fast', 'structure', '0_atomic',
     'bars since rolling-max(high, dist_window_fast)', 'unbounded_ratio', false, false, 'active', '151'),
    ('bars_since_high_slow', 'structure', '0_atomic',
     'bars since rolling-max(high, dist_window_slow)', 'unbounded_ratio', false, false, 'active', '151'),
    ('bars_since_low_fast', 'structure', '0_atomic',
     'bars since rolling-min(low, dist_window_fast)', 'unbounded_ratio', false, false, 'active', '151'),
    ('bars_since_low_slow', 'structure', '0_atomic',
     'bars since rolling-min(low, dist_window_slow)', 'unbounded_ratio', false, false, 'active', '151'),
    ('bars_since_52w_high', 'structure', '0_atomic',
     'bars since rolling-max(high, high_52w window)', 'unbounded_ratio', false, false, 'active', '151'),
    ('bars_since_52w_low', 'structure', '0_atomic',
     'bars since rolling-min(low, high_52w window)', 'unbounded_ratio', false, false, 'active', '151'),
    ('bars_since_extreme_move_fast', 'volatility', '0_atomic',
     'bars since abs(log_ret) > sigma_threshold * rolling_std, fast window', 'unbounded_ratio', false, false, 'active', '151'),
    ('bars_since_extreme_move_slow', 'volatility', '0_atomic',
     'bars since abs(log_ret) > sigma_threshold * rolling_std, slow window', 'unbounded_ratio', false, false, 'active', '151'),
    ('bars_since_vol_spike_fast', 'volume', '0_atomic',
     'bars since rel_volume > vol_spike_threshold, fast window', 'unbounded_ratio', false, false, 'active', '151'),
    ('bars_since_vol_spike_slow', 'volume', '0_atomic',
     'bars since rel_volume > vol_spike_threshold, slow window', 'unbounded_ratio', false, false, 'active', '151'),
    ('abs_ret_autocorr_1', 'volatility', '0_atomic',
     'lag-1 autocorrelation of abs(log_ret)', 'bounded_signed', true, false, 'active', '151')
ON CONFLICT (feature_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. APR keys: feature.bars_since_extreme_move.sigma_threshold,
--    feature.bars_since_vol_spike.threshold
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.bars_since_extreme_move.sigma_threshold',
    'float',
    '2.0',
    0.5, 10.0,
    '[conventional] Multiple of the rolling standard deviation of abs(log return) above which a bar counts as an extreme-move event for bars_since_extreme_move_fast/slow. Phase 151. ML learning target: yes.'
),
(
    'feature.bars_since_vol_spike.threshold',
    'float',
    '2.0',
    1.0, 20.0,
    '[conventional] rel_volume level above which a bar counts as a volume-spike event for bars_since_vol_spike_fast/slow. Phase 151. ML learning target: yes.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.bars_since_extreme_move.sigma_threshold', '2.0', 1),
    ('feature.bars_since_vol_spike.threshold', '2.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.bars_since_extreme_move.sigma_threshold', 1, '2.0', 'migration_288',
     'Seed extreme-move sigma threshold, Phase 151 [conventional]'),
    (NOW(), 'feature.bars_since_vol_spike.threshold', 1, '2.0', 'migration_288',
     'Seed volume-spike threshold, Phase 151 [conventional]')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. Phase 170 parity: concept_registry/concept_gate mirror for this
--    migration's 11 rows (see header note above).
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
    'bars_since_high_fast', 'bars_since_high_slow', 'bars_since_low_fast',
    'bars_since_low_slow', 'bars_since_52w_high', 'bars_since_52w_low',
    'bars_since_extreme_move_fast', 'bars_since_extreme_move_slow',
    'bars_since_vol_spike_fast', 'bars_since_vol_spike_slow', 'abs_ret_autocorr_1'
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
    'bars_since_high_fast', 'bars_since_high_slow', 'bars_since_low_fast',
    'bars_since_low_slow', 'bars_since_52w_high', 'bars_since_52w_low',
    'bars_since_extreme_move_fast', 'bars_since_extreme_move_slow',
    'bars_since_vol_spike_fast', 'bars_since_vol_spike_slow', 'abs_ret_autocorr_1'
)
ON CONFLICT (concept_id) DO NOTHING;

COMMIT;
