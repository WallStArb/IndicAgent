-- Migration 289: Cross-Asset Spread/Beta Atomics -- Phase 151 Plan 04
--
-- Adds todo 123's two macro spreads plus stock-bond correlation, and todo 180's
-- two factor betas -- 7 remaining Phase 151 tier-0 atomic candidates that
-- require cross-symbol data. TIP/HYG/LQD all entered the universe in the
-- 58->80 ETF expansion (2026-07-01), postdating intel-08's original "blocked
-- on data availability" deferral. equity_beta/rate_beta are the glossary's own
-- canonical primitive examples (docs/foundation/glossary.md:320) and have
-- never existed as live per-bar columns -- only as slow-moving static
-- instrument_tags.
--
-- Migration numbering note: the plan's own text names the file
-- "262_cross_asset_spread_beta_atomics.sql" (provisional target as of the
-- plan's 2026-07-24 authoring date). Live inspection at execution time
-- (2026-08-05) shows the sequence has since advanced through 288 (same
-- collision class already documented in migration 255/216/287/288's own
-- numbering notes) -- 289 is the verified next-free number, checked against
-- both `ls production/migrations/` and `config_history` (no
-- changed_by='migration_289' row exists) before this file's apply.
--
-- Column type: DOUBLE PRECISION for all 7 new columns, matching every other
-- feature_vectors column added since migration 201. ADD COLUMN IF NOT EXISTS
-- with no DEFAULT is metadata-only against the compressed hypertable -- no
-- decompression step required (confirmed via migration 197/206/216/255/266/
-- 267/287/288 precedent).
--
-- Nullable design (binding, todo 180 Fable review): equity_beta_z/rate_beta_z
-- are NULL for the factor proxy's own self-regression (SPY for equity_beta_z,
-- TLT for rate_beta_z) -- a self-regression is degenerate (beta identically
-- 1, r-squared identically 1), so emitting a constant 1.0 would be a
-- silently-wrong feature. None means "not measured," never a fake numeric
-- placeholder (same convention as the Phase 163/164/165 nullable blocks).
--
-- Namespace correction: todo 123 proposed the sb_corr window keys under an
-- unsanctioned top-level namespace beginning "macro" (e.g. "macro" + "." +
-- "sb_corr" + ".window_fast/slow"); that proposal is superseded here by the
-- feature namespace, matching every live sibling (feature.vix.zscore_window,
-- feature.yield_curve.zscore_window, feature.cross_asset.rv_window). The
-- "macro" namespace is NOT sanctioned for APR keys (root CLAUDE.md).
--
-- Phase 170 parity (Section 5 below, same requirement as migration 293/288's
-- own header notes): ic_engine.py's _apply_feature_transitions runs a PARITY
-- PRECONDITION on every corpus pass (Phase 170 Plan 06, T-170-17) that
-- hard-stops if any feature_registry row lacks a concept_registry
-- counterpart. Field mapping matches migration 284's feature-domain seed
-- exactly (derived from the feature_registry rows this migration's own
-- Section 3 just inserted, never re-typed literals, so the two tables cannot
-- drift).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 7 new columns
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS tip_tlt_ret_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS hyg_lqd_ret_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS sb_corr_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS sb_corr_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS sb_corr_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS equity_beta_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS rate_beta_z DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.tip_tlt_ret_z IS
    'Z-score of (log_ret(TIP) - log_ret(TLT)) -- TIPS/nominal Treasury spread proxy. Phase 151.';
COMMENT ON COLUMN feature_vectors.hyg_lqd_ret_z IS
    'Z-score of (log_ret(HYG) - log_ret(LQD)) -- high-yield/investment-grade credit spread proxy. Phase 151.';
COMMENT ON COLUMN feature_vectors.sb_corr_fast IS
    'Rolling Pearson correlation of SPY/TLT log returns, fast window. Bounded [-1, 1]; theory-free (no directional interpretation attached to sign). Phase 151.';
COMMENT ON COLUMN feature_vectors.sb_corr_slow IS
    'Rolling Pearson correlation of SPY/TLT log returns, slow window. Bounded [-1, 1]; theory-free (no directional interpretation attached to sign). Phase 151.';
COMMENT ON COLUMN feature_vectors.sb_corr_z IS
    'Z-score of sb_corr_fast. Phase 151.';
COMMENT ON COLUMN feature_vectors.equity_beta_z IS
    'Z-score of rolling OLS slope of symbol daily log_ret on SPY daily log_ret. NULL for the factor proxy itself (SPY) -- a self-regression is degenerate (beta identically 1) and is deliberately not emitted as a constant. Daily-grain rolling OLS slope, broadcast to all timeframes by date, same cadence contract as vix_z/yield_slope_z. Phase 151.';
COMMENT ON COLUMN feature_vectors.rate_beta_z IS
    'Z-score of rolling OLS slope of symbol daily log_ret on TLT daily log_ret. NULL for the factor proxy itself (TLT) -- a self-regression is degenerate (beta identically 1) and is deliberately not emitted as a constant. Daily-grain rolling OLS slope, broadcast to all timeframes by date, same cadence contract as vix_z/yield_slope_z. Phase 151.';

