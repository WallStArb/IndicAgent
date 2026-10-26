-- Migration 521: retire what deleting the dashboard's v2.x signal surface orphaned (todo 509
-- item 2, owner decision 2026-10-26: delete the signal panels, their API routes and the empty
-- tables; phase 188's forward runner builds its own views).
--
-- The API routes signals.py, features.py, validation.py and drift.py, the signal events
-- repository, src/intelligence/trading/ and the feature-validation service (its unit, timer and
-- analyzer, which read signal_ledger and shadow_registry and wrote validation_results) are
-- deleted in the same commit.
--
-- Tables: drift_state and setup_performance are empty (0 rows, checked 2026-10-26), have no
-- dependent view or foreign key, and were dumped by plan 185-45 and again to
-- data/backups/509-signal-surface/ (SHA256SUMS there). validation_results is already absent
-- live; IF EXISTS keeps a fresh database consistent. shadow_registry is not dropped: it holds 36
-- rows (I7 plugin enrollment settings), so it falls outside the owner's "empty tables" decision
-- and waits for an owner call in _KEEP_TABLES.
--
-- APR keys: the ten ui.signals.* keys were read only by the deleted signals.py. Retired in the
-- order history, state, schema. Rerun semantics: the DELETEs match nothing and the DROPs are IF
-- EXISTS. No compressed hypertable column is altered, so no VACUUM clause is owed.

BEGIN;

DROP TABLE IF EXISTS drift_state;
DROP TABLE IF EXISTS setup_performance;
DROP TABLE IF EXISTS validation_results;

DELETE FROM config_history WHERE config_key LIKE 'ui.signals.%';
DELETE FROM config_state WHERE config_key LIKE 'ui.signals.%';
DELETE FROM config_schema WHERE config_key LIKE 'ui.signals.%';

COMMIT;
