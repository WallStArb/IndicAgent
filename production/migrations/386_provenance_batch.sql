-- Migration 386: provenance_batch, the bulk-load lineage and idempotency record (phase 186)
--
-- Design: docs/plans/2026-09-26-unified-research-to-production-design.md (section 3.3, and
-- section 14.6 item 3) and
-- .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md
-- (D-24, D-37).
--
-- One row per bulk_load() unit: the identity (writer, target table, time column, tf, half-open
-- range, sorted symbols, per-kernel code key, APR snapshot hash and blob, input content digest)
-- hashed into batch_key, which is the primary key and therefore the idempotency key. A rerun
-- with the same identity finds the completed row and writes nothing; a killed run leaves a
-- 'started' row the next run takes over; a failed run leaves a 'failed' row with the error text
-- that the next run retries. Rows are never deleted: the triggers below enforce this in the
-- database, not only in Python.
--
-- Status lifecycle: started -> completed | failed, failed -> started (retry),
-- started -> started (takeover restamp after a kill), completed -> superseded (186-14's
-- replace path flips the previous unit's row when it delete-and-COPYs a replaced unit, so a
-- replaced unit keeps exactly one completed provenance row: the current key). superseded is
-- terminal. Identity columns are immutable once written.
--
-- Sole writer: services/_batch_utils.py bulk_load (enforced by
-- tests/unit/test_provenance_batch_sole_writer.py). No migration or service may
-- INSERT INTO provenance_batch, UPDATE provenance_batch or
-- DELETE FROM provenance_batch; the guard triggers below enforce the same rule in
-- the database.
--
-- Volume: one row per load unit (tens per rebuild partition), not per row and not per chunk
-- (design 12.1: no per-row provenance column).
-- Not a hypertable; no VACUUM step.
-- Not idempotent on purpose: a second apply fails loudly on CREATE TABLE.

BEGIN;

CREATE TABLE provenance_batch (
    batch_key    text        PRIMARY KEY,
    writer       text        NOT NULL,
    target_table text        NOT NULL,
    time_column  text        NOT NULL,
    tf           text        NOT NULL,
    range_start  timestamptz NOT NULL,
    range_end    timestamptz NOT NULL,
    symbols      text[]      NOT NULL,
    symbols_hash text        NOT NULL,
    code_key     text        NOT NULL,
    apr_hash     text        NOT NULL,
    apr_snapshot jsonb       NOT NULL,
    input_digest text        NOT NULL,
    row_count    bigint,
    status       text        NOT NULL DEFAULT 'started',
    attempts     integer     NOT NULL DEFAULT 1,
    error        text,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    CONSTRAINT provenance_batch_batch_key_check
        CHECK (batch_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT provenance_batch_symbols_hash_check
        CHECK (symbols_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT provenance_batch_apr_hash_check
        CHECK (apr_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT provenance_batch_code_key_check
        CHECK (code_key ~ '^[0-9a-f]{32,64}$'),
    CONSTRAINT provenance_batch_input_digest_check
        CHECK (input_digest ~ '^[0-9a-f]{32,64}$'),
    CONSTRAINT provenance_batch_range_check
        CHECK (range_start < range_end),
    CONSTRAINT provenance_batch_symbols_check
        CHECK (cardinality(symbols) > 0),
    CONSTRAINT provenance_batch_status_check
        CHECK (status = ANY (ARRAY['started', 'completed', 'failed', 'superseded'])),
    CONSTRAINT provenance_batch_completed_check
        CHECK (status <> 'completed' OR (row_count IS NOT NULL AND finished_at IS NOT NULL))
);

CREATE INDEX provenance_batch_target_tf_range
    ON provenance_batch (target_table, tf, range_start);

COMMENT ON TABLE provenance_batch IS
    'Bulk-load lineage and idempotency record (phase 186, migration 386, D-24/D-37): one row '
    'per bulk_load unit, primary key batch_key is the idempotency key, so a rerun with the same '
    'identity is a no-op and a killed or failed run is retried on the same key. Append-only: '
    'identity columns are immutable, completed rows are frozen, rows are never deleted. Sole '
    'writer: services/_batch_utils.py bulk_load.';

-- ---------------------------------------------------------------------------
-- Update guard: identity immutable, allowed status transitions only
-- ---------------------------------------------------------------------------

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
    'provenance_batch guard (migration 386): identity columns (batch_key through input_digest) '
    'are immutable; allowed status transitions are started->completed, started->failed, '
    'failed->started, started->started (takeover restamp) and completed->superseded; superseded '
    'is terminal; a completed row changes only its status.';

DROP TRIGGER IF EXISTS trg_provenance_batch_guard ON provenance_batch;

CREATE TRIGGER trg_provenance_batch_guard
    BEFORE UPDATE ON provenance_batch
    FOR EACH ROW
    EXECUTE FUNCTION fn_provenance_batch_guard();

-- ---------------------------------------------------------------------------
-- No delete, no truncate
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_provenance_batch_no_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'provenance_batch is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_provenance_batch_no_delete() IS
    'Refuses DELETE (row trigger) and TRUNCATE (statement trigger) on provenance_batch '
    '(migration 386): provenance rows are records, never deleted.';

DROP TRIGGER IF EXISTS trg_provenance_batch_no_delete ON provenance_batch;

CREATE TRIGGER trg_provenance_batch_no_delete
    BEFORE DELETE ON provenance_batch
    FOR EACH ROW
    EXECUTE FUNCTION fn_provenance_batch_no_delete();

DROP TRIGGER IF EXISTS trg_provenance_batch_no_truncate ON provenance_batch;

CREATE TRIGGER trg_provenance_batch_no_truncate
    BEFORE TRUNCATE ON provenance_batch
    FOR EACH STATEMENT
    EXECUTE FUNCTION fn_provenance_batch_no_delete();

-- ---------------------------------------------------------------------------
-- APR seeds (D-24)
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.bulk_load.statement_timeout_ms',
    'int',
    '14400000',
    60000, NULL,
    '[conventional] statement_timeout for one bulk_load() data transaction (COPY plus the '
    'completed-provenance update). Same value as the write session key '
    'infra.compressed_hypertable_write_session.statement_timeout_ms (migration 314): one load '
    'unit must survive a multiday rebuild''s slowest partition. Not an ML learning target.'
),
(
    'infra.bulk_load.compress_on_complete',
    'bool',
    'true',
    NULL, NULL,
    '[initial_estimate] Operator switch: when false, bulk_load() skips the per-chunk '
    'compress_completed_chunks step so a pilot can measure the uncompressed working set before '
    'committing to it. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.bulk_load.statement_timeout_ms', '14400000', 1),
('infra.bulk_load.compress_on_complete', 'true', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'infra.bulk_load.statement_timeout_ms', 1, '14400000', 'migration_386',
 'Initial value: matches the write session statement_timeout (migration 314) [conventional]'),
(NOW(), 'infra.bulk_load.compress_on_complete', 1, 'true', 'migration_386',
 'Initial value: compress completed chunks after each unit [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
