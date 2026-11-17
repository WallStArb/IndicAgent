-- 601: partial index on ticker_event (security_identifier_id) for unretired spans (todo 609).
--
-- The identity trigger ticker_event_identity_unretired runs, for every security_identifier row
-- being retired, EXISTS (SELECT 1 FROM ticker_event WHERE security_identifier_id = <id> AND
-- retired_at IS NULL). ticker_event has no index on that column (its indexes are the primary key
-- and two gist exclusion indexes), so each probe is a sequential scan. Measured 2026-11-16 on a
-- temporary copy of 39,600 rows (the size after the stage 2 install), probing as the plpgsql trigger
-- does: 10.3 ms a probe without the index, 0.01 ms with it, so retiring the roughly 47,700
-- identifiers of the install costs about 8 minutes without it and a lookup with it.
-- Numbered 601 because 599 is taken by the R2 retire-APR migration (renumber again at landing
-- if the number is taken).
--
-- The index is partial on the trigger's own predicate (retired_at IS NULL), so it holds only live
-- spans. ticker_event is a plain table, not a hypertable, and about 1,800 rows (39,000 after the
-- stage 2 install), so a plain CREATE INDEX holds its lock for milliseconds and CONCURRENTLY
-- (which cannot run inside this transaction) is not needed. No compressed table is touched and no
-- column type changes, so no VACUUM clause is owed. Rerun-safe (IF NOT EXISTS).

BEGIN;

CREATE INDEX IF NOT EXISTS idx_ticker_event_security_identifier
    ON ticker_event (security_identifier_id) WHERE retired_at IS NULL;

COMMIT;
