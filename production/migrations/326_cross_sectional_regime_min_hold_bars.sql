-- Migration 326: alpha.regime.cross_sectional.min_hold_bars APR key
--
-- Todo 005 (filed 2026-06-28, open for 2 months): market_regimes -- the live
-- cross-sectional regime label source ic_engine.py stratifies on whenever
-- alpha.regime.equity_model_enabled=true -- had ZERO transition guard of any kind.
-- cross_sectional_regime_model.py's _bucket() does pure per-bar threshold bucketing;
-- a signal value oscillating around a tier boundary flips regime_label on literally
-- the next bar, contaminating which stratum's IC a boundary-adjacent bar contributes
-- to in every regime-stratified measurement downstream. regime_writer.py's per-symbol
-- HMM path already had this exact protection (feature.hmm.min_hold_bars, migration
-- 176/179) -- this key closes the same gap for the cross-sectional path, the one
-- ic_engine.py's live stratification actually reads.
--
-- Fix (services/cross_sectional_regime_model.py): a new _smooth_labels() function
-- (ports regime_writer.py's _smooth_states to string/object-dtype label arrays)
-- applied independently to each tier dimension (labels1, labels2) inside
-- _assign_labels(), BEFORE combining into the final "{tier1}_{tier2}" regime_label
-- string. regime_prob_vector is unaffected -- it always reports the raw, unsmoothed
-- signal value, a continuous diagnostic independent of the (possibly-smoothed)
-- discrete label.
--
-- Value: 3, matching regime_writer.py's feature.hmm.min_hold_bars default EXACTLY --
-- [initial_estimate], not independently calibrated for this signal family. Reusing
-- the existing precedent's value is the right call here (same class of parameter,
-- same "prevent single-bar noise flips without meaningfully lagging genuine
-- transitions" goal, same honesty-about-provenance discipline already established
-- for this exact parameter shape) rather than inventing a fresh calibration study
-- for a value this project already has working, tested experience with.
--
-- Blast radius: same class as an HMM_RANDOM_STATE change -- this changes market_regimes
-- labels corpus-wide once a batch write picks it up (cross_sectional_regime_model.py has
-- no fingerprint/checkpoint mechanism; every run recomputes fully). Requires a
-- market_regimes relabel (step 4) followed by a full ic_engine recompute (step 5) to take
-- effect -- do not expect this key to retroactively change already-written market_regimes
-- rows or already-computed feature_ic_scores.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.regime.cross_sectional.min_hold_bars',
    'int',
    '3',
    1, 20,
    '[initial_estimate] Minimum consecutive bars a new threshold-bucketed tier label '
    'must persist before cross_sectional_regime_model.py confirms the transition, '
    'applied independently to each tier dimension before combining into the final '
    'regime_label. Prevents single-bar flips when a signal oscillates around a tier '
    'boundary -- market_regimes had zero transition guard before this (todo 005), '
    'unlike regime_writer.py''s per-symbol HMM path which already has the identical '
    'protection via feature.hmm.min_hold_bars (migration 176/179, same default value '
    '3, same provenance -- not independently calibrated for this signal family). '
    'Introduces at most min_hold_bars of lag on genuine transitions. Changing this '
    'value moves market_regimes labels corpus-wide on the next batch run -- same '
    'blast-radius class as an HMM_RANDOM_STATE change; requires a full market_regimes '
    'relabel + ic_engine recompute to take effect. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.regime.cross_sectional.min_hold_bars', '3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.regime.cross_sectional.min_hold_bars', 1, '3', 'migration_326',
    'Initial value: mirrors regime_writer.py''s feature.hmm.min_hold_bars default '
    'exactly (migration 176/179), same provenance class [initial_estimate]. Todo 005, '
    'open since 2026-06-28 -- closes the zero-hysteresis gap on the live '
    'cross-sectional regime stratification source before the next full corpus recompute.'
)
ON CONFLICT DO NOTHING;

COMMIT;
