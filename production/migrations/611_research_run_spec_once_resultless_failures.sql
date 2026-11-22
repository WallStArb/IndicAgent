-- Spec-once (D-02) no longer counts a result-less failed run.
--
-- A run killed (an OOM kill, a dropped session) and closed `failed` with no snapshot, no statistic
-- and no series recorded no result, so a rerun cannot be conditioned on one. The ledger guard
-- (src/intelligence/research/ledger.py, RESULTLESS_FAILURE_SQL) and this index must agree: the
-- unique index otherwise refuses the rerun's started rows for the same (spec_hash, concept_id).
-- A failed run with a snapshot, a completed run and a started run all stay in the index. The
-- predicate below is RESULTLESS_FAILURE_SQL verbatim; a unit test compares the two.
-- The ledger guard is stricter than this index (it also keeps a failed row with a series row or a
-- subset refit or a sibling in its run_group that has a snapshot or a statistic) and runs first under the ledger lock;
-- the index is the one-row backstop.
-- Rollback: once any exempt spec has been rerun, recreating the migration 366 index fails with a
-- unique violation. Roll back by recreating this index with a narrower exemption, never by
-- restoring the 366 definition.
-- Budget charging is unchanged (UNCHARGED_STATUSES). research_run is small and not a hypertable;
-- no VACUUM step. Not idempotent on purpose beyond the guarded DROP: the CREATE fails loudly if
-- the old definition was already replaced by hand with a different one.

BEGIN;

DROP INDEX research_run_real_spec_once;

CREATE UNIQUE INDEX research_run_real_spec_once
    ON research_run (spec_hash, concept_id)
    WHERE mode = 'real' AND NOT (status = 'failed' AND snapshot_hash IS NULL AND decision_t IS NULL AND decision_p IS NULL AND gross_sharpe IS NULL AND span_start IS NULL);

COMMIT;
