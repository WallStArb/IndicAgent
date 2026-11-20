-- 605: reset universe_membership and its build ledger so the stage 2 membership can be rebuilt
-- after the pit-map placement amendment (todo 609; docs/plans/2026-11-20-pit-map-unplaced-names-
-- measurement-and-amendment-draft.md, owner adoption required BEFORE this migration is applied).
--
-- Why a reset: both tables are insert only (migration 597: a correction is a dated amendment and a
-- new build). The amendment adds live names to the history, so every built month changes, and a new
-- build under the same primary keys cannot sit beside the old one. The old build is kept as a
-- record, never edited: its rows are copied to universe_membership_pre605 and
-- universe_membership_build_pre605 first, and the migration refuses unless the live tables hold the
-- rows measured on 2026-11-20 (858,454 member rows over 278 month-ends) and no research run exists
-- (a recorded run would lose its membership inputs).
--
-- Apply only with the runbook (docs/operations/stage2-membership-rebuild-runbook.md): the pg_dump
-- backup first, the strict sweep finished (one heavy job at a time), then this file, then the
-- verify query at its end. The insert-only triggers are disabled for the TRUNCATE and enabled
-- again before COMMIT, so a failure leaves them in force.

BEGIN;

DO $$
DECLARE
    n_rows bigint;
    n_months bigint;
    n_runs bigint;
BEGIN
    SELECT count(*) INTO n_rows FROM universe_membership;
    SELECT count(*) INTO n_months FROM universe_membership_build;
    SELECT count(*) INTO n_runs FROM research_run;
    IF n_rows <> 858454 OR n_months <> 278 THEN
        RAISE EXCEPTION 'universe_membership holds % rows over % month-ends, not the 858454 over 278 '
            'measured on 2026-11-20: this reset is for that build only', n_rows, n_months;
    END IF;
    IF n_runs <> 0 THEN
        RAISE EXCEPTION '% research_run row(s) exist: a reset would orphan their membership inputs', n_runs;
    END IF;
END
$$;

CREATE TABLE universe_membership_build_pre605 AS TABLE universe_membership_build;
CREATE TABLE universe_membership_pre605 AS TABLE universe_membership;
COMMENT ON TABLE universe_membership_build_pre605 IS
    'The stage 2 build ledger as built 2026-11-19 (rule ids stage2-2026-11-15, 278 month-ends), kept '
    'by migration 605 before the reset for the pit-map placement amendment. Record only.';
COMMENT ON TABLE universe_membership_pre605 IS
    'The stage 2 membership rows as built 2026-11-19 (858,454 rows), kept by migration 605 before the '
    'reset for the pit-map placement amendment. Record only.';

DO $$
BEGIN
    IF (SELECT count(*) FROM universe_membership_pre605) <> 858454
       OR (SELECT count(*) FROM universe_membership_build_pre605) <> 278 THEN
        RAISE EXCEPTION 'the pre-reset copy does not hold the live rows; nothing is reset';
    END IF;
END
$$;

-- the kept copies are records: the existing insert-only function guards them too
CREATE TRIGGER trg_universe_membership_pre605_insert_only
    BEFORE UPDATE OR DELETE ON universe_membership_pre605
    FOR EACH ROW EXECUTE FUNCTION universe_membership_insert_only();
CREATE TRIGGER trg_universe_membership_pre605_no_truncate
    BEFORE TRUNCATE ON universe_membership_pre605
    FOR EACH STATEMENT EXECUTE FUNCTION universe_membership_insert_only();
CREATE TRIGGER trg_universe_membership_build_pre605_insert_only
    BEFORE UPDATE OR DELETE ON universe_membership_build_pre605
    FOR EACH ROW EXECUTE FUNCTION universe_membership_insert_only();
CREATE TRIGGER trg_universe_membership_build_pre605_no_truncate
    BEFORE TRUNCATE ON universe_membership_build_pre605
    FOR EACH STATEMENT EXECUTE FUNCTION universe_membership_insert_only();

ALTER TABLE universe_membership DISABLE TRIGGER trg_universe_membership_no_truncate;
ALTER TABLE universe_membership_build DISABLE TRIGGER trg_universe_membership_build_no_truncate;

TRUNCATE universe_membership, universe_membership_build;

ALTER TABLE universe_membership ENABLE TRIGGER trg_universe_membership_no_truncate;
ALTER TABLE universe_membership_build ENABLE TRIGGER trg_universe_membership_build_no_truncate;

DO $$
BEGIN
    IF (SELECT count(*) FROM universe_membership) <> 0 OR (SELECT count(*) FROM universe_membership_build) <> 0 THEN
        RAISE EXCEPTION 'the reset left rows behind';
    END IF;
    IF (SELECT count(*) FROM pg_trigger
         WHERE tgrelid IN ('universe_membership'::regclass, 'universe_membership_build'::regclass)
           AND NOT tgisinternal AND tgenabled = 'O') <> 4 THEN
        RAISE EXCEPTION 'the four insert-only triggers are not all enabled';
    END IF;
END
$$;

COMMIT;

-- Verify after COMMIT (read only; expect 0 | 0 | 858454 | 278 | 4):
-- SELECT (SELECT count(*) FROM universe_membership) AS live_rows,
--        (SELECT count(*) FROM universe_membership_build) AS live_months,
--        (SELECT count(*) FROM universe_membership_pre605) AS kept_rows,
--        (SELECT count(*) FROM universe_membership_build_pre605) AS kept_months,
--        (SELECT count(*) FROM pg_trigger WHERE tgrelid IN ('universe_membership'::regclass,
--         'universe_membership_build'::regclass) AND NOT tgisinternal AND tgenabled = 'O') AS triggers_on;
