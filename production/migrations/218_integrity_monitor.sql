-- Migration 218: integrity_monitor hypertable — Phase 143 Plan 03
--
-- Observability-only gate-evaluation facts written by ic_engine's post-run lifecycle
-- hook (LIFECYCLE-03/04). NOT authoritative state — feature_transition_log remains the
-- sole authoritative transition record; this table exists purely so a run's decay/hold
-- decision is queryable (LIFECYCLE-06 diagnostics, T-143-07 repudiation mitigation).
--
-- Idempotency (T-143-11): TimescaleDB requires every unique index on a hypertable to
-- include the partitioning column (evaluated_at), so the DB-level UNIQUE index below is
-- keyed on (monitor_type, training_window_end, metric_name, subject, evaluated_at) --
-- it only catches an exact-instant double-insert (e.g. a retried statement within the
-- same transaction), not a rerun hours/days later with a fresh evaluated_at=now().
-- The REAL rerun-idempotency guarantee is the hook's own step-0 pre-check (SELECT 1
-- FROM integrity_monitor WHERE training_window_end=... LIMIT 1, done BEFORE any insert
-- is attempted) -- this is application-layer idempotency, and it is authoritative. The
-- DB UNIQUE index is defense-in-depth against a genuine concurrent/same-instant double
-- writer, not the primary de-dup mechanism. Postgres treats NULL as distinct from NULL
-- in a plain unique index, so the nullable subject column (NULL for run-level facts
-- like the regime-shift hold and the per-run gate-evaluation fact) is normalized via
-- COALESCE(subject, '') inside a functional unique index rather than relying on the
-- raw column.
--
-- All statements idempotent: CREATE TABLE IF NOT EXISTS, ON CONFLICT DO NOTHING.
-- Safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS integrity_monitor (
    id                   BIGSERIAL,
    monitor_type         TEXT NOT NULL,          -- this phase writes 'ic_lifecycle'
    subject              TEXT,                   -- feature/cell identifier; NULL for run-level facts
    metric_name          TEXT NOT NULL,
    metric_value         DOUBLE PRECISION,
    threshold_value      DOUBLE PRECISION,
    passed               BOOLEAN NOT NULL,
    training_window_end  TIMESTAMPTZ,
    evaluated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE integrity_monitor IS
    'Observability-only gate-evaluation facts (e.g. ic_engine lifecycle hook decay/hold '
    'decisions). NOT authoritative state -- feature_transition_log is the sole authoritative '
    'transition record. Query-only audit trail for LIFECYCLE-06 diagnostics.';

SELECT create_hypertable(
    'integrity_monitor',
    'evaluated_at',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS integrity_monitor_type_time_idx
    ON integrity_monitor (monitor_type, evaluated_at);

-- Idempotency key (T-143-11): defense-in-depth against an exact-instant double-insert.
-- Must include evaluated_at (the hypertable partitioning column, TimescaleDB requirement) --
-- see the header comment for why the hook's own pre-check, not this index, is the
-- authoritative rerun-idempotency guarantee.
CREATE UNIQUE INDEX IF NOT EXISTS integrity_monitor_idempotency_uq
    ON integrity_monitor (monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at);

COMMIT;
