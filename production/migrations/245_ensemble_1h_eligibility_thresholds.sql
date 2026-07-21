-- Migration 245: alpha.ensemble.{min_passing_features,max_feature_weight}.1h APR keys (todo 164)
--
-- 1h has comparable statistical power to 15m (median effective-N 13,754 vs 15m's 39,776;
-- CI width 0.0515 vs 0.0514 -- statistically indistinguishable) but only 1,395 total
-- base-eligible (symbol x regime x lookahead) cells vs 15m's 4,185 (~1/3 the population).
-- Live-verified via a real ensemble_trainer.py re-run (weight_version
-- debug_1h_investigation, cleaned up after): 1h strata were attempted on every regime and
-- skipped on every regime, purely because no single (1h, regime) stratum could ever
-- assemble the global min_passing_features=5 distinct qualifying features from that
-- smaller population.
--
-- Seed values are [initial_estimate], calibrated against 1h's actual achievable population
-- (~1/3 of 15m's) rather than guessed: min_passing_features=3 paired with
-- max_feature_weight=0.34 (3 * 0.34 = 1.02 >= 1.0, satisfying the same feasibility
-- constraint migration 164's original 5 * 0.20 = 1.0 pair encodes -- see
-- ensemble_trainer.py's _assert_feasible_thresholds, which enforces this at startup for
-- every configured timeframe). 5m/15m/1d are unaffected -- no per-tf key is set for them,
-- so they keep today's global-default behavior byte-for-byte.
--
-- Explicitly NOT addressed here: alpha.ensemble.meta_fdr_min_cells.1h. The live-debug
-- evidence above pins 1h's failure to min_passing_features, not this key -- seeding a
-- value for it with no supporting evidence would be undisciplined tuning. If 1h still
-- under-produces strata after this migration lands, check whether meta_fdr_min_cells is
-- now the binding constraint before setting alpha.ensemble.meta_fdr_min_cells.1h.
--
-- Also NOT addressed here: 1d's genuine small-sample power problem (median effective-N
-- 1,222, min 143, CI width 3x wider than every other timeframe) -- that needs a real
-- small-sample statistical treatment, not a threshold tweak, and is scoped as its own
-- follow-up todo, not this migration.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ensemble.min_passing_features.1h',
    'int',
    '3',
    1, 10,
    '[initial_estimate] Per-timeframe override of alpha.ensemble.min_passing_features for '
    '1h (todo 164). 1h''s base-eligible population is ~1/3 of 15m''s despite comparable '
    'per-cell statistical power (comparable effective-N and CI width) -- the global '
    'default of 5 structurally excludes every 1h regime stratum. Paired with '
    'max_feature_weight.1h=0.34 to satisfy the n*cap>=1.0 feasibility constraint (asserted '
    'at startup by ensemble_trainer.py). Not an ML learning target.'
),
(
    'alpha.ensemble.max_feature_weight.1h',
    'float',
    '0.34',
    0.10, 1.00,
    '[initial_estimate] Per-timeframe override of alpha.ensemble.max_feature_weight for 1h '
    '(todo 164). Paired with min_passing_features.1h=3 so 3*0.34=1.02>=1.0 remains a '
    'feasible normalized-weight-vector constraint (asserted at startup by '
    'ensemble_trainer.py''s _assert_feasible_thresholds). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ensemble.min_passing_features.1h', '3', 1),
    ('alpha.ensemble.max_feature_weight.1h', '0.34', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ensemble.min_passing_features.1h', 1, '3', 'migration_245',
     'Seed 1h-specific ensemble eligibility floor, todo 164 [initial_estimate]'),
    (NOW(), 'alpha.ensemble.max_feature_weight.1h', 1, '0.34', 'migration_245',
     'Seed 1h-specific concentration cap paired with min_passing_features.1h, todo 164 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
