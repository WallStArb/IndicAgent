-- 507: threshold.dividend.max_failure_fraction, the per-name isolation gate of the dividend
-- event writer (D-191-O precedent: one name's failure never blocks the others).
--
-- services/dividend_event_writer.py already isolates per-name derivation and write failures:
-- the successes of a pass are written and the failures are collected with symbol and reason.
-- Since 2026-10-16 the nightly Yahoo pass fails on a permanent minority of dead or thin names
-- (PSKY, WBD, QRVO, CCO) while the other ~1,525 names complete, and the unconditional
-- RuntimeError poisoned the systemd unit state every day. This key decides the run's end
-- state: a failed-symbol fraction at or below it completes with a partial status; above it the
-- unit exits nonzero. Read at init via ConfigService.get().
-- Provenance [conventional]; gates unit failure vs partial; not an ML learning target.
-- Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('threshold.dividend.max_failure_fraction', 'float', '0.05', 0, 1,
 '[conventional] Largest share of a dividend_event_writer run''s symbols that may fail derivation or write before the unit exits nonzero instead of completing with a partial status; gates unit failure vs partial (per-name isolation, D-191-O). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.dividend.max_failure_fraction', '0.05', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_507',
       'Initial value for the dividend writer per-name isolation gate (conventional)'
  FROM config_state
 WHERE config_key = 'threshold.dividend.max_failure_fraction'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_507');

COMMIT;
