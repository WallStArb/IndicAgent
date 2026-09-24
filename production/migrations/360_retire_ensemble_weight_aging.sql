-- Migration 360: retire alpha.ensemble.weight_half_life_days and
-- alpha.ensemble.weight_stale_max_days (todo 408).
--
-- ensemble_trainer aged each stratum's quality weights by the wall clock:
-- exp(-days_since / half_life), and 1/n once days_since passed stale_max_days. The decay
-- never did anything, because derive_weights renormalizes and a uniform scalar cancels.
-- The stale branch did: the 2026-09-22 champion was trained 272 days after its IC window
-- ended, so every 1d stratum weight came out exactly 1/n. The weight fit now lives in
-- src/intelligence/ensemble/stratum_fit.py as a pure function of the IC rows and the
-- training-window feature matrix, with no clock, so no code path reads either key.
-- Deleted rather than left registered-but-unused, same pattern as migrations 344/349.
--
-- Idempotent: DELETE on a primary key, safe to re-run.

BEGIN;

DELETE FROM config_history
 WHERE config_key IN ('alpha.ensemble.weight_half_life_days', 'alpha.ensemble.weight_stale_max_days');
DELETE FROM config_state
 WHERE config_key IN ('alpha.ensemble.weight_half_life_days', 'alpha.ensemble.weight_stale_max_days');
DELETE FROM config_schema
 WHERE config_key IN ('alpha.ensemble.weight_half_life_days', 'alpha.ensemble.weight_stale_max_days');

COMMIT;
