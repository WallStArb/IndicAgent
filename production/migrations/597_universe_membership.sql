-- 597: universe_membership and universe_membership_build (todo 609, stage 2 universe).
--
-- The point-in-time research universe of the preregistration
-- docs/plans/2026-11-13-stage2-universe-preregistration.md: one row per member per NYSE month-end
-- t, decided from data known at t and effective for the following month. A name is a member when
-- a row exists; non-members have no row (about 4,150 members a month-end over about 270
-- month-ends, so about 1.1M rows). The rule values are research-design constants in code
-- (src/intelligence/universe_membership.py, RULE_ID), not APR keys.
--
-- universe_membership_build is the ledger of built month-ends: a month exists exactly when its
-- ledger row does, so an empty month and an unbuilt month are never confused, and a resumed
-- build knows where to continue and under which rule.
--
-- Both tables are append-only (INSERT only; UPDATE, DELETE and TRUNCATE raise). A correction is a
-- dated amendment of the preregistration and a new build under a new rule id, never an edit.
-- Single writer: services/universe_membership_writer.py (one transaction per run, advisory lock).

BEGIN;

CREATE TABLE IF NOT EXISTS universe_membership_build (
    as_of date PRIMARY KEY,
    rule_id text NOT NULL CHECK (rule_id <> ''),
    n_members integer NOT NULL CHECK (n_members >= 0),
    recorded_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE universe_membership_build IS
    'Ledger of month-ends whose membership is built (migration 597, todo 609): one row per NYSE '
    'month-end, the rule id it was built under and its member count (zero only '
    'before 60 sessions of archive history exist; the writer refuses an empty month after the '
    'first member). Append-only. Single writer: UniverseMembershipWriter.';

CREATE TABLE IF NOT EXISTS universe_membership (
    as_of date NOT NULL REFERENCES universe_membership_build(as_of),
    symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    security_type text NOT NULL CHECK (security_type <> ''),
    median_dollar_volume double precision NOT NULL CHECK (median_dollar_volume > 0),
    close double precision NOT NULL CHECK (close > 0),
    sessions integer NOT NULL CHECK (sessions > 0),
    entered boolean NOT NULL,
    tier_5m boolean NOT NULL,
    PRIMARY KEY (as_of, symbol)
);

COMMENT ON TABLE universe_membership IS
    'Point-in-time stage 2 universe (migration 597, todo 609): symbol is a member as of the '
    'month-end as_of, effective for the following month, decided from bars through as_of only. '
    'median_dollar_volume is the trailing 60-session median of close x volume, close the close on '
    'as_of, sessions the count of own bars through as_of, security_type the Massive type on as_of; '
    'entered is true when the name crossed the entry floor and false when hysteresis kept it; '
    'tier_5m is true when the name is in the 5m tier (amendment 2026-11-15: median at or above the '
    'tier entry floor, kept above its exit floor; nested in the membership). '
    'Append-only. Single writer: UniverseMembershipWriter. Rule: preregistration 2026-11-13.';

CREATE INDEX IF NOT EXISTS idx_universe_membership_symbol
    ON universe_membership (symbol, as_of);

CREATE OR REPLACE FUNCTION universe_membership_insert_only()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is insert only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'check_violation';
END;
$$;

COMMENT ON FUNCTION universe_membership_insert_only() IS
    'Refuses UPDATE, DELETE and TRUNCATE on universe_membership and universe_membership_build '
    '(migration 597).';

DROP TRIGGER IF EXISTS trg_universe_membership_insert_only ON universe_membership;
CREATE TRIGGER trg_universe_membership_insert_only
    BEFORE UPDATE OR DELETE ON universe_membership
    FOR EACH ROW EXECUTE FUNCTION universe_membership_insert_only();

DROP TRIGGER IF EXISTS trg_universe_membership_no_truncate ON universe_membership;
CREATE TRIGGER trg_universe_membership_no_truncate
    BEFORE TRUNCATE ON universe_membership
    FOR EACH STATEMENT EXECUTE FUNCTION universe_membership_insert_only();

DROP TRIGGER IF EXISTS trg_universe_membership_build_insert_only ON universe_membership_build;
CREATE TRIGGER trg_universe_membership_build_insert_only
    BEFORE UPDATE OR DELETE ON universe_membership_build
    FOR EACH ROW EXECUTE FUNCTION universe_membership_insert_only();

DROP TRIGGER IF EXISTS trg_universe_membership_build_no_truncate ON universe_membership_build;
CREATE TRIGGER trg_universe_membership_build_no_truncate
    BEFORE TRUNCATE ON universe_membership_build
    FOR EACH STATEMENT EXECUTE FUNCTION universe_membership_insert_only();

COMMIT;