-- ---------------------------------------------------------------------------
-- 2. feature_registry: 7 new rows (tier='0_atomic', added_phase='151')
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase)
VALUES
    ('tip_tlt_ret_z', 'macro', '0_atomic',
     'zscore(log_ret(TIP) - log_ret(TLT))', 'z_scored', true, false, 'active', '151'),
    ('hyg_lqd_ret_z', 'macro', '0_atomic',
     'zscore(log_ret(HYG) - log_ret(LQD))', 'z_scored', true, false, 'active', '151'),
    ('sb_corr_fast', 'macro', '0_atomic',
     'rolling Pearson(log_ret(SPY), log_ret(TLT)) fast', 'bounded_signed', true, false, 'active', '151'),
    ('sb_corr_slow', 'macro', '0_atomic',
     'rolling Pearson(log_ret(SPY), log_ret(TLT)) slow', 'bounded_signed', true, false, 'active', '151'),
    ('sb_corr_z', 'macro', '0_atomic',
     'zscore(sb_corr_fast)', 'z_scored', true, false, 'active', '151'),
    ('equity_beta_z', 'macro', '0_atomic',
     'zscore(rolling OLS slope of symbol daily log_ret on SPY daily log_ret)', 'z_scored', true, false, 'active', '151'),
    ('rate_beta_z', 'macro', '0_atomic',
     'zscore(rolling OLS slope of symbol daily log_ret on TLT daily log_ret)', 'z_scored', true, false, 'active', '151')
ON CONFLICT (feature_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. APR keys: 7 new keys, all under the sanctioned feature namespace
--    (supersedes todo 123's unsanctioned "macro"-prefixed proposal, see
--    the header note above)
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.tip_tlt.zscore_window',
    'int',
    '252',
    20, 2520,
    '[conventional] Z-score window (bars) for tip_tlt_ret_z (TIPS/nominal Treasury spread proxy). Phase 151. ML learning target: yes.'
),
(
    'feature.hyg_lqd.zscore_window',
    'int',
    '252',
    20, 2520,
    '[conventional] Z-score window (bars) for hyg_lqd_ret_z (high-yield/investment-grade credit spread proxy). Phase 151. ML learning target: yes.'
),
(
    'feature.sb_corr.window_fast',
    'int',
    '30',
    5, 250,
    '[conventional] Fast rolling window (bars) for sb_corr_fast (SPY/TLT log-return correlation). Phase 151. ML learning target: yes.'
),
(
    'feature.sb_corr.window_slow',
    'int',
    '60',
    10, 500,
    '[conventional] Slow rolling window (bars) for sb_corr_slow (SPY/TLT log-return correlation). Phase 151. ML learning target: yes.'
),
(
    'feature.sb_corr.zscore_window',
    'int',
    '252',
    20, 2520,
    '[conventional] Z-score window (bars) for sb_corr_z (z-scores sb_corr_fast). Phase 151. ML learning target: yes.'
),
(
    'feature.factor_beta.window',
    'int',
    '60',
    10, 500,
    '[conventional] Rolling OLS window (bars) shared by both equity_beta_z and rate_beta_z (same statistic, different factor series). "factor_beta" naming (not bare "beta") avoids the glossary''s ban on an unqualified "beta" term. Phase 151. ML learning target: yes.'
),
(
    'feature.factor_beta.zscore_window',
    'int',
    '252',
    20, 2520,
    '[conventional] Z-score window (bars) shared by both equity_beta_z and rate_beta_z. Phase 151. ML learning target: yes.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.tip_tlt.zscore_window', '252', 1),
    ('feature.hyg_lqd.zscore_window', '252', 1),
    ('feature.sb_corr.window_fast', '30', 1),
    ('feature.sb_corr.window_slow', '60', 1),
    ('feature.sb_corr.zscore_window', '252', 1),
    ('feature.factor_beta.window', '60', 1),
    ('feature.factor_beta.zscore_window', '252', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.tip_tlt.zscore_window', 1, '252', 'migration_289',
     'Seed TIP/TLT spread z-score window, Phase 151 [conventional]'),
    (NOW(), 'feature.hyg_lqd.zscore_window', 1, '252', 'migration_289',
     'Seed HYG/LQD spread z-score window, Phase 151 [conventional]'),
    (NOW(), 'feature.sb_corr.window_fast', 1, '30', 'migration_289',
     'Seed stock-bond correlation fast window, Phase 151 [conventional]'),
    (NOW(), 'feature.sb_corr.window_slow', 1, '60', 'migration_289',
     'Seed stock-bond correlation slow window, Phase 151 [conventional]'),
    (NOW(), 'feature.sb_corr.zscore_window', 1, '252', 'migration_289',
     'Seed stock-bond correlation z-score window, Phase 151 [conventional]'),
    (NOW(), 'feature.factor_beta.window', 1, '60', 'migration_289',
     'Seed factor-beta rolling OLS window, Phase 151 [conventional]'),
    (NOW(), 'feature.factor_beta.zscore_window', 1, '252', 'migration_289',
     'Seed factor-beta z-score window, Phase 151 [conventional]')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. Phase 170 parity: concept_registry/concept_gate mirror for this
--    migration's 7 rows (see header note above).
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
    'tip_tlt_ret_z', 'hyg_lqd_ret_z', 'sb_corr_fast', 'sb_corr_slow', 'sb_corr_z',
    'equity_beta_z', 'rate_beta_z'
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
    'tip_tlt_ret_z', 'hyg_lqd_ret_z', 'sb_corr_fast', 'sb_corr_slow', 'sb_corr_z',
    'equity_beta_z', 'rate_beta_z'
)
ON CONFLICT (concept_id) DO NOTHING;

COMMIT;
