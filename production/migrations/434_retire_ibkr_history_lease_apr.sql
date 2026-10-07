-- Migration 434: retire the IBKR history lease APR keys (phase 189 plan 08).
--
-- Plan 189-08 turned the historical pipeline into the CLI-free helper library
-- scripts/infrastructure/backfill/_history_fetch.py and deleted its ibkr_history_stream
-- ResourceLease (D-29). Every IBKR history fetch now takes the phase 189 FetcherLock, which
-- is fail-fast and has no wait bound, so neither key below has a reader:
--   infra.ibkr_history_lease.nightly_wait_minutes   (seed 60, migration 380; last reader the
--                                                    deleted nightly, then the pipeline's help)
--   infra.ibkr_history_lease.priority_wait_minutes  (seed 240, migration 380; last reader the
--                                                    pipeline's _load_lease_apr_minutes)
-- Reader check, 2026-10-07: grep -rn "ibkr_history_lease" services src scripts  -> no output.
-- Live values before this migration: 60 and 240, one config_history row each.
--
-- History, then state, then schema (the retirement order of migrations 349 and 431), by
-- literal key, in one transaction. Idempotent: a rerun deletes nothing.
-- Rollback: re-run migration 380's two INSERT blocks for these keys.

BEGIN;

DELETE FROM config_history
 WHERE config_key IN ('infra.ibkr_history_lease.nightly_wait_minutes',
                      'infra.ibkr_history_lease.priority_wait_minutes');
DELETE FROM config_state
 WHERE config_key IN ('infra.ibkr_history_lease.nightly_wait_minutes',
                      'infra.ibkr_history_lease.priority_wait_minutes');
DELETE FROM config_schema
 WHERE config_key IN ('infra.ibkr_history_lease.nightly_wait_minutes',
                      'infra.ibkr_history_lease.priority_wait_minutes');

COMMIT;
