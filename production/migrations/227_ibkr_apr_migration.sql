-- Migration 227: infra.ibkr.retry_count / retry_backoff_base_s / no_data_confirmation_chunks
-- APR keys (todo 050)
--
-- Migrates the remaining hardcoded numeric constants in src/providers/ibkr.py's
-- fetch_historical_bars retry loop to APR, following the exact pattern migrations 197
-- (infra.ibkr.chunk_days.*) and 199 (infra.ibkr.*_timeout_sec) already established:
-- scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py overlays
-- these config_state values onto ibkr.py's module-level constants in place at backfill
-- startup (_load_ibkr_retry_config()); IBKRProvider itself has no ConfigService
-- integration and doesn't need one for this. All seeded to their exact current
-- hardcoded values -- byte-for-byte behavior preserved.
--
-- infra.ibkr.chunk_days.* and the two timeout keys already exist (migrations 197/199)
-- and are NOT touched here -- confirmed via live config_schema query before writing
-- this migration, to avoid creating a second, differently-named set of keys for the
-- same already-migrated constants.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ibkr.retry_count',
    'int',
    '3',
    1, 10,
    '[conventional] Number of retry attempts on an ambiguous (non-confirmed-no-data) empty historical-data result before giving up on a chunk. Not an ML learning target.'
),
(
    'infra.ibkr.retry_backoff_base_s',
    'int',
    '65',
    1, 300,
    '[conventional] Base seconds for exponential backoff between retry attempts (base * 2**attempt: 65s then 130s at the default retry_count=3). Not an ML learning target.'
),
(
    'infra.ibkr.no_data_confirmation_chunks',
    'int',
    '2',
    1, 10,
    '[conventional] Consecutive confirmed-no-data (Error 162) chunks required before treating a backward historical-data walk as having passed the instrument''s launch date (todo 049). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ibkr.retry_count', '3', 1),
    ('infra.ibkr.retry_backoff_base_s', '65', 1),
    ('infra.ibkr.no_data_confirmation_chunks', '2', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.ibkr.retry_count', 1, '3', 'migration_235', 'Initial value: matches pre-migration hardcoded constant exactly [conventional]'),
    (NOW(), 'infra.ibkr.retry_backoff_base_s', 1, '65', 'migration_235', 'Initial value: matches pre-migration hardcoded constant exactly [conventional]'),
    (NOW(), 'infra.ibkr.no_data_confirmation_chunks', 1, '2', 'migration_235', 'Initial value: matches pre-migration hardcoded constant exactly [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
