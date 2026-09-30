-- Migration 418: provenance_batch.generation, so a superseded identity can load again (phase 186
-- plan 14 review fixes, F1)
--
-- A replaced unit's key (K1) becomes 'superseded' when another identity (K2) replaces it, and
-- superseded is terminal. If the inputs then return to K1 (the ABA case), K1 is the right
-- identity again but its row cannot move back to completed, and before this migration the
-- writer computed K1 in full and then refused it. History must not be rewritten (the table is
-- append-only and guarded by a trigger), so a returning identity is a NEW row of the same
-- batch_key with generation + 1: the primary key becomes (batch_key, generation), the old
-- superseded row stays as history, and at most one row per batch_key is ever not superseded.
-- batch_key stays the content identity (the skip and idempotency key); generation is outside it.
--
-- Existing rows take generation 1. provenance_batch is a plain table (not a hypertable): no
-- compression, no VACUUM step. Not idempotent on purpose: a second apply fails loudly on
-- ADD COLUMN.

BEGIN;

ALTER TABLE provenance_batch ADD COLUMN generation integer NOT NULL DEFAULT 1;

ALTER TABLE provenance_batch
    ADD CONSTRAINT provenance_batch_generation_check CHECK (generation >= 1);

ALTER TABLE provenance_batch DROP CONSTRAINT provenance_batch_pkey;

ALTER TABLE provenance_batch
    ADD CONSTRAINT provenance_batch_pkey PRIMARY KEY (batch_key, generation);

COMMENT ON COLUMN provenance_batch.generation IS
    '1 for the first row of a batch_key (migration 418); a superseded identity that returns loads '
    'as a new row with generation + 1. Immutable. batch_key stays the content identity.';

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
    'provenance_batch guard (migrations 386, 416, 418): identity columns (batch_key through '
    'input_digest, unit_key and generation) are immutable; allowed status transitions are '
    'started->completed, started->failed, failed->started, started->started (takeover restamp) '
    'and completed->superseded; superseded is terminal; a completed row changes only its status.';

COMMIT;
