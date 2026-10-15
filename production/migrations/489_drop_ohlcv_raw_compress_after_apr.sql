-- Migration 489: drop the APR key infra.ohlcv_raw.compress_after_days (seeded by 486)
--
-- The age lives in the TimescaleDB job config (timescaledb_information.jobs.config ->>
-- 'compress_after'), the same place every other hypertable's compression age lives, and
-- services/compression_auditor.py reads it from there. The APR key only duplicated it with no
-- reader (tests/unit/test_table_and_apr_key_readers.py). The policy itself is unchanged.

BEGIN;
DELETE FROM config_state WHERE config_key = 'infra.ohlcv_raw.compress_after_days';
DELETE FROM config_schema WHERE config_key = 'infra.ohlcv_raw.compress_after_days';
COMMIT;
