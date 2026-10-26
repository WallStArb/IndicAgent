-- Migration 515: research attempt schema (phase 187 plan 01; unified design 10.2, 7.2, 7.3.2).
--
-- concept_recipe: append-only recipe versions per concept (design 10.2.2).
-- research_run: becomes the attempt table. recipe_hash and informed_by are set at insert and
--   never change; typed headline columns move from NULL to a value once, at the terminal
--   update (like snapshot_hash); mode gains exploration, kind gains pod_book and legacy_verdict.
-- research_run_series: the per-session E17 D_s of every counted attempt, the input of StepM
--   selection (7.3.2). Insert-only, and only for a run already terminal as completed or failed
--   (a run that computed a statistic and then failed still counts, 7.1).
-- Indexes on every FK in the UCR schema.
--
-- Sole writer of all three tables: src/intelligence/research/ledger.py (S6).

BEGIN;

-- ---------------------------------------------------------------------------
-- concept_recipe
-- ---------------------------------------------------------------------------

CREATE TABLE concept_recipe (
    recipe_id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id        uuid        NOT NULL REFERENCES concept_registry (concept_id),
    version           integer     NOT NULL CHECK (version >= 1),
    recipe_hash       text        NOT NULL UNIQUE CHECK (recipe_hash ~ '^[0-9a-f]{64}$'),
    code_pointer      text        NOT NULL CHECK (code_pointer ~ '^[A-Za-z0-9_.]+:[A-Za-z0-9_]+$'),
    code_commit       text        NOT NULL CHECK (code_commit ~ '^[0-9a-f]{40}$'),
    params            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    apr_values        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    inputs            jsonb       NOT NULL DEFAULT '[]'::jsonb,
    universe_selector jsonb,
    cvr_codes         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    mechanism         text,
    sources           text[]      NOT NULL DEFAULT '{}',
    author            text        NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT concept_recipe_concept_version_key UNIQUE (concept_id, version)
);

COMMENT ON TABLE concept_recipe IS
    'Recipe versions per concept (unified design 10.2.2, migration 515). Append-only: '
    'UPDATE, DELETE and TRUNCATE are refused. Sole writer: src/intelligence/research/ledger.py.';

CREATE OR REPLACE FUNCTION fn_concept_recipe_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'concept_recipe is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_concept_recipe_no_update
    BEFORE UPDATE OR DELETE ON concept_recipe
    FOR EACH ROW EXECUTE FUNCTION fn_concept_recipe_append_only();

CREATE TRIGGER trg_concept_recipe_no_truncate
    BEFORE TRUNCATE ON concept_recipe
    FOR EACH STATEMENT EXECUTE FUNCTION fn_concept_recipe_append_only();

-- ---------------------------------------------------------------------------
-- research_run: attempt columns
-- ---------------------------------------------------------------------------

ALTER TABLE research_run
    ADD COLUMN recipe_hash          text REFERENCES concept_recipe (recipe_hash),
    ADD COLUMN informed_by          uuid REFERENCES research_run (run_id),
    ADD COLUMN decision_t           double precision,
    ADD COLUMN decision_p           double precision,
    ADD COLUMN gross_sharpe         double precision,
    ADD COLUMN mean_session_pnl     double precision,
    ADD COLUMN turnover_per_session double precision,
    ADD COLUMN n_sessions           integer,
    ADD COLUMN span_start           date,
    ADD COLUMN span_end             date;

ALTER TABLE research_run DROP CONSTRAINT research_run_mode_check;
ALTER TABLE research_run ADD CONSTRAINT research_run_mode_check
    CHECK (mode = ANY (ARRAY['real', 'exploration']));

ALTER TABLE research_run DROP CONSTRAINT research_run_kind_check;
ALTER TABLE research_run ADD CONSTRAINT research_run_kind_check
    CHECK (kind = ANY (ARRAY['evidence', 'book_test', 'pod_book', 'legacy_verdict']));

