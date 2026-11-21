-- 607: the corpus rerun data gate's named exceptions (ledger 2026-11-21b, todo 593).
--
-- infra.corpus_rerun.data_gate.held_name_years is a JSON list of {symbol, year, evidence}: a name-year
-- in it does not gate and the gate result reports it as held with its evidence
-- (services/corpus_rerun_data_gate.py evaluate, read through services/corpus_rerun_apr.py).
-- Seeded with the two POWI years. It is part of APR_KEYS, so it joins every run's apr_hash (a new
-- pinned key moves the hash of every run created after it, which is intended). The Massive raw
-- rows for POWI are sparse (300 rows for 2006-01 to 2008-01 against about 525 expected, none for
-- Jan to Jul 2007 or Sep 2006) and canonical equals raw; the cause is unverified.
-- Idempotent; no table is rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.corpus_rerun.data_gate.held_name_years', 'json',
 '[{"symbol": "POWI", "year": 2006, "evidence": "Massive raw rows absent (300 rows for 2006-01 to 2008-01 against about 525 expected, none for Sep 2006), canonical equals raw, cause unverified; 70 of 251 judged sessions missing"}, {"symbol": "POWI", "year": 2007, "evidence": "Massive raw rows absent (none for Jan to Jul 2007), canonical equals raw, cause unverified; 153 of 251 judged sessions missing"}]',
 NULL, NULL,
 '[user_preference] JSON list (read with json.loads) of {symbol, year, evidence}: name-years the corpus rerun data gate holds instead of failing, reported with their evidence (ledger 2026-11-21b). Each entry needs written evidence. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('infra.corpus_rerun.data_gate.held_name_years',
 '[{"symbol": "POWI", "year": 2006, "evidence": "Massive raw rows absent (300 rows for 2006-01 to 2008-01 against about 525 expected, none for Sep 2006), canonical equals raw, cause unverified; 70 of 251 judged sessions missing"}, {"symbol": "POWI", "year": 2007, "evidence": "Massive raw rows absent (none for Jan to Jul 2007), canonical equals raw, cause unverified; 153 of 251 judged sessions missing"}]',
 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_607',
       'Initial value for the corpus rerun data gate named exceptions (ledger 2026-11-21b)'
  FROM config_state
 WHERE config_key = 'infra.corpus_rerun.data_gate.held_name_years'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = 'infra.corpus_rerun.data_gate.held_name_years'
                     AND h.changed_by = 'migration_607');

COMMIT;
