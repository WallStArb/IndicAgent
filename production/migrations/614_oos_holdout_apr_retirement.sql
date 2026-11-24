-- Migration 614: retire the APR key of the deleted ops_oos_holdout_eval diagnostic (todo 554). Its only
-- reader was that script, deleted 2026-11-24 with the other legacy feature_vectors readers; the key has no
-- reader left (tests/unit/test_table_and_apr_key_readers.py). Retired in the order history, state, schema.
--
-- Rerun semantics: the DELETEs match nothing. No table is rewritten, so no VACUUM clause is owed.

BEGIN;

DELETE FROM config_history WHERE config_key = 'alpha.validation.oos_significant_drop_fraction';

DELETE FROM config_state WHERE config_key = 'alpha.validation.oos_significant_drop_fraction';

DELETE FROM config_schema WHERE config_key = 'alpha.validation.oos_significant_drop_fraction';

COMMIT;
