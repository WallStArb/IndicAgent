-- Migration 613: retire the APR keys of the deleted grid_parity and check_daily_vs_intraday checks
-- (todo 657, commit 4c5e6fdf5). grid_recompute replaced the grid_parity archive comparison and the
-- daily-vs-intraday check was retired; these three keys have no reader left
-- (tests/unit/test_table_and_apr_key_readers.py). Retired in the order history, state, schema.
--
-- Rerun semantics: the DELETEs match nothing. No table is rewritten, so no VACUUM clause is owed.

BEGIN;

DELETE FROM config_history WHERE config_key IN (
    'infra.grid_parity.dated_exceptions',
    'threshold.bar_reconciliation.close_tolerance_bp',
    'threshold.bar_reconciliation.volume_tolerance_rel'
);

DELETE FROM config_state WHERE config_key IN (
    'infra.grid_parity.dated_exceptions',
    'threshold.bar_reconciliation.close_tolerance_bp',
    'threshold.bar_reconciliation.volume_tolerance_rel'
);

DELETE FROM config_schema WHERE config_key IN (
    'infra.grid_parity.dated_exceptions',
    'threshold.bar_reconciliation.close_tolerance_bp',
    'threshold.bar_reconciliation.volume_tolerance_rel'
);

COMMIT;
