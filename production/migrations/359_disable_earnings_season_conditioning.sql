-- Migration 359: disable ic_engine's earnings-season conditioning passes (todo 403)
--
-- The pre-registered, dependence-robust rule
-- (docs/research/earnings-season-conditioning-null-controlled-prereg.md, committed df8cea78b
-- before the run) returned CONDITIONING_VERDICT=NOT_SHARPENED on the persisted 176-08 rows:
-- 0 of 249 eligible (feature, tf) units significant under Benjamini-Yekutieli, in either the
-- in-season or the mirror arm, with unit median z centred on zero in every tf. It supersedes
-- 176-08's SHARPENS token, which came from a rule with no minimum N and no null.
--
-- alpha.ic.earnings_season_conditioned is a computational fingerprint field; this lands in the
-- post-176 bundle, whose recompute already invalidates every cell. Persisted earnings-season
-- rows are kept. Rollback token: DISABLED (set back to true to re-enable).

BEGIN;

UPDATE config_state
SET config_value = 'false', version = version + 1, updated_at = NOW()
WHERE config_key = 'alpha.ic.earnings_season_conditioned';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_359',
       'Todo 403 pre-registered null-controlled rule: NOT_SHARPENED (0/249 units BY-significant). '
       'docs/research/earnings-season-conditioning-null-controlled-prereg.md. Rollback token DISABLED. '
       '[rca_analysis]'
FROM config_state
WHERE config_key = 'alpha.ic.earnings_season_conditioned';

COMMIT;