-- Only a book_test carries the M = 30 budget columns (they retire with E18, plan 06).
ALTER TABLE research_run DROP CONSTRAINT research_run_book_budget_check;
ALTER TABLE research_run ADD CONSTRAINT research_run_book_budget_check
    CHECK (kind <> 'book_test' OR (budget_m IS NOT NULL AND screen_alpha IS NOT NULL));

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
           OR NEW.snapshot_hash IS NOT NULL
           OR NEW.decision_t IS NOT NULL OR NEW.decision_p IS NOT NULL
           OR NEW.gross_sharpe IS NOT NULL OR NEW.mean_session_pnl IS NOT NULL
           OR NEW.turnover_per_session IS NOT NULL OR NEW.n_sessions IS NOT NULL
           OR NEW.span_start IS NOT NULL OR NEW.span_end IS NOT NULL THEN
            RAISE EXCEPTION 'research_run is append-only: a started row carries no evidence, '
                'finished_at, snapshot_hash or headline numbers'
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
       OR NEW.started_at IS DISTINCT FROM OLD.started_at
       OR NEW.recipe_hash IS DISTINCT FROM OLD.recipe_hash
       OR NEW.informed_by IS DISTINCT FROM OLD.informed_by THEN
        RAISE EXCEPTION 'research_run is append-only: only status, snapshot_hash, evidence, '
            'finished_at and the headline numbers change, once'
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

COMMENT ON COLUMN research_run.recipe_hash IS
    'concept_recipe version the attempt ran (design 10.2.3); set at insert, never changed.';
COMMENT ON COLUMN research_run.informed_by IS
    'The attempt whose result prompted this one (design 10.2.3); set at insert, never changed.';

-- ---------------------------------------------------------------------------
-- research_run_series
-- ---------------------------------------------------------------------------

CREATE TABLE research_run_series (
    run_id     uuid        PRIMARY KEY REFERENCES research_run (run_id),
    sessions   date[]      NOT NULL,
    d_s        float8[]    NOT NULL,
    written_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_run_series_lengths_check
        CHECK (cardinality(sessions) > 0 AND cardinality(sessions) = cardinality(d_s))
);

COMMENT ON TABLE research_run_series IS
    'Per-session E17 D_s of each counted attempt, the StepM selection universe (design 7.3.2, '
    'migration 515). Insert-only, for a run already terminal as completed or failed. '
    'Sole writer: src/intelligence/research/ledger.py.';

CREATE OR REPLACE FUNCTION fn_research_run_series_guard()
RETURNS TRIGGER AS $$
DECLARE
    parent_status text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'research_run_series is append-only: % is not allowed', TG_OP
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT status INTO parent_status FROM research_run WHERE run_id = NEW.run_id;
    IF parent_status IS NULL OR parent_status NOT IN ('completed', 'failed') THEN
        RAISE EXCEPTION 'research_run_series: run % must be terminal as completed or failed, is %',
            NEW.run_id, parent_status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_research_run_series_guard
    BEFORE INSERT OR UPDATE OR DELETE ON research_run_series
    FOR EACH ROW EXECUTE FUNCTION fn_research_run_series_guard();

CREATE TRIGGER trg_research_run_series_no_truncate
    BEFORE TRUNCATE ON research_run_series
    FOR EACH STATEMENT EXECUTE FUNCTION fn_concept_recipe_append_only();

-- ---------------------------------------------------------------------------
-- Indexes on every FK in the UCR schema
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS concept_registry_parent_concept_id_idx
    ON concept_registry (parent_concept_id);
CREATE INDEX IF NOT EXISTS research_run_concept_id_idx ON research_run (concept_id);
CREATE INDEX IF NOT EXISTS research_run_informed_by_idx ON research_run (informed_by);
CREATE INDEX IF NOT EXISTS concept_recipe_concept_id_idx ON concept_recipe (concept_id);
CREATE INDEX IF NOT EXISTS instrument_classification_scheme_idx
    ON instrument_classification (scheme);

COMMIT;
