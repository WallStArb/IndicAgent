-- Migration 368: classification writes are same-day only; node paths must extend the parent's.
--
-- Phase 182 code review (2026-09-25), follow-up to migration 367:
--   1. 367 allowed a future valid_from on insert and a future valid_to on close. Readers that
--      define "current" as `valid_to IS NULL` (current_level_name_sql, onboarding's node check)
--      and the as-of-today reader (ClassificationService.assignment_as_of) then disagree: a
--      scheduled row shows next month's sector today, and the still-valid row reads as
--      unclassified. Nothing needs scheduled reclassification, so writes now use exactly
--      today's UTC date. "valid_to IS NULL" and "valid as of today" then mean the same thing.
--   2. `now()` is the transaction start time. A transaction that crosses UTC midnight could
--      insert rows dated yesterday that become visible today, changing yesterday's as-of
--      answers. A write whose transaction started on an earlier UTC date than the wall clock
--      is refused.
--   3. classification_node.path was checked only for length and last element. A node whose
--      path does not extend its parent's path would send ancestor lookups to the wrong branch.
--      Inserts now require path = parent.path || code (or {code} for a root) and
--      valid_from = today.
-- Live data before this migration: all rows dated 2026-09-25 and every node path consistent,
-- so the guards hold on arrival.
BEGIN;

CREATE OR REPLACE FUNCTION classification_write_date() RETURNS date
LANGUAGE plpgsql AS $$
DECLARE
    txn_day date := (now() AT TIME ZONE 'UTC')::date;
    wall_day date := (clock_timestamp() AT TIME ZONE 'UTC')::date;
BEGIN
    IF txn_day <> wall_day THEN
        RAISE EXCEPTION 'classification write refused: transaction started on % (UTC) but it is now %; rerun in a fresh transaction',
            txn_day, wall_day;
    END IF;
    RETURN txn_day;
END $$;

CREATE OR REPLACE FUNCTION instrument_classification_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    today date;
BEGIN
    IF TG_OP = 'INSERT' THEN
        today := classification_write_date();
        IF NEW.valid_from <> today THEN
            RAISE EXCEPTION 'instrument_classification: insert for % must have valid_from = today % (got %); no backdated or scheduled rows (D-07)',
                NEW.symbol, today, NEW.valid_from;
        END IF;
        IF NEW.valid_to IS NOT NULL THEN
            RAISE EXCEPTION 'instrument_classification: insert for % must be open (valid_to NULL)', NEW.symbol;
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        today := classification_write_date();
        IF OLD.valid_to IS NOT NULL THEN
            RAISE EXCEPTION 'instrument_classification: row (%, %, %) is closed and immutable',
                OLD.symbol, OLD.scheme, OLD.valid_from;
        END IF;
        IF (NEW.symbol, NEW.scheme, NEW.code, NEW.valid_from, NEW.source_ref, NEW.created_at)
           IS DISTINCT FROM
           (OLD.symbol, OLD.scheme, OLD.code, OLD.valid_from, OLD.source_ref, OLD.created_at) THEN
            RAISE EXCEPTION 'instrument_classification: only valid_to may change (close the row, insert a new one)';
        END IF;
        IF NEW.valid_to IS DISTINCT FROM today THEN
            RAISE EXCEPTION 'instrument_classification: close % with valid_to = today % (got %)',
                OLD.symbol, today, NEW.valid_to;
        END IF;
        RETURN NEW;
    ELSE
        RAISE EXCEPTION 'instrument_classification is append-only: % is not allowed', TG_OP;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION classification_node_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    today date;
    parent_path text[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        today := classification_write_date();
        IF NEW.valid_from <> today THEN
            RAISE EXCEPTION 'classification_node %.%: valid_from must be today % (got %)',
                NEW.scheme, NEW.code, today, NEW.valid_from;
        END IF;
        IF NEW.parent_code IS NULL THEN
            IF NEW.path IS DISTINCT FROM ARRAY[NEW.code] THEN
                RAISE EXCEPTION 'classification_node %.%: a root path must be {%}', NEW.scheme, NEW.code, NEW.code;
            END IF;
        ELSE
            SELECT path INTO parent_path FROM classification_node
            WHERE scheme = NEW.scheme AND code = NEW.parent_code;
            IF NEW.path IS DISTINCT FROM parent_path || NEW.code THEN
                RAISE EXCEPTION 'classification_node %.%: path % does not extend parent % path %',
                    NEW.scheme, NEW.code, NEW.path, NEW.parent_code, parent_path;
            END IF;
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF (NEW.scheme, NEW.code, NEW.parent_code, NEW.level, NEW.path, NEW.valid_from)
           IS DISTINCT FROM
           (OLD.scheme, OLD.code, OLD.parent_code, OLD.level, OLD.path, OLD.valid_from) THEN
            RAISE EXCEPTION 'classification_node %.%: identity columns are immutable; a reparent mints a new code (D-01)',
                OLD.scheme, OLD.code;
        END IF;
        IF NEW.valid_to IS DISTINCT FROM OLD.valid_to THEN
            today := classification_write_date();
            IF OLD.valid_to IS NOT NULL OR NEW.valid_to IS DISTINCT FROM today THEN
                RAISE EXCEPTION 'classification_node %.%: valid_to may only be set once, to today %',
                    OLD.scheme, OLD.code, today;
            END IF;
        END IF;
        RETURN NEW;
    ELSE
        RAISE EXCEPTION 'classification_node is append-only: % is not allowed', TG_OP;
    END IF;
END $$;

-- 367 attached this function to UPDATE/DELETE/TRUNCATE only; inserts now go through it too.
CREATE TRIGGER trg_classification_node_insert
    BEFORE INSERT ON classification_node
    FOR EACH ROW EXECUTE FUNCTION classification_node_immutable();

COMMIT;
