-- Migration 183: APR key for ic_engine cross-sectional timestamp chunk size
--
-- The cross-sectional pass pre-fetches regime timestamps from market_regimes, then
-- queries feature_vectors+forward_returns in timestamp chunks to avoid the 3-way
-- JOIN that caused PostgreSQL backend OOM for large regimes (5m/low_bull: 7M rows).
-- cs_chunk_ts controls how many regime timestamps are processed per query.
-- 5_000 timestamps × 58 symbols = ~290K rows per query (safe for both PG and Python).
-- [initial_estimate] [infra.ic_engine] — tunable but not an ML learning target.
BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'infra.ic_engine.cs_chunk_ts',
    'int',
    '5000',
    'Regime timestamps per chunk in the cross-sectional IC pass. '
    '5000 × 58 symbols ≈ 290K rows per query; avoids PG backend OOM on large '
    'regimes (5m/low_bull = 7M rows in a single 3-way JOIN). [initial_estimate] '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.ic_engine.cs_chunk_ts', '5000', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
