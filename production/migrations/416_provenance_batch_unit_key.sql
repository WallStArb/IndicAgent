-- Migration 416: provenance_batch.unit_key, the identity of a replaceable unit (phase 186 plan 14)
--
-- A bulk_load unit that replaces its prior rows (replace_where) is identified by a unit_key:
-- sha256 over (writer, target_table, tf, replace_where), computed once by BulkLoadSpec. The
-- replace path deletes the rows named by replace_where and flips every other completed row
-- with the same unit_key to 'superseded', so the DELETE predicate and the provenance flip are
-- one definition. Before this column the flip matched on (writer, target, tf, range, symbols),
-- so a run over a different symbol set loaded beside the prior unit instead of replacing it.
--
-- Existing rows would have no unit_key and none can be derived (replace_where was never stored),
-- so the migration refuses when the table holds any row; provenance_batch is empty when it is
-- applied (the only writer of rows is services/ic_measure.py, which has not run for real).
--
-- provenance_batch is a plain table (not a hypertable): no compression, no VACUUM step.
-- Not idempotent on purpose: a second apply fails loudly on ADD COLUMN.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM provenance_batch) THEN
        RAISE EXCEPTION 'migration 416 refuses: provenance_batch holds rows that have no unit_key and none can be derived; decide their fate before adding the column'
            USING ERRCODE = 'check_violation';
    END IF;
END
$$;

ALTER TABLE provenance_batch ADD COLUMN unit_key text NOT NULL;

ALTER TABLE provenance_batch
    ADD CONSTRAINT provenance_batch_unit_key_check CHECK (unit_key ~ '^[0-9a-f]{64}$');

CREATE INDEX provenance_batch_unit_key_status ON provenance_batch (unit_key, status);

COMMENT ON COLUMN provenance_batch.unit_key IS
    'sha256 of (writer, target_table, tf, replace_where) (migration 416): the identity of the '
    'unit whose rows a replacing load owns. Every completed row sharing it, other than the '
    'current batch_key, is flipped to superseded by the replace path.';

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

    IF OLD.status = 'completed' THEN
        -- The one completed -> superseded flip changes status and nothing else
        -- (186-14 replace path).
        IF NEW.row_count IS DISTINCT FROM OLD.row_count
           OR NEW.attempts IS DISTINCT FROM OLD.attempts
           OR NEW.error IS DISTINCT FROM OLD.error
           OR NEW.started_at IS DISTINCT FROM OLD.started_at
           OR NEW.finished_at IS DISTINCT FROM OLD.finished_at THEN
            RAISE EXCEPTION 'provenance_batch: a completed row can change only its status '
                '(to superseded), not row_count, attempts, error, started_at or finished_at'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_provenance_batch_guard() IS
    'provenance_batch guard (migrations 386 and 416): identity columns (batch_key through '
    'input_digest, and unit_key) are immutable; allowed status transitions are '
    'started->completed, started->failed, failed->started, started->started (takeover restamp) '
    'and completed->superseded; superseded is terminal; a completed row changes only its status.';

COMMIT;
