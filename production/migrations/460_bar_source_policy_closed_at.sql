-- Migration 460: bar_source_policy.closed_at, stamped by the closing update (phase 185 plan 50,
-- todo 508)
--
-- A close changes valid_to only (migration 446's one allowed UPDATE), so recorded_at never moved
-- and nothing recorded when the decision changed. The daily stage's revision-ratio waiver and its
-- nightly --changed-only probe compare policy rows with the symbol's last applied daily load by
-- recorded_at, so neither saw a close: plan 185-49 closed the 185-38 rows of FTV, IP and STE at
-- the first day plus one and the stage refused their re-derivation at revision ratio 0.999
-- against the 0.02 limit.
--
-- closed_at is the close's timestamp. The append-only trigger sets it on the closing UPDATE
-- (now(), the closing transaction's time, as recorded_at is the inserting one's), so no writer
-- can omit or forge it; an INSERT cannot carry one (a row inserted already closed is a decision
-- recorded at recorded_at); a closed row stays immutable, closed_at included. The daily stage
-- reads GREATEST(recorded_at, closed_at) as the time a row last changed (services/
-- bar_derivation.py, _POLICY_CHANGED_AT); NULL on a row closed before this migration counts as
-- not newer than recorded_at.
--
-- Backfill: the three closes of plan 185-49 are the only closes whose effect is not yet in the
-- stored bars (D7 policy_conformance fails on exactly FTV, IP and STE on 2026-10-08; every other
-- closed row conforms, so leaving it NULL hides nothing). They ran through
-- scripts/ops/bars/ops_source_policy.py --close after OUT's row was inserted (recorded_at
-- 2026-10-08 20:15:24.633 UTC) and before logs/185-49/policy_apply.log was last written
-- (20:15:26.826 UTC); the stamp is that upper bound. The trigger is disabled only around that one
-- UPDATE, inside this transaction.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, DROP CONSTRAINT IF EXISTS before ADD, CREATE OR REPLACE
-- FUNCTION, and the backfill touches only rows whose closed_at is still NULL.

BEGIN;

ALTER TABLE bar_source_policy ADD COLUMN IF NOT EXISTS closed_at timestamptz NULL;

COMMENT ON COLUMN bar_source_policy.closed_at IS
    'When the row was closed (valid_to set by the one allowed UPDATE); stamped by the append-only '
    'trigger, never by a writer (migration 460, plan 185-50). NULL on an open row, on a row '
    'inserted closed, and on a row closed before migration 460 (except the three 185-49 closes, '
    'backfilled). The daily stage reads GREATEST(recorded_at, closed_at) as when the row changed.';

ALTER TABLE bar_source_policy DROP CONSTRAINT IF EXISTS ck_bar_source_policy_closed_at;
ALTER TABLE bar_source_policy ADD CONSTRAINT ck_bar_source_policy_closed_at
    CHECK (closed_at IS NULL OR (valid_to IS NOT NULL AND closed_at >= recorded_at));

CREATE OR REPLACE FUNCTION bar_source_policy_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.closed_at IS NOT NULL THEN
            RAISE EXCEPTION 'bar_source_policy: closed_at is stamped by the closing update, not inserted'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.valid_to IS NOT NULL THEN
            RAISE EXCEPTION 'bar_source_policy: row % is closed and immutable', OLD.policy_id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.valid_to IS NULL THEN
            RAISE EXCEPTION 'bar_source_policy: an update must close open row % with a date',
                OLD.policy_id USING ERRCODE = 'check_violation';
        END IF;
        IF (NEW.policy_id, NEW.timeframe, NEW.symbol, NEW.valid_from, NEW.ingress_mode,
            NEW.primary_source, NEW.fallback_source, NEW.reason, NEW.evidence, NEW.recorded_at)
           IS DISTINCT FROM
           (OLD.policy_id, OLD.timeframe, OLD.symbol, OLD.valid_from, OLD.ingress_mode,
            OLD.primary_source, OLD.fallback_source, OLD.reason, OLD.evidence, OLD.recorded_at) THEN
            RAISE EXCEPTION 'bar_source_policy: only valid_to may change (close the row, insert a new one)'
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.closed_at := now();
        RETURN NEW;
    ELSE
        RAISE EXCEPTION 'bar_source_policy is append-only: % is not allowed', TG_OP
            USING ERRCODE = 'check_violation';
    END IF;
END $$;

COMMENT ON FUNCTION bar_source_policy_append_only() IS
    'Allows INSERT (closed_at NULL) and the one UPDATE that closes an open row (valid_to NULL to '
    'a date), stamping closed_at = now(); refuses every other UPDATE, DELETE and TRUNCATE on '
    'bar_source_policy (migrations 446 and 460).';

-- The three 185-49 closes (FTV at 2016-06-14, IP and STE at 2006-10-03), matched on policy_id
-- and valid_to.
ALTER TABLE bar_source_policy DISABLE TRIGGER trg_bar_source_policy_append_only;
UPDATE bar_source_policy p SET closed_at = TIMESTAMPTZ '2026-10-08 20:15:26.826+00'
FROM (VALUES
    ('e8207a5d-f6cf-4fec-909f-716771394f7c'::uuid, DATE '2016-06-14'),
    ('a4a06df8-44be-4886-9a80-8396f1c890fe'::uuid, DATE '2006-10-03'),
    ('de2b15f0-9238-4422-80a6-fff9ed0b3f9d'::uuid, DATE '2006-10-03')
) AS v (policy_id, valid_to)
WHERE p.policy_id = v.policy_id AND p.valid_to = v.valid_to
  AND p.valid_to IS NOT NULL AND p.closed_at IS NULL;
ALTER TABLE bar_source_policy ENABLE TRIGGER trg_bar_source_policy_append_only;

COMMIT;
