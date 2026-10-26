-- Migration 503: seed the InstrumentsListener timings (todo 509 item 1).
--
-- The LISTEN instruments loop moved out of the v2.x pipeline CacheManager into
-- src/config/instruments_listener.py, and its two hard-coded timings become APR keys at the
-- values the code used: the heartbeat that bounds how long a closed connection goes unnoticed
-- (10 s) and the reconnect backoff after a failure (5 s). Reader:
-- services/feature_vector_pipeline.py, which passes both to InstrumentsListener.
-- Not ML learning targets.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'infra.instruments_listener.heartbeat_s',
        'int',
        '10',
        1, NULL,
        '[initial_estimate] Seconds between checks that the LISTEN instruments connection is still open; bounds how long a dropped connection goes unnoticed before a reconnect. Value carried over from the v2.x CacheManager. Not an ML learning target.'
    ),
    (
        'infra.instruments_listener.reconnect_backoff_s',
        'int',
        '5',
        1, NULL,
        '[initial_estimate] Seconds to wait before reconnecting the LISTEN instruments connection after a failure. Value carried over from the v2.x CacheManager. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.instruments_listener.heartbeat_s', '10', 1),
    ('infra.instruments_listener.reconnect_backoff_s', '5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
    (now(), 'infra.instruments_listener.heartbeat_s', 1, '10', 'migration_503',
     'seed: InstrumentsListener heartbeat, extracted from the v2.x CacheManager (todo 509)'),
    (now(), 'infra.instruments_listener.reconnect_backoff_s', 1, '5', 'migration_503',
     'seed: InstrumentsListener reconnect backoff, extracted from the v2.x CacheManager (todo 509)');

COMMIT;
