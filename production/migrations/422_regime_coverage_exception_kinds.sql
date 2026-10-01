-- Migration 422: kind and clears_on on the regime coverage auditor exceptions
-- (phase 186 follow-up to 186-18, todo 341)
--
-- Migration 420 seeded five exceptions with a reason and an expiry. The auditor now validates a
-- `kind` per entry: `rebuild_pending` (needs expires and clears_on, the trigger that ends it) or
-- `permanent_degenerate` (a reason, no expiry, capped and listed in the log every run). The five
-- seeded entries are all waiting for the 186-26 rebuild to write their labels, so each becomes
-- kind = rebuild_pending, clears_on = '186-26 rebuild'. Migration 420 is applied and not edited.
-- Also seeds alpha.regime.coverage_auditor.max_permanent_exceptions, the cap on permanent entries.
--
-- Guarded: the update runs only while some entry still lacks `kind`; the seed is ON CONFLICT DO
-- NOTHING; a rerun changes nothing and writes no second history row.

BEGIN;

WITH updated AS (
    UPDATE config_state
    SET config_value = (
            SELECT jsonb_agg(
                       e || jsonb_build_object('kind', 'rebuild_pending', 'clears_on', '186-26 rebuild')
                       ORDER BY ord
                   )::text
            FROM jsonb_array_elements(config_value::jsonb) WITH ORDINALITY AS t(e, ord)
        ),
        version = version + 1,
        updated_at = NOW()
    WHERE config_key = 'alpha.regime.coverage_auditor.known_exceptions'
      AND EXISTS (
          SELECT 1 FROM jsonb_array_elements(config_value::jsonb) AS t(e) WHERE NOT (e ? 'kind')
      )
    RETURNING config_key, config_value, version
)
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_422',
       'Added kind=rebuild_pending and clears_on="186-26 rebuild" to the five seeded exceptions'
FROM updated;

UPDATE config_schema
SET description = '[user_preference] JSON list of {symbol, kind, reason, clears_on, expires, todo}: '
    'symbols whose stored regime is all NULL for a diagnosed reason; regime_coverage_auditor '
    'stays green on these. kind rebuild_pending needs expires (ISO date; after it the entry fails '
    'the job again) and clears_on (the trigger that ends it); kind permanent_degenerate needs a '
    'reason and no expiry, is capped by alpha.regime.coverage_auditor.max_permanent_exceptions '
    'and is listed in the log every run. A listed symbol that is no longer a gap warns; a '
    'malformed list fails the job. Operator-visible switch, not an ML learning target.'
WHERE config_key = 'alpha.regime.coverage_auditor.known_exceptions';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.regime.coverage_auditor.max_permanent_exceptions',
    'int',
    '5',
    0, 50,
    '[initial_estimate] Largest number of permanent_degenerate entries the regime coverage '
    'auditor accepts in known_exceptions; a list above it fails the job, so a permanent '
    'suppression cannot accumulate unnoticed. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.regime.coverage_auditor.max_permanent_exceptions', '5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.regime.coverage_auditor.max_permanent_exceptions', 1, '5', 'migration_422',
       'Initial value [initial_estimate]: cap on permanent coverage exceptions'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = 'alpha.regime.coverage_auditor.max_permanent_exceptions'
      AND h.changed_by = 'migration_422'
);

COMMIT;
