-- Migration 268: feature.smc.order_blocks.strength_fallback APR key
--
-- Found during a /simplify pass over Phase 164's SMC diff: _compute_order_blocks() in
-- feature_factory.py used a hardcoded 0.5 literal as ob_strength when avg_volume <= 0
-- (both the bullish and bearish candidate branches) -- a numeric constant in src/ that
-- had no APR key, violating CLAUDE.md's APR mandate. avg_volume <= 0 only happens when
-- the sliced volume window is empty or degenerate, which should be rare in the live
-- corpus (real bars always carry a positive volume), but the fallback path exists and is
-- exercised by tests/unit/intelligence/test_smc_order_blocks.py -- it needs a real,
-- tunable value rather than a silent magic number.
--
-- 0.5 (neutral midpoint of the [0,1] strength range) is carried forward unchanged as the
-- seed value -- this migration adds APR plumbing around an already-shipped constant, it
-- does not change any live behavior. [conventional], not an ML learning target (a
-- degenerate-volume fallback, not a calibrated signal weight).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.smc.order_blocks.strength_fallback',
    'float',
    '0.5',
    0.0, 1.0,
    '[conventional] ob_strength fallback when avg_volume <= 0 (degenerate/empty volume '
    'window) in _compute_order_blocks -- neutral midpoint of the [0,1] strength range. '
    'Not an ML learning target: this is a rare degenerate-input guard, not a calibrated '
    'signal weight. Phase 164 migration 266 shipped this as a hardcoded 0.5 literal; this '
    'migration only adds APR plumbing around the existing value.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.smc.order_blocks.strength_fallback', '0.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.smc.order_blocks.strength_fallback', 1, '0.5', 'migration_268',
     'Seed order-block strength degenerate-volume fallback, extracted from a hardcoded '
     '0.5 literal found during a /simplify pass over Phase 164. [conventional], no '
     'behavior change from the value already shipped in migration 266.')
ON CONFLICT DO NOTHING;

COMMIT;
