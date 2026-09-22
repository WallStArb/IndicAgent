-- Migration 349: retire the dead infra.ibkr.nightly_backfill_batch_size APR key.
--
-- Companion to today's fix in scripts/infrastructure/backfill/infrastructure_nightly_backfill.py
-- (todo 382, see that file's module docstring for the full incident writeup). The key drove a
-- `LIMIT batch_size` on nightly candidate selection that throttled the wrong resource and
-- mathematically guaranteed a permanent staleness floor; the fix deletes the cap entirely, so
-- no code path reads this key anymore. Deleting rather than leaving it registered-but-unused,
-- per this project's own bias against config knobs that look like they do something but don't
-- -- same reasoning and same pattern as migration 344, which retired this key's sibling
-- (infra.ibkr.nightly_backfill_completeness_threshold) from the same script six days earlier.
--
-- Idempotent: DELETE on a primary key, safe to re-run (zero rows deleted on a re-run).

BEGIN;

DELETE FROM config_history WHERE config_key = 'infra.ibkr.nightly_backfill_batch_size';
DELETE FROM config_state WHERE config_key = 'infra.ibkr.nightly_backfill_batch_size';
DELETE FROM config_schema WHERE config_key = 'infra.ibkr.nightly_backfill_batch_size';

COMMIT;
