-- Migration 323: infra.alpha_publisher.chunk_size APR key
--
-- Found while fixing a real OOM incident (2026-08-22): alpha_publisher.py's Kafka-publish
-- path accumulated every emitted event as a dict in one unbounded list for the whole run
-- (skip_kafka=False, the corpus pipeline's default) -- confirmed via dmesg to have
-- OOM-killed a corpus run at 24.6GB RSS once ensemble_alpha grew past ~30M rows. The fix
-- unifies both paths (skip_kafka True/False) onto one chunked accumulate-and-flush helper,
-- shared with the code touched to fix the leak -- migrate-as-you-go (CLAUDE.md): any
-- hardcoded batch-size constant encountered while fixing adjacent code moves to APR in
-- the same session.
--
-- _CHUNK_SIZE was a hardcoded class constant (50_000) in services/alpha_publisher.py,
-- never APR-backed despite the class already loading APR config for every other
-- numeric parameter (effective_n_gate, top_features_count, per-tf thresholds/cost
-- hurdles). Seeded at the exact pre-migration value -- behavior byte-for-byte unchanged
-- unless an operator explicitly edits the value via /config/parameters.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.alpha_publisher.chunk_size',
    'int',
    '50000',
    1, 500000,
    '[initial_estimate] Row batch size for alpha_events INSERT + Kafka publish in '
    'services/alpha_publisher.py (_flush_chunk). Pure infrastructure throughput/memory '
    'knob -- output is invariant to this value; only wall-clock and peak RSS change. '
    'Seeded at the pre-migration hardcoded default. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.alpha_publisher.chunk_size', '50000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'infra.alpha_publisher.chunk_size', 1, '50000', 'migration_323',
    'Initial value: migrated from a hardcoded class constant while fixing the '
    '2026-08-22 alpha_publisher OOM incident (unbounded Kafka-path accumulation). '
    'Byte-for-byte unchanged from the pre-migration default [initial_estimate].'
)
ON CONFLICT DO NOTHING;

COMMIT;
