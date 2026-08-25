-- Migration 324: alpha.ic.broadcast_variance_threshold APR key
--
-- Phase 173 (Broadcast Feature Significance Correction, todo 270): registers the single
-- shared epsilon used by BOTH readers of the broadcast/idiosyncratic classification:
--   1. The offline detector `scripts/ops/alpha/ops_broadcast_feature_audit.py`, which uses
--      it to CLASSIFY each active feature's cross-symbol `max - min` spread at a given
--      bar_ts as within-tolerance (symbol-invariant, i.e. broadcast) or not.
--   2. `services/ic_engine.py::_compute_one_broadcast_cell` (landing in Plan 173-04, not
--      yet wired as of this migration), which reads the SAME key to ASSERT the same
--      invariance still holds at compute time -- a crash guard against a feature that was
--      classified broadcast offline silently drifting to per-symbol values.
--
-- ONE key, not two: same quantity, same units, same seed. Two separately-tunable keys
-- would let a feature be classified broadcast offline and then crash (or silently
-- misbehave) at compute time, or vice versa -- a guaranteed inconsistency for zero
-- benefit (see planner_findings 9 in 173-01-PLAN.md). Loosening this key affects both
-- classification and the compute-time crash guard -- an operator tuning it should see
-- the full blast radius, which is why both readers are named in this description rather
-- than only the currently-wired one.
--
-- Seed value 1e-9 is the exact epsilon that was hardcoded as module constant
-- `_BROADCAST_EPSILON` in ops_broadcast_feature_audit.py prior to this migration --
-- carried forward unchanged so this migration is behavior-preserving for the existing
-- classifier. [initial_estimate]: 1e-9 was picked as "smaller than any float32 rounding
-- difference," never benchmarked against this corpus's real feature distributions --
-- same honesty-about-provenance pattern as migration 298's five unbenchmarked
-- bootstrap-early-stop keys. Not an ML learning target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ic.broadcast_variance_threshold',
    'float',
    '1e-9',
    0.0, 1.0,
    '[initial_estimate] Per-bar_ts cross-symbol max-minus-min tolerance below which a '
    'feature is considered symbol-invariant (broadcast) rather than idiosyncratic. '
    'Picked as "smaller than any float32 rounding difference," never benchmarked. '
    'Shared by TWO readers, both affected by any change to this value: the offline '
    'classifier scripts/ops/alpha/ops_broadcast_feature_audit.py (uses it to CLASSIFY '
    'features into concept_registry.metadata->>''broadcast''), and -- after Phase '
    '173 Plan 04 lands -- the compute-time invariance assertion in '
    'services/ic_engine.py::_compute_one_broadcast_cell (uses it to ASSERT the same '
    'classification still holds, crashing rather than silently computing on drifted '
    'data if it does not). Loosening this key affects both classification and the '
    'compute-time crash guard. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.broadcast_variance_threshold', '1e-9', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ic.broadcast_variance_threshold', 1, '1e-9', 'migration_324',
    'Initial value: migrated from the hardcoded _BROADCAST_EPSILON module constant in '
    'ops_broadcast_feature_audit.py, Phase 173 / todo 270. Byte-for-byte unchanged from '
    'the pre-migration default [initial_estimate].'
)
ON CONFLICT DO NOTHING;

COMMIT;
