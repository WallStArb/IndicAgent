-- 599: retire the APR keys of the retired streaming feature path (R2 item 5a, lead ruling
-- 2026-11-15).
--
-- services/feature_vector_pipeline.py and services/feature_vector_writer.py, their units, DLQ topics
-- and settings are deleted in the same change, so nothing reads these keys: the writer's consumer
-- lag threshold, the pipeline's ofi-continuation magnitude floors, its instruments-listener
-- heartbeat and reconnect backoff, and the cross-asset role-symbols key that no code has read since
-- plan 151-09. Each key is deleted from config_history, then config_state, then config_schema, by
-- literal key. The dated fixture tests/integration/fixtures/seed_config_2026-11-05.sql keeps its
-- snapshot rows.
--
-- Rerun semantics: the DELETEs match nothing. No table is rewritten, so no VACUUM clause is owed.

BEGIN;

DELETE FROM config_history WHERE config_key IN (
    'alert.lag.feature-vector-writer',
    'feature.cross_asset.role_symbols',
    'infra.instruments_listener.heartbeat_s',
    'infra.instruments_listener.reconnect_backoff_s',
    'threshold.ofi_continuation.magnitude_floors'
);

DELETE FROM config_state WHERE config_key IN (
    'alert.lag.feature-vector-writer',
    'feature.cross_asset.role_symbols',
    'infra.instruments_listener.heartbeat_s',
    'infra.instruments_listener.reconnect_backoff_s',
    'threshold.ofi_continuation.magnitude_floors'
);

DELETE FROM config_schema WHERE config_key IN (
    'alert.lag.feature-vector-writer',
    'feature.cross_asset.role_symbols',
    'infra.instruments_listener.heartbeat_s',
    'infra.instruments_listener.reconnect_backoff_s',
    'threshold.ofi_continuation.magnitude_floors'
);

COMMIT;
