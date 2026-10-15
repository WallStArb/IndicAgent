-- Migration 486: compression policy for ohlcv_raw (phase 191)
--
-- The design (docs/plans/2026-10-12-unified-raw-bar-table-design.md) makes raw a compressed
-- hypertable segmented by (symbol, timeframe, vendor). Migration-era setup enabled compression
-- and set the segmentby, but never added a policy, so on 2026-10-15 all 339 chunks were
-- uncompressed: 517M rows, 57 GB heap plus 71 GB of indexes. The archive it replaces holds
-- 202M rows compressed in 7.2 GB.
--
-- Chunks older than `infra.ohlcv_raw.compress_after_days` are compressed. Recent chunks stay
-- row-form so last-wins replacements of recent bars stay cheap; a replacement in an older
-- chunk is a decompress-and-update, accepted in the design because restatements are rare.
-- New rows into old chunks (the deep 5m backfill) are inserts and stay cheap.
--
-- Existing eligible chunks are compressed outside this transaction, one chunk at a time.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'infra.ohlcv_raw.compress_after_days',
    'int', '60', 7, 3650,
    '[initial_estimate] ohlcv_raw chunks older than this many days are compressed by the '
    'TimescaleDB policy (migration 486). Younger chunks stay row-form so last-wins replacements '
    'of recent bars avoid a decompress. Changing it needs the policy re-added '
    '(remove_compression_policy, add_compression_policy). Not an ML target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.ohlcv_raw.compress_after_days', '60', 1)
ON CONFLICT (config_key) DO NOTHING;

DO $$
DECLARE
    days int := (SELECT config_value::int FROM config_state
                 WHERE config_key = 'infra.ohlcv_raw.compress_after_days');
BEGIN
    PERFORM add_compression_policy('ohlcv_raw', make_interval(days => days), if_not_exists => true);
END
$$;

COMMIT;
