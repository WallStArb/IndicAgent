-- Migration 602: retire the two APR keys of the alpaca_basis_run check with the check (todo 623).
--
-- IBKR is removed (Part F deletes its raw rows from 2003-09-10), so the Alpaca-against-IBKR basis
-- run has no input. `threshold.bar_integrity.vendor_ratio_run_min_sessions` was read only by it;
-- `threshold.bar_integrity.alpaca_basis_tolerance_bp` (migration 463) has had no reader since the
-- phase 521 flag was never built. `fallback_basis_window_sessions` and `fallback_basis_tolerance_bp`
-- stay: the daily rule's derivation reads them.
--
-- The earlier history is kept and a final row records the retirement (the 594 pattern); then
-- config_state, then config_schema. The dated fixture tests/integration/fixtures/seed_config_2026-11-05.sql
-- keeps its snapshot rows. Rerun semantics: the history rows are guarded by NOT EXISTS and the DELETEs
-- match nothing. No table is rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version + 1, s.config_value, 'migration_602',
       'Retired: the alpaca_basis_run check was retired with IBKR (todo 623); no reader remains'
  FROM config_state s
 WHERE s.config_key IN ('threshold.bar_integrity.vendor_ratio_run_min_sessions',
                        'threshold.bar_integrity.alpaca_basis_tolerance_bp')
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = s.config_key AND h.changed_by = 'migration_602');

DELETE FROM config_state WHERE config_key IN ('threshold.bar_integrity.vendor_ratio_run_min_sessions',
                                              'threshold.bar_integrity.alpaca_basis_tolerance_bp');
DELETE FROM config_schema WHERE config_key IN ('threshold.bar_integrity.vendor_ratio_run_min_sessions',
                                               'threshold.bar_integrity.alpaca_basis_tolerance_bp');

COMMIT;
