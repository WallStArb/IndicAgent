-- 606: security_type (todo 648, stage 2 universe; amendment 2026-11-21 of
-- docs/plans/2026-11-13-stage2-universe-preregistration.md, proposed, owner adoption required
-- BEFORE this migration is applied and the writer run).
--
-- One resolved type per security, built from every typed row the security holds in any captured
-- Massive point-in-time ticker list (reference_raw_current, endpoint pit_snapshots), so the
-- membership no longer needs the security to be on a list, with a label, at each month-end. A
-- security that no list typed has no row: untyped is never filled or guessed. The class mapping is
-- src/intelligence/security_type.py (TYPE_RULE_ID); the table's primary key carries the rule id, so
-- a rule change is a new build beside the old one, never an edit.
--
-- Append only (INSERT only; UPDATE, DELETE and TRUNCATE raise). Single writer:
-- services/security_type_writer.py (one transaction per run, advisory lock). Not compressed and
-- not a hypertable (about 30,000 rows per rule), so no VACUUM clause.

BEGIN;

CREATE TABLE IF NOT EXISTS security_type (
    symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    rule_id text NOT NULL CHECK (rule_id <> ''),
    security_type text NOT NULL CHECK (security_type <> ''),
    class_conflict boolean NOT NULL,
    evidence jsonb NOT NULL,
    source text NOT NULL CHECK (source <> ''),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, rule_id)
);

COMMENT ON TABLE security_type IS
    'Security type resolved once per security (migration 606, todo 648): security_type is the '
    'resolved label under rule_id (ETN, WARRANT, RIGHT, PFD, ADRP win, then the ETF class, FUND, '
    'CS or ADRC by snapshot count, UNIT, any other label); class_conflict is true when the labels '
    'the security carried span more than one class; evidence holds the label counts (snapshot '
    'dates per label) and the first and last snapshot date; source names where the labels came '
    'from (pit_snapshots). A security with no label has no row. The labels are Massive''s as '
    'rebuilt in 2025, not point in time. Append-only. Single writer: SecurityTypeWriter.';

CREATE OR REPLACE FUNCTION security_type_insert_only()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is insert only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'check_violation';
END;
$$;

COMMENT ON FUNCTION security_type_insert_only() IS
    'Refuses UPDATE, DELETE and TRUNCATE on security_type (migration 606).';

DROP TRIGGER IF EXISTS trg_security_type_insert_only ON security_type;
CREATE TRIGGER trg_security_type_insert_only
    BEFORE UPDATE OR DELETE ON security_type
    FOR EACH ROW EXECUTE FUNCTION security_type_insert_only();

DROP TRIGGER IF EXISTS trg_security_type_no_truncate ON security_type;
CREATE TRIGGER trg_security_type_no_truncate
    BEFORE TRUNCATE ON security_type
    FOR EACH STATEMENT EXECUTE FUNCTION security_type_insert_only();

COMMIT;
