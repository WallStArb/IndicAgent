-- Migration 490: retire infra.bar_campaign.bootstrap_years (phase 191 plan 11).
--
-- Plan 191-11 deleted scripts/ops/bars/ops_d1_bootstrap.py, the phase 185 D1 bootstrap (legacy
-- import plus one paired TRADES / ADJUSTED_LAST fresh fetch, both done 2026-09-30; the history it
-- wrote is in ohlcv_raw since the plan 03 backfill). It was the only reader of this key (seeded
-- by migration 400, live value 20).
-- Reader check, 2026-10-15: grep -rn "bootstrap_years" scripts services src  -> no output.
--
-- Config rows only. History, then state, then schema (the retirement order of migration 457),
-- by literal key, in one transaction. Idempotent: a rerun deletes nothing.
-- Rollback: \copy data/backups/191-11/config_{schema,state,history}.csv back (that order), or
-- re-run the seed block of migration 400.

BEGIN;

DELETE FROM config_history
 WHERE config_key IN ('infra.bar_campaign.bootstrap_years');
DELETE FROM config_state
 WHERE config_key IN ('infra.bar_campaign.bootstrap_years');
DELETE FROM config_schema
 WHERE config_key IN ('infra.bar_campaign.bootstrap_years');

COMMIT;
