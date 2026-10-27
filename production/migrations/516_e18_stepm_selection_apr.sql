-- 516: E18 selection parameters (phase 187 plans 04 and 06; unified design 7.3.2; methodology-
-- change-ledger E18). Seeds the four alpha.selection.stepm.* keys read by
-- scripts/research/select_books.py, and restates the E15 budget keys for their post-E18 role:
-- the ledger no longer refuses a book test past M; M remains the book test's power bar divisor
-- and a disclosure count. Not ML learning targets. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('alpha.selection.stepm.fwer', 'float', '0.05', 0.001, 0.2,
 '[user_preference] Family-wise error of the Romano-Wolf StepM selection set over every counted attempt of the vintage (E18, design 7.3.2). A change needs a methodology-change-ledger entry. Not an ML learning target.'),
('alpha.selection.stepm.block_mean_sessions', 'float', '20', 2, 252,
 '[conventional] Mean block length in sessions of the joint stationary bootstrap (about n^(1/3) for 4,000 sessions, rounded up). Must exceed the longest holding horizon in the universe; select_books refuses otherwise. Not an ML learning target.'),
('alpha.selection.stepm.reps', 'integer', '2000', 200, 100000,
 '[conventional] Bootstrap draws for StepM selection. Not an ML learning target.'),
('alpha.selection.stepm.seed', 'integer', '187', 0, 2147483647,
 '[initial_estimate] Seed of the StepM bootstrap index draw. Changing it changes the reported selection set and adjusted p-values; record the change. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.selection.stepm.fwer', '0.05', 1),
    ('alpha.selection.stepm.block_mean_sessions', '20', 1),
    ('alpha.selection.stepm.reps', '2000', 1),
    ('alpha.selection.stepm.seed', '187', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_516',
       'phase 187: E18 StepM selection parameters seeded'
  FROM config_state
 WHERE config_key LIKE 'alpha.selection.stepm.%'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_516');

UPDATE config_schema
   SET description = '[user_preference] M of E15. Since E18 (phase 187) the ledger no longer refuses a book test past M: every attempt is recorded and StepM selection prices them all. M remains the divisor of the book test''s power bar (screen_alpha / M) and is disclosed on book_test rows. A change needs a methodology-change-ledger entry. Not an ML learning target.'
 WHERE config_key = 'alpha.research.budget_m';

UPDATE config_schema
   SET description = '[user_preference] One-sided alpha of E15''s book screen. Since E18 (phase 187) it sets the book test''s power bar (screen_alpha / M) and the disclosed screen block; selection is StepM at alpha.selection.stepm.fwer. A change needs a methodology-change-ledger entry. Not an ML learning target.'
 WHERE config_key = 'alpha.research.screen_alpha';

COMMIT;
