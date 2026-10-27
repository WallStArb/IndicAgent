-- Migration 520: a bar_source_policy row can be retired (D-191-P, owner decision 2026-10-26).
--
-- The table is append-only: a row may only be closed once with a date (migration 460), and closed
-- rows are immutable. That cannot express a ranking decision that replaces existing rows, because
-- a symbol row beats the timeframe default and new spans may not overlap old ones: the 5m policy
-- seeded at plan 191-07 (1,642 symbol rows, IBKR primary, plus 56 Alpaca windows that preserved an
-- old load order) cannot be replaced by D-191-P (Alpaca SIP primary for 5m from 2016-01-04, IBKR
-- fallback; IBKR before) through closes alone.
--
-- Retirement keeps the row and its history and takes it out of force: retired_at and
-- retired_reason are set once, by the one writer (scripts/ops/bars/ops_source_policy.py
-- --retire), on any row, open or closed; nothing else about the row may change. Every reader reads
-- bar_source_policy_current (live rows only; a guard test forbids reading the table directly), and
-- the no-overlap constraint binds live rows only, so a decision can replace retired spans.
-- Idempotent.

BEGIN;

ALTER TABLE bar_source_policy ADD COLUMN IF NOT EXISTS retired_at timestamptz;
ALTER TABLE bar_source_policy ADD COLUMN IF NOT EXISTS retired_reason text;

ALTER TABLE bar_source_policy DROP CONSTRAINT IF EXISTS ck_bar_source_policy_retired;
ALTER TABLE bar_source_policy ADD CONSTRAINT ck_bar_source_policy_retired
    CHECK ((retired_at IS NULL) = (retired_reason IS NULL));

ALTER TABLE bar_source_policy DROP CONSTRAINT IF EXISTS ex_bar_source_policy_no_overlap;
ALTER TABLE bar_source_policy ADD CONSTRAINT ex_bar_source_policy_no_overlap
    EXCLUDE USING gist (
        timeframe WITH =,
        COALESCE(symbol, ''::text) WITH =,
        daterange(valid_from, valid_to, '[)'::text) WITH &&
    ) WHERE (retired_at IS NULL);

CREATE OR REPLACE FUNCTION bar_source_policy_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.closed_at IS NOT NULL THEN
            RAISE EXCEPTION 'bar_source_policy: closed_at is stamped by the closing update, not inserted'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.retired_at IS NOT NULL OR NEW.retired_reason IS NOT NULL THEN
            RAISE EXCEPTION 'bar_source_policy: a row is retired by an update, never inserted retired'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.retired_at IS NOT NULL THEN
            RAISE EXCEPTION 'bar_source_policy: row % is retired and immutable', OLD.policy_id
                USING ERRCODE = 'check_violation';
        END IF;
        -- Retirement: only retired_at and retired_reason change, on any live row (open or closed).
        IF NEW.retired_at IS NOT NULL THEN
            IF (NEW.policy_id, NEW.timeframe, NEW.symbol, NEW.valid_from, NEW.valid_to,
                NEW.ingress_mode, NEW.primary_source, NEW.fallback_source, NEW.reason,
                NEW.evidence, NEW.recorded_at, NEW.closed_at)
               IS DISTINCT FROM
               (OLD.policy_id, OLD.timeframe, OLD.symbol, OLD.valid_from, OLD.valid_to,
                OLD.ingress_mode, OLD.primary_source, OLD.fallback_source, OLD.reason,
                OLD.evidence, OLD.recorded_at, OLD.closed_at) THEN
                RAISE EXCEPTION 'bar_source_policy: a retirement changes only retired_at and retired_reason'
                    USING ERRCODE = 'check_violation';
            END IF;
            NEW.retired_at := now();
            RETURN NEW;
        END IF;
        -- Close: an open row gets its valid_to, once.
        IF OLD.valid_to IS NOT NULL THEN
            RAISE EXCEPTION 'bar_source_policy: row % is closed and immutable', OLD.policy_id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.valid_to IS NULL THEN
            RAISE EXCEPTION 'bar_source_policy: an update must close open row % with a date',
                OLD.policy_id USING ERRCODE = 'check_violation';
        END IF;
        IF (NEW.policy_id, NEW.timeframe, NEW.symbol, NEW.valid_from, NEW.ingress_mode,
            NEW.primary_source, NEW.fallback_source, NEW.reason, NEW.evidence, NEW.recorded_at,
            NEW.retired_reason)
           IS DISTINCT FROM
           (OLD.policy_id, OLD.timeframe, OLD.symbol, OLD.valid_from, OLD.ingress_mode,
            OLD.primary_source, OLD.fallback_source, OLD.reason, OLD.evidence, OLD.recorded_at,
            OLD.retired_reason) THEN
            RAISE EXCEPTION 'bar_source_policy: only valid_to may change (close the row, insert a new one)'
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.closed_at := now();
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'bar_source_policy is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'check_violation';
END;
$$;

CREATE OR REPLACE VIEW bar_source_policy_current AS
SELECT policy_id, timeframe, symbol, valid_from, valid_to, ingress_mode, primary_source,
       fallback_source, reason, evidence, recorded_at, closed_at
FROM bar_source_policy
WHERE retired_at IS NULL;

COMMENT ON VIEW bar_source_policy_current IS
    'The bar_source_policy rows in force (not retired; migration 520). Every reader reads this view.';

-- Change detection (the daily stage's --changed-only probes) must see a retirement as a change,
-- so it reads every row, retired ones included, through this view and never the table itself.
CREATE OR REPLACE VIEW bar_source_policy_changes AS
SELECT policy_id, timeframe, symbol, valid_from, valid_to, recorded_at, closed_at, retired_at
FROM bar_source_policy;

COMMENT ON VIEW bar_source_policy_changes IS
    'Every bar_source_policy row with its change stamps, retired rows included (migration 520): '
    'for change detection only; selection reads bar_source_policy_current.';

GRANT SELECT ON bar_source_policy_current TO bar_derivation_writer;
GRANT SELECT ON bar_source_policy_changes TO bar_derivation_writer;

COMMENT ON COLUMN bar_source_policy.retired_at IS
    'When the row was taken out of force (migration 520); the row and its history stay.';

COMMIT;
