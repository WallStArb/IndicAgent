-- 596: retire alpha.ic.active_scales.{5m,15m,1h,1d} (migration 271).
--
-- The keys fed canonicalize_active_scales and ACTIVE_SCALES_FALLBACKS_BY_TF in the batch helpers.
-- Their readers (ic_engine, forward_return_writer) were deleted by 186-19 and 186-23, and the two
-- helpers are deleted in the same commit, so nothing reads the keys (the reader check in
-- tests/unit/test_table_and_apr_key_readers.py). Retired in the order history, state, schema.
--
-- Rerun semantics: the DELETEs match nothing. No table is rewritten, so no VACUUM clause is owed.

BEGIN;

DELETE FROM config_history WHERE config_key IN (
    'alpha.ic.active_scales.15m',
    'alpha.ic.active_scales.1d',
    'alpha.ic.active_scales.1h',
    'alpha.ic.active_scales.5m'
);

DELETE FROM config_state WHERE config_key IN (
    'alpha.ic.active_scales.15m',
    'alpha.ic.active_scales.1d',
    'alpha.ic.active_scales.1h',
    'alpha.ic.active_scales.5m'
);

DELETE FROM config_schema WHERE config_key IN (
    'alpha.ic.active_scales.15m',
    'alpha.ic.active_scales.1d',
    'alpha.ic.active_scales.1h',
    'alpha.ic.active_scales.5m'
);

COMMIT;
