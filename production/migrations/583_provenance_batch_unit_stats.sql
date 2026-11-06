-- Migration 583: per-unit measurements on the provenance record (phase 186 plan 31 review
-- round 4, lead ruling 2026-11-06, todo 593).
--
-- provenance_batch.unit_stats holds what the writer measured of a unit's rows when it loaded
-- them. The rebuild writer records, per object-dependent feature column (and the event
-- columns), {present, nan_present}: rows where the kernel's own object or validity state is true
-- (its none mask is 0), and of those the rows stored missing. The corpus rerun's G6 judges an
-- object column's NULL share as sum(nan_present) / sum(present) over the run's units, per (tf,
-- column). NULL for every writer that measures nothing (ic_measure) and for rows written before
-- this migration.
--
-- Not identity (outside batch_key and unit_key). The 578 guard is extended: unit_stats is set
-- only on the started -> completed transition and, like every execution column of a completed
-- row, frozen afterwards (the completed -> superseded flip cannot touch it). Adding a nullable
-- column rewrites nothing, so no VACUUM step. Not idempotent on purpose: a second apply fails
-- on ADD COLUMN.

BEGIN;

ALTER TABLE provenance_batch ADD COLUMN unit_stats jsonb NULL
    CHECK (unit_stats IS NULL OR jsonb_typeof(unit_stats) = 'object');

COMMENT ON COLUMN provenance_batch.unit_stats IS
    'What the writer measured of the unit''s rows at load (rebuild: per object-dependent column '
    '{present, nan_present}); set with the completion, frozen after (migration 583).';

CREATE OR REPLACE FUNCTION fn_provenance_batch_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.batch_key IS DISTINCT FROM OLD.batch_key THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: batch_key'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.writer IS DISTINCT FROM OLD.writer THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: writer'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.target_table IS DISTINCT FROM OLD.target_table THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: target_table'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.time_column IS DISTINCT FROM OLD.time_column THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: time_column'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.tf IS DISTINCT FROM OLD.tf THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: tf'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.range_start IS DISTINCT FROM OLD.range_start
       OR NEW.range_end IS DISTINCT FROM OLD.range_end THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: range_start/range_end'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.symbols IS DISTINCT FROM OLD.symbols THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: symbols'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.symbols_hash IS DISTINCT FROM OLD.symbols_hash THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: symbols_hash'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.code_key IS DISTINCT FROM OLD.code_key THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: code_key'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.apr_hash IS DISTINCT FROM OLD.apr_hash THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: apr_hash'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.apr_snapshot IS DISTINCT FROM OLD.apr_snapshot THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: apr_snapshot'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.input_digest IS DISTINCT FROM OLD.input_digest THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: input_digest'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.unit_key IS DISTINCT FROM OLD.unit_key THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: unit_key'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.generation IS DISTINCT FROM OLD.generation THEN
        RAISE EXCEPTION 'provenance_batch identity is immutable: generation'
            USING ERRCODE = 'check_violation';
    END IF;

    IF OLD.status = 'superseded' THEN
        RAISE EXCEPTION 'provenance_batch: superseded is terminal, no transition out'
            USING ERRCODE = 'check_violation';
    END IF;

    IF NOT (
        (OLD.status = 'started' AND NEW.status IN ('completed', 'failed', 'started'))
        OR (OLD.status = 'failed' AND NEW.status = 'started')
        OR (OLD.status = 'completed' AND NEW.status = 'superseded')
    ) THEN
        RAISE EXCEPTION 'provenance_batch: status transition % -> % is not allowed',
            OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;

    -- The run a row was loaded under moves only when a takeover re-stamps it (a stale started
    -- row or a failed row retried under another run, migration 578).
    IF NEW.run_id IS DISTINCT FROM OLD.run_id
       AND NOT (NEW.status = 'started' AND OLD.status IN ('started', 'failed')) THEN
        RAISE EXCEPTION 'provenance_batch: run_id may change only on a takeover to started '
            '(% -> %)', OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;

    -- unit_stats (migration 583) is what the writer measured of the unit's rows: it is set only
    -- with the completion, never on a started, failed or superseded transition.
    IF NEW.unit_stats IS DISTINCT FROM OLD.unit_stats
       AND NOT (OLD.status = 'started' AND NEW.status = 'completed') THEN
        RAISE EXCEPTION 'provenance_batch: unit_stats is set only on started -> completed '
            '(% -> %)', OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;

    IF OLD.status = 'completed' THEN
        -- The one completed -> superseded flip changes status and nothing else
        -- (186-14 replace path).
        IF NEW.row_count IS DISTINCT FROM OLD.row_count
           OR NEW.attempts IS DISTINCT FROM OLD.attempts
           OR NEW.error IS DISTINCT FROM OLD.error
           OR NEW.started_at IS DISTINCT FROM OLD.started_at
           OR NEW.finished_at IS DISTINCT FROM OLD.finished_at
           OR NEW.run_id IS DISTINCT FROM OLD.run_id
           OR NEW.unit_stats IS DISTINCT FROM OLD.unit_stats THEN
            RAISE EXCEPTION 'provenance_batch: a completed row can change only its status '
                '(to superseded), not row_count, attempts, error, started_at, finished_at, '
                'run_id or unit_stats'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_provenance_batch_guard() IS
    'provenance_batch guard (migrations 386, 416, 418, 578, 583): identity columns (batch_key '
    'through input_digest, unit_key and generation) are immutable; allowed status transitions are '
    'started->completed, started->failed, failed->started, started->started (takeover restamp) '
    'and completed->superseded; superseded is terminal; run_id changes only on a takeover to '
    'started; unit_stats is set only on started->completed; a completed row changes only its '
    'status.';

COMMIT;
