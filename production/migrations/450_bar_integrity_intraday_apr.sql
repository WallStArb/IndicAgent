-- 450: tunable thresholds of the intraday integrity checks (phase 185 plan 185-40).
--
-- services/bar_reconciliation_audit.py (D7) reads both keys at init and writes the intraday
-- bar_integrity verdicts: slot_coverage (5m, per calendar year, against the floor below) and the
-- digest_fresh cadence (months written since the previous report, and every month once the last
-- full sweep is older than the cadence below). Data layer integrity design sections 5 and 6.
-- The zero-tolerance intraday checks (grid_parity on 15m, stray_vendor_rows, coverage_cache,
-- digest_fresh) are definitions in code, not keys. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('threshold.bar_integrity.slot_coverage_min_intraday', 'float', '0.995', 0, 1,
 '[rca_analysis] Smallest share of expected regular-hours 5m slots (NYSE calendar, half days and DST) that must hold a stored bar, a zero-volume provider bar or an answered-empty request window, in every calendar year from a name''s first 5m bar, for the slot_coverage verdict to pass. Measured 2007-2023 level 0.996. Not an ML learning target.'),
('infra.bar_integrity.intraday_full_sweep_days', 'int', '7', 1, 365,
 '[conventional] Days after which the intraday digest_fresh check recomputes every month of every name instead of only the months written since the previous report; the weekly full sweep of the data layer integrity design. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.slot_coverage_min_intraday', '0.995', 1),
    ('infra.bar_integrity.intraday_full_sweep_days', '7', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_450',
       'Initial value for the intraday integrity checks (rca_analysis / conventional)'
  FROM config_state
 WHERE config_key IN ('threshold.bar_integrity.slot_coverage_min_intraday',
                      'infra.bar_integrity.intraday_full_sweep_days')
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_450');

COMMIT;
