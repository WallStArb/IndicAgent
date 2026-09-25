-- Migration 366: research_run, the S6 run-record ledger of the research layer (phase 183)
--
-- Design: .planning/phases/183-research-layer-runner-ledger-combiner-book-test/183-CONTEXT.md
-- (D-02, D-05 to D-08) and docs/plans/2026-09-24-evidence-framework.md (E15).
--
-- One row per evidence measurement (kind 'evidence', one row per family member) or per book
-- test (kind 'book_test'). The runner writes a 'started' row before it touches the data
-- snapshot, and moves it exactly once to a terminal status ('completed', 'guard_failed',
-- 'refused', 'failed') when the run ends. Rows are never edited after that and never deleted:
-- the triggers below enforce this in the database, not only in Python.
--
-- Why concept_evaluation (migration 357) is not reused (D-06): its primary key
-- (concept_id, window_end, evidence_key), its lifecycle evaluated_status enumeration and its
-- guard_status enumeration belong to the feature lifecycle and do not fit a started/terminal
-- run state. This is a deliberate deviation from the evidence framework draft 3 sketch, which
-- put run records in concept_evaluation.
--
-- Identity (families, members, book versions) lives in concept_registry with
-- domain = 'construction'; lineage lives in concept_parent. Both, and this table, are written
-- only by src/intelligence/research/ledger.py (D-05, enforced by
-- tests/unit/research/test_ledger_sole_writer.py).
--
-- Writer contract (migration 283 wording): any writer of research_run, of construction-domain
-- identity rows or of their concept_parent edges MUST take pg_advisory_xact_lock(183366)
-- first, then count and insert in the same transaction. That makes the spec-once check and
-- the vintage budget count (M) race-free and satisfies concept_parent's cycle-guard contract.
--
-- Spec-once (D-02): the partial unique index research_run_real_spec_once refuses a second
-- real-mode row for the same (spec_hash, concept_id); ledger.py additionally refuses any
-- second run for a spec hash. mode is 'real' only: D-04 writes no synthetic rows.
--
-- Budget (D-08): book tests with status 'started', 'completed' or 'failed' are charged
-- against alpha.research.budget_m for their vintage; 'refused' and 'guard_failed' book tests
-- and all evidence runs are uncharged.
--
-- Volume: tens of rows per vintage. Not a hypertable; no VACUUM step.
-- Not idempotent on purpose: a second apply fails loudly on CREATE TABLE.

BEGIN;

CREATE TABLE research_run (
    run_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_group     uuid        NOT NULL,
    concept_id    uuid        NOT NULL REFERENCES concept_registry (concept_id),
    kind          text        NOT NULL,
    mode          text        NOT NULL,
    spec_path     text        NOT NULL,
    spec_hash     text        NOT NULL,
    spec_blob     text        NOT NULL,
    code_commit   text        NOT NULL,
    snapshot_hash text,
    vintage       text        NOT NULL,
    budget_m      integer,
    screen_alpha  double precision,
    status        text        NOT NULL DEFAULT 'started',
    evidence      jsonb,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    CONSTRAINT research_run_kind_check
        CHECK (kind = ANY (ARRAY['evidence', 'book_test'])),
    CONSTRAINT research_run_mode_check
        CHECK (mode = 'real'),
    CONSTRAINT research_run_spec_hash_check
        CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT research_run_code_commit_check
        CHECK (code_commit ~ '^[0-9a-f]{40}$'),
    CONSTRAINT research_run_status_check
        CHECK (status = ANY (ARRAY['started', 'completed', 'guard_failed', 'refused', 'failed'])),
    CONSTRAINT research_run_book_budget_check
        CHECK (kind = 'evidence' OR (budget_m IS NOT NULL AND screen_alpha IS NOT NULL))
);

CREATE UNIQUE INDEX research_run_real_spec_once
    ON research_run (spec_hash, concept_id) WHERE mode = 'real';

CREATE INDEX research_run_budget_idx
    ON research_run (vintage, kind, status);

COMMENT ON TABLE research_run IS
    'S6 run records of the research layer (phase 183, migration 366): one row per evidence '
    'measurement or book test. Append-only: inserted as started, moved exactly once to a '
    'terminal status, never deleted. Sole writer: src/intelligence/research/ledger.py, under '
    'pg_advisory_xact_lock(183366).';

