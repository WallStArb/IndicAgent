-- Migration 167: APR key for feature_factory ProcessPoolExecutor parallelism.
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.feature_factory.workers',
    'int',
    '12',
    1, 32,
    '[initial_estimate] Number of ProcessPoolExecutor workers for backfill_feature_factory.py symbol-level parallelism. Each worker opens its own psycopg2 connection. Default 12 = min(24_cores // 2, 16). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.feature_factory.workers', '12', 1)
ON CONFLICT (config_key) DO NOTHING;
