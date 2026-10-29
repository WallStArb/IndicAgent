-- Migration 539: lower the exact-Shapley family limit from 12 to 8 (phase 187 plan 14 review).
--
-- alpha.research.contribution.shapley_exact_max_families bounds the family count at which Shapley is
-- computed exactly: 2^F - 2 subset refits, each one a counted attempt in StepM's universe (design
-- 7.1). 12 families would write 4,094 attempts for one book; 8 writes 254. 8 = [initial_estimate]
-- of what the selection universe can absorb per book until StepM's time is measured on the
-- resulting size (the 187-14 review amendment). Above it a book records leave-one-family-out only.
-- Not an ML learning target. Idempotent.

BEGIN;

UPDATE config_schema
SET default_value = '8',
    description = '[initial_estimate] Contribution accounting: Shapley over families is exact (every subset refit, each a counted attempt) while the book has at most this many families; above it the block records leave-one-family-out only. 8 = 254 subset refits per book; 12 would be 4,094 attempts in the StepM universe. Not an ML learning target.'
WHERE config_key = 'alpha.research.contribution.shapley_exact_max_families';

WITH moved AS (
    UPDATE config_state
    SET config_value = '8', version = version + 1
    WHERE config_key = 'alpha.research.contribution.shapley_exact_max_families'
      AND config_value <> '8'
    RETURNING config_key, version, config_value
)
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), config_key, version, config_value, 'migration_539',
       'exact Shapley limit 12 to 8: each subset refit is a counted attempt (plan 187-14 review)'
FROM moved;

COMMIT;
