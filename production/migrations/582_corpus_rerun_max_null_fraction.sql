-- 582: the corpus rerun's NULL-share gate (phase 186 plan 186-31 review fix 2, todo 593).
--
-- feature_complete (services/corpus_rerun.py) runs the column screen with --null-gate: per
-- (tf, column) the NULL or non-finite share of the rows past the column's declared warmup, on
-- the columns the registry declares applicable to the tf, must stay at or below this value.
-- 0.05 is the threshold of the deleted corpus verifier (corpus.verifier.max_null_rate default).
-- Read through services/corpus_rerun_apr.py load_corpus_rerun_apr. Idempotent; no table is
-- rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.corpus_rerun.max_null_fraction', 'float', '0.05', 0, 1,
 '[conventional] Largest NULL or non-finite share of a feature column''s post-warmup rows on a timeframe the column applies to, for the corpus rerun''s feature_complete step to pass (the deleted corpus verifier''s max_null_rate). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.corpus_rerun.max_null_fraction', '0.05', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_582',
       'Initial value for the corpus rerun NULL-share gate (186-31)'
  FROM config_state
 WHERE config_key = 'infra.corpus_rerun.max_null_fraction'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = 'infra.corpus_rerun.max_null_fraction'
                     AND h.changed_by = 'migration_582');

COMMIT;
