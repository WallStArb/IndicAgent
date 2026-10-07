-- 449: tunable thresholds of the 1d integrity verdict report (phase 185 plan 185-33 Task 1).
--
-- services/bar_reconciliation_audit.py (D7) reads all three keys at init and writes one
-- bar_integrity verdict row per (symbol, timeframe, check) (data layer integrity design
-- section 6). The zero-tolerance checks (policy_conformance, lineage_missing,
-- canonical_recompute, digest_fresh) are definitions in code, not keys: a tolerance on them
-- would be a way to pass. Keys are seeded where they are first read; the intraday half (185-40)
-- seeds its own. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('threshold.bar_integrity.session_coverage_min_1d', 'float', '0.999', 0, 1,
 '[initial_estimate] Smallest share of NYSE sessions since a name''s first 1d bar that must hold a bar or an answered-empty record for the session_coverage verdict to pass; a session with neither is a hole the vendors were never asked about. Not an ML learning target.'),
('threshold.bar_integrity.vendor_ratio_run_min_sessions', 'int', '5', 1, 1000,
 '[initial_estimate] Fewest consecutive common sessions on which the IBKR/Tradier close ratio must leave threshold.bar_integrity.fallback_basis_tolerance_bp for the vendor_basis_run verdict to report a run; shorter excursions are single-day vendor noise. Not an ML learning target.'),
('threshold.bar_integrity.report_max_age_hours', 'int', '30', 1, 720,
 '[initial_estimate] Hours a name''s newest integrity verdict may trail its latest 1d load before report_age fails; the gates that read the report re-evaluate the age against now. One nightly cycle plus slack. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.session_coverage_min_1d', '0.999', 1),
    ('threshold.bar_integrity.vendor_ratio_run_min_sessions', '5', 1),
    ('threshold.bar_integrity.report_max_age_hours', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_449',
       'Initial value for the 1d integrity verdict report [initial_estimate]'
  FROM config_state
 WHERE config_key IN ('threshold.bar_integrity.session_coverage_min_1d',
                      'threshold.bar_integrity.vendor_ratio_run_min_sessions',
                      'threshold.bar_integrity.report_max_age_hours')
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_449');

COMMIT;
