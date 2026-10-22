-- Migration 501: drop market_data_ohlcv_old (phase 191 plan 17, design doc step 9).
--
-- The plan 14 swap (migration 497, committed 2026-10-17T00:25:12Z) renamed the proven
-- vendor/kind rebuild into market_data_ohlcv and kept the pre-swap label-column table under
-- this name for one nightly cycle. That cycle has passed: the 2026-10-18 06:00 UTC nightly
-- (fetcher daily and grid stages plus the bar reconciliation audit, 06:12:04Z) ran clean on
-- the new table, R6 unexplained is 0 in every (source, timeframe) group, the selection gate
-- compares equal on 1m/5m/4h, and lineage_missing carries only the known pre-phase failures
-- (CTVA 1848 bars, held since 2026-10-08; small-count ibkr re-serve churn). The table is
-- dead weight: 461,198,119 rows, 16 GB compressed, nothing reads it.
--
-- Live object map, re-verified 2026-10-18: no view, FK or external table depends on it (the
-- four dependent views were recreated over market_data_ohlcv by migration 497); its only
-- association is the unscheduled compression policy job (bgw_job 1075), removed explicitly
-- before the drop so no orphan job row survives the table. The pg_depend guard below allows
-- exactly the table family (the table, its chunks, the family's own constraints and
-- non-internal triggers) and aborts on any other dependent, so a view or FK somebody adds
-- later cannot be destroyed silently. No CASCADE anywhere: anything the explicit statements
-- cannot take must stop the migration, not cascade to it.
--
-- Rerun semantics, stated exactly: remove_compression_policy is if_exists (rerun-tolerant);
-- the DROP TABLE is deliberately plain (no IF EXISTS), so a rerun after the table is gone
-- fails loudly on the missing relation instead of silently passing. Not a decompress/ALTER
-- COLUMN/recompress migration, so no trailing VACUUM clause is owed here; the post-apply bare
-- VACUUM of market_data_ohlcv runs as a separate statement per the plan.

BEGIN;

SET LOCAL lock_timeout = '30s';

DO $$
DECLARE
    offender text;
BEGIN
    WITH family AS (
        SELECT 'market_data_ohlcv_old'::regclass AS tbl
        UNION ALL
        SELECT i.inhrelid
          FROM pg_inherits i
         WHERE i.inhparent = 'market_data_ohlcv_old'::regclass
    )
    SELECT format('%s (a %s)', d.objid, d.classid::regclass)
      INTO offender
      FROM pg_depend d
      JOIN family f ON d.refobjid = f.tbl
     WHERE d.deptype = 'n'
       AND NOT (
            (d.classid = 'pg_class'::regclass AND d.objid IN (SELECT tbl FROM family))
         OR (d.classid = 'pg_constraint'::regclass AND d.objid IN (
                SELECT con.oid FROM pg_constraint con
                 WHERE con.conrelid IN (SELECT tbl FROM family)))
         OR (d.classid = 'pg_trigger'::regclass AND d.objid IN (
                SELECT t.oid FROM pg_trigger t
                 WHERE t.tgrelid IN (SELECT tbl FROM family)
                   AND NOT t.tgisinternal))
       )
     LIMIT 1;
    IF offender IS NOT NULL THEN
        RAISE EXCEPTION
            'unexpected dependent on market_data_ohlcv_old: %; name it and handle it before this drop',
            offender;
    END IF;
END $$;

DO $$
BEGIN
    PERFORM remove_compression_policy('market_data_ohlcv_old', if_exists => true);
EXCEPTION
    WHEN undefined_function THEN
        RAISE EXCEPTION 'remove_compression_policy unavailable; delete bgw_job for hypertable 130 explicitly';
END $$;

DROP TABLE market_data_ohlcv_old;

COMMIT;
