-- Migration 246: alpha.ensemble.meta_fdr_min_cells.1h APR key (todo 164, emergent follow-up)
--
-- Migration 245 seeded min_passing_features.1h=3/max_feature_weight.1h=0.34, but a live
-- ensemble_trainer.py re-run (weight_version debug_164_1h_verify, cleaned up after)
-- confirmed 1h STILL wrote zero strata on every regime -- the real bottleneck sits one gate
-- upstream, at meta_fdr_min_cells (global default 3), which migration 245 deliberately left
-- unseeded pending exactly this live evidence.
--
-- Live-queried against feature_ic_scores (2026-07-21): at min_cells=3, only 3 features are
-- meta-eligible for tf='1h' corpus-wide (gap_z, momentum_z_fast, dist_from_high_fast). At
-- min_cells=2, 8 more clear the bar (vol_asymmetry_z, days_to_month_end, month_position,
-- range_to_close, ofi_div, quarter_position, shannon, vol_skew_product) -- checking actual
-- per-regime co-occurrence of those 11 names confirms 5 of 7 1h regimes (high_bear: 4
-- features, mid_bull: 5, mid_bear: 3, low_bull: 3, mid_neutral: 3) would clear the
-- min_passing_features.1h=3 floor. low_neutral (2 features) and high_neutral (zero IC rows
-- entirely) remain unfixed by this key -- an honest partial outcome, not a full fix for
-- every regime.
--
-- Seed 2, not 1: _meta_eligible's own docstring warns a single-cell 100% pass rate is a
-- tautology, not replication -- 2 is the minimum floor requiring real cross-cell agreement,
-- mirroring frame_gate_passes' own >=2 day-cluster minimum for a bootstrap CI to exist.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ensemble.meta_fdr_min_cells.1h',
    'int',
    '2',
    2, 10,
    '[initial_estimate] Per-timeframe override of alpha.ensemble.meta_fdr_min_cells for 1h '
    '(todo 164, emergent follow-up to migration 245). Live-queried against feature_ic_scores: '
    'at the global default of 3, only 3 features are meta-eligible for 1h corpus-wide; at 2, '
    '5 of 7 1h regimes assemble enough co-occurring meta-eligible features to clear '
    'min_passing_features.1h=3. Floor kept at 2 (not 1) since a single-cell pass rate is a '
    'tautology, not replication (see _meta_eligible docstring). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ensemble.meta_fdr_min_cells.1h', '2', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ensemble.meta_fdr_min_cells.1h', 1, '2', 'migration_246',
     'Seed 1h-specific meta-FDR cross-cell floor, live-verified against feature_ic_scores after '
     'migration 245 alone proved insufficient to unblock 1h, todo 164 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