-- ---------------------------------------------------------------------------
-- Insert/update guard: started on insert, one terminal transition, nothing else edits
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_research_run_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'started' THEN
            RAISE EXCEPTION 'research_run is append-only: a row must be inserted as started, got %',
                NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.evidence IS NOT NULL OR NEW.finished_at IS NOT NULL
           OR NEW.snapshot_hash IS NOT NULL THEN
            RAISE EXCEPTION 'research_run is append-only: a started row carries no evidence, '
                'finished_at or snapshot_hash'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    -- UPDATE
    IF OLD.status <> 'started' THEN
        RAISE EXCEPTION 'research_run is append-only: run % is already terminal (%)',
            OLD.run_id, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status NOT IN ('completed', 'guard_failed', 'refused', 'failed') THEN
        RAISE EXCEPTION 'research_run is append-only: a started row may only move to a '
            'terminal status, got %', NEW.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.finished_at IS NULL THEN
        RAISE EXCEPTION 'research_run is append-only: a terminal row needs finished_at'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.run_group IS DISTINCT FROM OLD.run_group
       OR NEW.concept_id IS DISTINCT FROM OLD.concept_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.mode IS DISTINCT FROM OLD.mode
       OR NEW.spec_path IS DISTINCT FROM OLD.spec_path
       OR NEW.spec_hash IS DISTINCT FROM OLD.spec_hash
       OR NEW.spec_blob IS DISTINCT FROM OLD.spec_blob
       OR NEW.code_commit IS DISTINCT FROM OLD.code_commit
       OR NEW.vintage IS DISTINCT FROM OLD.vintage
       OR NEW.budget_m IS DISTINCT FROM OLD.budget_m
       OR NEW.screen_alpha IS DISTINCT FROM OLD.screen_alpha
       OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
        RAISE EXCEPTION 'research_run is append-only: only status, snapshot_hash, evidence and '
            'finished_at change, once'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.snapshot_hash IS NOT NULL
       AND NEW.snapshot_hash IS DISTINCT FROM OLD.snapshot_hash THEN
        RAISE EXCEPTION 'research_run is append-only: snapshot_hash may go from NULL to a '
            'value, never change'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_research_run_guard() IS
    'research_run append-only guard (migration 366): INSERT must be started with no evidence, '
    'finished_at or snapshot_hash; UPDATE only moves a started row to a terminal status once, '
    'setting finished_at, evidence and snapshot_hash (NULL to value only, pitfall 7); every '
    'other column is immutable.';

DROP TRIGGER IF EXISTS trg_research_run_guard ON research_run;

CREATE TRIGGER trg_research_run_guard
    BEFORE INSERT OR UPDATE ON research_run
    FOR EACH ROW
    EXECUTE FUNCTION fn_research_run_guard();

-- ---------------------------------------------------------------------------
-- No delete, no truncate
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_research_run_no_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'research_run is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_research_run_no_delete() IS
    'Refuses DELETE (row trigger) and TRUNCATE (statement trigger) on research_run '
    '(migration 366): run records are permanent, a run that was seen cannot be unseen.';

DROP TRIGGER IF EXISTS trg_research_run_no_delete ON research_run;

CREATE TRIGGER trg_research_run_no_delete
    BEFORE DELETE ON research_run
    FOR EACH ROW
    EXECUTE FUNCTION fn_research_run_no_delete();

DROP TRIGGER IF EXISTS trg_research_run_no_truncate ON research_run;

CREATE TRIGGER trg_research_run_no_truncate
    BEFORE TRUNCATE ON research_run
    FOR EACH STATEMENT
    EXECUTE FUNCTION fn_research_run_no_delete();

-- ---------------------------------------------------------------------------
-- APR seeds (D-08): vintage-1 budget and runner workers
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.research.vintage_id',
    'str',
    'vintage_1',
    NULL, NULL,
    '[user_preference] Research vintage the screen budget is charged against. Vintage 1 = '
    'data before alpha.validation.oos_start (2025-12-24). A change needs a '
    'methodology-change-ledger entry (docs/plans/methodology-change-ledger.md). Not an ML '
    'learning target.'
),
(
    'alpha.research.budget_m',
    'int',
    '30',
    1, NULL,
    '[user_preference] M, the number of book versions that may be screen-tested on the '
    'vintage (evidence framework E15); the bar is screen_alpha / M. A change needs a '
    'methodology-change-ledger entry (docs/plans/methodology-change-ledger.md). Not an ML '
    'learning target.'
),
(
    'alpha.research.screen_alpha',
    'float',
    '0.05',
    0, 1,
    '[user_preference] One-sided family alpha of the book screen before division by M '
    '(evidence framework E15). A change needs a methodology-change-ledger entry '
    '(docs/plans/methodology-change-ledger.md). Not an ML learning target.'
),
(
    'infra.research_runner.workers',
    'int',
    '8',
    1, NULL,
    '[initial_estimate] Worker processes for the research runner''s shift null and power '
    'replicates. Throughput only; results do not depend on it. Matches '
    'infra.ic_engine.workers. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.research.vintage_id', 'vintage_1', 1),
('alpha.research.budget_m', '30', 1),
('alpha.research.screen_alpha', '0.05', 1),
('infra.research_runner.workers', '8', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
