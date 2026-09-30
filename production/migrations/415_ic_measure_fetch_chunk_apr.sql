-- Migration 415: APR key for the IC writer's feature-fetch chunk size (phase 186 plan 14)
--
-- services/ic_measure.py streams feature rows from feature_vectors with a server-side cursor in
-- chunks of this many rows. A memory and round-trip knob that never enters a value (APR category
-- 3, infrastructure performance constants). Seeds use ON CONFLICT DO NOTHING (the 375 shape).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    ('infra.ic_measure.fetch_chunk_rows', 'int', '200000', '1000', NULL,
     '[initial_estimate] Rows per server-side cursor fetch when the IC writer streams feature_vectors into arrays; bounds the Python tuple overhead per round trip, never enters a value. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.ic_measure.fetch_chunk_rows', '200000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
    (NOW(), 'infra.ic_measure.fetch_chunk_rows', 1, '200000', 'migration_415', 'Initial value [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
