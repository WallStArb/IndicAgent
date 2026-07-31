-- Migration 275: todo 009 Part A -- APR services sweep, 4 hardcoded constants
--
-- Seeds config_schema/config_state for 4 constants that were hardcoded in
-- services/ with no live ConfigService/APR integration (found in the 2026-07-29
-- verification pass of todo 009 Part A):
--
--   services/backfill_feature_factory.py  _INSERT_BATCH_SIZE           500  -> infra.backfill.insert_batch_size
--   services/forward_return_writer.py     _INSERT_BATCH_SIZE_DEFAULT   500  -> alpha.ic.insert_batch_size
--   services/regime_writer.py             _MIN_OBS_FACTOR              50   -> feature.hmm.min_obs_factor
--   services/signal_auditor.py            _AUDIT_INTERVAL              300  -> infra.signal_auditor.audit_interval_seconds
--
-- forward_return_writer.py's code path already reads
-- cfg.get_sync("alpha.ic.insert_batch_size", _INSERT_BATCH_SIZE_DEFAULT) (landed
-- separately, date unknown) but the key was never seeded here -- the read was
-- silently always falling through to the hardcoded default. The other 3 files'
-- code was migrated in this same session to read the equivalent live key,
-- threaded through their ProcessPoolExecutor worker args (backfill_feature_factory,
-- regime_writer) or BaseDaemon.get_config() (signal_auditor).
--
-- All 4 seeded at their exact pre-migration hardcoded values -- behavior
-- byte-for-byte unchanged unless an operator explicitly edits the value via
-- /config/parameters.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.backfill.insert_batch_size',
    'int',
    '500',
    1, 50000,
    '[initial_estimate] Row batch size for feature_vectors INSERT in '
    'services/backfill_feature_factory.py (_compute_symbol_tf). Pure infrastructure '
    'throughput knob -- output is invariant to this value. Not an ML learning target.'
),
(
    'alpha.ic.insert_batch_size',
    'int',
    '500',
    1, 50000,
    '[initial_estimate] Row batch size for forward_returns INSERT in '
    'services/forward_return_writer.py (_label_symbol_tf). Pure infrastructure '
    'throughput knob -- output is invariant to this value. Not an ML learning target.'
),
(
    'feature.hmm.min_obs_factor',
    'int',
    '50',
    10, 1000,
    '[initial_estimate] Minimum obs-row multiplier for regime_writer.py''s HMM fit '
    'gate: min_rows = n_components * min_obs_factor. Below this, the fit is '
    'meaningless (too few state transitions to estimate the transition matrix). '
    'Raising this makes the fit more conservative (skips more thin symbol/tf '
    'cells); lowering it risks fitting HMMs on insufficient data. Not an ML '
    'learning target -- a data-sufficiency gate, not a model parameter. Domain '
    'is feature.hmm.* (matches the other 10 HMM tunables regime_writer.py reads '
    'in the same block -- n_components, vol_window, full_cov_min_obs, etc.), not '
    'alpha.hmm.* (reserved for alpha.hmm.random_state, the one HMM key that '
    'specifically invalidates downstream alpha outputs when changed). min_value '
    'floored at 10, not 1 -- a multiplier of 1 would let min_rows collapse to '
    'n_components alone, defeating the gate the key exists to enforce.'
),
(
    'infra.signal_auditor.audit_interval_seconds',
    'int',
    '300',
    10, 3600,
    '[initial_estimate] Seconds between signal_auditor.py audit cycles during '
    'market hours. Pure infrastructure cadence knob. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.backfill.insert_batch_size', '500', 1),
    ('alpha.ic.insert_batch_size', '500', 1),
    ('feature.hmm.min_obs_factor', '50', 1),
    ('infra.signal_auditor.audit_interval_seconds', '300', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.backfill.insert_batch_size', 1, '500', 'migration_275',
     'Seed at pre-migration hardcoded value, todo 009 Part A [initial_estimate]'),
    (NOW(), 'alpha.ic.insert_batch_size', 1, '500', 'migration_275',
     'Seed at pre-migration hardcoded value -- code already read this key with no '
     'row ever inserted, so the live read was silently always falling back to the '
     'hardcoded default, todo 009 Part A [initial_estimate]'),
    (NOW(), 'feature.hmm.min_obs_factor', 1, '50', 'migration_275',
     'Seed at pre-migration hardcoded value, todo 009 Part A [initial_estimate]'),
    (NOW(), 'infra.signal_auditor.audit_interval_seconds', 1, '300', 'migration_275',
     'Seed at pre-migration hardcoded value, todo 009 Part A [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
