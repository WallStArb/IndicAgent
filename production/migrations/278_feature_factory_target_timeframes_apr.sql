-- Migration 278: feature.factory.target_timeframes -- APR-migrate backfill_feature_factory's
-- hardcoded timeframe-scope list (todo 199)
--
-- services/backfill_feature_factory.py:92 hardcoded a module-level constant,
-- _TARGET_TIMEFRAMES = ["5m", "15m", "1h", "1d"], as the sole driver of which
-- timeframes _load_status_map() and the compute/fetch loops process. Per
-- docs/foundation/adaptive-parameter-registry.md's "behavioral lists" APR category
-- (lists controlling WHAT the algorithm processes must be APR-backed JSON, not a
-- Python literal), this is an architecture violation independent of what the list
-- currently contains.
--
-- 1m is deliberately excluded from this list -- confirmed intentional with the user
-- when todo 199 was filed (live pipeline owns 1m; backfill_feature_factory never
-- has). This migration does not change that; it only moves the existing list's
-- storage location from a Python literal to config_state, seeded to the exact same
-- 4 values so behavior is unchanged unless an operator edits this key later.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.factory.target_timeframes',
    'json',
    '["5m", "15m", "1h", "1d"]',
    null, null,
    '[conventional] JSON array of timeframes services/backfill_feature_factory.py processes -- drives _load_status_map() and both the fetch and compute stage loops. 1m intentionally excluded (live FeatureVectorPipeline owns 1m, not this batch job -- confirmed intentional, todo 199). Matches the long-standing hardcoded _TARGET_TIMEFRAMES module constant this key replaces. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.factory.target_timeframes', '["5m", "15m", "1h", "1d"]', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.factory.target_timeframes', 1, '["5m", "15m", "1h", "1d"]', 'migration_278',
     'Seed backfill_feature_factory target-timeframe list, todo 199 APR migration [conventional] -- byte-identical to prior hardcoded _TARGET_TIMEFRAMES constant.')
ON CONFLICT DO NOTHING;

COMMIT;
