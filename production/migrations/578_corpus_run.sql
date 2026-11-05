-- Migration 578: run identity for the corpus rerun and the fresh IC run (phase 186 plan 30,
-- todo 593, lead decision 2026-11-04).
--
-- corpus_run is one rerun: its identity (run_id, created_at, code_commit, code_key, horizon,
-- apr_hash, spans, free_bytes_at_launch) is fixed when 186-31's --new-run creates it and never
-- changes (a trigger raises), so every gate that reads "the run" reads the run that was planned.
-- caveats only grows: an update must keep the old array as its prefix (append only), so a
-- disclosed caveat (the pre-2016 survivorship caveat of 186-32's data gate) cannot be dropped
-- or rewritten. data_gate holds the data_gate step's measured counts; measured holds the
-- figures the run measures as it goes (bytes per row, stored bytes per spool byte).
-- corpus_run_step is the step runner's bookkeeping, one row per (run, step).
--
-- provenance_batch.run_id records the run a unit was loaded under. It is outside batch_key and
-- unit_key (computed in services/_batch_utils.py, never here), so a unit resumed under another
-- run keeps its identity and a completed unit is skipped whatever run asks for it. The 418 guard
-- is extended: run_id moves only on a takeover to started (a stale started row or a failed row
-- retried, the only path where bulk_load re-stamps a row), and a completed row's run_id is
-- frozen with its other execution columns, so the completed -> superseded flip cannot touch it.
--
-- No hypertable, no compression, no VACUUM step. Not idempotent on purpose: a second apply fails
-- loudly on CREATE TABLE.

BEGIN;

CREATE TABLE corpus_run (
    run_id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    code_commit text NOT NULL CHECK (code_commit ~ '^[0-9a-f]{40,64}$'),
    code_key text NOT NULL CHECK (code_key ~ '^[0-9a-f]{32,64}$'),
    horizon timestamptz NOT NULL,
    apr_hash text NOT NULL CHECK (apr_hash ~ '^[0-9a-f]{64}$'),
    spans jsonb NOT NULL CHECK (jsonb_typeof(spans) = 'array'),
    free_bytes_at_launch bigint NOT NULL CHECK (free_bytes_at_launch > 0),
    caveats jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(caveats) = 'array'),
    data_gate jsonb NULL,
    measured jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(measured) = 'object'),
    status text NOT NULL DEFAULT 'started'
        CHECK (status IN ('started', 'completed', 'failed'))
);

COMMENT ON TABLE corpus_run IS
    'One corpus rerun and fresh IC run (186-30, todo 593). Identity columns are immutable '
    '(fn_corpus_run_guard); caveats is append only; provenance_batch.run_id names the run a '
    'unit was loaded under.';
COMMENT ON COLUMN corpus_run.spans IS
    'The [span_start, span_end) pairs of the intraday history, Jan 1 UTC bounds, in run order '
    '(186-31 --new-run picks them from the disk budget). Immutable.';
COMMENT ON COLUMN corpus_run.free_bytes_at_launch IS
    'Free bytes of the database volume when the run was created (statvfs); the disk budget '
    'base. Immutable.';
COMMENT ON COLUMN corpus_run.caveats IS
    'Disclosures every gate summary carries verbatim (for example the pre-2016 survivorship '
    'caveat). Append only: an update keeps the old array as its prefix.';
COMMENT ON COLUMN corpus_run.data_gate IS
    'The data_gate step''s measured counts (186-32 run_data_gate); NULL until it runs.';
COMMENT ON COLUMN corpus_run.measured IS
    'Figures measured during the run: bytes per row, stored bytes per spool byte.';

CREATE TABLE corpus_run_step (
    run_id uuid NOT NULL REFERENCES corpus_run (run_id),
    step text NOT NULL,
    status text NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz NULL,
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, step)
);

COMMENT ON TABLE corpus_run_step IS
    'One row per (corpus_run, step) of the 186-31 step runner: status and the step summary.';

CREATE OR REPLACE FUNCTION fn_corpus_run_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.code_commit IS DISTINCT FROM OLD.code_commit
       OR NEW.code_key IS DISTINCT FROM OLD.code_key
       OR NEW.horizon IS DISTINCT FROM OLD.horizon
       OR NEW.apr_hash IS DISTINCT FROM OLD.apr_hash
       OR NEW.spans IS DISTINCT FROM OLD.spans
       OR NEW.free_bytes_at_launch IS DISTINCT FROM OLD.free_bytes_at_launch THEN
        RAISE EXCEPTION 'corpus_run identity is immutable: run_id, created_at, code_commit, '
            'code_key, horizon, apr_hash, spans and free_bytes_at_launch'
            USING ERRCODE = 'check_violation';
    END IF;
    -- Append only: every old element stays at its position, so the old array is the new
    -- array's prefix (a missing position reads NULL and fails). Containment (@>) alone would
    -- let an element be rewritten by adding keys to it, or a duplicate be dropped.
    IF EXISTS (
           SELECT 1
           FROM jsonb_array_elements(OLD.caveats) WITH ORDINALITY AS o(elem, i)
           WHERE o.elem IS DISTINCT FROM NEW.caveats -> (o.i::int - 1)
       ) THEN
        RAISE EXCEPTION 'corpus_run.caveats is append only: an update must keep every '
            'existing caveat, in place'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_corpus_run_guard() IS
    'corpus_run guard (migration 578): the identity columns are immutable and caveats is '
    'append only.';

CREATE TRIGGER trg_corpus_run_guard
    BEFORE UPDATE ON corpus_run
    FOR EACH ROW EXECUTE FUNCTION fn_corpus_run_guard();

ALTER TABLE provenance_batch ADD COLUMN run_id uuid NULL;

COMMENT ON COLUMN provenance_batch.run_id IS
    'The corpus_run this row was loaded under (NULL outside a run). Outside batch_key and '
    'unit_key; moves only on a takeover to started; frozen on a completed row (migration 578).';

CREATE INDEX provenance_batch_run_id_status ON provenance_batch (run_id, status);

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

    IF OLD.status = 'completed' THEN
        -- The one completed -> superseded flip changes status and nothing else
        -- (186-14 replace path).
        IF NEW.row_count IS DISTINCT FROM OLD.row_count
           OR NEW.attempts IS DISTINCT FROM OLD.attempts
           OR NEW.error IS DISTINCT FROM OLD.error
           OR NEW.started_at IS DISTINCT FROM OLD.started_at
           OR NEW.finished_at IS DISTINCT FROM OLD.finished_at
           OR NEW.run_id IS DISTINCT FROM OLD.run_id THEN
            RAISE EXCEPTION 'provenance_batch: a completed row can change only its status '
                '(to superseded), not row_count, attempts, error, started_at, finished_at '
                'or run_id'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_provenance_batch_guard() IS
    'provenance_batch guard (migrations 386, 416, 418, 578): identity columns (batch_key through '
    'input_digest, unit_key and generation) are immutable; allowed status transitions are '
    'started->completed, started->failed, failed->started, started->started (takeover restamp) '
    'and completed->superseded; superseded is terminal; run_id changes only on a takeover to '
    'started; a completed row changes only its status.';

COMMIT;
