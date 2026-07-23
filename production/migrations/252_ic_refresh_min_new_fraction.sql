-- Migration 252: alpha.ic.refresh_min_new_fraction APR key (162-04 Task 2, todo 134
-- follow-on)
--
-- alpha.ic.refresh_min_new_fraction: the minimum fraction-of-new-bars (since a cell's
-- last computed training_window_end) BELOW which that cell's prior IC value MAY be
-- carried forward across a --training-window-end bump, instead of recomputed from
-- scratch. Seeded 0 (disabled) -- at 0, no cell ever qualifies for carry-forward
-- (every window-end bump still triggers a full recompute via the whole-cell
-- fingerprint gate, migration 251/162-03), so this seed is a pure no-op: zero
-- behavior change on top of 162-03's fingerprint mechanism. Stays disabled until
-- Plan 04's drift study (`scripts/ops/corpus/ops_ic_fingerprint_equivalence.py
-- --drift-study`) produces an empirical IC-stability-vs-lag curve that justifies a
-- nonzero value -- [rca_analysis] once that study lands, [initial_estimate]/disabled
-- today. Not an ML learning target (this is a policy threshold gating a mechanism,
-- not a model-learned parameter).
--
-- NOTE: this key is bound in ICEngineConfig.from_apr() (defaulted 0.0) as a
-- forward-looking field only -- no auto-carry-forward behavior is wired to read it
-- yet. Classified COMPUTATIONAL in ic_engine.py's fingerprint field partition: once
-- wired, a nonzero value would change which rows get carried-forward vs recomputed
-- (moves feature_ic_scores content), so a config change to this key must invalidate
-- every fingerprint-valid cell, not silently leave stale carry-forward decisions in
-- place under an unchanged apr_snapshot_key.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ic.refresh_min_new_fraction',
    'float',
    '0',
    0, 1,
    '[rca_analysis, disabled] Minimum fraction-of-new-bars below which a cell''s '
    'prior IC MAY be carried forward across a --training-window-end bump, instead '
    'of recomputed. Seeded 0 (disabled) -- at 0 every cell always recomputes on a '
    'window-end bump; zero behavior change until Plan 04''s drift study '
    '(ops_ic_fingerprint_equivalence.py --drift-study) justifies a nonzero value. '
    'Not an ML learning target. See services/ic_engine.py ICEngineConfig docstring.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.refresh_min_new_fraction', '0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.refresh_min_new_fraction', 1, '0', 'migration_252',
     'Seed refresh_min_new_fraction disabled (0) -- forward-looking key, no '
     'carry-forward behavior wired yet; stays disabled until the drift study '
     'justifies a nonzero value, todo 134 follow-on [rca_analysis]')
ON CONFLICT DO NOTHING;

COMMIT;
