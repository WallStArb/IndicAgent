-- Migration 362: APR keys for compressed_hypertable_write_session's disk-headroom pre-flight
-- (todo 426). Measured 2026-09-25: feature_vectors' compressed chunks are 491 GB decompressed
-- against 414 GB free; the session decompresses every chunk on entry with no check, so any
-- caller (regime_writer, backfill_feature_factory's compute stage, the ops_* scripts) would
-- fill the disk before writing a row -- the 2026-08-13 incident shape. The session now
-- refuses up front unless the decompressed size still leaves min_free_after_fraction free.

BEGIN;

INSERT INTO config_schema (config_key, value_type, description) VALUES
    ('infra.compressed_hypertable_write_session.disk_path', 'str',
     '[rca_analysis] A path on the filesystem that holds the TimescaleDB volume, read with '
     'shutil.disk_usage by the compressed write session''s pre-flight (the Docker volume dir '
     'itself is not readable by the service user; "/" is the same filesystem on this host). '
     'Not an ML learning target.'),
    ('infra.compressed_hypertable_write_session.min_free_after_fraction', 'float',
     '[initial_estimate] Fraction of that filesystem that must remain free after the session '
     'decompresses every compressed chunk (conservative peak: full uncompressed size). The '
     'session raises before touching anything otherwise. Same role as ic_engine''s '
     'scratch_min_free_after_fraction. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.compressed_hypertable_write_session.disk_path', '/', 1),
    ('infra.compressed_hypertable_write_session.min_free_after_fraction', '0.10', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
