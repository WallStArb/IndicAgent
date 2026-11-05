-- Migration 576: APR changes for the regime_writer retirement (todo 590).
--
-- 1. Retire infra.regime_writer.workers. services/regime_writer.py, the v1 in-place writer of
--    feature_vectors' regime columns, is deleted in the same commit: since migration 570
--    feature_vectors is the kernel table, which the rebuild writer fills (regime columns
--    included) through bulk_load. The key has no reader left
--    (tests/unit/test_table_and_apr_key_readers.py). Retired in the order history, state, schema
--    (as migrations 499, 502, 504, 505 and 561).
-- 2. Seed infra.tradeable_series.fetch_block_rows. The writer's full-series bar fetch moved to
--    services/_batch_utils.fetch_tradeable_series for the regime screening and golden-capture
--    tools, and its hard-coded fetchmany(10000) becomes this key (migrate-as-you-go), seeded at
--    the same value so the tools' results do not change.
--
-- Rerun semantics: the DELETEs match nothing and the INSERTs skip on conflict. No table is
-- rewritten, so no VACUUM clause is owed.

BEGIN;

DELETE FROM config_history WHERE config_key = 'infra.regime_writer.workers';
DELETE FROM config_state WHERE config_key = 'infra.regime_writer.workers';
DELETE FROM config_schema WHERE config_key = 'infra.regime_writer.workers';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.tradeable_series.fetch_block_rows',
        'int', '10000', 1000, 1000000,
        '[conventional] Rows per server-side cursor round trip in services/_batch_utils.py fetch_tradeable_series, the whole-series market_data_ohlcv_tradeable fetch the regime screening and golden-capture tools share (moved from the retired regime_writer, todo 590). Memory and round trips only; results do not depend on it. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.tradeable_series.fetch_block_rows', '10000', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
