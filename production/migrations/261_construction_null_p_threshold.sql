-- Migration 261: alpha.construction.null_p_threshold APR key
--
-- Phase 167 code review CR/WR-01: Validation Gate 1's shuffled-ranking-null significance
-- level (`null_p < 0.05`) was a hardcoded literal in
-- services/cross_sectional_spread_tracker.py's binding gate1_passes computation, violating
-- CLAUDE.md's APR mandate ("Hard-coded numeric thresholds... in src/ or services/ are an
-- architecture violation" / "Migrate-as-you-go... MUST be migrated in the same session").
-- Every other Gate 1/Gate 2 tunable in the same module (decile_fraction,
-- cost_hurdle_bps_round_trip, null_shuffles, attribution_max_static_r2) was correctly
-- migrated to alpha.construction.* by migration 260; this significance level was missed.
--
-- Idempotent, safe to re-run.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
(
    'alpha.construction.null_p_threshold',
    'float',
    '0.05',
    '[conventional] Phase 167: Validation Gate 1''s shuffled-ranking-null significance level -- '
    'a scale''s null_p must be strictly below this value, at BOTH lookahead scales, for the '
    'binding gate1_passes verdict to be true (alongside the bootstrap CI clearing at the most '
    'conservative cost tier). Standard 5% two-sided significance convention; not an ML learning '
    'target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('alpha.construction.null_p_threshold', '0.05', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'alpha.construction.null_p_threshold', 1, '0.05', 'migration_261', 'Conventional: standard 5% significance level for the shuffled-ranking null, migrated from a hardcoded literal per code review CR/WR-01 [conventional]');

COMMIT;
