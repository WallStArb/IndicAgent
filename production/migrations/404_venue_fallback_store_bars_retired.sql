-- 404: infra.ibkr.venue_fallback.store_bars is retired (phase 185 plan 19, D-17).
--
-- D3 is rebased on D1: the provider records every venue's answer through on_observation and
-- never returns venue bars for storage, whatever this key says. Whether venue history ever
-- becomes canonical 1d bars is D2's decision (infra.bar_derivation.venue_bars_1d, gated on
-- the venue study verdict). The key stays, value false, read only so a true value logs its
-- retirement in the provider. Idempotent.

BEGIN;

UPDATE config_schema
SET description = '[retired 2026-10-03, migration 404] Governs nothing: the provider never returns venue bars for storage; venue answers reach D1 through on_observation and D2 decides (infra.bar_derivation.venue_bars_1d). Left false; a true value only logs its retirement. Not an ML learning target.'
WHERE config_key = 'infra.ibkr.venue_fallback.store_bars'
  AND description NOT LIKE '[retired%';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.venue_fallback.store_bars', 1, 'false', 'migration_404',
       'Retired: venue bars never reach storage through the provider (plan 185-19, D-17)'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history
    WHERE config_key = 'infra.ibkr.venue_fallback.store_bars' AND changed_by = 'migration_404'
);

COMMIT;
