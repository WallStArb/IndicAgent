-- Migration 367: enforce the classification tables' point-in-time invariants in the DB.
--
-- Phase 182 review (2026-09-25). Migration 364 states these invariants in comments only; any
-- writer could break them silently, and each break is a look-ahead leak through reference
-- data, the failure class the tables exist to prevent:
--   1. Overlapping validity windows. The partial unique index allows one OPEN row per
--      (symbol, scheme), but a closed row [2026-09-25, 2026-12-01) and a later row
--      [2026-11-01, open) could coexist, and an as-of lookup for November would return two
--      classifications (ClassificationService returns the first match: an arbitrary answer).
--   2. Rewriting history. An UPDATE of code or valid_from, a DELETE, or a TRUNCATE changes what
--      the table says was true on past dates.
--   3. Backdating. D-07: no history before the date it is recorded. A row inserted with a past
--      valid_from, or closed with a past valid_to, rewrites past as-of answers.
-- Node rows get the same treatment for their identity columns (D-01 node immutability).
-- Live data before this migration: 295 rows, one per symbol, all valid_from 2026-09-25, so
-- every guard holds on arrival.
BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- 1. No two rows for the same (symbol, scheme) may cover the same day.
ALTER TABLE instrument_classification
    ADD CONSTRAINT ex_instrument_classification_no_overlap
    EXCLUDE USING gist (
        symbol WITH =,
        scheme WITH =,
        daterange(valid_from, valid_to, '[)') WITH &&
    );

-- 2 and 3. Append-only membership: insert with valid_from on or after today (UTC); the only
-- permitted update closes an open row with valid_to on or after today; no delete, no truncate.
CREATE OR REPLACE FUNCTION instrument_classification_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    today date := (now() AT TIME ZONE 'UTC')::date;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.valid_from < today THEN
            RAISE EXCEPTION 'instrument_classification: backdated insert for % (valid_from % < today %); history is recorded forward only (D-07)',
                NEW.symbol, NEW.valid_from, today;
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.valid_to IS NOT NULL THEN
            RAISE EXCEPTION 'instrument_classification: row (%, %, %) is closed and immutable',
                OLD.symbol, OLD.scheme, OLD.valid_from;
        END IF;
        IF (NEW.symbol, NEW.scheme, NEW.code, NEW.valid_from, NEW.source_ref, NEW.created_at)
           IS DISTINCT FROM
           (OLD.symbol, OLD.scheme, OLD.code, OLD.valid_from, OLD.source_ref, OLD.created_at) THEN
            RAISE EXCEPTION 'instrument_classification: only valid_to may change (close the row, insert a new one)';
        END IF;
        IF NEW.valid_to IS NULL OR NEW.valid_to < today THEN
            RAISE EXCEPTION 'instrument_classification: close % with valid_to on or after today % (got %)',
                OLD.symbol, today, NEW.valid_to;
        END IF;
        RETURN NEW;
    ELSE
        RAISE EXCEPTION 'instrument_classification is append-only: % is not allowed', TG_OP;
    END IF;
END $$;

CREATE TRIGGER trg_instrument_classification_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON instrument_classification
    FOR EACH ROW EXECUTE FUNCTION instrument_classification_append_only();
CREATE TRIGGER trg_instrument_classification_no_truncate
    BEFORE TRUNCATE ON instrument_classification
    FOR EACH STATEMENT EXECUTE FUNCTION instrument_classification_append_only();

-- Nodes: identity (scheme, code, parent_code, level, path, valid_from) is immutable; name may
-- change (display metadata); valid_to may be set once, on or after today; no delete, no truncate.
CREATE OR REPLACE FUNCTION classification_node_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    today date := (now() AT TIME ZONE 'UTC')::date;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.scheme, NEW.code, NEW.parent_code, NEW.level, NEW.path, NEW.valid_from)
           IS DISTINCT FROM
           (OLD.scheme, OLD.code, OLD.parent_code, OLD.level, OLD.path, OLD.valid_from) THEN
            RAISE EXCEPTION 'classification_node %.%: identity columns are immutable; a reparent mints a new code (D-01)',
                OLD.scheme, OLD.code;
        END IF;
        IF NEW.valid_to IS DISTINCT FROM OLD.valid_to
           AND (OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL OR NEW.valid_to < today) THEN
            RAISE EXCEPTION 'classification_node %.%: valid_to may only be set once, on or after today %',
                OLD.scheme, OLD.code, today;
        END IF;
        RETURN NEW;
    ELSE
        RAISE EXCEPTION 'classification_node is append-only: % is not allowed', TG_OP;
    END IF;
END $$;

CREATE TRIGGER trg_classification_node_immutable
    BEFORE UPDATE OR DELETE ON classification_node
    FOR EACH ROW EXECUTE FUNCTION classification_node_immutable();
CREATE TRIGGER trg_classification_node_no_truncate
    BEFORE TRUNCATE ON classification_node
    FOR EACH STATEMENT EXECUTE FUNCTION classification_node_immutable();

COMMIT;
