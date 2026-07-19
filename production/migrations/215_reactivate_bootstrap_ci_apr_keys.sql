-- Migration 215: Reactivate alpha.ic.bootstrap_* APR keys -- Phase 143.1-01 (Component A, todo 091)
--
-- These 6 keys were seeded by migrations 161/165/177 for the circular block bootstrap CI
-- that was removed in commit c6f5056b (2026-06-26, replaced by the Fisher z-transform CI)
-- and marked "[deprecated] ... code no longer reads these keys" in config_schema.description
-- at that time. Phase 143.1-01 restores the corrected bootstrap
-- (src/intelligence/statistics/ic_math.py:_circular_block_bootstrap_ic) as the production
-- CI at all 3 services/ic_engine.py call sites -- these keys have a real reader again as of
-- this same commit. Strip the [deprecated] prefix so the config UI (/config/parameters)
-- stops surfacing them as unused.
--
-- Note (todo 095): a directory-split migration-numbering collision risk exists across
-- concurrent plans in this wave; this migration claims 222 (verified next-free at execution
-- time -- 221 was already in-flight, uncommitted, from unrelated concurrent work).

BEGIN;

UPDATE config_schema
SET description = REPLACE(description, '[deprecated] ', '')
WHERE config_key IN (
    'alpha.ic.bootstrap_seed',
    'alpha.ic.bootstrap_resamples',
    'alpha.ic.bootstrap_block_size.5m',
    'alpha.ic.bootstrap_block_size.15m',
    'alpha.ic.bootstrap_block_size.1h',
    'alpha.ic.bootstrap_block_size.1d'
);

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT
    NOW(),
    cs.config_key,
    cs.version,
    cst.config_value,
    'migration_222',
    'Reactivated: circular block bootstrap CI restored as production CI (Component A, '
        || 'todo 091, Phase 143.1-01) -- description [deprecated] prefix stripped, key now '
        || 'has a real reader in services/ic_engine.py.'
FROM config_schema cs
JOIN config_state cst ON cst.config_key = cs.config_key
WHERE cs.config_key IN (
    'alpha.ic.bootstrap_seed',
    'alpha.ic.bootstrap_resamples',
    'alpha.ic.bootstrap_block_size.5m',
    'alpha.ic.bootstrap_block_size.15m',
    'alpha.ic.bootstrap_block_size.1h',
    'alpha.ic.bootstrap_block_size.1d'
)
ON CONFLICT DO NOTHING;

COMMIT;
