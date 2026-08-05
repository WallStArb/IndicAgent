-- Migration 286: alpha.ensemble.cluster_regime_conditioned APR flag -- Phase 151 Plan 02
--
-- Widens ic_engine.py's existing regime_passes mechanism so the second (per-symbol HMM)
-- stratification axis for feature collinearity clustering runs for every regime-group-routed
-- symbol, not only those whose group sets dual_write_symbol_hmm (live: rates only, migration
-- 247). Purely additive: emits new regime_scope='symbol_hmm' feature_ic_scores rows, never
-- modifies existing regime_scope='cross_sectional' or 'pooled' rows. Seeded true per ROADMAP
-- Phase 151's explicit specification; safe because the pass is additive at the row level, which
-- this plan's Task 3 verifies empirically before it is trusted at corpus scale. Task 3 also
-- measures the wall-clock cost against a pre-registered budget rule and may flip this key back
-- to false via a runtime UPDATE (no code change, no migration revert) if the cost exceeds it.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ensemble.cluster_regime_conditioned',
    'bool',
    'true',
    NULL, NULL,
    '[initial_estimate] When true, ic_engine runs a second per-cell clustering/IC pass stratified '
    'on the per-symbol HMM regime axis (regime_scope=''symbol_hmm'') for every regime-group-routed '
    'symbol, not only those whose group sets dual_write_symbol_hmm. Purely additive: emits new '
    'regime_scope=''symbol_hmm'' rows, never modifies regime_scope=''cross_sectional'' or ''pooled'' '
    'rows. Increases ic_engine wall-clock roughly proportionally to the number of distinct HMM '
    'states per symbol. Phase 151. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ensemble.cluster_regime_conditioned', 'true', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ensemble.cluster_regime_conditioned', 1, 'true', 'migration_286',
    'Seed alpha.ensemble.cluster_regime_conditioned=true [initial_estimate] -- Phase 151 '
    'regime-conditioned collinearity clustering. ROADMAP Phase 151 specifies true.'
)
ON CONFLICT DO NOTHING;

COMMIT;
