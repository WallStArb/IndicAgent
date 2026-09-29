-- Migration 387: feature_lifecycle decides status from data quality (phase 186 plan 09, D-30)
--
-- Design 11 changes what a feature's status means: computed, valid (finite) and covered
-- across symbols. Weak standalone IC never changes status (E15: never drop data that could
-- contain signal). services/feature_lifecycle.py reads four APR keys and records its two
-- automated transitions under two new trigger reasons.
--
-- (a) Four APR keys. The coverage floor is the one definition shared by feature_lifecycle,
--     todo 421's coverage check and todo 435's S0 floor
--     (src/intelligence/statistics/feature_coverage.py).
-- (b) concept_transition_log_trigger_reason_check gains data_quality_fail and
--     data_quality_restored (the nine earlier values are unchanged). The table is a
--     hypertable that is not compressed, so no VACUUM step applies.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    ('feature.coverage.min_symbol_fraction', 'float', '0.95', 0, 1,
     '[initial_estimate] Minimum share of symbols with rows at a tf that must carry at least one non-NULL value of a feature over the span. One definition shared by feature_lifecycle (186-09), todo 421 coverage check and todo 435 S0 floor (src/intelligence/statistics/feature_coverage.py). Not an ML learning target.'),
    ('feature.lifecycle.lookback_days', 'int', '90', 1, NULL,
     '[initial_estimate] Span ending at the evaluated window over which feature_lifecycle measures data quality. Not an ML learning target.'),
    ('feature.lifecycle.demotion_min_consecutive', 'int', '2', 1, NULL,
     '[conventional] Trailing failing windows before a feature moves active to shadow_only (data_quality_fail). Not an ML learning target.'),
    ('feature.lifecycle.recovery_min_passes', 'int', '1', 1, NULL,
     '[initial_estimate] Trailing passing windows before a feature moves shadow_only to active (data_quality_restored). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.coverage.min_symbol_fraction', '0.95', 1),
    ('feature.lifecycle.lookback_days', '90', 1),
    ('feature.lifecycle.demotion_min_consecutive', '2', 1),
    ('feature.lifecycle.recovery_min_passes', '1', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.coverage.min_symbol_fraction', 1, '0.95', 'migration', 'phase 186-09 D-30: initial value [initial_estimate]'),
    (NOW(), 'feature.lifecycle.lookback_days', 1, '90', 'migration', 'phase 186-09 D-30: initial value [initial_estimate]'),
    (NOW(), 'feature.lifecycle.demotion_min_consecutive', 1, '2', 'migration', 'phase 186-09 D-30: initial value [conventional]'),
    (NOW(), 'feature.lifecycle.recovery_min_passes', 1, '1', 'migration', 'phase 186-09 D-30: initial value [initial_estimate]')
ON CONFLICT DO NOTHING;

ALTER TABLE concept_transition_log DROP CONSTRAINT IF EXISTS concept_transition_log_trigger_reason_check;
ALTER TABLE concept_transition_log ADD CONSTRAINT concept_transition_log_trigger_reason_check
    CHECK (trigger_reason = ANY (ARRAY[
        'promotion', 'demotion_performance', 'demotion_decay', 'demotion_redundancy',
        'operator_override', 'parent_cascade', 'candidate_timeout', 'implementation_change',
        'genesis_seed', 'data_quality_fail', 'data_quality_restored'
    ]));

COMMIT;
