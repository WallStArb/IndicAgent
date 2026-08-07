-- Migration 305: feature.ctf.higher_tf_map -- APR-migrate the CTF (cross-timeframe)
-- higher-timeframe source mapping (todo 242)
--
-- src/intelligence/feature_cache.py hardcoded a module-level constant,
-- _CTF_HIGHER_TF = {"5m": "1h", "15m": "1h", "1h": "1d", "1d": "1d"}, as the single
-- source of truth for both backfill_feature_factory.py's batch _build_ctf_series() and
-- feature_vector_pipeline.py's live per-HTF-bar update (which HTF is used to compute
-- ctf_momentum/ctf_vwap_align/ctf_regime_align for a given source timeframe). Per
-- docs/foundation/adaptive-parameter-registry.md's "behavioral lists" APR category
-- (lists controlling WHAT the algorithm processes must be APR-backed JSON, not a
-- Python literal), this is an architecture violation independent of what the map
-- currently contains -- the same category migrations 278/279 already fixed for two
-- sibling hardcoded lists.
--
-- This migration does not change the mapping; it only moves the existing map's
-- storage location from a Python literal (now FeatureFactoryConfig.ctf_higher_tf_map,
-- src/intelligence/feature_factory.py) to config_state, seeded to the exact same 4
-- entries so behavior is unchanged unless an operator edits this key later. "1d" is
-- self-referential (no timeframe above 1d exists in this corpus) -- ctf_momentum
-- degenerates into a same-tf RSI oscillator there rather than genuine cross-timeframe
-- signal (todo 189); kept for batch/live parity, not because it's a good statistic.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.ctf.higher_tf_map',
    'json',
    '{"5m": "1h", "15m": "1h", "1h": "1d", "1d": "1d"}',
    null, null,
    '[conventional] JSON object mapping source timeframe -> higher timeframe (HTF) used to compute ctf_momentum/ctf_vwap_align/ctf_regime_align. Single source of truth for both services/backfill_feature_factory.py''s batch path and services/feature_vector_pipeline.py''s live path -- both read it via FeatureFactoryConfig.ctf_higher_tf_map, never a hardcoded dict. "1d" is deliberately self-referential (no timeframe above 1d exists in this corpus). Matches the long-standing hardcoded feature_cache._CTF_HIGHER_TF module constant this key replaces. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.ctf.higher_tf_map', '{"5m": "1h", "15m": "1h", "1h": "1d", "1d": "1d"}', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.ctf.higher_tf_map', 1, '{"5m": "1h", "15m": "1h", "1h": "1d", "1d": "1d"}', 'migration_305',
     'Seed CTF higher-timeframe source mapping, todo 242 APR migration [conventional] -- byte-identical to prior hardcoded feature_cache._CTF_HIGHER_TF constant.')
ON CONFLICT DO NOTHING;

COMMIT;
