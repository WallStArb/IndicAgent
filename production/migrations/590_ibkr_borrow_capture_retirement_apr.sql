-- Migration 590: retire the infra.borrow.* APR keys with the IBKR removal (owner 2026-11-13).
--
-- services/borrow_availability_capture.py (the daily IBKR shortability snapshot, todo 438) and
-- its timer are deleted in the same commit: the capture read a reqMktData tick from the IBKR
-- gateway, which is removed. The three keys have no reader left
-- (tests/unit/test_table_and_apr_key_readers.py). Retired in the order history, state, schema.
-- The borrow_availability_snapshots rows stay: raw capture is permanent data.
--
-- Rerun semantics: the DELETEs match nothing. No table is rewritten, so no VACUUM clause is owed.

BEGIN;

DELETE FROM config_history
WHERE config_key IN ('infra.borrow.batch_size', 'infra.borrow.batch_pause_s', 'infra.borrow.batch_wait_s');
DELETE FROM config_state
WHERE config_key IN ('infra.borrow.batch_size', 'infra.borrow.batch_pause_s', 'infra.borrow.batch_wait_s');
DELETE FROM config_schema
WHERE config_key IN ('infra.borrow.batch_size', 'infra.borrow.batch_pause_s', 'infra.borrow.batch_wait_s');

COMMIT;
